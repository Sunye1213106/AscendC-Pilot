from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from understand_operator._operator.artifacts import (
    REQUIRED_TILING_ARCHIVE_FILES,
    operator_root,
    read_text,
    safe_op_name,
    write_json,
)
from understand_operator._operator.kb_compiler import RELATION_TYPES
from understand_operator._operator.yaml_gate import (
    YamlGateError,
    owner_retry_report,
    resource_semantic_errors,
    validate_yaml_document,
)


PHASE_HOST_FLOW = "host_flow"
PHASE_KERNEL_PATH = "kernel_path"

HOST_FLOW_ARTIFACTS = [
    "archive/proposals/host_tiling_proposal.yaml",
    "tiling/route.md",
    "tiling/index.yaml",
    "tiling/variables.yaml",
    "tiling/key_space.yaml",
    "tiling/exhaustive_key_space.yaml",
    "tiling/constraints.yaml",
    "tiling/families.yaml",
    "tiling/data_model.yaml",
    "tiling/coverage_model.yaml",
    "tiling/evidence_index.yaml",
] + list(REQUIRED_TILING_ARCHIVE_FILES)

FLOW_ARTIFACTS = [
    "archive/proposals/flow_dataflow_proposal.yaml",
    "flow/index.yaml",
    "flow/compute_graph.yaml",
    "flow/dataflow.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
]

HOST_FLOW_COMPLETION = "tiling/.uo_host_extraction_complete.json"
FLOW_COMPLETION = "flow/.uo_flow_extraction_complete.json"

KERNEL_CANONICAL = [
    "kernel/paths.yaml",
    "kernel/pipeline.yaml",
    "kernel/resources.yaml",
]

# Keep this in lockstep with kb_compiler.STABLE_ID_RE.  The barrier uses it on
# untrusted phase artifacts so an agent gets feedback before the host consumes
# its output or the final quality gate reports hundreds of rename candidates.
_STABLE_ID_RE = re.compile(
    r"^(SYM|VAR|REL|EV|SRC|KEY|FAM|COMP|GOLD|KPATH|KBR|KTPL|CL|CON|VIEW|BUF|SYNC|RES|TDF|KVAR|KDEC|PIPE|COV|NUM)_[A-Z0-9_]+$"
)
_LEGACY_ID_RE = re.compile(r"^(TF\d+|K\d+|C\d+|D\d+|P\d+)$")


def _yaml_problem(rel_path: str, text: str) -> str | None:
    """Return a concise failure reason for a required YAML artifact.

    Barriers run before the host consumes a subagent's material, so accepting a
    non-empty but malformed YAML document merely defers a cheap failure until a
    much later quality gate.  Markdown artifacts are intentionally excluded.
    """
    if not rel_path.endswith((".yaml", ".yml")):
        return None
    _data, errors = validate_yaml_document(text, rel_path, required_sections=())
    if not errors:
        return None
    first = errors[0]
    if first.code == "YAML_SYNTAX_ERROR":
        return f"invalid YAML: {first.message}"
    if first.code == "YAML_ROOT_NOT_MAPPING":
        return "YAML root must be a mapping"
    if first.code == "REQUIRED_SECTION_EMPTY":
        return "empty YAML document"
    return f"{first.code}: {first.message}"
    return None


def _yaml_gate_errors(rel_path: str, text: str, *, phase: str) -> list[YamlGateError]:
    data, errors = validate_yaml_document(text, rel_path, phase=phase)
    if rel_path == "kernel/resources.yaml" and not errors:
        errors.extend(resource_semantic_errors(data, rel_path, phase=phase))
    return errors


def _stale_error_code(item: str) -> str:
    if "YAML root must be a mapping" in item:
        return "YAML_ROOT_NOT_MAPPING"
    if "invalid YAML" in item:
        return "YAML_SYNTAX_ERROR"
    if "empty YAML" in item:
        return "REQUIRED_SECTION_EMPTY"
    match = re.search(r"\(([A-Z_]+)", item)
    return match.group(1) if match else "YAML_SCHEMA_ERROR"


def _id_contract_problems(rel_path: str, text: str) -> list[str]:
    """Validate ids/references that agents commonly get wrong in phase output."""
    if not rel_path.endswith((".yaml", ".yml")) or yaml is None:
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []  # _yaml_problem reports the parse error once.

    problems: list[str] = []

    def visit(value: Any, location: str) -> None:
        if isinstance(value, dict):
            for id_key in ("id", "stable_id"):
                if id_key not in value:
                    continue
                item_id = value[id_key]
                if not isinstance(item_id, str) or not (
                    _STABLE_ID_RE.fullmatch(item_id) or _LEGACY_ID_RE.fullmatch(item_id)
                ):
                    problems.append(f"{location}.{id_key} has invalid stable id {item_id!r}")
            if "evidence_refs" in value:
                refs = value["evidence_refs"]
                if not isinstance(refs, list):
                    problems.append(f"{location}.evidence_refs must be a YAML list")
                else:
                    for index, ref in enumerate(refs):
                        if not isinstance(ref, str) or not re.fullmatch(r"(?:EV|SRC)_[A-Z0-9_]+", ref):
                            problems.append(f"{location}.evidence_refs[{index}] has invalid evidence ref {ref!r}")
            for key, child in value.items():
                visit(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{location}[{index}]")

    visit(data, rel_path)
    return problems[:12]


def _proposal_contract_problems(rel_path: str, text: str) -> list[str]:
    """Catch proposal-envelope drift before a host reads or promotes it."""
    if not rel_path.startswith("archive/proposals/") or yaml is None:
        return []
    try:
        proposal = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(proposal, dict):
        return ["proposal root must be a mapping"]
    required = ("version", "op_name", "proposal_id", "producer", "canonical_updates")
    missing = [key for key in required if key not in proposal]
    if missing:
        return ["proposal missing required fields: " + ", ".join(missing)]
    if not isinstance(proposal.get("producer"), dict):
        return ["proposal producer must be a mapping with agent and phase"]
    updates = proposal.get("canonical_updates")
    if not isinstance(updates, list) or not updates:
        return ["proposal canonical_updates must be a non-empty YAML list"]
    problems: list[str] = []
    has_evidence_merge = False
    for index, update in enumerate(updates):
        if not isinstance(update, dict):
            problems.append(f"canonical_updates[{index}] must be a mapping")
            continue
        if update.get("target") == "registry/evidence.yaml" and update.get("section") == "evidence":
            has_evidence_merge = True
        missing_update = [key for key in ("target", "section", "merge_mode", "entries") if key not in update]
        if missing_update:
            problems.append(f"canonical_updates[{index}] missing: {', '.join(missing_update)}")
        if "mode" in update or "items" in update:
            problems.append(f"canonical_updates[{index}] uses obsolete mode/items; use merge_mode/entries")
    if not has_evidence_merge:
        problems.append("missing evidence merge target: registry/evidence.yaml section evidence")
    return problems[:12]


def _entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _semantic_contract_problems(rel_path: str, text: str) -> list[str]:
    """Validate phase-owner semantics before the host accepts completion."""
    if not rel_path.endswith((".yaml", ".yml")) or yaml is None:
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    problems: list[str] = []

    if rel_path == "tiling/variables.yaml":
        variables = data.get("variables")
        mechanism = data.get("tiling_mechanism")
        classification = data.get("impact_classification")
        if not isinstance(variables, dict) or not variables:
            problems.append("variables must be a non-empty mapping")
        if not isinstance(mechanism, dict) or not any(mechanism.values()):
            problems.append("tiling_mechanism must be a populated mapping")
        if not isinstance(classification, dict) or not any(
            isinstance(value, list) and value for value in classification.values()
        ):
            problems.append("impact_classification must contain a non-empty category list")

    if rel_path == "tiling/constraints.yaml":
        for index, relation in enumerate(_entries(data.get("relations"))):
            relation_type = str(relation.get("type") or "")
            if relation_type not in RELATION_TYPES:
                problems.append(f"relations[{index}].type is not in compiler RELATION_TYPES: {relation_type!r}")
            missing = [key for key in ("id", "type", "expr", "case_impact") if not relation.get(key)]
            if missing:
                problems.append(f"relations[{index}] missing: {', '.join(missing)}")
        for section in ("tiling_key_pruning", "tiling_key_merging"):
            value = data.get(section)
            if not isinstance(value, dict) or value.get("performed") not in (True, False, "unknown"):
                problems.append(f"{section}.performed must be true, false, or unknown")

    if rel_path == "tiling/exhaustive_key_space.yaml":
        if str(data.get("status") or "") == "not_applicable":
            if not data.get("reason") or not data.get("evidence_refs"):
                problems.append("not_applicable requires reason and evidence_refs")
            return problems[:12]
        source = data.get("enumeration_source")
        summary = data.get("summary")
        blocks = data.get("template_blocks")
        if not isinstance(source, dict) or not source.get("files"):
            problems.append("enumeration_source.files must list source-backed pruning/template files")
        if not isinstance(summary, dict):
            problems.append("summary must be a mapping")
        if not isinstance(blocks, list) or not blocks:
            problems.append("template_blocks must be non-empty when exhaustive key enumeration is applicable")
        else:
            total = 0
            for index, block in enumerate(blocks):
                if not isinstance(block, dict):
                    problems.append(f"template_blocks[{index}] must be a mapping")
                    continue
                if not block.get("id") or not isinstance(block.get("field_domains"), dict):
                    problems.append(f"template_blocks[{index}] missing id or field_domains")
                try:
                    total += int(block.get("product_count") or 0)
                except (TypeError, ValueError):
                    problems.append(f"template_blocks[{index}].product_count must be an integer")
            expected = summary.get("expanded_key_count") if isinstance(summary, dict) else None
            if isinstance(expected, int) and total != expected:
                problems.append(f"summary.expanded_key_count={expected} but template block product sum={total}")
        if not isinstance(data.get("reverse_realization_index"), dict):
            problems.append("reverse_realization_index must be a mapping")

    if rel_path in ("flow/compute_graph.yaml", "flow/golden_model.yaml"):
        # The cross-file check is completed in verify_host_flow_barrier.
        required = "compute_steps" if rel_path.endswith("compute_graph.yaml") else "golden_generation_contract"
        if not data.get(required):
            problems.append(f"{required} must be non-empty")

    if rel_path.endswith("_kernel_path.yaml") and rel_path != "kernel/paths.yaml":
        required_sections = (
            "kernel_path", "kernel_compile_model", "kernel_variable_inventory",
            "template_bindings", "branch_frontier", "tiling_backfill_candidates",
            "io_alignment", "compute_step_alignment", "tiling_data_usage", "pipeline",
            "buffer_map", "sync_events", "missing_items", "evidence", "confidence",
        )
        missing = [section for section in required_sections if section not in data]
        if missing:
            problems.append("raw kernel artifact missing sections: " + ", ".join(missing))
        if not _entries(data.get("compute_step_alignment")):
            problems.append("compute_step_alignment must be non-empty")

    if rel_path == "kernel/paths.yaml" and not _entries(data.get("kernel_paths")):
        problems.append("kernel_paths must be non-empty")
    if rel_path == "kernel/pipeline.yaml" and not _entries(data.get("compute_step_alignment")):
        problems.append("compute_step_alignment must be non-empty")
    if rel_path == "kernel/resources.yaml":
        if not _entries(data.get("sync_events")):
            problems.append("sync_events must be non-empty")
        resource_entries: list[dict[str, Any]] = []
        for section in ("buffers", "workspaces", "resources"):
            resource_entries.extend(_entries(data.get(section)))
        if not any(item.get("producer") and item.get("consumer") for item in resource_entries):
            problems.append("at least one resource must have both producer and consumer")

    return problems[:12]


def _flow_has_golden_mapping(uo_root: Path) -> bool:
    if yaml is None:
        return False
    try:
        compute = yaml.safe_load(read_text(uo_root / "flow/compute_graph.yaml")) or {}
        golden = yaml.safe_load(read_text(uo_root / "flow/golden_model.yaml")) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(compute, dict) or not isinstance(golden, dict):
        return False
    if any(item.get("golden_step_ref") or item.get("golden_role") for item in _entries(compute.get("compute_steps"))):
        return True
    if golden.get("maps_to_compute_steps"):
        return True
    return any(item.get("maps_to_compute_steps") for item in _entries(golden.get("golden_outputs")))


@dataclass
class BarrierResult:
    ok: bool
    phase: str
    missing: list[str]
    stale: list[str]
    message: str
    errors: list[dict[str, Any]] | None = None


def _approved_task_ids(uo_root: Path) -> list[str]:
    # prefer human/kernel_dispatch_review.yaml; fall back to legacy path
    candidates = [
        uo_root / "human" / "kernel_dispatch_review.yaml",
        uo_root / "kernel" / "kernel_dispatch_review.yaml",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return []
    ids: list[str] = []
    in_block = False
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("approved_task_ids:"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("- "):
                ids.append(stripped[2:].strip().strip('"').strip("'"))
            elif stripped and not line.startswith((" ", "\t")):
                break
    return ids


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_placeholder(rel_path: str, text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if rel_path.endswith("route.md") and "Tiling Entry\nunknown" in stripped:
        return True
    if rel_path.endswith("decision_tree.md") and (
        "host extraction must replace this skeleton" in stripped or stripped.endswith("unknown")
    ):
        return True
    placeholders = {
        "tiling/index.yaml": {"op_name: unknown"},
        "tiling/key_space.yaml": {"fields: {}", "encoding:\n  macro: unknown"},
        "tiling/exhaustive_key_space.yaml": {"status: pending", "template_blocks: []"},
        "tiling/variables.yaml": {"variables: {}"},
        "tiling/families.yaml": {"families: {}"},
        "tiling/data_model.yaml": {"family_to_struct: {}"},
        "tiling/coverage_model.yaml": {"family_obligations: []"},
        "tiling/evidence_index.yaml": {"symbols: {}"},
        "tiling/archive/frontier.yaml": {"status: pending"},
        "tiling/archive/dispatch_variables.yaml": {"status: pending"},
        "tiling/archive/predicate_space.yaml": {"status: pending"},
        "tiling/archive/compile_time_bindings.yaml": {"status: pending"},
        "flow/compute_graph.yaml": {"compute_steps: {}"},
        "flow/dataflow.yaml": {"dataflow_edges: {}"},
        "flow/golden_model.yaml": {"golden_steps: {}"},
        "flow/numerical_model.yaml": {"dtype_policy: []"},
        "kernel/paths.yaml": {"kernel_paths: {}"},
        "kernel/pipeline.yaml": {"pipelines: {}"},
        "kernel/resources.yaml": {"buffers: {}"},
    }
    if rel_path == "tiling/key_space.yaml":
        # key_space is now encoding-only; a draft is macro unknown + no fields.
        if "encoding:\n  macro: unknown" in stripped and "fields: {}" in stripped:
            return True
        return False
    if rel_path == "tiling/exhaustive_key_space.yaml":
        if (
            "status: pending" in stripped
            or "template_blocks: []" in stripped
            or "expanded_key_count: 0" in stripped
            or "status: unknown" in stripped
        ):
            return True
        return False
    if rel_path == "tiling/variables.yaml":
        # Step 1 draft: no variables and mechanism entry still unknown.
        if "variables: {}" in stripped and "entry: {file: unknown" in stripped:
            return True
        if "variables: {}" in stripped:
            return True
        return False
    if rel_path == "tiling/constraints.yaml":
        # Step 2 draft: relations empty, input_realization empty, pruning/merging unanswered.
        if (
            "relations: []" in stripped
            and "input_realization: {}" in stripped
            and "performed: unknown" in stripped
        ):
            return True
        return False
    if rel_path == "tiling/coverage_model.yaml":
        if "family_obligations: []" in stripped and "key_relation_obligations: []" in stripped:
            return True
        if "family_obligations: []" in stripped:
            return True
        return False
    for marker in placeholders.get(rel_path, set()):
        if marker in stripped:
            return True
    if rel_path.endswith("frontier.yaml") and "frontier_nodes: []" in stripped:
        return True
    if rel_path.endswith("dispatch_variables.yaml") and re.search(r"(?m)^variables:\s*\[\]\s*(?:#.*)?$", stripped):
        return True
    if rel_path.endswith("predicate_space.yaml") and "predicate_atoms: []" in stripped:
        return True
    # compile_time_bindings: empty macros+constexpr+templates with no unresolved is lazy
    if rel_path.endswith("compile_time_bindings.yaml"):
        if (
            "macros: []" in stripped
            and "constexpr_constants: []" in stripped
            and "instantiations: []" in stripped
            and "unresolved_symbols: []" in stripped
        ):
            return True
    return False

def _completion_ok(
    path: Path,
    expected_subagent: str,
    required_artifacts: list[str] | None = None,
) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing completion manifest: {path.as_posix()}"
    data = _load_json(path)
    if data.get("status") != "complete":
        return False, f"incomplete manifest: {path.as_posix()} status={data.get('status')!r}"
    if data.get("subagent") != expected_subagent:
        return False, f"unexpected subagent in {path.name}: {data.get('subagent')!r}"
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not all(isinstance(item, str) and item.strip() for item in artifacts):
        return False, f"completion manifest has invalid artifacts list: {path.as_posix()}"
    if required_artifacts:
        omitted = sorted(set(required_artifacts) - set(artifacts))
        if omitted:
            return False, f"completion manifest missing artifacts: {', '.join(omitted)}"
    if expected_subagent == "uo-host-extraction":
        archive = data.get("archive_artifacts") or []
        required = set(REQUIRED_TILING_ARCHIVE_FILES)
        if not required.issubset(set(archive)):
            missing = sorted(required - set(archive))
            return False, f"host completion missing archive_artifacts: {', '.join(missing)}"
    return True, ""


def verify_host_flow_barrier(uo_root: Path) -> BarrierResult:
    missing: list[str] = []
    stale: list[str] = []

    for rel in HOST_FLOW_ARTIFACTS + FLOW_ARTIFACTS:
        path = uo_root / rel
        if not path.exists():
            missing.append(rel)
            continue
        text = read_text(path)
        yaml_problem = _yaml_problem(rel, text)
        if yaml_problem:
            stale.append(f"{rel} ({yaml_problem})")
            for error in _yaml_gate_errors(rel, text, phase=PHASE_HOST_FLOW):
                stale.append(f"{rel} ({error.code})")
            continue
        for problem in _id_contract_problems(rel, text):
            stale.append(f"{rel} ({problem})")
        for problem in _proposal_contract_problems(rel, text):
            stale.append(f"{rel} ({problem})")
        for problem in _semantic_contract_problems(rel, text):
            stale.append(f"{rel} ({problem})")
        if _is_placeholder(rel, text):
            stale.append(rel)

    if not _flow_has_golden_mapping(uo_root):
        stale.append("flow compute_graph/golden_model missing compute-to-golden mapping")

    for rel, expected, required in (
        (HOST_FLOW_COMPLETION, "uo-host-extraction", HOST_FLOW_ARTIFACTS[:-len(REQUIRED_TILING_ARCHIVE_FILES)]),
        (FLOW_COMPLETION, "uo-flow-extraction", FLOW_ARTIFACTS),
    ):
        ok, reason = _completion_ok(uo_root / rel, expected, required)
        if not ok:
            missing.append(reason)

    ok = not missing and not stale
    if ok:
        message = "host_flow barrier passed"
    else:
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if stale:
            parts.append(f"still placeholder: {', '.join(stale)}")
        message = "; ".join(parts)
    errors = []
    for item in missing + stale:
        rel = item.split(" ", 1)[0]
        if rel.endswith((".yaml", ".yml")):
            errors.append(owner_retry_report({"artifact": rel, "error_code": "MANIFEST_INCOMPLETE", "error_message": item}, phase=PHASE_HOST_FLOW))
    return BarrierResult(ok, PHASE_HOST_FLOW, missing, stale, message, errors)


def verify_kernel_path_barrier(uo_root: Path, task_ids: list[str]) -> BarrierResult:
    """Accept either merged canonical kernel/*.yaml or per-task raw agent outputs."""
    missing: list[str] = []
    stale: list[str] = []

    paths_yaml = uo_root / "kernel" / "paths.yaml"
    pipeline_yaml = uo_root / "kernel" / "pipeline.yaml"
    resources_yaml = uo_root / "kernel" / "resources.yaml"
    canonical_ready = all(p.exists() and not _is_placeholder(p.relative_to(uo_root).as_posix(), read_text(p)) for p in (paths_yaml, pipeline_yaml, resources_yaml))

    if canonical_ready:
        for path in (paths_yaml, pipeline_yaml, resources_yaml):
            rel = path.relative_to(uo_root).as_posix()
            text = read_text(path)
            problem = _yaml_problem(rel, text)
            if problem:
                stale.append(f"{rel} ({problem})")
                continue
            for error in _yaml_gate_errors(rel, text, phase=PHASE_KERNEL_PATH):
                stale.append(f"{rel} ({error.code}: {error.message})")
            for detail in _id_contract_problems(rel, text) + _semantic_contract_problems(rel, text):
                stale.append(f"{rel} ({detail})")
        # ensure each approved task appears in paths.yaml
        text = read_text(paths_yaml)
        for task_id in task_ids:
            task_id = task_id.strip()
            if not task_id:
                continue
            if task_id not in text and not re.search(rf"(?m)^\s*{re.escape(task_id)}\s*:", text):
                # also allow Kxxx ids mapped via stable_key / name
                missing.append(f"kernel/paths.yaml missing task {task_id}")
            completion_rel = f"archive/raw_agents/kernel_paths/.uo_kernel_path_{task_id}_complete.json"
            legacy_completion = f"kernel/paths/.uo_kernel_path_{task_id}_complete.json"
            expected_raw = [
                f"archive/raw_agents/kernel_paths/{task_id}_kernel_path.yaml",
                f"archive/raw_agents/kernel_paths/{task_id}_kernel_path.md",
            ]
            ok_raw, _ = _completion_ok(uo_root / completion_rel, "uo-kernel-path", expected_raw)
            ok_legacy, reason = _completion_ok(uo_root / legacy_completion, "uo-kernel-path")
            if not ok_raw and not ok_legacy:
                # if host aggregator merged, allow missing per-task completion when aggregator manifest exists
                agg = uo_root / "kernel" / ".uo_kernel_alignment_complete.json"
                if not agg.exists():
                    missing.append(reason if reason else f"missing completion for {task_id}")
    else:
        # fall back to per-task raw outputs under archive or legacy kernel/paths
        for task_id in task_ids:
            task_id = task_id.strip()
            if not task_id:
                continue
            candidates = [
                f"archive/raw_agents/kernel_paths/{task_id}_kernel_path.yaml",
                f"kernel/paths/{task_id}_kernel_path.yaml",
            ]
            found = False
            for rel in candidates:
                path = uo_root / rel
                if not path.exists():
                    continue
                text = read_text(path)
                yaml_problem = _yaml_problem(rel, text)
                if yaml_problem:
                    stale.append(f"{rel} ({yaml_problem})")
                    continue
                for error in _yaml_gate_errors(rel, text, phase=PHASE_KERNEL_PATH):
                    stale.append(f"{rel} ({error.code}: {error.message})")
                for problem in _id_contract_problems(rel, text):
                    stale.append(f"{rel} ({problem})")
                for problem in _semantic_contract_problems(rel, text):
                    stale.append(f"{rel} ({problem})")
                if text.strip():
                    found = True
                    break
            if not found:
                missing.append(f"raw/canonical kernel path missing for {task_id}")
            for completion_rel in (
                f"archive/raw_agents/kernel_paths/.uo_kernel_path_{task_id}_complete.json",
                f"kernel/paths/.uo_kernel_path_{task_id}_complete.json",
            ):
                expected_raw = [
                    f"archive/raw_agents/kernel_paths/{task_id}_kernel_path.yaml",
                    f"archive/raw_agents/kernel_paths/{task_id}_kernel_path.md",
                ] if completion_rel.startswith("archive/") else None
                ok, reason = _completion_ok(uo_root / completion_rel, "uo-kernel-path", expected_raw)
                if ok:
                    break
            else:
                missing.append(reason)

        for rel in KERNEL_CANONICAL:
            if not (uo_root / rel).exists():
                stale.append(f"{rel} not merged yet (raw agent outputs present)")

    ok = not missing and not stale
    message = "kernel_path barrier passed" if ok else f"missing: {', '.join(missing + stale)}"
    errors = []
    for item in missing + stale:
        rel = item.split(" ", 1)[0]
        if rel.endswith((".yaml", ".yml")):
            code = _stale_error_code(item)
            errors.append(owner_retry_report({"artifact": rel, "error_code": code, "error_message": item}, phase=PHASE_KERNEL_PATH))
    return BarrierResult(ok, PHASE_KERNEL_PATH, missing, stale, message, errors)


def write_barrier_report(uo_root: Path, result: BarrierResult) -> Path:
    report = {
        "phase": result.phase,
        "ok": result.ok,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "missing": result.missing,
        "stale": result.stale,
        "errors": result.errors or [],
        "message": result.message,
    }
    out_dir = uo_root / "archive" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"barrier_{result.phase}.json"
    write_json(out, report)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify subagent completion before host continues.")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--phase", choices=[PHASE_HOST_FLOW, PHASE_KERNEL_PATH], required=True)
    parser.add_argument("--task-ids", help="Comma-separated task ids for kernel_path phase")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = operator_root(repo_root, op_name)

    if args.phase == PHASE_HOST_FLOW:
        result = verify_host_flow_barrier(uo_root)
    else:
        task_ids = [item.strip() for item in (args.task_ids or "").split(",") if item.strip()]
        if not task_ids:
            task_ids = _approved_task_ids(uo_root)
        if not task_ids:
            result = BarrierResult(False, PHASE_KERNEL_PATH, ["approved_task_ids"], [], "no approved task ids")
        else:
            result = verify_kernel_path_barrier(uo_root, task_ids)

    report_path = write_barrier_report(uo_root, result)
    print(json.dumps({"ok": result.ok, "phase": result.phase, "message": result.message, "report": str(report_path)}, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
