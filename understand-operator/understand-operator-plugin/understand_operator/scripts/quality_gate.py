from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import (
    CANONICAL_EVIDENCE_FILES,
    CANONICAL_FLOW_FILES,
    CANONICAL_KERNEL_FILES,
    CANONICAL_CONTRACT_FILES,
    CANONICAL_CROSS_LAYER_FILES,
    CANONICAL_QUERY_FILES,
    CANONICAL_REGISTRY_FILES,
    CANONICAL_ROOT_FILES,
    CANONICAL_TEST_FILES,
    CANONICAL_TILING_FILES,
    REQUIRED_TILING_ARCHIVE_FILES,
    existing_operator_root,
    read_text,
    resolve_existing_operator_root,
    safe_op_name,
    write_text,
)
from understand_operator._operator.evidence import validate_evidence_closure
from understand_operator._operator.yaml_gate import artifact_owner

_LAST_COMPILER_ISSUES: list[object] = []
from understand_operator._operator.kb_compiler import RELATION_TYPES

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

FORBIDDEN_TEST_FIELDS = (
    "generated_cases",
    "actual_test_result",
    "observed_coverage",
    "case_csv",
)
MOJIBAKE_MARKERS = ("鈥", "鈫", "锟", "\ufffd")
KEY_CONFIDENCE_SCORES = (
    "tiling_confidence",
    "kernel_confidence",
    "evidence_confidence",
    "test_contract_confidence",
)
GREEN_CONFIDENCE_FLOOR = 0.6

LEGACY_REQUIRED_MARKERS = [
    "summary/operator_io.yaml",
    "flows/compute_flow.yaml",
    "testing_hints/golden_hint.yaml",
    "kernel/kernel_task_plan.yaml",
    "route.json",
    "quality_gate.yaml",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run understand-operator canonical KB quality gate")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    resolved = resolve_existing_operator_root(repo_root, op_name)
    if resolved is None:
        base = existing_operator_root(repo_root, op_name)
        print(f"KB not found: {base}")
        print("Run /uo-init first, or pass the canonical --op-name used by the existing KB.")
        return 2
    op_name, base = resolved

    blockers: list[str] = []
    warnings: list[str] = []
    checks: dict[str, str] = {}

    canonical = (
        CANONICAL_ROOT_FILES
        + CANONICAL_TILING_FILES
        + CANONICAL_FLOW_FILES
        + CANONICAL_KERNEL_FILES
        + CANONICAL_TEST_FILES
        + CANONICAL_EVIDENCE_FILES
        + CANONICAL_REGISTRY_FILES
        + CANONICAL_CROSS_LAYER_FILES
        + CANONICAL_QUERY_FILES
        + CANONICAL_CONTRACT_FILES
    )

    missing = [rel for rel in canonical if not (base / rel).exists()]
    if missing:
        legacy = [m for m in LEGACY_REQUIRED_MARKERS if (base / m).exists()]
        hint = (
            " Legacy artifacts detected; run /uo-update or /uo-init to regenerate canonical KB."
            if legacy
            else ""
        )
        blockers.append(f"canonical files missing: {', '.join(missing[:8])}{'...' if len(missing) > 8 else ''}.{hint}")
        checks["canonical_files_present"] = "fail"
    else:
        checks["canonical_files_present"] = "pass"

    parsed: dict[str, object] = {}
    yaml_fail = False
    for rel in canonical:
        path = base / rel
        if not path.exists():
            continue
        text = read_text(path)
        if rel.endswith((".yaml", ".yml")):
            if yaml is None:
                warnings.append("PyYAML not installed; yaml_parse check degraded to text presence")
                parsed[rel] = text
                continue
            try:
                data = yaml.safe_load(text) if text.strip() else None
                if data is None and text.strip():
                    yaml_fail = True
                    blockers.append(f"YAML parse returned null: {rel}")
                parsed[rel] = data
            except Exception as exc:  # noqa: BLE001
                yaml_fail = True
                blockers.append(f"YAML parse failed for {rel}: {exc}")
        else:
            parsed[rel] = text
    checks["yaml_parse"] = "fail" if yaml_fail else "pass"

    # route integrity
    index = parsed.get("index.yaml")
    if isinstance(index, dict):
        cf = index.get("canonical_files") or {}
        bad = []
        if isinstance(cf, dict):
            for _key, rel in cf.items():
                if isinstance(rel, str) and not (base / rel).exists():
                    bad.append(rel)
        checks["route_integrity"] = "fail" if bad else "pass"
        if bad:
            blockers.append("index.yaml canonical_files missing on disk: " + ", ".join(bad[:6]))
        # domain index qa_routes
        domain_bad = _check_domain_indexes(base, warnings)
        checks["domain_index_integrity"] = "fail" if domain_bad else "pass"
        if domain_bad:
            warnings.append("domain index qa_routes reference missing files: " + ", ".join(domain_bad[:6]))
    else:
        checks["route_integrity"] = "fail"
        checks["domain_index_integrity"] = "fail"
        blockers.append("index.yaml missing or unreadable")

    operator = parsed.get("operator.yaml")
    if isinstance(operator, dict):
        io = operator.get("io") or {}
        if isinstance(io, dict):
            if not io.get("required_inputs"):
                blockers.append("operator.yaml io.required_inputs is empty")
            if not io.get("outputs"):
                blockers.append("operator.yaml io.outputs is empty")
    else:
        blockers.append("operator.yaml missing or unreadable")

    # evidence / source locator checks (lightweight)
    fact_index = parsed.get("evidence/fact_index.yaml")
    source_index = parsed.get("evidence/source_index.yaml")
    evidence_ok, locator_ok = _check_evidence(
        parsed.get("registry/evidence.yaml"),
        fact_index,
        source_index,
        parsed,
        warnings,
        blockers,
    )
    checks["evidence_refs_resolve"] = "pass" if evidence_ok else "fail"
    checks["source_locators_present_for_key_facts"] = "pass" if locator_ok else "fail"

    deps = parsed.get("evidence/artifact_dependencies.yaml")
    if isinstance(deps, dict) and (deps.get("dependencies") is not None or deps.get("artifact_to_source")):
        checks["artifact_dependencies_present"] = "pass"
    else:
        checks["artifact_dependencies_present"] = "fail"
        warnings.append("evidence/artifact_dependencies.yaml is empty or missing structure")

    # no legacy required outputs as primary
    legacy_present = [m for m in LEGACY_REQUIRED_MARKERS if (base / m).exists() and not (base / "archive" / "legacy").joinpath(Path(m).name).exists()]
    # tolerate legacy only under archive; warn if still at old paths
    live_legacy = [m for m in LEGACY_REQUIRED_MARKERS if (base / m).exists()]
    if live_legacy and missing:
        checks["no_legacy_required_outputs"] = "fail"
        warnings.append("legacy primary artifacts still present: " + ", ".join(live_legacy[:5]))
    else:
        checks["no_legacy_required_outputs"] = "pass"

    # test contract forbidden fields
    contract_text = read_text(base / "test" / "contract.yaml")
    forbidden_hit = [f for f in FORBIDDEN_TEST_FIELDS if re.search(rf"(?m)^\s*{f}\s*:", contract_text)]
    if forbidden_hit:
        checks["no_generated_tests_in_uo"] = "fail"
        blockers.append("test/contract.yaml contains forbidden fields: " + ", ".join(forbidden_hit))
    else:
        checks["no_generated_tests_in_uo"] = "pass"

    golden_text = read_text(base / "flow" / "golden_model.yaml")
    if "def " in golden_text or "import torch" in golden_text or "generated_code:" in golden_text:
        checks["no_generated_golden_code_in_uo"] = "fail"
        blockers.append("flow/golden_model.yaml appears to contain generated golden code")
    else:
        checks["no_generated_golden_code_in_uo"] = "pass"

    # tiling rules
    coverage = read_text(base / "tiling" / "coverage_model.yaml")
    families = read_text(base / "tiling" / "families.yaml")
    key_space = read_text(base / "tiling" / "key_space.yaml")
    if "already covered" in coverage.lower() or "observed_coverage" in coverage.lower():
        checks["family_not_equal_key_coverage_rule"] = "fail"
        warnings.append("coverage_model.yaml must declare obligations only, not observed coverage")
    else:
        checks["family_not_equal_key_coverage_rule"] = "pass"

    seed_section = _top_level_section(coverage, "seed_cases")
    seed_count = len(re.findall(r"(?m)^\s*-\s+", seed_section))
    family_ids_for_seed = _family_ids(parsed.get("tiling/families.yaml"))
    family_count = len(family_ids_for_seed)
    if family_count and seed_count > max(10, family_count * 5) and "role:" not in coverage.lower():
        checks["branch_matrix_not_full_enum_rule"] = "fail"
        warnings.append("seed_cases look like full enumeration instead of representative samples")
    else:
        checks["branch_matrix_not_full_enum_rule"] = "pass"

    if not key_space.strip() or ("fields:" not in key_space and "fields_order:" not in key_space):
        warnings.append("tiling/key_space.yaml missing fields definition")

    # REQUIRED tiling archive intermediates (anti-laziness for macros / constexpr)
    archive_fail = _check_tiling_archive(base, warnings, blockers)
    checks["tiling_archive_intermediates"] = "fail" if archive_fail else "pass"

    # Two-step tiling logic: variables.yaml (step1) + constraints.yaml (step2)
    key_logic = _check_key_logic_relations(
        parsed.get("tiling/variables.yaml"),
        parsed.get("tiling/key_space.yaml"),
        parsed.get("tiling/constraints.yaml"),
        parsed.get("tiling/coverage_model.yaml"),
        parsed.get("tiling/families.yaml"),
        warnings,
        blockers,
    )
    checks.update(key_logic)
    checks.update(
        _check_exhaustive_tiling_key_model(
            parsed.get("tiling/exhaustive_key_space.yaml"),
            parsed.get("tiling/key_space.yaml"),
            parsed.get("tiling/constraints.yaml"),
            warnings,
            blockers,
        )
    )

    # golden / kernel alignment presence
    compute_graph = read_text(base / "flow" / "compute_graph.yaml")
    if _has_compute_golden_mapping(
        parsed.get("flow/compute_graph.yaml"), parsed.get("flow/golden_model.yaml")
    ):
        checks["golden_model_has_compute_mapping"] = "pass"
    else:
        checks["golden_model_has_compute_mapping"] = "fail"
        blockers.append("compute_graph/golden_model missing compute-to-golden mapping")

    pipeline = read_text(base / "kernel" / "pipeline.yaml")
    if _has_nonempty_collection(
        _as_mapping(parsed.get("kernel/pipeline.yaml")).get("compute_step_alignment")
    ):
        checks["kernel_pipeline_has_compute_alignment"] = "pass"
    else:
        checks["kernel_pipeline_has_compute_alignment"] = "fail"
        blockers.append("kernel/pipeline.yaml missing compute_step_alignment entries")

    resources = read_text(base / "kernel" / "resources.yaml")
    if _has_resource_flow(parsed.get("kernel/resources.yaml")):
        checks["resources_have_producer_consumer"] = "pass"
    else:
        checks["resources_have_producer_consumer"] = "fail"
        blockers.append("kernel/resources.yaml missing producer/consumer/sync relations")

    # route.md length
    route_md = read_text(base / "route.md")
    route_lines = len([ln for ln in route_md.splitlines() if ln.strip()])
    if route_lines > 220:
        warnings.append(f"route.md looks like a long report ({route_lines} non-empty lines); keep 100-200")

    # kernel paths vs families
    paths = read_text(base / "kernel" / "paths.yaml")
    planned = _planned_family_ids(parsed.get("kernel/paths.yaml"))
    family_ids = _family_ids(parsed.get("tiling/families.yaml"))
    if family_ids and "normal_kernel_task" in families.lower():
        missing_map = sorted(fid for fid in family_ids if fid not in planned)
        if missing_map:
            warnings.append("some families have no kernel path mapping yet: " + ", ".join(missing_map[:5]))

    compiler_checks = _run_kb_compiler(base, op_name, warnings, blockers)
    checks.update(compiler_checks)
    checks.update(_check_cross_layer_graph_completeness(base, warnings, blockers))
    checks.update(_check_text_encoding(base, warnings))

    scores = {
        "boundary_confidence": _score_text(read_text(base / "operator.yaml")),
        "tiling_confidence": _score_text(families + key_space + coverage),
        "compute_confidence": _score_text(compute_graph),
        "dataflow_confidence": _score_text(read_text(base / "flow" / "dataflow.yaml")),
        "golden_model_confidence": _score_text(golden_text),
        "kernel_confidence": _score_text(paths + pipeline + resources),
        "evidence_confidence": _score_text(read_text(base / "evidence" / "fact_index.yaml")),
        "test_contract_confidence": _score_text(contract_text),
    }
    if any(scores.get(key, 0.0) < GREEN_CONFIDENCE_FLOOR for key in KEY_CONFIDENCE_SCORES):
        warnings.append(
            "key confidence scores below green threshold: "
            + ", ".join(f"{key}={scores.get(key, 0.0)}" for key in KEY_CONFIDENCE_SCORES if scores.get(key, 0.0) < GREEN_CONFIDENCE_FLOOR)
        )

    if blockers:
        status = "red"
        decision = "not_usable"
    elif warnings:
        status = "yellow"
        decision = "usable_for_query"
        if checks.get("golden_model_has_compute_mapping") == "pass":
            decision = "usable_for_golden_with_review"
        if checks.get("kernel_pipeline_has_compute_alignment") == "pass":
            decision = "usable_for_testgenerate_with_review"
    else:
        status = "green"
        decision = "usable_for_testgenerate"

    body = _render_quality(
        op_name=op_name,
        status=status,
        scores=scores,
        checks=checks,
        blockers=blockers,
        warnings=warnings,
        decision=decision,
    )
    write_text(base / "quality.yaml", body)
    if status == "red":
        _write_red_gate_repair_queue(base, blockers)
    print(f"Quality gate: {status} / {decision} -> {base / 'quality.yaml'}")
    return 0 if status != "red" else 2


def _write_red_gate_repair_queue(base: Path, blockers: list[str]) -> None:
    grouped: dict[str, list[dict[str, str]]] = {}
    for issue in _LAST_COMPILER_ISSUES:
        if getattr(issue, "severity", "") != "error":
            continue
        artifact = str(getattr(issue, "artifact", "") or "archive/runs/kb_compile_report.yaml")
        target = str(getattr(issue, "target", "") or "")
        owner = str(getattr(issue, "owner", "") or artifact_owner(artifact))
        grouped.setdefault(owner, []).append(
            {
                "phase": str(getattr(issue, "phase", "") or ""),
                "artifact": artifact,
                "target": target,
                "error_code": str(getattr(issue, "code", "") or "COMPILER_ERROR"),
                "message": str(getattr(issue, "message", "") or ""),
                "retry_task_id": str(getattr(issue, "retry_task_id", "") or _retry_task_id(owner, artifact)),
                "allowed_repair_scope": "owner_retry",
            }
        )
    for blocker in blockers:
        artifact = _artifact_from_blocker(blocker)
        if any(item.get("message") == blocker for items in grouped.values() for item in items):
            continue
        if not artifact:
            artifact = "archive/runs/kb_compile_report.yaml"
        owner = artifact_owner(artifact)
        grouped.setdefault(owner, []).append(
            {
                "artifact": artifact,
                "target": "",
                "error_code": "QUALITY_BLOCKER",
                "message": blocker,
                "retry_task_id": _retry_task_id(owner, artifact),
                "allowed_repair_scope": "owner_retry",
                "repair_action": "resume owner and rerun phase barrier, final compiler, and quality gate",
            }
        )
    payload = {
        "version": 1,
        "status": "blocked",
        "error_code": "RED_GATE_REMEDIATION_INCOMPLETE",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "groups": grouped,
    }
    if yaml is not None:
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    else:
        import json

        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    write_text(base / "archive" / "runs" / "red_gate_repair_queue.yaml", text)


def _retry_task_id(owner: str, artifact: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", artifact).strip("_").lower() or "artifact"
    return f"retry_{owner}_{slug}"


def _artifact_from_blocker(blocker: str) -> str:
    match = re.search(r"\(([^()]+\.(?:yaml|yml|md))\)", blocker)
    if match:
        return match.group(1).replace("\\", "/")
    match = re.search(r"\b((?:registry|tiling|flow|kernel|cross_layer|query|contracts|evidence|test)/[A-Za-z0-9_./-]+\.(?:yaml|yml|md))\b", blocker)
    if match:
        return match.group(1).replace("\\", "/")
    return "quality.yaml"


def _check_tiling_archive(base: Path, warnings: list[str], blockers: list[str]) -> bool:
    """Return True if archive intermediates are missing/placeholder (check failed)."""
    failed = False
    for rel in REQUIRED_TILING_ARCHIVE_FILES:
        path = base / rel
        if not path.exists():
            failed = True
            blockers.append(f"required tiling archive missing: {rel}")
            continue
        text = read_text(path)
        if not text.strip():
            failed = True
            blockers.append(f"required tiling archive empty: {rel}")
            continue
        data: object = None
        if rel.endswith(".yaml") and yaml is not None:
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                failed = True
                blockers.append(f"required tiling archive invalid YAML: {rel}: {exc}")
                continue
        mapping = data if isinstance(data, dict) else {}
        if mapping.get("status") == "pending":
            failed = True
            warnings.append(f"{rel} still status: pending (host extraction skipped depth)")
        if rel.endswith("frontier.yaml") and mapping.get("frontier_nodes") == []:
            failed = True
            warnings.append(f"{rel} frontier_nodes empty")
        if rel.endswith("dispatch_variables.yaml") and mapping.get("variables") == []:
            failed = True
            warnings.append(f"{rel} variables empty")
        if rel.endswith("predicate_space.yaml") and mapping.get("predicate_atoms") == []:
            failed = True
            warnings.append(f"{rel} predicate_atoms empty")
        if rel.endswith("compile_time_bindings.yaml"):
            empty_all = (
                mapping.get("macros") == []
                and mapping.get("constexpr_constants") == []
                and mapping.get("instantiations") == []
                and mapping.get("unresolved_symbols") == []
            )
            if empty_all:
                failed = True
                warnings.append(
                    f"{rel} has no macros/constexpr/templates and no unresolved_symbols "
                    "(likely skipped compile-time analysis)"
                )
        if rel.endswith("decision_tree.md") and "host extraction must replace this skeleton" in text:
            failed = True
            warnings.append(f"{rel} still skeleton")
    return failed


def _check_domain_indexes(base: Path, warnings: list[str]) -> list[str]:
    bad: list[str] = []
    for rel in ("tiling/index.yaml", "flow/index.yaml", "kernel/index.yaml", "test/index.yaml"):
        text = read_text(base / rel)
        if not text.strip():
            bad.append(rel)
            continue
        for match in re.finditer(r"(?m)^\s*-\s+([A-Za-z0-9_./-]+\.(?:yaml|md))\s*$", text):
            target = match.group(1)
            # resolve relative to domain dir
            domain_dir = (base / rel).parent
            candidate = (domain_dir / target).resolve()
            if not candidate.exists():
                # also try from base
                if not (base / target).exists():
                    bad.append(f"{rel}:{target}")
    return bad


def _check_evidence(
    registry_evidence: object,
    fact_index: object,
    source_index: object,
    parsed_docs: dict[str, object],
    warnings: list[str],
    blockers: list[str],
) -> tuple[bool, bool]:
    evidence_ok = True
    locator_ok = True
    closure_docs = dict(parsed_docs)
    closure_docs["registry/evidence.yaml"] = registry_evidence
    closure_docs["evidence/fact_index.yaml"] = fact_index
    closure_docs["evidence/source_index.yaml"] = source_index
    closure_issues = validate_evidence_closure(closure_docs)
    if closure_issues:
        evidence_ok = False
        for issue in closure_issues:
            blockers.append(f"{issue.code}: {issue.message} ({issue.artifact})")
    if not isinstance(fact_index, dict):
        blockers.append("evidence/fact_index.yaml missing structure")
        return False, False
    facts = fact_index.get("facts") or {}
    refs = fact_index.get("evidence_refs") or {}
    if not isinstance(facts, dict):
        return False, False
    if facts:
        for fact_id, meta in facts.items():
            if not isinstance(meta, dict):
                continue
            ev = meta.get("evidence_refs") or []
            if not ev:
                evidence_ok = False
                blockers.append(f"fact {fact_id} missing evidence_refs")
            for ref in ev if isinstance(ev, list) else []:
                if isinstance(refs, dict) and ref not in refs:
                    evidence_ok = False
                    blockers.append(f"evidence_ref {ref} not in fact_index.evidence_refs")
            spans = meta.get("source_spans") or meta.get("source_locator") or []
            if not spans and not meta.get("reason"):
                locator_ok = False
                blockers.append(f"fact {fact_id} missing source locator or explicit reason")
    else:
        # Phase 8 is a final usability gate, not the fresh-layout initializer.
        evidence_ok = False
        locator_ok = False
        blockers.append("evidence/fact_index.yaml has no facts yet")

    if isinstance(source_index, dict):
        spans = source_index.get("source_spans") or {}
        if facts and isinstance(spans, dict) and not spans:
            locator_ok = False
            blockers.append("evidence/source_index.yaml has no source_spans")
    else:
        locator_ok = False
        blockers.append("evidence/source_index.yaml missing structure")
    return evidence_ok, locator_ok


def _as_mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _has_nonempty_collection(value: object) -> bool:
    return isinstance(value, (list, dict)) and bool(value)


def _iter_structured_entries(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _family_ids(families_doc: object) -> set[str]:
    doc = _as_mapping(families_doc)
    return {
        str(item.get("id"))
        for item in _iter_structured_entries(doc.get("families"))
        if item.get("id")
    }


def _planned_family_ids(paths_doc: object) -> set[str]:
    doc = _as_mapping(paths_doc)
    return {
        str(item.get("source_family"))
        for item in _iter_structured_entries(doc.get("kernel_paths"))
        if item.get("source_family")
    }


def _has_compute_golden_mapping(compute_graph: object, golden_model: object) -> bool:
    compute = _as_mapping(compute_graph)
    golden = _as_mapping(golden_model)
    for step in _iter_structured_entries(compute.get("compute_steps")):
        if step.get("golden_step_ref") or step.get("golden_role"):
            return True
    if _has_nonempty_collection(golden.get("maps_to_compute_steps")):
        return True
    for section in ("golden_steps", "golden_outputs"):
        for item in _iter_structured_entries(golden.get(section)):
            if _has_nonempty_collection(item.get("maps_to_compute_steps")):
                return True
    return False


def _has_resource_flow(resources: object) -> bool:
    doc = _as_mapping(resources)
    if not _iter_structured_entries(doc.get("sync_events")):
        return False
    entries: list[dict] = []
    for section in ("buffers", "workspaces", "resources"):
        entries.extend(_iter_structured_entries(doc.get(section)))
    return any(item.get("producer") and item.get("consumer") for item in entries)


def _has_hard_dispatch(fields: object) -> bool:
    if not isinstance(fields, dict):
        return False
    for meta in fields.values():
        if isinstance(meta, dict) and str(meta.get("kind", "")).strip() == "hard_dispatch":
            return True
    return False


def _check_key_logic_relations(
    variables: object,
    key_space: object,
    constraints: object,
    coverage_model: object,
    families: object,
    warnings: list[str],
    blockers: list[str],
) -> dict[str, str]:
    """Validate the two-step host tiling logic needed by TestGenerate.

    Step 1: variables.yaml (mechanism + variables + impact classification).
    Step 2: constraints.yaml (relations + tiling_key pruning/merging + input_realization).
    """
    checks: dict[str, str] = {
        "tiling_variables_present": "pass",
        "key_relations_present": "pass",
        "input_realization_present": "pass",
        "tiling_key_pruning_documented": "pass",
        "tiling_key_merging_documented": "pass",
        "key_relation_obligations_executable": "pass",
        "key_vs_family_unreachable_separated": "pass",
    }

    var = _as_mapping(variables)
    ks = _as_mapping(key_space)
    con = _as_mapping(constraints)
    cov = _as_mapping(coverage_model)
    fam = _as_mapping(families)

    # Fresh placeholder KB (macro unknown / empty fields) — soft fail only.
    encoding = _as_mapping(ks.get("encoding"))
    fields = ks.get("fields")
    fields_empty = not fields or fields == {}
    is_placeholder = (not ks) or (
        encoding.get("macro") in (None, "", "unknown") and fields_empty
    )
    if is_placeholder:
        for key in checks:
            checks[key] = "fail"
        checks["key_vs_family_unreachable_separated"] = "pass"
        blockers.append(
            "two-step tiling logic not filled yet "
            "(variables.yaml + constraints.yaml: relations / pruning / merging / input_realization)"
        )
        return checks

    hard = _has_hard_dispatch(fields)

    # --- Step 1: variables.yaml ---
    var_inventory = _as_mapping(var.get("variables"))
    mechanism = _as_mapping(var.get("tiling_mechanism"))
    classification = _as_mapping(var.get("impact_classification"))
    if not var_inventory or not (mechanism and any(mechanism.values())):
        checks["tiling_variables_present"] = "fail"
        blockers.append(
            "tiling/variables.yaml missing tiling_mechanism or variables inventory (Step 1)"
        )
    elif not any(_as_list(v) for v in classification.values()):
        checks["tiling_variables_present"] = "fail"
        blockers.append("tiling/variables.yaml impact_classification is empty (Step 1)")

    # --- Step 2: constraints.yaml ---
    relations = _as_list(con.get("relations"))
    input_realization = _as_mapping(con.get("input_realization"))
    key_unreachable = _as_list(con.get("key_unreachable"))
    pruning = _as_mapping(con.get("tiling_key_pruning"))
    merging = _as_mapping(con.get("tiling_key_merging"))
    var_constraints = _as_list(con.get("variable_constraints"))
    relation_obs = _as_list(cov.get("key_relation_obligations"))

    # independence documented via variable_constraints[].independent == True
    independence_documented = any(
        isinstance(vc, dict) and vc.get("independent") is True for vc in var_constraints
    )

    if hard and not relations and not independence_documented:
        checks["key_relations_present"] = "fail"
        blockers.append(
            "tiling/constraints.yaml has no relations while key_space has hard_dispatch fields; "
            "extract mutex/implies/requires/compatible_set or document independence in variable_constraints"
        )
    elif relations:
        bad_types = []
        missing_keys = []
        for item in relations:
            if not isinstance(item, dict):
                missing_keys.append("non-mapping relation")
                continue
            ctype = str(item.get("type", "")).strip()
            if ctype and ctype not in RELATION_TYPES:
                bad_types.append(ctype)
            for req in ("id", "type", "expr", "case_impact"):
                if not item.get(req):
                    missing_keys.append(f"{item.get('id', '?')}.{req}")
        if bad_types:
            checks["key_relations_present"] = "fail"
            blockers.append(
                "constraints.relations has unknown type(s): " + ", ".join(sorted(set(bad_types))[:6])
            )
        if missing_keys:
            checks["key_relations_present"] = "fail"
            blockers.append(
                "constraints.relations missing required keys: " + ", ".join(missing_keys[:8])
            )

    # pruning / merging must be explicitly answered
    if pruning.get("performed") in (None, ""):
        checks["tiling_key_pruning_documented"] = "fail"
        blockers.append("constraints.tiling_key_pruning.performed must be true/false/unknown")
    if merging.get("performed") in (None, ""):
        checks["tiling_key_merging_documented"] = "fail"
        blockers.append("constraints.tiling_key_merging.performed must be true/false/unknown")

    reachable_families = []
    family_map = _as_mapping(fam.get("families"))
    for fid, meta in family_map.items():
        if not isinstance(meta, dict):
            continue
        reach = str(meta.get("reachability", "")).strip()
        if reach in ("unreachable", "excluded"):
            continue
        reachable_families.append(fid)

    if hard and reachable_families and not input_realization:
        checks["input_realization_present"] = "fail"
        blockers.append(
            "tiling/constraints.yaml input_realization is empty while reachable families exist; "
            "TestGenerate cannot map key patterns to inputs"
        )
    elif input_realization:
        weak = []
        for ir_id, entry in input_realization.items():
            if not isinstance(entry, dict):
                weak.append(str(ir_id))
                continue
            matches = _as_mapping(entry.get("matches"))
            inputs = _as_mapping(entry.get("inputs"))
            if not matches.get("key_pattern") and not matches.get("family_refs"):
                weak.append(str(ir_id))
            elif not (
                inputs.get("required")
                or inputs.get("optional_present")
                or inputs.get("optional_absent")
                or entry.get("shape_intent")
                or entry.get("dtype_layout_intent")
            ):
                weak.append(str(ir_id))
        if weak:
            checks["input_realization_present"] = "fail"
            blockers.append(
                "input_realization entries lack matches/inputs intent: " + ", ".join(weak[:6])
            )

    if hard and not relation_obs:
        checks["key_relation_obligations_executable"] = "fail"
        blockers.append(
            "coverage_model.key_relation_obligations is empty while hard_dispatch fields exist"
        )
    elif relation_obs:
        weak_rel = []
        for item in relation_obs:
            if not isinstance(item, dict):
                weak_rel.append("non-mapping")
                continue
            if not item.get("id") or not item.get("relation_type") or not item.get("fields"):
                weak_rel.append(str(item.get("id", "?")))
                continue
            if not item.get("must_cover") and not item.get("linked_relations"):
                weak_rel.append(str(item.get("id", "?")))
        if weak_rel:
            checks["key_relation_obligations_executable"] = "fail"
            blockers.append(
                "key_relation_obligations not executable (need must_cover or linked_relations): "
                + ", ".join(weak_rel[:6])
            )

    # Separation: constraints.key_unreachable should be key-level, not family ids.
    family_ids = set(family_map.keys())
    mixed = []
    for item in key_unreachable:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level", "key")).strip() or "key"
        constraint = str(item.get("constraint", ""))
        if level == "family" or (constraint in family_ids and level != "key"):
            mixed.append(str(item.get("id", constraint)))
    if mixed:
        checks["key_vs_family_unreachable_separated"] = "fail"
        warnings.append(
            "constraints.key_unreachable appears to mix family-level entries: " + ", ".join(mixed[:5])
        )

    policy = _as_mapping(cov.get("coverage_policy"))
    if policy and policy.get("input_realization_coverage") not in ("required", True):
        warnings.append("coverage_policy.input_realization_coverage should be required")

    audit = _as_mapping(cov.get("audit_requirements"))
    for flag in (
        "report_missing_input_realization",
        "report_illegal_cartesian_without_constraints",
    ):
        if audit and flag not in audit:
            warnings.append(f"coverage_model.audit_requirements missing {flag}")

    return checks


def _check_exhaustive_tiling_key_model(
    exhaustive: object,
    key_space: object,
    constraints: object,
    warnings: list[str],
    blockers: list[str],
) -> dict[str, str]:
    checks: dict[str, str] = {
        "exhaustive_tiling_key_model_present": "pass",
        "exhaustive_tiling_key_counts_consistent": "pass",
        "exhaustive_tiling_key_reverse_hints_present": "pass",
    }
    ex = _as_mapping(exhaustive)
    ks = _as_mapping(key_space)
    con = _as_mapping(constraints)
    fields = ks.get("fields")
    hard = _has_hard_dispatch(fields)

    if not ex:
        checks["exhaustive_tiling_key_model_present"] = "fail"
        blockers.append("tiling/exhaustive_key_space.yaml missing; TestGenerate cannot do full TilingKey enumeration")
        return checks

    status = str(ex.get("status") or "").strip()
    if status == "not_applicable":
        if not ex.get("reason") or not _as_list(ex.get("evidence_refs")):
            checks["exhaustive_tiling_key_model_present"] = "fail"
            blockers.append("tiling/exhaustive_key_space.yaml not_applicable requires reason and evidence_refs")
        elif hard:
            warnings.append("hard_dispatch fields exist but exhaustive TilingKey model is marked not_applicable")
        return checks

    source = _as_mapping(ex.get("enumeration_source"))
    summary = _as_mapping(ex.get("summary"))
    blocks = _as_list(ex.get("template_blocks"))
    has_source = bool(_as_list(source.get("files")) or _as_list(source.get("evidence_refs")))
    if hard and (not has_source or not blocks):
        checks["exhaustive_tiling_key_model_present"] = "fail"
        blockers.append(
            "hard_dispatch key_space exists but tiling/exhaustive_key_space.yaml has no source-backed template_blocks"
        )
    elif not blocks:
        warnings.append("tiling/exhaustive_key_space.yaml has no template_blocks; full TilingKey enumeration is unavailable")

    try:
        expected_count = int(summary.get("expanded_key_count") or 0)
    except (TypeError, ValueError):
        expected_count = -1
    try:
        expected_blocks = int(summary.get("block_count") or 0)
    except (TypeError, ValueError):
        expected_blocks = -1
    product_sum = 0
    bad_blocks: list[str] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            bad_blocks.append(f"#{index}")
            continue
        try:
            product = int(block.get("product_count") or 0)
        except (TypeError, ValueError):
            product = 0
        if product <= 0:
            bad_blocks.append(str(block.get("id") or f"#{index}"))
        product_sum += product
        if not _as_mapping(block.get("field_domains")) and not _as_mapping(block.get("fixed_fields")):
            bad_blocks.append(str(block.get("id") or f"#{index}") + ":no_fields")
    if bad_blocks:
        checks["exhaustive_tiling_key_counts_consistent"] = "fail"
        blockers.append("exhaustive template_blocks invalid: " + ", ".join(bad_blocks[:8]))
    if blocks and expected_blocks not in (0, len(blocks)):
        checks["exhaustive_tiling_key_counts_consistent"] = "fail"
        blockers.append(
            f"exhaustive summary.block_count={expected_blocks} but template_blocks={len(blocks)}"
        )
    if blocks and expected_count not in (0, product_sum):
        checks["exhaustive_tiling_key_counts_consistent"] = "fail"
        blockers.append(
            f"exhaustive summary.expanded_key_count={expected_count} but product_count sum={product_sum}"
        )
    contract = _as_mapping(ex.get("exhaustive_coverage_contract"))
    if blocks and contract.get("mode") not in ("macro_block_cartesian", "source_block_cartesian"):
        checks["exhaustive_tiling_key_counts_consistent"] = "fail"
        blockers.append("exhaustive_coverage_contract.mode must be macro_block_cartesian")

    reverse = _as_mapping(ex.get("reverse_realization_index"))
    known_derived = {
        "SplitAxis",
        "S1TemplateNum",
        "S2TemplateNum",
        "DTemplateNum",
        "DTemplateType",
        "IsNzOut",
        "IsTndSwizzle",
        "IsBn2MultiBlk",
        "IsDNoEqual",
        "DeterType",
    }
    used_fields: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        used_fields.update(str(name) for name in _as_mapping(block.get("fixed_fields")))
        used_fields.update(str(name) for name in _as_mapping(block.get("field_domains")))
    fields_needing_reverse = sorted(known_derived.intersection(used_fields))
    missing_reverse = [name for name in fields_needing_reverse if not _as_mapping(reverse.get(name))]
    if blocks and missing_reverse:
        checks["exhaustive_tiling_key_reverse_hints_present"] = "fail"
        blockers.append(
            "exhaustive_key_space.reverse_realization_index missing derived fields: "
            + ", ".join(missing_reverse[:8])
        )
    input_realization = _as_mapping(con.get("input_realization"))
    if blocks and not input_realization:
        checks["exhaustive_tiling_key_reverse_hints_present"] = "fail"
        blockers.append(
            "exhaustive TilingKey blocks exist but constraints.input_realization is empty; inputs cannot be solved"
        )

    return checks


def _run_kb_compiler(
    base: Path,
    op_name: str,
    warnings: list[str],
    blockers: list[str],
) -> dict[str, str]:
    global _LAST_COMPILER_ISSUES
    _LAST_COMPILER_ISSUES = []
    checks: dict[str, str] = {
        "kb_compiler_passed": "pass",
        "stable_ids_present": "pass",
        "registry_aliases_valid": "pass",
        "cross_layer_graphs_present": "pass",
        "kernel_two_step_present": "pass",
        "task_contracts_present": "pass",
    }
    try:
        from understand_operator._operator.kb_compiler import compile_kb

        result = compile_kb(base, op_name, write_outputs=True)
    except Exception as exc:  # noqa: BLE001
        checks["kb_compiler_passed"] = "fail"
        blockers.append(f"KB compiler crashed: {exc}")
        return checks

    if result.status == "fail":
        checks["kb_compiler_passed"] = "fail"
    elif result.status == "warn":
        checks["kb_compiler_passed"] = "warn"
    _LAST_COMPILER_ISSUES = list(result.issues)

    if result.entity_count == 0:
        checks["stable_ids_present"] = "fail"
        warnings.append("registry has no stable ids yet")
    # No aliases is a valid registry state.  Actual conflicts are emitted by
    # the compiler and retain their warning/error severity below.

    for issue in result.issues:
        line = f"{issue.code}: {issue.message}"
        if issue.artifact:
            line += f" ({issue.artifact})"
        if issue.severity == "error":
            blockers.append(line)
        elif issue.severity == "warning":
            warnings.append(line)

    for rel in (
        "cross_layer/input_to_tiling.yaml",
        "cross_layer/tiling_to_kernel.yaml",
        "cross_layer/variable_lineage.yaml",
        "cross_layer/behavior_graph.yaml",
        "cross_layer/impact_graph.yaml",
    ):
        if not (base / rel).exists():
            checks["cross_layer_graphs_present"] = "fail"
    for rel in ("kernel/compile_model.yaml", "kernel/variables.yaml", "kernel/branches.yaml"):
        if not (base / rel).exists():
            checks["kernel_two_step_present"] = "fail"
    for rel in ("contracts/query.yaml", "contracts/code_change.yaml", "contracts/pr_review.yaml", "contracts/testcase.yaml"):
        if not (base / rel).exists():
            checks["task_contracts_present"] = "fail"

    return checks


def _check_cross_layer_graph_completeness(base: Path, warnings: list[str], blockers: list[str]) -> dict[str, str]:
    checks = {
        "cross_layer_graph_schema": "pass",
        "cross_layer_graph_coverage": "pass",
    }
    variables = _read_yaml(base / "tiling" / "variables.yaml")
    behavior = _read_yaml(base / "cross_layer" / "behavior_graph.yaml")
    impact = _read_yaml(base / "cross_layer" / "impact_graph.yaml")

    var_inventory = _as_mapping(_as_mapping(variables).get("variables"))
    variable_count = len(var_inventory)
    behavior_nodes = _as_list(_as_mapping(behavior).get("nodes"))
    impact_nodes = _as_list(_as_mapping(impact).get("nodes"))
    behavior_edges = _as_list(_as_mapping(behavior).get("edges"))
    impact_edges = _as_list(_as_mapping(impact).get("edges"))

    for rel, graph in (
        ("cross_layer/behavior_graph.yaml", behavior),
        ("cross_layer/impact_graph.yaml", impact),
    ):
        graph_map = _as_mapping(graph)
        if graph_map.get("version") != 1 or not str(graph_map.get("purpose", "")).startswith("deterministically"):
            checks["cross_layer_graph_schema"] = "fail"
            blockers.append(f"{rel} was not generated by deterministic graph builder")

    if variable_count:
        min_nodes = max(1, int(variable_count * 0.5))
        if len(behavior_nodes) < min_nodes or len(impact_nodes) < min_nodes:
            checks["cross_layer_graph_coverage"] = "fail"
            blockers.append(
                "cross-layer graphs are too small for tiling variable inventory "
                f"(variables={variable_count}, behavior_nodes={len(behavior_nodes)}, impact_nodes={len(impact_nodes)})"
            )
    if variable_count > 1 and not behavior_edges:
        checks["cross_layer_graph_coverage"] = "fail"
        blockers.append("cross_layer/behavior_graph.yaml has no edges despite non-trivial tiling variables")
    if variable_count > 1 and not impact_edges:
        checks["cross_layer_graph_coverage"] = "fail"
        blockers.append("cross_layer/impact_graph.yaml has no impact edges despite non-trivial tiling variables")

    class_members: dict[str, set[str]] = {}
    classification = _as_mapping(_as_mapping(variables).get("impact_classification"))
    for scope, items in classification.items():
        for name in _as_list(items):
            class_members.setdefault(str(name), set()).add(str(scope))
    conflicts = sorted(name for name, scopes in class_members.items() if "constant" in scopes and len(scopes) > 1)
    if conflicts:
        checks["cross_layer_graph_coverage"] = "fail"
        blockers.append(
            "tiling/variables.yaml classifies variable as constant and non-constant: "
            + ", ".join(conflicts[:8])
        )

    if checks["cross_layer_graph_coverage"] == "pass" and variable_count and len(behavior_nodes) < variable_count:
        warnings.append(
            "behavior graph has fewer nodes than tiling variables "
            f"(variables={variable_count}, behavior_nodes={len(behavior_nodes)})"
        )
    return checks


def _check_text_encoding(base: Path, warnings: list[str]) -> dict[str, str]:
    checks = {"canonical_text_encoding": "pass"}
    roots = [
        "operator.yaml",
        "route.md",
        "manifest.yaml",
        "quality.yaml",
        "tiling",
        "flow",
        "kernel",
        "cross_layer",
        "contracts",
        "test",
        "evidence",
        "registry",
        "query",
    ]
    hits: list[str] = []
    for item in roots:
        path = base / item
        files = [path] if path.is_file() else list(path.rglob("*")) if path.exists() else []
        for candidate in files:
            if not candidate.is_file() or candidate.suffix.lower() not in {".yaml", ".yml", ".md"}:
                continue
            text = read_text(candidate)
            if any(marker in text for marker in MOJIBAKE_MARKERS):
                hits.append(str(candidate.relative_to(base)).replace("\\", "/"))
    if hits:
        checks["canonical_text_encoding"] = "warn"
        warnings.append("possible mojibake markers in canonical text: " + ", ".join(hits[:8]))
    return checks


def _read_yaml(path: Path) -> object:
    if yaml is None or not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _score_text(text: str) -> float:
    lowered = text.lower()
    if not text.strip():
        return 0.0
    if "confidence: high" in lowered:
        return 0.9
    if "confidence: medium" in lowered:
        return 0.6
    if "unknown" in lowered and "confidence: low" in lowered:
        return 0.2
    if "confidence: low" in lowered:
        return 0.3
    # non-empty draft
    return 0.4


def _top_level_section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}\s*:\s*(?:#.*)?$", text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_match = re.search(r"(?m)^[A-Za-z0-9_]+\s*:", rest)
    return rest[: next_match.start()] if next_match else rest


def _render_quality(
    op_name: str,
    status: str,
    scores: dict[str, float],
    checks: dict[str, str],
    blockers: list[str],
    warnings: list[str],
    decision: str,
) -> str:
    lines = [
        "version: 1",
        f"op_name: {op_name}",
        f"status: {status}",
        "",
        "scores:",
    ]
    for key, value in scores.items():
        lines.append(f"  {key}: {value}")
    lines.append("")
    lines.append("checks:")
    for key, value in checks.items():
        lines.append(f"  {key}: {value}")
    lines.append("")
    lines.append("blockers:")
    if blockers:
        lines.extend(f"  - {_yaml_escape(item)}" for item in blockers)
    else:
        lines.append("  []")
    lines.append("warnings:")
    if warnings:
        lines.extend(f"  - {_yaml_escape(item)}" for item in warnings)
    else:
        lines.append("  []")
    lines.append(f"decision: {decision}")
    lines.append("")
    return "\n".join(lines)


def _yaml_escape(text: str) -> str:
    if any(ch in text for ch in (":", "#", "{", "}", "[", "]", ",", '"', "'")):
        return '"' + text.replace('"', '\\"') + '"'
    return text


if __name__ == "__main__":
    raise SystemExit(main())
