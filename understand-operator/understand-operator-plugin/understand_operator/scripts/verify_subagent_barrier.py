from __future__ import annotations

import json
import hashlib
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
    parts = rel_path.replace("\\", "/").split("/")
    problems: list[str] = []
    if len(parts) < 4 or not parts[2]:
        problems.append("proposal must live under archive/proposals/<run_id>/; root proposal paths are obsolete")
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
    if rel_path.endswith("/flow_dataflow_proposal.yaml"):
        required_updates = {
            ("registry/evidence.yaml", "evidence"),
            ("evidence/fact_index.yaml", "facts"),
            ("evidence/source_index.yaml", "source_spans"),
        }
        actual = {
            (str(update.get("target") or ""), str(update.get("section") or ""))
            for update in updates
            if isinstance(update, dict)
        }
        missing_updates = sorted(required_updates - actual)
        if missing_updates:
            problems.append(
                "flow proposal missing evidence canonical_updates: "
                + ", ".join(f"{target}:{section}" for target, section in missing_updates)
            )
    return problems[:12]


def _entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


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


def _flow_proposal_has_golden_mapping(uo_root: Path, rel: str) -> bool:
    if yaml is None:
        return False
    try:
        proposal = yaml.safe_load(read_text(uo_root / rel)) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(proposal, dict):
        return False
    for update in _as_list(proposal.get("canonical_updates")):
        if not isinstance(update, dict):
            continue
        if update.get("target") == "flow/compute_graph.yaml":
            for entry in _as_list(update.get("entries")):
                if isinstance(entry, dict) and (entry.get("golden_step_ref") or entry.get("golden_role")):
                    return True
        if update.get("target") == "flow/golden_model.yaml":
            for entry in _as_list(update.get("entries")):
                if isinstance(entry, dict) and (entry.get("maps_to_compute_steps") or entry.get("golden_generation_contract")):
                    return True
    return False


@dataclass
class BarrierResult:
    ok: bool
    phase: str
    missing: list[str]
    stale: list[str]
    message: str
    errors: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class RunContext:
    run_id: str
    source_commit: str = ""
    started_at: datetime | None = None


def host_proposal_rel(run_id: str) -> str:
    return f"archive/proposals/{run_id}/host_tiling_proposal.yaml"


def flow_proposal_rel(run_id: str) -> str:
    return f"archive/proposals/{run_id}/flow_dataflow_proposal.yaml"


def phase5_proposal_rel(run_id: str) -> str:
    return f"archive/proposals/{run_id}/phase5_kernel_alignment_proposal.yaml"


def _host_flow_artifacts(run_id: str) -> tuple[list[str], list[str]]:
    return [host_proposal_rel(run_id)] + list(REQUIRED_TILING_ARCHIVE_FILES), [flow_proposal_rel(run_id)]


def _approved_task_ids(uo_root: Path) -> list[str]:
    # Retired kernel dispatch review compatibility path.
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


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_run_context(uo_root: Path, run_id: str, source_commit: str = "") -> RunContext:
    state = _load_yaml_mapping(uo_root / "archive" / "runs" / run_id / "workflow_state.yaml")
    commit = source_commit or str(state.get("source_commit") or "")
    started = _parse_iso8601(state.get("started_at"))
    return RunContext(run_id=run_id, source_commit=commit, started_at=started)


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

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _manifest_paths(items: Any) -> dict[str, str]:
    if not isinstance(items, list):
        return {}
    paths: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "").replace("\\", "/")
        digest = str(item.get("sha256") or "")
        if rel:
            paths[rel] = digest
    return paths


def _completion_ok(
    uo_root: Path,
    path: Path,
    expected_subagent: str,
    ctx: RunContext,
    *,
    required_artifacts: list[str] | None = None,
    archive_artifacts: list[str] | None = None,
    proposal_rel: str | None = None,
) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing completion manifest: {path.as_posix()}"
    data = _load_json(path)
    if data.get("status") != "complete":
        return False, f"incomplete manifest: {path.as_posix()} status={data.get('status')!r}"
    if data.get("run_id") != ctx.run_id:
        return False, f"manifest run_id mismatch: {path.as_posix()} run_id={data.get('run_id')!r} expected={ctx.run_id!r}"
    if data.get("subagent") != expected_subagent:
        return False, f"unexpected subagent in {path.name}: {data.get('subagent')!r}"
    source_commit = str(data.get("source_commit") or "")
    if not source_commit:
        return False, f"manifest missing source_commit: {path.as_posix()}"
    if ctx.source_commit and source_commit != ctx.source_commit:
        return False, f"manifest source_commit mismatch: {path.as_posix()} source_commit={source_commit!r} expected={ctx.source_commit!r}"
    completed_at = _parse_iso8601(data.get("completed_at"))
    if completed_at is None:
        return False, f"manifest missing or invalid completed_at: {path.as_posix()}"
    if ctx.started_at and completed_at < ctx.started_at:
        return False, f"manifest completed_at predates current run: {path.as_posix()}"
    artifacts = _manifest_paths(data.get("artifacts"))
    if not artifacts:
        return False, f"completion manifest has invalid artifacts list: {path.as_posix()}"
    archive = _manifest_paths(data.get("archive_artifacts"))
    if required_artifacts:
        omitted = sorted(set(required_artifacts) - set(artifacts))
        if omitted:
            return False, f"completion manifest missing artifacts: {', '.join(omitted)}"
    if archive_artifacts:
        omitted_archive = sorted(set(archive_artifacts) - set(archive))
        if omitted_archive:
            return False, f"completion manifest missing archive_artifacts: {', '.join(omitted_archive)}"
    for rel, expected_hash in {**artifacts, **archive}.items():
        target = uo_root / rel
        if not target.exists():
            return False, f"manifest artifact missing on disk: {rel}"
        actual_hash = _sha256(target)
        if expected_hash != actual_hash:
            return False, f"manifest artifact hash mismatch: {rel}"
    if proposal_rel:
        proposal_hash = str(data.get("proposal_hash") or "")
        expected = artifacts.get(proposal_rel) or archive.get(proposal_rel)
        if not proposal_hash or proposal_hash != expected:
            return False, f"proposal_hash mismatch in manifest: {path.as_posix()}"
    return True, ""


def verify_host_flow_barrier(uo_root: Path, ctx: RunContext) -> BarrierResult:
    missing: list[str] = []
    stale: list[str] = []
    host_artifacts, flow_artifacts = _host_flow_artifacts(ctx.run_id)

    for rel in host_artifacts + flow_artifacts:
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

    if not _flow_proposal_has_golden_mapping(uo_root, flow_proposal_rel(ctx.run_id)):
        stale.append("flow proposal missing compute-to-golden mapping")

    for rel, expected, required in (
        (HOST_FLOW_COMPLETION, "uo-host-extraction", [host_proposal_rel(ctx.run_id)]),
        (FLOW_COMPLETION, "uo-flow-extraction", [flow_proposal_rel(ctx.run_id)]),
    ):
        ok, reason = _completion_ok(
            uo_root,
            uo_root / rel,
            expected,
            ctx,
            required_artifacts=required,
            archive_artifacts=list(REQUIRED_TILING_ARCHIVE_FILES) if expected == "uo-host-extraction" else None,
            proposal_rel=required[0],
        )
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
            errors.append(owner_retry_report({"artifact": rel, "error_code": _stale_error_code(item), "error_message": item}, phase=PHASE_HOST_FLOW, run_id=ctx.run_id))
    return BarrierResult(ok, PHASE_HOST_FLOW, missing, stale, message, errors)


def verify_kernel_path_barrier(uo_root: Path, task_ids: list[str], ctx: RunContext) -> BarrierResult:
    """Verify per-task raw agent outputs for the current run.

    Kernel canonical files and the host alignment aggregator are deliberately
    ignored here. They are products of later compiler phases and must not
    satisfy the raw subagent barrier.
    """
    missing: list[str] = []
    stale: list[str] = []

    for task_id in task_ids:
        task_id = task_id.strip()
        if not task_id:
            continue
        yaml_rel = f"archive/raw_agents/kernel_paths/{task_id}_kernel_path.yaml"
        md_rel = f"archive/raw_agents/kernel_paths/{task_id}_kernel_path.md"
        completion_rel = f"archive/raw_agents/kernel_paths/.uo_kernel_path_{task_id}_complete.json"
        yaml_path = uo_root / yaml_rel
        if not yaml_path.exists():
            missing.append(yaml_rel)
        else:
            text = read_text(yaml_path)
            yaml_problem = _yaml_problem(yaml_rel, text)
            if yaml_problem:
                stale.append(f"{yaml_rel} ({yaml_problem})")
            else:
                for error in _yaml_gate_errors(yaml_rel, text, phase=PHASE_KERNEL_PATH):
                    stale.append(f"{yaml_rel} ({error.code}: {error.message})")
                for problem in _id_contract_problems(yaml_rel, text):
                    stale.append(f"{yaml_rel} ({problem})")
                for problem in _semantic_contract_problems(yaml_rel, text):
                    stale.append(f"{yaml_rel} ({problem})")
        if not (uo_root / md_rel).exists():
            missing.append(md_rel)
        ok, reason = _completion_ok(
            uo_root,
            uo_root / completion_rel,
            "uo-kernel-path",
            ctx,
            required_artifacts=[yaml_rel, md_rel],
        )
        if not ok:
            missing.append(reason)

    ok = not missing and not stale
    message = "kernel_path barrier passed" if ok else f"missing: {', '.join(missing + stale)}"
    errors = []
    for item in missing + stale:
        rel = item.split(" ", 1)[0]
        if rel.endswith((".yaml", ".yml")):
            code = _stale_error_code(item)
            errors.append(owner_retry_report({"artifact": rel, "error_code": code, "error_message": item, "owner": "uo-kernel-path"}, phase=PHASE_KERNEL_PATH, run_id=ctx.run_id))
    return BarrierResult(ok, PHASE_KERNEL_PATH, missing, stale, message, errors)


def write_barrier_report(uo_root: Path, result: BarrierResult, ctx: RunContext) -> Path:
    report = {
        "phase": result.phase,
        "run_id": ctx.run_id,
        "source_commit": ctx.source_commit,
        "ok": result.ok,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "missing": result.missing,
        "stale": result.stale,
        "errors": result.errors or [],
        "message": result.message,
    }
    out_dir = uo_root / "archive" / "runs" / ctx.run_id
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
    parser.add_argument("--run-id", required=True, help="Current workflow run id; barrier only accepts artifacts from this run")
    parser.add_argument("--source-commit", help="Workflow source commit; defaults to archive/runs/<run_id>/workflow_state.yaml")
    parser.add_argument("--task-ids", help="Comma-separated task ids for kernel_path phase")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = operator_root(repo_root, op_name)
    ctx = _load_run_context(uo_root, args.run_id, args.source_commit or "")

    if args.phase == PHASE_HOST_FLOW:
        result = verify_host_flow_barrier(uo_root, ctx)
    else:
        task_ids = [item.strip() for item in (args.task_ids or "").split(",") if item.strip()]
        if not task_ids:
            task_ids = _approved_task_ids(uo_root)
        if not task_ids:
            result = BarrierResult(False, PHASE_KERNEL_PATH, ["approved_task_ids"], [], "no approved task ids")
        else:
            result = verify_kernel_path_barrier(uo_root, task_ids, ctx)

    report_path = write_barrier_report(uo_root, result, ctx)
    print(json.dumps({"ok": result.ok, "phase": result.phase, "message": result.message, "report": str(report_path)}, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
