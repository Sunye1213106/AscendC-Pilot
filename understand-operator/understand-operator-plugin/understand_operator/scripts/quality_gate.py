from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import (
    CANONICAL_EVIDENCE_FILES,
    CANONICAL_FLOW_FILES,
    CANONICAL_KERNEL_FILES,
    CANONICAL_ROOT_FILES,
    CANONICAL_TEST_FILES,
    CANONICAL_TILING_FILES,
    REQUIRED_TILING_ARCHIVE_FILES,
    operator_root,
    read_text,
    safe_op_name,
    write_text,
)

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
    base = operator_root(repo_root, op_name)

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
    evidence_ok, locator_ok = _check_evidence(fact_index, source_index, warnings, blockers)
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
    family_count = len(set(re.findall(r"(?m)^\s*(TF\d+)\s*:", families)))
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

    # golden / kernel alignment presence
    compute_graph = read_text(base / "flow" / "compute_graph.yaml")
    if "golden_step_ref" in compute_graph or "golden_role" in compute_graph or "maps_to_compute_steps" in golden_text:
        checks["golden_model_has_compute_mapping"] = "pass"
    else:
        checks["golden_model_has_compute_mapping"] = "fail"
        warnings.append("compute_graph/golden_model missing compute↔golden mapping")

    pipeline = read_text(base / "kernel" / "pipeline.yaml")
    if "compute_step_alignment" in pipeline and not re.search(r"compute_step_alignment:\s*\[\]", pipeline):
        checks["kernel_pipeline_has_compute_alignment"] = "pass"
    else:
        checks["kernel_pipeline_has_compute_alignment"] = "fail"
        warnings.append("kernel/pipeline.yaml missing compute_step_alignment entries")

    resources = read_text(base / "kernel" / "resources.yaml")
    if ("producer" in resources.lower() or "consumer" in resources.lower()) and "sync_events" in resources:
        checks["resources_have_producer_consumer"] = "pass"
    else:
        checks["resources_have_producer_consumer"] = "fail"
        warnings.append("kernel/resources.yaml missing producer/consumer/sync relations")

    # route.md length
    route_md = read_text(base / "route.md")
    route_lines = len([ln for ln in route_md.splitlines() if ln.strip()])
    if route_lines > 220:
        warnings.append(f"route.md looks like a long report ({route_lines} non-empty lines); keep 100-200")

    # kernel paths vs families
    paths = read_text(base / "kernel" / "paths.yaml")
    planned = set(re.findall(r"(?m)^\s*source_family\s*:\s*(TF\d+)", paths))
    family_ids = set(re.findall(r"(?m)^\s*(TF\d+)\s*:", families))
    if family_ids and "normal_kernel_task" in families.lower():
        missing_map = sorted(fid for fid in family_ids if fid not in planned)
        if missing_map:
            warnings.append("some families have no kernel path mapping yet: " + ", ".join(missing_map[:5]))

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
        decision = "usable_for_testgenerate_with_review"

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
    print(f"Quality gate: {status} / {decision} -> {base / 'quality.yaml'}")
    return 0 if status != "red" else 2


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
        if "status: pending" in text and rel.endswith(".yaml"):
            failed = True
            warnings.append(f"{rel} still status: pending (host extraction skipped depth)")
        if rel.endswith("frontier.yaml") and "frontier_nodes: []" in text:
            failed = True
            warnings.append(f"{rel} frontier_nodes empty")
        if rel.endswith("dispatch_variables.yaml") and "variables: []" in text:
            failed = True
            warnings.append(f"{rel} variables empty")
        if rel.endswith("predicate_space.yaml") and "predicate_atoms: []" in text:
            failed = True
            warnings.append(f"{rel} predicate_atoms empty")
        if rel.endswith("compile_time_bindings.yaml"):
            empty_all = (
                "macros: []" in text
                and "constexpr_constants: []" in text
                and "instantiations: []" in text
                and "unresolved_symbols: []" in text
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
    fact_index: object,
    source_index: object,
    warnings: list[str],
    blockers: list[str],
) -> tuple[bool, bool]:
    evidence_ok = True
    locator_ok = True
    if not isinstance(fact_index, dict):
        warnings.append("evidence/fact_index.yaml missing structure")
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
                warnings.append(f"fact {fact_id} missing evidence_refs")
            for ref in ev if isinstance(ev, list) else []:
                if isinstance(refs, dict) and ref not in refs:
                    evidence_ok = False
                    warnings.append(f"evidence_ref {ref} not in fact_index.evidence_refs")
            spans = meta.get("source_spans") or []
            if not spans:
                locator_ok = False
    else:
        # empty facts on fresh init is expected; treat as fail for usability but not hard blocker alone
        evidence_ok = False
        locator_ok = False
        warnings.append("evidence/fact_index.yaml has no facts yet")

    if isinstance(source_index, dict):
        spans = source_index.get("source_spans") or {}
        if facts and isinstance(spans, dict) and not spans:
            locator_ok = False
            warnings.append("evidence/source_index.yaml has no source_spans")
    else:
        locator_ok = False
        warnings.append("evidence/source_index.yaml missing structure")
    return evidence_ok, locator_ok


_ALLOWED_CONSTRAINT_TYPES = {
    "mutex",
    "implies",
    "requires",
    "compatible_set",
    "compile_time_fixed",
    "runtime_guard",
    "other",
}


def _as_mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


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
        warnings.append(
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
        warnings.append(
            "tiling/variables.yaml missing tiling_mechanism or variables inventory (Step 1)"
        )
    elif not any(_as_list(v) for v in classification.values()):
        checks["tiling_variables_present"] = "fail"
        warnings.append("tiling/variables.yaml impact_classification is empty (Step 1)")

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
            if ctype and ctype not in _ALLOWED_CONSTRAINT_TYPES:
                bad_types.append(ctype)
            for req in ("id", "type", "expr", "case_impact"):
                if not item.get(req):
                    missing_keys.append(f"{item.get('id', '?')}.{req}")
        if bad_types:
            checks["key_relations_present"] = "fail"
            warnings.append(
                "constraints.relations has unknown type(s): " + ", ".join(sorted(set(bad_types))[:6])
            )
        if missing_keys:
            checks["key_relations_present"] = "fail"
            warnings.append(
                "constraints.relations missing required keys: " + ", ".join(missing_keys[:8])
            )

    # pruning / merging must be explicitly answered
    if pruning.get("performed") in (None, ""):
        checks["tiling_key_pruning_documented"] = "fail"
        warnings.append("constraints.tiling_key_pruning.performed must be true/false/unknown")
    if merging.get("performed") in (None, ""):
        checks["tiling_key_merging_documented"] = "fail"
        warnings.append("constraints.tiling_key_merging.performed must be true/false/unknown")

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
            warnings.append(
                "input_realization entries lack matches/inputs intent: " + ", ".join(weak[:6])
            )

    if hard and not relation_obs:
        checks["key_relation_obligations_executable"] = "fail"
        warnings.append(
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
            warnings.append(
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
