from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import operator_root, read_text, safe_op_name, write_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a lightweight understand-operator quality gate")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    base = operator_root(repo_root, op_name)

    operator_io = read_text(base / "summary" / "operator_io.yaml")
    evidence = read_text(base / "evidence" / "evidence_check.yaml")
    tiling_families_path = base / "tiling" / "tiling_branch_families.yaml"
    tiling_route_path = base / "tiling" / "tiling_route.yaml"
    dispatch_variables_path = base / "tiling" / "dispatch_variables.yaml"
    predicate_space_path = base / "tiling" / "tiling_predicate_space.yaml"
    tiling_families = read_text(tiling_families_path)
    tiling_route = read_text(tiling_route_path)
    dispatch_variables = read_text(dispatch_variables_path)
    predicate_space = read_text(predicate_space_path)
    branch_matrix = read_text(base / "tiling" / "branch_matrix.yaml")
    kernel_task_plan = read_text(base / "kernel" / "kernel_task_plan.yaml")
    kernel_dispatch_review = read_text(base / "kernel" / "kernel_dispatch_review.yaml")
    kernel_matrix = read_text(base / "kernel" / "kernel_path_matrix.yaml")
    compute_flow = read_text(base / "flows" / "compute_flow.yaml")

    blockers: list[str] = []
    warnings: list[str] = []
    if not operator_io:
        blockers.append("summary/operator_io.yaml is missing")
    if re.search(r"required_inputs:\s*\[\]", operator_io):
        blockers.append("required input evidence is missing")
    if re.search(r"outputs:\s*\[\]", operator_io):
        blockers.append("output evidence is missing")
    if "status: fail" in evidence or "result: fail" in evidence:
        blockers.append("evidence consistency reported fail")
    if not tiling_families_path.exists() or not tiling_families.strip():
        blockers.append("tiling/tiling_branch_families.yaml is missing")
    elif re.search(r"families:\s*\[\]", tiling_families):
        warnings.append("tiling branch families are empty")
    if not tiling_route_path.exists() or not tiling_route.strip():
        blockers.append("tiling/tiling_route.yaml is missing")
    elif re.search(r"routes:\s*\[\]", tiling_route):
        warnings.append("tiling route is empty")
    if not dispatch_variables_path.exists() or not dispatch_variables.strip():
        warnings.append("tiling/dispatch_variables.yaml is missing")
    if not predicate_space_path.exists() or not predicate_space.strip():
        warnings.append("tiling/tiling_predicate_space.yaml is missing")
    if re.search(r"branches:\s*\[\]", branch_matrix):
        warnings.append("tiling branch matrix is empty")
    if re.search(r"kernel_paths:\s*\[\]", kernel_matrix):
        warnings.append("kernel path matrix is empty")
    if tiling_families:
        _check_tiling_family_contract(tiling_families, tiling_route, kernel_task_plan, warnings, blockers)
    if branch_matrix and not re.search(r"branches:\s*\[\]", branch_matrix):
        _check_tiling_branch_contract(branch_matrix, _family_count(tiling_families), warnings, blockers)
    if tiling_route:
        _check_tiling_route_contract(tiling_route, warnings)
    if kernel_task_plan:
        _check_kernel_task_contract(kernel_task_plan, warnings)
    if kernel_dispatch_review:
        _check_kernel_dispatch_contract(kernel_dispatch_review, kernel_task_plan, warnings, blockers)

    quality_inputs = [
        operator_io,
        evidence,
        tiling_families,
        tiling_route,
        dispatch_variables,
        predicate_space,
        branch_matrix,
        kernel_task_plan,
        kernel_dispatch_review,
        kernel_matrix,
        compute_flow,
    ]
    unknown_count = sum(text.lower().count("unknown") for text in quality_inputs)
    token_count = max(1, sum(len(text.split()) for text in quality_inputs))
    unknown_ratio = min(1.0, round(unknown_count / token_count, 4))

    if blockers:
        decision = "red"
    elif warnings or unknown_ratio > 0.15:
        decision = "yellow"
    else:
        decision = "green"

    blocker_lines = [f"  - {item}" for item in blockers] if blockers else ["  []"]
    warning_lines = [f"  - {item}" for item in warnings] if warnings else ["  []"]
    lines = [
        f"io_confidence: {_confidence(operator_io)}",
        f"boundary_confidence: {_confidence(read_text(base / 'summary' / 'operator_boundary.md'))}",
        f"tiling_family_confidence: {_confidence(tiling_families)}",
        f"tiling_route_confidence: {_confidence(tiling_route)}",
        f"dispatch_variable_confidence: {_confidence(dispatch_variables)}",
        f"predicate_space_confidence: {_confidence(predicate_space)}",
        f"branch_matrix_materialization_status: {_branch_materialization_status(branch_matrix, _family_count(tiling_families))}",
        f"compute_flow_confidence: {_confidence(compute_flow)}",
        f"kernel_alignment_confidence: {_confidence(kernel_matrix)}",
        f"evidence_consistency_status: {'fail' if blockers else ('warning' if warnings else 'pass')}",
        f"unknown_ratio: {unknown_ratio}",
        f"decision: {decision}",
        "blockers:",
        *blocker_lines,
        "warnings:",
        *warning_lines,
        "next_actions:",
        *_next_actions(decision),
        "",
    ]
    body = "\n".join(lines)
    write_text(base / "quality_gate.yaml", body)
    print(f"Quality gate: {decision} -> {base / 'quality_gate.yaml'}")
    return 0 if decision != "red" else 2


def _confidence(text: str) -> str:
    lowered = text.lower()
    if "confidence: high" in lowered:
        return "high"
    if "confidence: medium" in lowered:
        return "medium"
    return "low"


def _check_tiling_family_contract(
    tiling_families: str,
    tiling_route: str,
    kernel_task_plan: str,
    warnings: list[str],
    blockers: list[str],
) -> None:
    family_count = _family_count(tiling_families)
    if family_count == 0:
        return

    family_section = _top_level_section(tiling_families, "families")
    has_known_reachability = re.search(
        r"\breachability\s*:\s*(?:\r?\n\s+[A-Za-z_]+:.*)*\r?\n\s+status\s*:\s*(taken|not_taken|runtime_conditional|skipped_by_review)\b",
        family_section,
        re.IGNORECASE,
    )
    has_unknown_reachability = re.search(
        r"\breachability\s*:\s*(?:\r?\n\s+[A-Za-z_]+:.*)*\r?\n\s+status\s*:\s*unknown\b",
        family_section,
        re.IGNORECASE,
    )
    if has_unknown_reachability and not has_known_reachability:
        blockers.append("all tiling branch families have unknown reachability")

    high_priority_families = _route_family_ids(tiling_route, priorities={"high"}, actions={"normal_kernel_task", "needs_review", "needs_alignment"})
    planned_families = _planned_family_ids(kernel_task_plan)
    missing_high_priority = sorted(high_priority_families - planned_families)
    if missing_high_priority:
        blockers.append(
            "high priority tiling families have no normal, needs_alignment, or needs_review kernel task: "
            + ", ".join(missing_high_priority)
        )

    lowered = tiling_families.lower()
    if high_priority_families and (
        "unknown_compile_time_binding" in lowered
        or re.search(r"\bunknown\b[\s\S]{0,120}\b(compile[-_ ]time|constexpr|macro|platform)\b", lowered)
    ):
        warnings.append("unknown compile-time binding may affect a high priority tiling family")

    repeated_sources = _repeated_source_families(kernel_task_plan)
    if repeated_sources and "numeric_variants" in kernel_task_plan.lower():
        warnings.append(
            "possible task over-splitting: one source_family appears in multiple kernel tasks with numeric_variants"
        )

    required_family_markers = {
        "source_spans": "source_spans" in lowered,
        "trigger_preconditions": "trigger_preconditions" in lowered,
        "tiling_key_expectation": "tiling_key_expectation" in lowered,
        "downstream_preparation": "downstream_preparation" in lowered,
        "impact_trace": "impact_trace" in lowered,
    }
    missing_family_markers = [name for name, present in required_family_markers.items() if not present]
    if missing_family_markers:
        warnings.append("tiling branch families are missing traceability/downstream fields: " + ", ".join(missing_family_markers))


def _check_tiling_branch_contract(
    branch_matrix: str,
    family_count: int,
    warnings: list[str],
    blockers: list[str],
) -> None:
    lowered = branch_matrix.lower()
    required_markers = {
        "family_id": "family_id" in lowered,
        "materialization_role": "materialization_role" in lowered,
        "representative_case_id": "representative_case_id" in lowered,
        "condition_snapshot": "condition_snapshot" in lowered,
        "reachability": "reachability" in lowered,
        "trigger_preconditions": "trigger_preconditions" in lowered,
        "source_spans": "source_spans" in lowered,
        "predicate_refs": "predicate_refs" in lowered,
        "structural_tiling_signature_id": "structural_tiling_signature_id" in lowered,
    }
    missing = [name for name, present in required_markers.items() if not present]
    if missing:
        warnings.append(f"tiling branch representative samples are missing fields: {', '.join(missing)}")

    branch_count = _branch_count(branch_matrix)
    if branch_count and "family_id" not in lowered:
        warnings.append("tiling branch matrix has branch entries without family_id")
    if branch_count and "materialization_role" not in lowered:
        warnings.append("tiling branch matrix is missing materialization_role for representative samples")
    if family_count and branch_count > max(10, family_count * 5) and "materialization_role" not in lowered:
        warnings.append("branch_matrix.yaml looks like full enumeration instead of representative materialization")


def _check_tiling_route_contract(tiling_route: str, warnings: list[str]) -> None:
    lowered = tiling_route.lower()
    required_route_markers = {
        "dispatchable": "dispatchable" in lowered,
        "required_followups": "required_followups" in lowered,
        "blocks_downstream_preparation": "blocks_downstream_preparation" in lowered,
    }
    missing = [name for name, present in required_route_markers.items() if not present]
    if missing:
        warnings.append("tiling route is missing downstream dispatch fields: " + ", ".join(missing))


def _check_kernel_task_contract(kernel_task_plan: str, warnings: list[str]) -> None:
    lowered = kernel_task_plan.lower()
    required_task_markers = {
        "traceability": "traceability" in lowered,
        "downstream_preparation": "downstream_preparation" in lowered,
        "dispatchable": "dispatchable" in lowered,
    }
    missing = [name for name, present in required_task_markers.items() if not present]
    if missing and not re.search(r"kernel_tasks:\s*\[\]", lowered):
        warnings.append("kernel task plan is missing traceability/downstream fields: " + ", ".join(missing))


def _check_kernel_dispatch_contract(
    kernel_dispatch_review: str,
    kernel_task_plan: str,
    warnings: list[str],
    blockers: list[str],
) -> None:
    lowered = kernel_dispatch_review.lower()
    required_dispatch_markers = {
        "dispatchable_task_ids": "dispatchable_task_ids" in lowered,
        "non_dispatchable_task_ids": "non_dispatchable_task_ids" in lowered,
        "needs_review_task_ids": "needs_review_task_ids" in lowered,
    }
    missing = [name for name, present in required_dispatch_markers.items() if not present]
    if missing:
        warnings.append("kernel dispatch review is missing dispatchability fields: " + ", ".join(missing))
    if re.search(r"(?m)^\s*decision\s*:\s*dispatch_all\s*$", lowered):
        approved = set(_yaml_list_values(kernel_dispatch_review, "approved_task_ids"))
        needs_review = set(_yaml_list_values(kernel_dispatch_review, "needs_review_task_ids"))
        non_dispatchable = set(_yaml_list_values(kernel_dispatch_review, "non_dispatchable_task_ids"))
        non_auto_actions = _task_ids_by_route_action(kernel_task_plan, {"needs_review", "needs_alignment"})
        invalid = sorted(approved & (needs_review | non_dispatchable | non_auto_actions))
        if invalid:
            blockers.append("dispatch_all includes non-dispatchable, needs_review, or needs_alignment tasks: " + ", ".join(invalid))

def _top_level_section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}\s*:\s*(?:#.*)?$", text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_match = re.search(r"(?m)^[A-Za-z0-9_]+\s*:", rest)
    return rest[: next_match.start()] if next_match else rest


def _family_count(tiling_families: str) -> int:
    section = _top_level_section(tiling_families, "families")
    return len(set(re.findall(r"(?m)^\s*-\s+family_id\s*:\s*([^\s#]+)", section)))


def _branch_count(branch_matrix: str) -> int:
    section = _top_level_section(branch_matrix, "branches")
    return len(re.findall(r"(?m)^\s*-\s+id\s*:\s*([^\s#]+)", section))


def _route_family_ids(tiling_route: str, priorities: set[str], actions: set[str]) -> set[str]:
    section = _top_level_section(tiling_route, "routes")
    result: set[str] = set()
    for block in re.split(r"(?m)^\s*-\s+route_id\s*:", section)[1:]:
        family = _field_value(block, "family_id")
        priority = _field_value(block, "task_priority").lower()
        action = _field_value(block, "action").lower()
        if family and priority in priorities and action in actions:
            result.add(family)
    return result


def _planned_family_ids(kernel_task_plan: str) -> set[str]:
    ids = set(re.findall(r"(?m)^\s*source_family\s*:\s*([^\s#]+)", kernel_task_plan))
    ids.update(re.findall(r"(?m)^\s*family_id\s*:\s*([^\s#]+)", _top_level_section(kernel_task_plan, "needs_review_families")))
    return ids


def _repeated_source_families(kernel_task_plan: str) -> set[str]:
    ids = re.findall(r"(?m)^\s*source_family\s*:\s*([^\s#]+)", kernel_task_plan)
    return {family_id for family_id in ids if ids.count(family_id) > 1}


def _task_ids_by_route_action(kernel_task_plan: str, actions: set[str]) -> set[str]:
    result: set[str] = set()
    section = _top_level_section(kernel_task_plan, "kernel_tasks")
    for block in re.split(r"(?m)^\s*-\s+task_id\s*:", section)[1:]:
        first_line, _, rest = block.partition("\n")
        task_id = first_line.strip().split()[0] if first_line.strip() else ""
        action = _field_value(rest, "route_action").lower()
        if task_id and action in actions:
            result.add(task_id.strip().strip('"').strip("'"))
    return result


def _field_value(block: str, field: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(field)}\s*:\s*([^\s#]+)", block)
    return match.group(1).strip().strip('"').strip("'") if match else ""


def _branch_materialization_status(branch_matrix: str, family_count: int) -> str:
    if not branch_matrix.strip():
        return "missing"
    branch_count = _branch_count(branch_matrix)
    if branch_count == 0:
        return "empty"
    lowered = branch_matrix.lower()
    if (
        "family_id" not in lowered
        or "materialization_role" not in lowered
        or "representative_case_id" not in lowered
        or "condition_snapshot" not in lowered
        or "trigger_preconditions" not in lowered
        or "source_spans" not in lowered
    ):
        return "warning"
    if family_count and branch_count > max(10, family_count * 5):
        return "warning"
    return "pass"


def _yaml_list_values(text: str, key: str) -> list[str]:
    values: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            in_block = True
            inline = stripped[len(key) + 1 :].strip()
            if inline.startswith("[") and inline.endswith("]"):
                body = inline.strip("[]").strip()
                if body:
                    values.extend(item.strip().strip('"').strip("'") for item in body.split(","))
                in_block = False
            continue
        if in_block:
            if stripped.startswith("- "):
                values.append(stripped[2:].strip().strip('"').strip("'"))
            elif stripped and not line.startswith((" ", "\t")):
                break
    return [value for value in values if value]


def _next_actions(decision: str) -> list[str]:
    if decision == "green":
        return ["  - Use route.md and kernel task traceability for downstream analysis."]
    if decision == "yellow":
        return ["  - Review warnings before downstream impact analysis.", "  - Fill missing evidence where possible."]
    return ["  - Complete Macro Boundary Agent outputs.", "  - Fill IO, tiling family, and kernel alignment evidence."]


if __name__ == "__main__":
    raise SystemExit(main())
