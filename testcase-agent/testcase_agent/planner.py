from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

from .hashing import semantic_plan_hash, semantic_snapshot_hash, stable_hash
from .io import ensure_output_dirs, output_root, read_json, read_yaml, write_yaml


SUPPORTED_KINDS = [
    "family",
    "tiling_key_field_value",
    "tiling_key_field",
    "tiling_key_relation",
    "compile_template",
    "kernel_path",
    "kernel_branch",
    "runtime_variable_state",
    "optional_input_mode",
    "dtype_layout_class",
    "tilingdata_boundary",
    "core_split_boundary",
    "tail_boundary",
    "workspace_boundary",
    "pipeline_resource_mode",
    "numerical_mode",
]
KIND_ORDER = {kind: idx for idx, kind in enumerate(SUPPORTED_KINDS)}
REACHABLE = {"reachable", "reachable_narrow", "runtime_conditional", "conditional", "unknown", ""}
UNREACHABLE = {"unreachable", "excluded", "not_reachable"}
NON_SEMANTIC_COMBO_FIELDS = {"reachability", "status", "reason", "unreachable_reason", "notes", "evidence_refs", "source_refs"}
RESERVED_MATCH_KEYS = {
    "key_pattern",
    "pattern",
    "family_refs",
    "kernel_path_refs",
    "dtype",
    "dtypes",
    "layout",
    "layouts",
    "dtype_layout_class",
    "dtype_layout_classes",
    "optional_inputs",
    "feature_flags",
}
TEST_LEVELS = ("L0", "L1", "L2")
LEVEL_ORDER = {level: idx for idx, level in enumerate(TEST_LEVELS)}
BOUNDARY_KIND_LEVELS = {
    "tilingdata_boundary",
    "core_split_boundary",
    "tail_boundary",
    "workspace_boundary",
    "pipeline_resource_mode",
}


class TgPlanError(RuntimeError):
    pass


def tg_plan(project_root: Path, op_name: str, *, level: str = "L1", focus: str = "") -> dict[str, Any]:
    project_root = project_root.resolve()
    out_root = output_root(project_root, op_name)
    ensure_output_dirs(out_root)
    snapshot_path = out_root / "snapshot" / "understand_contract.json"
    if not snapshot_path.exists():
        raise TgPlanError(f"Snapshot missing. Run tg-init first: {snapshot_path}")

    snapshot = read_json(snapshot_path)
    expected_hash = semantic_snapshot_hash(snapshot)
    if snapshot.get("snapshot_hash") != expected_hash:
        raise TgPlanError("SNAPSHOT_HASH_MISMATCH: snapshot_hash does not match snapshot contents")
    plan = build_plan(snapshot, level=level, focus=focus)
    write_plan_outputs(out_root, plan, snapshot)
    return plan


def build_plan(snapshot: dict[str, Any], *, level: str = "L1", focus: str = "") -> dict[str, Any]:
    level = normalize_level(level)
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    contract = _as_dict(files.get("contracts/testcase.yaml"))
    coverage = _as_dict(files.get("tiling/coverage_model.yaml"))
    branches = _as_dict(files.get("kernel/branches.yaml"))
    impact = _as_dict(files.get("cross_layer/impact_graph.yaml"))
    semantic_focus = build_semantic_focus(files, level, focus)

    obligations: list[dict[str, Any]] = []
    if level == "L0":
        add_l0_obligations(obligations, files, coverage, contract, semantic_focus)
    elif level == "L2":
        add_l2_exhaustive_key_obligations(obligations, files, contract, semantic_focus)
    else:
        add_l1_obligations(obligations, files, coverage, contract, branches, impact, semantic_focus)
    obligations = filter_obligations_by_focus(obligations, semantic_focus)
    obligations = deterministic_obligations(obligations)
    validate_unique_obligation_ids(obligations)
    level_blockers = level_specific_blockers(level, obligations, semantic_focus)
    blockers = hard_blockers(obligations, contract) + level_blockers
    matrix = build_matrix(obligations)
    planning_context = {
        "test_level": level,
        "semantic_focus": semantic_focus,
        "selected_semantic_subgraph": semantic_focus.get("selected_semantic_subgraph", {}),
        "exhaustive_key_scope": semantic_focus.get("exhaustive_within_scope") is True,
        "boundary_policy": boundary_policy(level),
        "negative_case_policy": negative_case_policy(level),
        "pruning_result": _as_dict(semantic_focus.get("tiling_key_coverage")).get("pruned_count"),
        "merging_result": _as_dict(semantic_focus.get("tiling_key_coverage")).get("semantic_merge_group_count"),
        "realization_result": {
            key: _as_dict(semantic_focus.get("tiling_key_coverage")).get(key)
            for key in ("realized_key_count", "unrealized_key_count", "ambiguous_key_count")
        },
    }
    gaps = contract_gaps(level, contract, coverage, files)
    unresolved = {
        "status": "blocked" if blockers or gaps else "ready_for_manual_review",
        "blocking_hard_obligations": blockers,
        "unresolved_obligations": [item for item in obligations if item["status"] in {"unresolved", "conflicting"}],
        "contract_gaps": gaps,
    }
    if semantic_focus.get("unresolved_terms"):
        unresolved["status"] = "blocked"
        unresolved["blocking_hard_obligations"].append(
            {
                "id": "SEMANTIC_FOCUS_UNRESOLVED",
                "kind": "semantic_focus",
                "priority": "hard",
                "status": "unresolved",
                "target_refs": [],
                "reason": "focus contains unresolved terms",
            }
        )
    review = build_review(snapshot, obligations, matrix, unresolved, level=level, semantic_focus=semantic_focus)
    plan_hash = semantic_plan_hash(snapshot.get("snapshot_hash"), obligations, matrix, unresolved, planning_context)
    return {
        "version": 1,
        "created_at": _now(),
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "test_level": level,
        "semantic_focus": semantic_focus,
        "planning_context": planning_context,
        "obligations": obligations,
        "matrix": matrix,
        "unresolved": unresolved,
        "review": review,
        "plan_hash": plan_hash,
    }


def add_l1_obligations(
    out: list[dict[str, Any]],
    files: dict[str, Any],
    coverage: dict[str, Any],
    contract: dict[str, Any],
    branches: dict[str, Any],
    impact: dict[str, Any],
    semantic_focus: dict[str, Any],
) -> None:
    before = len(out)
    add_family_obligations(out, coverage, contract)
    add_key_field_obligations(out, coverage, contract)
    add_key_relation_obligations(out, coverage, contract)
    add_contract_bucket_obligations(out, contract)
    add_kernel_branch_obligations(out, branches)
    add_interface_dimension_obligations(out, contract)
    add_impact_resource_obligations(out, impact)
    add_runtime_variable_obligations(out, files, semantic_focus)
    add_boundary_value_obligations(out, files, semantic_focus)
    add_negative_obligations(out, files, contract, semantic_focus)
    for item in out[before:]:
        if item.get("test_level"):
            continue
        reason = "main runtime, functional, boundary, or reject coverage"
        decorate_obligation(item, "L1", default_origin_for(item, files), reason, semantic_focus)


def add_l0_obligations(out: list[dict[str, Any]], files: dict[str, Any], coverage: dict[str, Any], contract: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    families = [item for item in _iter_items(coverage.get("family_obligations")) if _reachable_item(item)]
    buckets = _as_dict(contract.get("coverage_obligations"))
    families.extend(item for item in _iter_items(buckets.get("families")) if _reachable_item(item))
    paths = resolve_kernel_path_specs(files, contract)
    dtypes = [item for item in _iter_items(_as_dict(contract.get("interface")).get("dtype_layout_domains")) if _reachable_item(item)]
    input_realizations = _as_dict(_as_dict(files.get("tiling/constraints.yaml")).get("input_realization"))

    selected_family, selected_path, selected_dtype, selection = select_l0_smoke(files, families, paths, dtypes, input_realizations)
    if not selection.get("compatible"):
        blocker = make_obligation(
            "family",
            {"id": "L0_MINIMAL_INPUT_BLOCKED", "status": "unresolved", "reason": selection.get("reason") or "no compatible minimal smoke tuple"},
            target_refs=[],
            priority="hard",
        )
        decorate_obligation(blocker, "L0", {"artifact": "contracts/testcase.yaml", "entity_ref": "", "reason": "minimal_input_unavailable"}, selection, semantic_focus)
        out.append(blocker)
        return
    if selected_family:
        family_ref = str(selected_family.get("family_id") or selected_family.get("target_ref") or _first_ref(selected_family) or selected_family.get("id"))
        item = make_obligation("family", selected_family, target_refs=[family_ref], priority=selected_family.get("priority") or "hard")
        decorate_obligation(item, "L0", {"artifact": "tiling/coverage_model.yaml", "entity_ref": family_ref, "reason": "minimal_reachable_family"}, selection, semantic_focus)
        out.append(item)
    if selected_path:
        item = make_obligation("kernel_path", selected_path, priority=selected_path.get("priority") or "hard")
        decorate_obligation(item, "L0", {"artifact": "contracts/testcase.yaml", "entity_ref": _first_ref(item), "reason": "minimal_main_kernel_path"}, selection, semantic_focus)
        out.append(item)
    if selected_dtype:
        name = str(selected_dtype.get("id") or selected_dtype.get("name") or selected_dtype.get("class") or selected_dtype.get("dtype") or "")
        if name:
            item = make_obligation("dtype_layout_class", selected_dtype, target_refs=[name], priority=selected_dtype.get("priority") or "normal")
            decorate_obligation(item, "L0", {"artifact": "contracts/testcase.yaml", "entity_ref": name, "reason": "mainstream_dtype_layout"}, selection, semantic_focus)
            out.append(item)
    if not out:
        blocker = make_obligation(
            "family",
            {"id": "L0_MINIMAL_INPUT_BLOCKED", "status": "unresolved", "reason": "minimal legal input cannot be proven from KB"},
            target_refs=[],
            priority="hard",
        )
        decorate_obligation(blocker, "L0", {"artifact": "contracts/testcase.yaml", "entity_ref": "", "reason": "minimal_input_unavailable"}, "block instead of inventing shape", semantic_focus)
        out.append(blocker)


def add_l2_exhaustive_key_obligations(out: list[dict[str, Any]], files: dict[str, Any], contract: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    exhaustive = _as_dict(files.get("tiling/exhaustive_key_space.yaml"))
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    blocks = _iter_items(exhaustive.get("template_blocks"))
    if not blocks:
        blocker = make_obligation(
            "tiling_key_field_value",
            {
                "id": "L2_EXHAUSTIVE_KEY_SPACE_BLOCKED",
                "status": "unresolved",
                "reason": "exhaustive_key_space_unavailable",
                "constraints": {},
            },
            target_refs=[],
            priority="hard",
        )
        decorate_obligation(blocker, "L2", {"artifact": "tiling/exhaustive_key_space.yaml", "entity_ref": "", "reason": "exhaustive_key_space_unavailable"}, "block L2 when exhaustive key space is unavailable", semantic_focus)
        out.append(blocker)
        semantic_focus["level_status"] = "blocked"
        semantic_focus["reason"] = "exhaustive_key_space_unavailable"
        semantic_focus["tiling_key_coverage"] = {
            "raw_expanded_count": 0,
            "pruned_count": 0,
            "merged_count": 0,
            "reachable_key_count": 0,
            "realized_key_count": 0,
            "unrealized_key_count": 0,
        }
        return

    keys, stats, blockers = expand_l2_tiling_keys(exhaustive, constraints, semantic_focus)
    for blocker in blockers:
        decorate_obligation(blocker, "L2", {"artifact": "tiling/exhaustive_key_space.yaml", "entity_ref": "", "reason": blocker.get("unresolved_reason") or blocker.get("reason") or "exhaustive_key_blocker"}, str(blocker.get("unresolved_reason") or "exhaustive key blocker"), semantic_focus)
        out.append(blocker)
    for idx, key in enumerate(keys, start=1):
        realization = key["realization"]
        status = "pending" if realization["status"] == "realized" else "unresolved"
        item = make_obligation(
            "tiling_key_field_value",
            {
                "id": f"L2_KEY_{idx:04d}",
                "status": status,
                "reason": "" if status == "pending" else realization["reason"],
                "target_value": key["fields"],
                "target_expr": _combo_expr(key["fields"]),
                "constraints": {"expr": _combo_expr(key["fields"])},
                "realization_hints": {
                    "expected_tiling_key": key["fields"],
                    "realization_source": key.get("realization_source"),
                    "realization_confidence": realization["confidence"],
                },
            },
            target_refs=sorted(key["fields"]),
            priority="high",
        )
        item["expected_tiling_key"] = key["fields"]
        item["realization_source"] = key.get("realization_source")
        item["realization"] = realization
        item["merge"] = key.get("merge", {})
        item["audit"] = {"expected_tiling_key": key["fields"], "observed_tiling_key": None, "mismatch_policy": "fail"}
        decorate_obligation(item, "L2", {"artifact": "tiling/exhaustive_key_space.yaml", "entity_ref": str(key.get("block_id") or ""), "reason": "reachable_exhaustive_tiling_key"}, "one witness for reachable TilingKey", semantic_focus)
        out.append(item)
    semantic_focus["tiling_key_coverage"] = stats


def add_family_obligations(out: list[dict[str, Any]], coverage: dict[str, Any], contract: dict[str, Any]) -> None:
    items = coverage.get("family_obligations") or []
    for item in _iter_items(items):
        family_id = str(item.get("family_id") or item.get("id") or item.get("target") or "")
        if not family_id:
            continue
        out.append(make_obligation("family", item, target_refs=[family_id], priority=item.get("priority") or "hard"))

    buckets = _as_dict(contract.get("coverage_obligations"))
    for item in _iter_items(buckets.get("families")):
        out.append(make_obligation("family", item, priority=item.get("priority") or "hard"))


def add_key_field_obligations(out: list[dict[str, Any]], coverage: dict[str, Any], contract: dict[str, Any]) -> None:
    fields = _as_dict(coverage.get("key_field_obligations"))
    for field_name, item in sorted(fields.items()):
        item = item if isinstance(item, dict) else {"values": item}
        if is_derived_or_bound(item):
            continue
        payload = {"field": field_name, **item}
        out.extend(expand_key_field_obligations(payload, priority=item.get("priority") or "high"))

    for item in _iter_items(_as_dict(contract.get("coverage_obligations")).get("tiling_keys")):
        kind = str(item.get("kind") or item.get("coverage_kind") or "").lower()
        if kind and kind != "tiling_key_field":
            continue
        if is_relation_item(item):
            continue
        if is_derived_or_bound(item):
            continue
        if item.get("field") or item.get("field_name") or item.get("values"):
            out.extend(expand_key_field_obligations(item, priority=item.get("priority") or "high"))


def add_key_relation_obligations(out: list[dict[str, Any]], coverage: dict[str, Any], contract: dict[str, Any]) -> None:
    for item in _iter_items(coverage.get("key_relation_obligations")):
        out.extend(expand_relation_obligations(item, priority=item.get("priority") or "high"))

    for item in _iter_items(_as_dict(contract.get("coverage_obligations")).get("tiling_keys")):
        if is_relation_item(item):
            out.extend(expand_relation_obligations(item, priority=item.get("priority") or "high"))


def add_contract_bucket_obligations(out: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    buckets = _as_dict(contract.get("coverage_obligations"))
    bucket_kind = {
        "compile_templates": "compile_template",
        "template_bindings": "compile_template",
        "kernel_paths": "kernel_path",
        "kernel_branches": "kernel_branch",
        "tilingdata": "tilingdata_boundary",
        "core_split": "core_split_boundary",
        "tail": "tail_boundary",
        "workspace": "workspace_boundary",
        "pipeline_resources": "pipeline_resource_mode",
        "pipeline": "pipeline_resource_mode",
        "numerical": "numerical_mode",
    }
    for bucket, kind in bucket_kind.items():
        for item in _iter_items(buckets.get(bucket)):
            if kind == "kernel_branch":
                out.extend(expand_kernel_branch_obligations(item, priority=item.get("priority") or default_priority(kind)))
            else:
                out.append(make_obligation(kind, item, priority=item.get("priority") or default_priority(kind)))
    for item in _iter_items(contract.get("kernel_branch_obligations")):
        out.extend(expand_kernel_branch_obligations(item, priority=item.get("priority") or "high"))


def add_kernel_branch_obligations(out: list[dict[str, Any]], branches: dict[str, Any]) -> None:
    for item in _iter_items(branches.get("branches")):
        if is_derived_or_bound(item) or item.get("compile_time_fixed") is True or item.get("runtime") is False:
            continue
        out.extend(expand_kernel_branch_obligations(item, priority=item.get("priority") or "high"))


def add_runtime_variable_obligations(out: list[dict[str, Any]], files: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    variable_constraints = {
        str(item.get("var") or item.get("id") or ""): item
        for item in _iter_items(_as_dict(files.get("tiling/constraints.yaml")).get("variable_constraints"))
        if str(item.get("var") or item.get("id") or "")
    }
    for item in _iter_items(_as_dict(files.get("registry/variables.yaml")).get("variables")):
        var_ref = str(item.get("id") or item.get("stable_id") or "")
        if var_ref and var_ref not in variable_constraints:
            variable_constraints[var_ref] = item
    for field_name, spec in _as_dict(_as_dict(files.get("tiling/coverage_model.yaml")).get("key_field_obligations")).items():
        if not isinstance(spec, dict):
            continue
        for var_ref in {
            str(spec.get("id") or ""),
            f"VAR_{str(spec.get('id') or field_name).removeprefix('KEY_')}",
            f"VAR_KEY_{str(field_name).upper()}",
        }:
            if var_ref and var_ref not in variable_constraints and (spec.get("values") or spec.get("enum_values")):
                variable_constraints[var_ref] = {"values": spec.get("values") or spec.get("enum_values")}
    for artifact, section in (
        ("tiling/variables.yaml", "variables"),
        ("kernel/variables.yaml", "runtime_variables"),
        ("kernel/variables.yaml", "path_decision_points"),
        ("kernel/variables.yaml", "tilingdata_reads"),
    ):
        for item in _iter_items(_as_dict(files.get(artifact)).get(section)):
            if is_derived_or_bound(item) or item.get("compile_time_fixed") is True:
                continue
            var_id = str(item.get("id") or item.get("var") or item.get("name") or "")
            if not var_id:
                continue
            if item.get("branch_ref") or item.get("branch_refs"):
                continue
            values, gap = runtime_variable_values({**_as_dict(variable_constraints.get(var_id)), **item})
            if gap:
                payload = {
                    **item,
                    "id": f"RUNTIME_DOMAIN_NOT_PARTITIONED_{slugify(var_id)}",
                    "status": "unresolved",
                    "reason": gap,
                    "coverage_bucket": "runtime_variable",
                    "variable_scope": runtime_variable_scope(section),
                }
                obligation = make_obligation("runtime_variable_state", payload, target_refs=[var_id], priority="hard")
                decorate_obligation(obligation, "L1", {"artifact": artifact, "entity_ref": var_id, "reason": f"{section}_runtime_variable"}, "runtime variable domain needs declared partitions", semantic_focus)
                out.append(obligation)
                continue
            for value in values:
                payload = {
                    **item,
                    "target_value": value,
                    "constraints": _expr_eq(_var_id(var_id), value),
                    "coverage_bucket": "runtime_variable",
                    "variable_scope": runtime_variable_scope(section),
                }
                obligation = make_obligation("runtime_variable_state", payload, target_refs=[var_id], priority=item.get("priority") or "normal")
                decorate_obligation(obligation, "L1", {"artifact": artifact, "entity_ref": var_id, "reason": f"{section}_runtime_variable"}, "runtime variable state/domain bucket", semantic_focus)
                out.append(obligation)


def runtime_variable_scope(section: str) -> str:
    return {
        "variables": "tiling",
        "runtime_variables": "kernel",
        "path_decision_points": "path_decision",
        "tilingdata_reads": "tilingdata_read",
    }.get(section, "kernel")


def runtime_variable_values(item: dict[str, Any]) -> tuple[list[Any], str]:
    domain = item.get("domain")
    var_type = str(item.get("type") or item.get("data_type") or item.get("kind") or "").lower()
    if var_type in {"bool", "boolean"}:
        return [True, False], ""
    values = _as_list(domain if isinstance(domain, list) else item.get("values") or item.get("enum_values") or _as_dict(domain).get("values"))
    if values:
        return values, ""
    buckets = _as_list(item.get("buckets") or item.get("equivalence_classes") or item.get("runtime_states") or item.get("branch_partitions") or item.get("boundary_values") or _as_dict(domain).get("buckets"))
    if buckets:
        out = []
        for bucket in buckets:
            if isinstance(bucket, dict):
                out.append(bucket.get("representative", bucket.get("value", bucket.get("id", bucket.get("name")))))
            else:
                out.append(bucket)
        return [value for value in out if value not in (None, "")], ""
    if var_type in {"int", "integer"} or any(key in item for key in ("min", "max")) or any(key in _as_dict(domain) for key in ("min", "max")):
        return [], "RUNTIME_DOMAIN_NOT_PARTITIONED"
    return [], ""


def add_interface_dimension_obligations(out: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    interface = _as_dict(contract.get("interface"))
    for item in _iter_items(interface.get("optional_inputs")):
        name = str(item.get("id") or item.get("name") or item.get("input") or "")
        if not name:
            continue
        for state, value in (("present", True), ("absent", False)):
            payload = {
                "id": item.get("id") or f"optional_{name}_{state}",
                "name": name,
                "target_value": value,
                "target_state": state,
                "optional_state": state,
                "dimension_policy": "additional_dimension_no_cartesian_product",
                "notes": "Optional input modes are additional dimensions, not a family cartesian expansion.",
                **item,
            }
            out.append(make_obligation("optional_input_mode", payload, target_refs=[_optional_ref(name)], priority=item.get("priority") or "normal"))

    for item in _iter_items(interface.get("dtype_layout_domains")):
        name = str(item.get("id") or item.get("name") or item.get("class") or item.get("dtype") or "")
        if not name:
            continue
        payload = {"dimension_policy": "attach_to_existing_family_or_path", **item}
        out.append(make_obligation("dtype_layout_class", payload, target_refs=[name], priority=item.get("priority") or "normal"))


def add_impact_resource_obligations(out: list[dict[str, Any]], impact: dict[str, Any]) -> None:
    for item in _iter_items(impact.get("nodes")) + _iter_items(impact.get("impacts")):
        kind = str(item.get("kind") or item.get("type") or "").lower()
        if "workspace" in kind:
            out.append(make_obligation("workspace_boundary", item, priority=item.get("priority") or "normal"))
        elif "pipeline" in kind or "resource" in kind:
            out.append(make_obligation("pipeline_resource_mode", item, priority=item.get("priority") or "normal"))


def expand_key_field_obligations(item: dict[str, Any], *, priority: str) -> list[dict[str, Any]]:
    field = str(item.get("field") or item.get("field_name") or item.get("id") or "")
    target_ref = str(item.get("target_ref") or item.get("id") or field)
    if not field:
        return []
    fixed = item.get("compile_time_fixed") is True or item.get("fixed") is True
    values = _as_list(item.get("values") or item.get("enum_values"))
    if fixed:
        fixed_value = item.get("value", values[0] if values else item.get("fixed_value"))
        payload = {**item, "field": field, "target_value": fixed_value, "coverage_bucket": "fixed_value"}
        payload["constraints"] = _expr_eq(_key_var_id(target_ref, field), fixed_value)
        return [make_obligation("tiling_key_field_value", payload, target_refs=[target_ref], priority=priority)]
    if values:
        obligations = []
        unreachable_values = {str(value) for value in _as_list(item.get("unreachable_values"))}
        for value in values:
            payload = {**item, "field": field, "target_value": value, "coverage_bucket": "discrete_value"}
            payload["constraints"] = _expr_eq(_key_var_id(target_ref, field), value)
            if str(value) in unreachable_values:
                payload["reachability"] = "unreachable"
                payload.setdefault("reason", "value marked unreachable by contract")
            obligations.append(make_obligation("tiling_key_field_value", payload, target_refs=[target_ref], priority=priority))
        return obligations
    boundary_values = _as_list(item.get("boundary_values") or item.get("buckets"))
    return [
        make_obligation(
            "tiling_key_field_value",
            {**item, "field": field, "target_value": value, "coverage_bucket": "declared_boundary", "constraints": _expr_eq(_key_var_id(target_ref, field), value)},
            target_refs=[target_ref],
            priority=priority,
        )
        for value in boundary_values
    ]


def expand_kernel_branch_obligations(item: dict[str, Any], *, priority: str) -> list[dict[str, Any]]:
    target = str(item.get("target_ref") or item.get("branch_ref") or item.get("id") or item.get("branch_id") or item.get("name") or "")
    if not target:
        return []
    variants = [str(value) for value in _as_list(item.get("variants")) if str(value)]
    if variants:
        obligations = []
        for variant in variants:
            payload = {
                **item,
                "target_value": variant,
                "target_state": variant,
                "coverage_bucket": "declared_variant",
                "constraints": _expr_eq(_branch_var_id(target), variant),
            }
            obligations.append(make_obligation("kernel_branch", payload, target_refs=[target], priority=priority))
        return obligations
    if "target_value" in item:
        value = _bool_or_none(item["target_value"])
        if value is None:
            return []
        payload = {**item, "target_value": value, "constraints": _expr_eq(_branch_var_id(target), value)}
        return [make_obligation("kernel_branch", payload, target_refs=[target], priority=priority)]
    if item.get("single_side") is True or item.get("cover_false") is False:
        values = [True]
    else:
        values = [True, False]
    unreachable_values = {str(_bool_or_none(value)).lower() for value in _as_list(item.get("unreachable_values") or item.get("unreachable_sides"))}
    obligations = []
    for value in values:
        payload = {**item, "target_value": value, "target_state": str(value).lower(), "constraints": _expr_eq(_branch_var_id(target), value)}
        if str(value).lower() in unreachable_values:
            payload["reachability"] = "unreachable"
            payload.setdefault("reason", f"branch side {value} marked unreachable by contract")
        obligations.append(make_obligation("kernel_branch", payload, target_refs=[target], priority=priority))
    return obligations


def expand_relation_obligations(item: dict[str, Any], *, priority: str) -> list[dict[str, Any]]:
    constraints = _as_dict(item.get("constraints"))
    relation_type = str(item.get("relation_type") or constraints.get("relation_type") or "").lower()
    combinations = item.get("combinations") or constraints.get("combinations")
    if combinations is None:
        combinations = item.get("must_cover") or constraints.get("must_cover")
    if relation_type in {"compatible_set", "must_cover"} or isinstance(combinations, list):
        if not combinations:
            return [
                make_obligation(
                    "tiling_key_relation",
                    {**item, "status": "unresolved", "reason": "empty relation combination list", "coverage_bucket": relation_type or "must_cover"},
                    priority=priority,
                )
            ]
        obligations: list[dict[str, Any]] = []
        seen: dict[str, str] = {}
        for combo in combinations:
            if not isinstance(combo, dict):
                return [
                    make_obligation(
                        "tiling_key_relation",
                        {**item, "status": "unresolved", "reason": "relation combination must be a mapping", "coverage_bucket": relation_type or "must_cover"},
                        priority=priority,
                    )
                ]
            combo_values = {key: value for key, value in combo.items() if key not in NON_SEMANTIC_COMBO_FIELDS}
            signature = stable_hash(combo_values)
            state = "unreachable" if str(combo.get("reachability") or combo.get("status") or "").lower() in UNREACHABLE else "reachable"
            if signature in seen and seen[signature] != state:
                obligations.append(
                    make_obligation(
                        "tiling_key_relation",
                        {
                            **item,
                            "status": "conflicting",
                            "reason": "RELATION_COMBINATION_STATUS_CONFLICT",
                            "coverage_bucket": relation_type or "must_cover",
                            "target_refs": sorted(str(key) for key in combo_values),
                        },
                        target_refs=sorted(str(key) for key in combo_values),
                        priority="hard",
                    )
                )
                continue
            if signature in seen:
                continue
            seen[signature] = state
            unreachable = state == "unreachable"
            payload = {
                **item,
                "parent_obligation_id": str(item.get("id") or item.get("target_ref") or ""),
                "coverage_bucket": relation_type or "must_cover",
                "target_expr": _combo_expr(combo_values),
                "target_value": combo_values,
                "target_refs": sorted(str(key) for key in combo_values),
            }
            if unreachable:
                payload["reachability"] = "unreachable"
                payload["reason"] = str(combo.get("reason") or combo.get("unreachable_reason") or "relation combination marked unreachable")
            obligations.append(make_obligation("tiling_key_relation", payload, target_refs=payload["target_refs"], priority=priority))
        return obligations
    return [make_obligation("tiling_key_relation", item, priority=priority)]


def is_relation_item(item: dict[str, Any]) -> bool:
    constraints = _as_dict(item.get("constraints"))
    kind = str(item.get("kind") or item.get("coverage_kind") or "").lower()
    return bool(
        kind == "tiling_key_relation"
        or item.get("relation_type")
        or item.get("linked_relations")
        or item.get("must_cover")
        or item.get("combinations")
        or constraints.get("relation_type")
        or constraints.get("linked_relations")
        or constraints.get("must_cover")
        or constraints.get("combinations")
    )


def normalize_level(level: str) -> str:
    normalized = str(level or "L1").strip().upper()
    if normalized not in TEST_LEVELS:
        raise TgPlanError(f"Unsupported test level: {level}")
    return normalized


def build_semantic_focus(files: dict[str, Any], level: str, focus: str) -> dict[str, Any]:
    focus = str(focus or "").strip()
    result = {
        "original_query": focus,
        "level": level,
        "exhaustive_within_scope": level == "L2",
        "layout_predicates": {"include": [], "exclude": []},
        "dtype_predicates": {"include": [], "exclude": []},
        "family_refs": [],
        "kernel_path_refs": [],
        "branch_predicates": [],
        "tiling_key_predicates": [],
        "variable_predicates": [],
        "optional_input_predicates": [],
        "resolved_entities": [],
        "unresolved_terms": [],
    }
    if not focus:
        return result

    aliases = alias_index(files)
    known = known_entity_index(files)
    tokens = extract_focus_terms(focus)
    consumed: set[str] = set()
    for token in tokens:
        upper = token.upper()
        if upper in {"TND", "ND", "NZ", "NCHW", "NHWC"}:
            result["layout_predicates"]["include"].append(upper)
            result["resolved_entities"].append(_resolved(token, upper, "high", "layout_literal"))
            consumed.add(token)
            continue
        if upper in {"FP16", "BF16", "FP32", "INT8", "INT32"}:
            result["dtype_predicates"]["include"].append(upper)
            result["resolved_entities"].append(_resolved(token, upper, "high", "dtype_literal"))
            consumed.add(token)
            continue
        ref = aliases.get(token.lower()) or aliases.get(upper.lower()) or known.get(upper)
        if ref:
            add_focus_ref(result, token, ref, "registry_alias" if token.lower() in aliases else "stable_id")
            consumed.add(token)
    for token in tokens:
        if token in consumed or token.lower() in {"all", "only", "tilingkey", "tiling", "key"}:
            continue
        if re.search(r"[A-Za-z0-9_]*[A-Za-z][A-Za-z0-9_]*", token):
            result["unresolved_terms"].append({"query_term": token, "reason": "unable_to_resolve_unique_stable_id"})
    for key in ("include", "exclude"):
        result["layout_predicates"][key] = sorted(dict.fromkeys(result["layout_predicates"][key]))
        result["dtype_predicates"][key] = sorted(dict.fromkeys(result["dtype_predicates"][key]))
    for key in ("family_refs", "kernel_path_refs"):
        result[key] = sorted(dict.fromkeys(result[key]))
    result["branch_predicates"] = sorted(result["branch_predicates"], key=lambda item: (item["branch_ref"], str(item["state"])))
    return result


def alias_index(files: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for rel in ("registry/aliases.yaml", "query/terminology.yaml"):
        data = _as_dict(files.get(rel))
        for item in _iter_items(data.get("aliases") or data.get("terms")):
            alias = str(item.get("alias") or item.get("term") or item.get("name") or "")
            target = str(item.get("target_id") or item.get("id") or item.get("resolved_ref") or "")
            if alias and target:
                aliases[alias.lower()] = target
    return aliases


def known_entity_index(files: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    for rel in ("tiling/families.yaml", "kernel/paths.yaml", "kernel/branches.yaml", "cross_layer/behavior_graph.yaml", "cross_layer/impact_graph.yaml"):
        for item, _path in _iter_dicts(files.get(rel)):
            ref = str(item.get("id") or item.get("stable_id") or "")
            if ref:
                found[ref.upper()] = ref
            name = str(item.get("name") or item.get("canonical_name") or "")
            if name and ref:
                found[name.upper()] = ref
    return found


def extract_focus_terms(focus: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]+", focus)


def add_focus_ref(result: dict[str, Any], term: str, ref: str, source: str) -> None:
    if ref.startswith("FAM_"):
        result["family_refs"].append(ref)
    elif ref.startswith("KPATH_"):
        result["kernel_path_refs"].append(ref)
    elif ref.startswith(("KBR_", "KDEC_")):
        result["branch_predicates"].append({"branch_ref": ref, "state": infer_branch_state(result.get("original_query", ""), term)})
    elif ref.startswith("KEY_"):
        result["tiling_key_predicates"].append({"field_ref": ref})
    elif ref.startswith("VAR_"):
        result["variable_predicates"].append({"var_ref": ref})
    result["resolved_entities"].append(_resolved(term, ref, "high", source))


def infer_branch_state(query: str, term: str) -> Any:
    prefix = query[: max(query.lower().find(term.lower()), 0)]
    lowered = prefix.lower()
    if any(word in lowered for word in ("\u4e0d\u8d70", "exclude", "without", "not ", "false", "off", "absent")):
        return False
    if any(word in lowered for word in ("\u8d70", "include", "with", "true", "on", "present")):
        return True
    idx = query.lower().find(term.lower())
    suffix = query[idx : idx + len(term) + 12] if idx >= 0 else ""
    if "\u5206\u652f" in suffix or "branch" in suffix.lower():
        return True
    return "unspecified"


def _resolved(term: str, ref: str, confidence: str, source: str) -> dict[str, str]:
    return {"query_term": term, "resolved_ref": ref, "confidence": confidence, "resolution_source": source}


def filter_obligations_by_focus(obligations: list[dict[str, Any]], semantic_focus: dict[str, Any]) -> list[dict[str, Any]]:
    if not semantic_focus.get("original_query"):
        return obligations
    if semantic_focus.get("unresolved_terms"):
        return obligations
    family_refs = set(semantic_focus.get("family_refs") or [])
    path_refs = set(semantic_focus.get("kernel_path_refs") or [])
    branch_refs = {item.get("branch_ref") for item in semantic_focus.get("branch_predicates") or []}
    if not any((family_refs, path_refs, branch_refs)):
        return obligations
    kept: list[dict[str, Any]] = []
    for item in obligations:
        refs = set(str(ref) for ref in item.get("target_refs") or [])
        if family_refs and item.get("kind") == "family" and not refs.intersection(family_refs):
            continue
        if path_refs and item.get("kind") == "kernel_path" and not refs.intersection(path_refs):
            continue
        if branch_refs and item.get("kind") == "kernel_branch" and not refs.intersection(branch_refs):
            continue
        if branch_refs and item.get("kind") == "kernel_branch":
            pred = next((pred for pred in semantic_focus.get("branch_predicates") or [] if pred.get("branch_ref") in refs), {})
            state = pred.get("state")
            if state != "unspecified" and "target_value" in item and normalize_literal(item.get("target_value")) != normalize_literal(state):
                continue
        item["semantic_scope_refs"] = sorted(set(item.get("semantic_scope_refs") or []) | family_refs | path_refs | branch_refs)
        item["focus_decision"] = {"action": "include", "reason": "matches semantic focus", "path_refs": sorted(refs)}
        kept.append(item)
    return kept


def decorate_obligation(item: dict[str, Any], level: str, origin: dict[str, Any], reason: str, semantic_focus: dict[str, Any], *, expected_behavior: str = "success") -> None:
    item["test_level"] = level
    item["coverage_origin"] = origin
    item["selection_reason"] = reason
    item["semantic_scope_refs"] = sorted(
        dict.fromkeys(
            [str(ref) for ref in (semantic_focus.get("family_refs") or []) + (semantic_focus.get("kernel_path_refs") or [])]
            + [str(pred.get("branch_ref")) for pred in semantic_focus.get("branch_predicates") or [] if pred.get("branch_ref")]
        )
    )
    item["expected_behavior"] = expected_behavior
    if expected_behavior == "reject":
        item.setdefault(
            "case_expectation",
            {
                "expected_result": "reject",
                "reject_stage": "host_validation",
                "expected_error_class": "",
                "reason": item.get("unresolved_reason") or reason,
                "source_refs": item.get("source_refs") or [],
                "evidence_refs": item.get("evidence_refs") or [],
            },
        )


def default_origin_for(item: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    kind = item.get("kind")
    artifact = {
        "family": "tiling/coverage_model.yaml",
        "tiling_key_field_value": "tiling/coverage_model.yaml",
        "tiling_key_relation": "tiling/coverage_model.yaml",
        "compile_template": "kernel/compile_model.yaml",
        "kernel_path": "kernel/paths.yaml",
        "kernel_branch": "kernel/branches.yaml",
        "optional_input_mode": "contracts/testcase.yaml",
        "dtype_layout_class": "contracts/testcase.yaml",
        "tilingdata_boundary": "tiling/data_model.yaml",
        "core_split_boundary": "kernel/resources.yaml",
        "tail_boundary": "tiling/constraints.yaml",
        "workspace_boundary": "kernel/resources.yaml",
        "pipeline_resource_mode": "kernel/pipeline.yaml",
        "numerical_mode": "flow/numerical_model.yaml",
    }.get(str(kind), "contracts/testcase.yaml")
    return {"artifact": artifact, "entity_ref": _first_ref(item), "reason": f"{kind}_coverage"}


def add_boundary_value_obligations(out: list[dict[str, Any]], files: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    for item in _iter_items(constraints.get("variable_constraints")):
        var = str(item.get("var") or item.get("id") or "")
        for value in _as_list(item.get("boundary_values") or _as_dict(item.get("domain")).get("boundary_values")):
            payload = {**item, "target_value": value, "coverage_bucket": "boundary_value", "constraints": _expr_eq(var, value)}
            obligation = make_obligation("tiling_key_field_value", payload, target_refs=[var], priority=item.get("priority") or "high")
            decorate_obligation(obligation, "L1", {"artifact": "tiling/constraints.yaml", "entity_ref": var, "reason": "declared_boundary_value"}, "declared legal boundary value", semantic_focus)
            out.append(obligation)
    for rel, kind, bucket in (
        ("tiling/data_model.yaml", "tilingdata_boundary", "tilingdata_boundary"),
        ("kernel/resources.yaml", "workspace_boundary", "workspace_boundary"),
        ("kernel/pipeline.yaml", "pipeline_resource_mode", "pipeline_resource_mode"),
    ):
        for item, _path in _iter_dicts(files.get(rel)):
            for value in _as_list(item.get("boundary_values") or item.get("boundary_buckets")):
                payload = {**item, "target_value": value, "coverage_bucket": bucket}
                obligation = make_obligation(kind, payload, priority=item.get("priority") or "normal")
                decorate_obligation(obligation, "L1", {"artifact": rel, "entity_ref": _first_ref(obligation), "reason": "declared_boundary_value"}, "declared legal boundary value", semantic_focus)
                out.append(obligation)


def add_negative_obligations(out: list[dict[str, Any]], files: dict[str, Any], contract: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    pruning = _as_dict(constraints.get("tiling_key_pruning"))
    sources = [
        ("tiling/constraints.yaml", "key_unreachable", constraints.get("key_unreachable")),
        ("tiling/constraints.yaml", "tiling_key_pruning", pruning.get("pruned_combinations")),
        ("contracts/testcase.yaml", "negative", _as_dict(contract.get("coverage_obligations")).get("negative")),
    ]
    for artifact, reason, values in sources:
        for item in _iter_items(values):
            pattern = key_pattern_from(item)
            expr = compile_pattern_to_expr(pattern)
            status = "pending" if expr else "unresolved"
            payload = {
                **item,
                "status": status,
                "coverage_bucket": reason,
                "target_expr": expr or {},
                "constraints": {"expr": expr} if expr else {},
            }
            if not expr:
                payload["reason"] = "NEGATIVE_PATTERN_NOT_COMPILABLE"
            obligation = make_obligation("tiling_key_relation", payload, priority=item.get("priority") or "high")
            if not expr:
                obligation["priority"] = "hard"
                obligation["status"] = "unresolved"
                obligation["unresolved_reason"] = "NEGATIVE_PATTERN_NOT_COMPILABLE"
            stage = reject_stage_for(item)
            decorate_obligation(obligation, "L1", {"artifact": artifact, "entity_ref": str(item.get("id") or ""), "reason": reason}, "expected reject negative scenario", semantic_focus, expected_behavior="reject")
            expectation = _as_dict(obligation.get("case_expectation"))
            expectation["reject_stage"] = stage
            if stage == "unknown":
                obligation["status"] = "unresolved"
                obligation["priority"] = "hard"
                obligation["unresolved_reason"] = obligation.get("unresolved_reason") or "NEGATIVE_REJECT_STAGE_UNKNOWN"
            obligation["case_expectation"] = expectation
            out.append(obligation)


def compile_pattern_to_expr(pattern: dict[str, Any]) -> dict[str, Any]:
    pattern = _as_dict(pattern)
    if not pattern:
        return {}
    args = [{"op": "eq", "var": _var_id(str(key)), "value": value} for key, value in sorted(pattern.items())]
    return args[0] if len(args) == 1 else {"op": "and", "args": args}


def reject_stage_for(item: dict[str, Any]) -> str:
    for key in ("reject_stage", "expected_reject_stage", "validation_stage", "stage"):
        value = str(item.get(key) or "").strip()
        if value in {"interface", "host_validation", "tiling", "runtime"}:
            return value
    return "unknown"


def expand_l2_tiling_keys(exhaustive: dict[str, Any], constraints: dict[str, Any], semantic_focus: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    field_order = [str(item) for item in _as_list(exhaustive.get("field_order"))]
    raw_count = 0
    focus_filtered_count = 0
    pruned_count = 0
    relation_rejected_count = 0
    duplicate_key_count = 0
    merged_away_count = 0
    blockers: list[dict[str, Any]] = []
    merged: dict[str, dict[str, Any]] = {}
    summary = _as_dict(exhaustive.get("summary"))
    declared_sum = 0
    for block in _iter_items(exhaustive.get("template_blocks")):
        fixed = _as_dict(block.get("fixed_fields"))
        domains = _as_dict(block.get("field_domains"))
        fields = field_order or sorted(set(fixed) | set(domains))
        domain_lists = []
        varying_fields = []
        for field in fields:
            if field in fixed:
                continue
            values = _as_list(domains.get(field))
            if values:
                varying_fields.append(field)
                domain_lists.append(values)
        product_count = 1
        for values in domain_lists:
            product_count *= len(values)
        if not domain_lists:
            product_count = 1
        declared = int(block.get("product_count") or product_count)
        declared_sum += declared
        if declared != product_count:
            blockers.append(_blocker(f"L2_BLOCK_PRODUCT_COUNT_MISMATCH_{slugify(str(block.get('id') or stable_hash(block)[:8]))}", f"template block {block.get('id')} product_count={declared} actual={product_count}"))
            continue
        raw_count += declared
        for combo_values in product(*domain_lists) if domain_lists else [()]:
            combo = dict(fixed)
            combo.update(dict(zip(varying_fields, combo_values)))
            if focus_excludes_key(combo, semantic_focus):
                focus_filtered_count += 1
                continue
            if is_pruned_key(combo, constraints, block):
                pruned_count += 1
                continue
            relation_result = relation_allows_key(combo, constraints)
            if relation_result["status"] == "reject":
                relation_rejected_count += 1
                continue
            if relation_result["status"] == "block":
                blockers.append(_blocker(f"L2_RELATION_COMPILE_FAILED_{slugify(relation_result['reason'])[:40]}", relation_result["reason"]))
                continue
            merge_key, merge_info = merged_key_for(combo, constraints)
            canonical_fields = _as_dict(merge_info.get("canonical_fields")) or combo
            if merge_key in merged:
                duplicate_key_count += 1
                merged_away_count += 1
                merged[merge_key].setdefault("merge", {}).setdefault("overlay_witnesses", []).append(combo)
                continue
            realization = match_key_realization(canonical_fields, constraints, exhaustive)
            merged[merge_key] = {
                "fields": canonical_fields,
                "source_fields": combo,
                "block_id": block.get("id"),
                "realization_source": "reverse_realization_index" if realization["matched_reverse_realization_refs"] else "constraints.input_realization",
                "realization": realization,
                "merge": merge_info,
            }
    if "expanded_key_count" in summary and int(summary.get("expanded_key_count") or 0) != declared_sum:
        blockers.append(_blocker("L2_SUMMARY_COUNT_MISMATCH", f"summary.expanded_key_count={summary.get('expanded_key_count')} sum_product_count={declared_sum}"))
    for missing_ref in missing_pruning_refs(exhaustive, constraints):
        blockers.append(_blocker(f"L2_PRUNING_REF_MISSING_{slugify(missing_ref)}", f"template block pruning_ref not found: {missing_ref}"))
    reachable = [merged[key] for key in sorted(merged)]
    stats = {
        "raw_expanded_count": raw_count,
        "focus_filtered_count": focus_filtered_count,
        "pruned_count": pruned_count,
        "relation_rejected_count": relation_rejected_count,
        "duplicate_key_count": duplicate_key_count,
        "semantic_merge_group_count": len({str(key["merge"].get("group_id")) for key in merged.values() if key["merge"].get("semantic_merge") and key["merge"].get("group_id")}),
        "semantic_merged_source_count": len([key for key in merged.values() if key["merge"].get("semantic_merge")]),
        "merged_away_count": merged_away_count,
        "reachable_key_count": len(reachable),
        "realized_key_count": 0,
        "unrealized_key_count": 0,
        "ambiguous_key_count": 0,
    }
    stats["realized_key_count"] = len([key for key in reachable if key["realization"]["status"] == "realized"])
    stats["unrealized_key_count"] = len([key for key in reachable if key["realization"]["status"] == "unrealized"])
    stats["ambiguous_key_count"] = len([key for key in reachable if key["realization"]["status"] == "ambiguous"])
    return reachable, stats, blockers


def focus_excludes_key(combo: dict[str, Any], semantic_focus: dict[str, Any]) -> bool:
    includes = set(semantic_focus.get("layout_predicates", {}).get("include") or [])
    if includes:
        blob = " ".join(str(value).upper() for value in combo.values())
        if not any(value in blob for value in includes):
            return True
    for pred in semantic_focus.get("branch_predicates") or []:
        branch_ref = str(pred.get("branch_ref") or "")
        wanted = pred.get("state")
        if wanted == "unspecified":
            continue
        suffix = re.sub(r"^(KBR|KDEC)_", "", branch_ref).lower()
        suffix = re.sub(r"[^a-z0-9]+", "", suffix)
        for field, value in combo.items():
            field_key = re.sub(r"[^a-z0-9]+", "", str(field).lower())
            if suffix and (suffix in field_key or field_key in suffix):
                if normalize_literal(value) != normalize_literal(wanted):
                    return True
    return False


def match_key_realization(key_fields: dict[str, Any], constraints: dict[str, Any], exhaustive: dict[str, Any]) -> dict[str, Any]:
    input_realization = _as_dict(constraints.get("input_realization"))
    matched = []
    for rid, rule in sorted(input_realization.items()):
        if isinstance(rule, dict) and match_input_realization(key_fields, rule):
            matched.append(str(rid))
    reverse_index = _as_dict(exhaustive.get("reverse_realization_index"))
    reverse_matches = []
    for rid, rule in sorted(reverse_index.items()):
        if isinstance(rule, dict):
            pattern = _as_dict(rule.get("key_pattern") or rule.get("pattern") or rule.get("matches"))
            if pattern and pattern_matches(key_fields, pattern):
                reverse_matches.append(str(rid))
        elif isinstance(rule, str) and rule == stable_hash(key_fields):
            reverse_matches.append(str(rid))
    if len(matched) == 1 and not reverse_matches:
        status = "realized"
    elif not matched and len(reverse_matches) == 1:
        status = "realized"
    elif len(matched) + len(reverse_matches) == 0:
        status = "unrealized"
    else:
        status = "ambiguous"
    return {
        "status": status,
        "matched_input_realization_refs": matched,
        "matched_reverse_realization_refs": reverse_matches,
        "confidence": "high" if status == "realized" else "none" if status == "unrealized" else "low",
        "reason": "" if status == "realized" else "no matching realization rule" if status == "unrealized" else "multiple realization rules match this key",
    }


def match_input_realization(key_fields: dict[str, Any], rule: dict[str, Any]) -> bool:
    context = {
        "family_refs": _as_list(key_fields.get("family_refs") or key_fields.get("family")),
        "kernel_path_refs": _as_list(key_fields.get("kernel_path_refs") or key_fields.get("kernel_path")),
        "dtype": key_fields.get("dtype"),
        "layout": key_fields.get("layout"),
        "dtype_layout_class": key_fields.get("dtype_layout") or key_fields.get("dtype_layout_class"),
        "optional_inputs": key_fields.get("optional_inputs") if isinstance(key_fields.get("optional_inputs"), dict) else {"present": [], "absent": []},
        "key_fields": {key: value for key, value in key_fields.items() if key not in {"family", "family_refs", "kernel_path", "kernel_path_refs", "optional_inputs"}},
    }
    return match_input_realization_context(context, rule)


def match_input_realization_context(context: dict[str, Any], rule: dict[str, Any]) -> bool:
    matches = _as_dict(rule.get("matches"))
    pattern = input_realization_key_pattern(rule)
    if pattern and not pattern_matches(_as_dict(context.get("key_fields")), pattern):
        return False
    family_refs = set(str(ref) for ref in _as_list(matches.get("family_refs") or rule.get("family_refs")) if ref)
    if family_refs and not family_refs.intersection(set(str(ref) for ref in _as_list(context.get("family_refs")))):
        return False
    path_refs = set(str(ref) for ref in _as_list(matches.get("kernel_path_refs") or rule.get("kernel_path_refs")) if ref)
    if path_refs and not path_refs.intersection(set(str(ref) for ref in _as_list(context.get("kernel_path_refs")))):
        return False
    dtypes = set(str(item).upper() for item in _as_list(matches.get("dtypes") or matches.get("dtype") or rule.get("dtypes") or rule.get("dtype")) if item)
    if dtypes and str(context.get("dtype") or "").upper() not in dtypes:
        return False
    layouts = set(str(item).upper() for item in _as_list(matches.get("layouts") or matches.get("layout") or rule.get("layouts") or rule.get("layout")) if item)
    if layouts:
        key_fields = _as_dict(context.get("key_fields"))
        context_layout = str(context.get("layout") or key_fields.get("layout") or "").upper()
        if context_layout not in layouts:
            return False
    classes = set(str(item).upper() for item in _as_list(matches.get("dtype_layout_classes") or matches.get("dtype_layout_class") or rule.get("dtype_layout_classes") or rule.get("dtype_layout_class")) if item)
    if classes and str(context.get("dtype_layout_class") or "").upper() not in classes:
        return False
    optional = _as_dict(matches.get("optional_inputs") or rule.get("optional_inputs"))
    if optional:
        present = set(str(item) for item in _as_list(optional.get("present")))
        absent = set(str(item) for item in _as_list(optional.get("absent")))
        actual = _as_dict(context.get("optional_inputs"))
        if present and not present <= set(str(item) for item in _as_list(actual.get("present"))):
            return False
        if absent and not absent <= set(str(item) for item in _as_list(actual.get("absent"))):
            return False
    dtype_layout = str(rule.get("dtype_layout_intent") or "")
    if dtype_layout:
        blob = " ".join(str(value).upper() for value in (list(_as_dict(context.get("key_fields")).values()) + [context.get("dtype"), context.get("layout"), context.get("dtype_layout_class")]))
        tokens = [token.upper() for token in re.findall(r"[A-Za-z0-9_]+", dtype_layout)]
        if tokens and not any(token in blob for token in tokens):
            return False
    return bool(pattern or family_refs or path_refs or dtypes or layouts or classes or optional or dtype_layout)


def input_realization_key_pattern(rule: dict[str, Any]) -> dict[str, Any]:
    matches = _as_dict(rule.get("matches"))
    pattern = _as_dict(matches.get("key_pattern") or matches.get("pattern") or rule.get("key_pattern") or rule.get("pattern"))
    direct = {key: value for key, value in matches.items() if key not in RESERVED_MATCH_KEYS}
    if direct:
        merged = dict(pattern)
        merged.update(direct)
        return merged
    return pattern


def pattern_matches(combo: dict[str, Any], pattern: dict[str, Any]) -> bool:
    return all(normalize_literal(combo.get(key)) == normalize_literal(value) for key, value in pattern.items())


def is_pruned_key(combo: dict[str, Any], constraints: dict[str, Any], block: dict[str, Any]) -> bool:
    pruning = _as_dict(constraints.get("tiling_key_pruning"))
    pruning_items = _iter_items(pruning.get("pruned_combinations"))
    for item in _iter_items(constraints.get("key_unreachable")) + pruning_items:
        predicate = key_pattern_from(item)
        if predicate and all(combo.get(key) == value for key, value in predicate.items()):
            return True
    for ref in _as_list(block.get("pruning_refs")):
        for item in pruning_items:
            if str(item.get("id")) == str(ref):
                predicate = key_pattern_from(item)
                if predicate and all(combo.get(key) == value for key, value in predicate.items()):
                    return True
    return False


def missing_pruning_refs(exhaustive: dict[str, Any], constraints: dict[str, Any]) -> list[str]:
    pruning = _as_dict(constraints.get("tiling_key_pruning"))
    known = {str(item.get("id")) for item in _iter_items(pruning.get("pruned_combinations")) if item.get("id")}
    missing = []
    for block in _iter_items(exhaustive.get("template_blocks")):
        for ref in _as_list(block.get("pruning_refs")):
            if str(ref) not in known:
                missing.append(str(ref))
    return sorted(dict.fromkeys(missing))


def key_pattern_from(item: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(item.get("pattern") or item.get("fields") or item.get("key") or item.get("combo") or item.get("matches"))


def relation_allows_key(combo: dict[str, Any], constraints: dict[str, Any]) -> dict[str, str]:
    for rel in _iter_items(constraints.get("relations")):
        rtype = str(rel.get("type") or rel.get("relation_type") or "").lower()
        try:
            if rtype == "mutex":
                predicates = _as_list(rel.get("predicates"))
                if not predicates:
                    fields = _as_list(rel.get("fields"))
                    active_value = rel.get("active_value")
                    if active_value is None:
                        if fields and all(isinstance(combo.get(str(field)), bool) for field in fields):
                            active_value = True
                        else:
                            return {"status": "block", "reason": f"mutex relation requires predicates or active_value: {rel.get('id') or 'mutex'}"}
                    predicates = [{"field": field, "equals": active_value} for field in fields]
                active = [pred for pred in predicates if isinstance(pred, dict) and evaluate_relation_predicate(combo, pred)]
                if len(active) > 1:
                    return {"status": "reject", "reason": str(rel.get("id") or "mutex")}
            elif rtype in {"implies", "requires"}:
                source = relation_predicate_from(rel.get("source") or rel.get("if"))
                target = relation_predicate_from(rel.get("target") or rel.get("then") or rel.get("requires"))
                if not source or not target:
                    return {"status": "block", "reason": f"{rtype} relation requires structured source/target predicates: {rel.get('id') or rtype}"}
                if evaluate_relation_predicate(combo, source) and not evaluate_relation_predicate(combo, target):
                    return {"status": "reject", "reason": str(rel.get("id") or rtype)}
            elif rtype == "compatible_set":
                combos = _as_list(rel.get("combinations") or rel.get("must_cover"))
                match_mode = str(rel.get("match_mode") or "partial").lower()
                if match_mode not in {"partial", "exact"}:
                    return {"status": "block", "reason": f"unsupported compatible_set match_mode: {match_mode}"}
                if combos and not any(isinstance(item, dict) and compatible_set_matches(combo, item, match_mode) for item in combos):
                    return {"status": "reject", "reason": str(rel.get("id") or "compatible_set")}
            elif rtype == "compile_time_fixed":
                field = str(rel.get("field") or rel.get("var") or rel.get("target") or "")
                value = rel.get("value", rel.get("fixed_value"))
                if field and normalize_literal(combo.get(field)) != normalize_literal(value):
                    return {"status": "reject", "reason": str(rel.get("id") or "compile_time_fixed")}
            elif rtype == "runtime_guard":
                continue
            elif rtype:
                return {"status": "block", "reason": f"unsupported relation type: {rtype}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "block", "reason": f"relation compile failed: {exc}"}
    return {"status": "allow", "reason": ""}


def relation_predicate_from(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        field = value.get("field") or value.get("var") or value.get("key")
        if field and any(key in value for key in ("equals", "value", "is")):
            return {"field": str(field), "equals": value.get("equals", value.get("value", value.get("is")))}
    return {}


def evaluate_relation_predicate(combo: dict[str, Any], predicate: dict[str, Any]) -> bool:
    field = str(predicate.get("field") or predicate.get("var") or predicate.get("key") or "")
    if not field:
        raise ValueError("relation predicate missing field")
    if "equals" in predicate or "value" in predicate or "is" in predicate:
        expected = predicate.get("equals", predicate.get("value", predicate.get("is")))
        return normalize_literal(combo.get(field)) == normalize_literal(expected)
    if "in" in predicate or "values" in predicate:
        values = [normalize_literal(value) for value in _as_list(predicate.get("in") or predicate.get("values"))]
        return normalize_literal(combo.get(field)) in values
    raise ValueError("relation predicate missing equals/in")


def compatible_set_matches(combo: dict[str, Any], item: dict[str, Any], match_mode: str) -> bool:
    pattern = {key: value for key, value in item.items() if key not in NON_SEMANTIC_COMBO_FIELDS}
    if match_mode == "exact":
        return {key: normalize_literal(value) for key, value in combo.items()} == {key: normalize_literal(value) for key, value in pattern.items()}
    return pattern_matches(combo, pattern)


def merged_key_for(combo: dict[str, Any], constraints: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    merging = _as_dict(constraints.get("tiling_key_merging"))
    for group in _iter_items(merging.get("merged_groups")):
        for source in _as_list(group.get("source_combinations")):
            if isinstance(source, dict) and pattern_matches(combo, source):
                merged_into = _as_dict(group.get("merged_into")) or combo
                return stable_hash(merged_into), {
                    "semantic_merge": True,
                    "group_id": group.get("id"),
                    "canonical_fields": merged_into,
                    "source_fields": combo,
                    "source_combinations": _as_list(group.get("source_combinations")),
                    "overlay_witnesses": [],
                }
    return stable_hash(combo), {"semantic_merge": False, "canonical_fields": combo, "source_fields": combo, "overlay_witnesses": []}


def level_specific_blockers(level: str, obligations: list[dict[str, Any]], semantic_focus: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if level == "L2":
        stats = _as_dict(semantic_focus.get("tiling_key_coverage"))
        if semantic_focus.get("level_status") == "blocked":
            blockers.append({"id": "L2_EXHAUSTIVE_KEY_SPACE_BLOCKED", "kind": "tiling_key_coverage", "priority": "hard", "status": "unresolved", "target_refs": [], "reason": "exhaustive_key_space_unavailable"})
        elif stats.get("unrealized_key_count", 0) or stats.get("ambiguous_key_count", 0):
            blockers.append({"id": "L2_UNREALIZED_KEYS", "kind": "tiling_key_coverage", "priority": "hard", "status": "unresolved", "target_refs": [], "reason": "some reachable TilingKeys have no unique realization witness"})
    return blockers


def boundary_policy(level: str) -> dict[str, Any]:
    return {"enabled": level == "L1", "source": "KB declared boundary values only"}


def negative_case_policy(level: str) -> dict[str, Any]:
    return {"enabled": level == "L1", "expectation_schema": "case_expectation"}


def _blocker(code: str, reason: str) -> dict[str, Any]:
    item = make_obligation("tiling_key_field_value", {"id": code, "status": "unresolved", "reason": reason}, target_refs=[], priority="hard")
    item["id"] = code
    return item


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").upper()
    return slug or stable_hash(str(value))[:8].upper()


def validate_unique_obligation_ids(obligations: list[dict[str, Any]]) -> None:
    ids = [str(item.get("id") or "") for item in obligations]
    duplicates = sorted(item for item, count in Counter(ids).items() if item and count > 1)
    if duplicates:
        raise TgPlanError(f"DUPLICATE_OBLIGATION_ID: {', '.join(duplicates)}")


def select_l0_smoke(
    files: dict[str, Any],
    families: list[dict[str, Any]],
    paths: list[dict[str, Any]],
    dtypes: list[dict[str, Any]],
    input_realizations: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    family_path_index = build_family_path_index(files)
    rejected: list[dict[str, Any]] = []
    candidates: list[tuple[int, str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for family in families:
        family_ref = str(family.get("family_id") or _first_ref(family) or family.get("id") or "")
        for path in paths or [{}]:
            path_ref = str(_first_ref(path) or path.get("id") or "")
            compatibility = l0_compatible_refs(family_ref, path, family_path_index)
            if compatibility == "incompatible":
                rejected.append({"family": family_ref, "kernel_path": path_ref, "reason": "family/path incompatible"})
                continue
            for dtype in dtypes or [{}]:
                dtype_context = dtype_layout_context(dtype)
                dtype_ref = dtype_context["dtype_layout_class"]
                realization_refs = compatible_l0_realizations(family_ref, path_ref, dtype_context, input_realizations)
                if input_realizations and not realization_refs:
                    rejected.append({"family": family_ref, "kernel_path": path_ref, "dtype_layout": dtype_ref, "reason": "no compatible input realization"})
                    continue
                score = l0_score(family) + l0_score(path) + l0_score(dtype)
                if compatibility == "unknown":
                    score -= 1
                key = "|".join((family_ref, path_ref, dtype_ref))
                candidates.append((score, key, family, path, dtype))
    if not candidates:
        return None, None, None, {
            "compatible": False,
            "reason": "no compatible L0 family/path/dtype/input realization tuple",
            "rejected_candidates": rejected,
        }
    score, _key, family, path, dtype = sorted(candidates, key=lambda row: (-row[0], row[1]))[0]
    family_ref = str(family.get("family_id") or _first_ref(family) or family.get("id") or "")
    path_ref = str(_first_ref(path) or path.get("id") or "")
    dtype_context = dtype_layout_context(dtype)
    dtype_ref = dtype_context["dtype_layout_class"]
    return family, path if path else None, dtype if dtype else None, {
        "compatible": True,
        "score": score,
        "selected_family": family_ref,
        "selected_kernel_path": path_ref if path else "",
        "selected_dtype_layout": dtype_ref,
        "family_path_compatibility": l0_compatible_refs(family_ref, path, family_path_index) if path else "unknown",
        "compatible_input_realization_refs": compatible_l0_realizations(family_ref, path_ref, dtype_context, input_realizations),
        "rejected_candidates": rejected[:20],
    }


def resolve_kernel_path_specs(files: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in _iter_items(_as_dict(files.get("kernel/paths.yaml")).get("kernel_paths") or _as_dict(files.get("kernel/paths.yaml")).get("paths")):
        ref = str(item.get("id") or item.get("stable_id") or item.get("path_ref") or "")
        if ref and _reachable_item(item):
            by_id[ref] = dict(item)
    for item in _iter_items(_as_dict(contract.get("coverage_obligations")).get("kernel_paths")):
        if not _reachable_item(item):
            continue
        ref = str(_first_ref(item) or item.get("id") or item.get("stable_id") or "")
        if not ref:
            continue
        merged = dict(by_id.get(ref, {}))
        merged.update(item)
        merged.setdefault("id", ref)
        by_id[ref] = merged
    return [by_id[key] for key in sorted(by_id)]


def build_family_path_index(files: dict[str, Any]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    def add(path_ref: str, family_ref: str) -> None:
        if path_ref and family_ref:
            index.setdefault(str(path_ref), set()).add(str(family_ref))

    for item in _iter_items(_as_dict(files.get("kernel/paths.yaml")).get("kernel_paths") or _as_dict(files.get("kernel/paths.yaml")).get("paths")):
        path_ref = str(item.get("id") or item.get("stable_id") or item.get("path_ref") or "")
        for family_ref in _as_list(item.get("family_refs") or item.get("families") or item.get("family_ref")):
            add(path_ref, str(family_ref))
    for item in _iter_items(_as_dict(files.get("tiling/families.yaml")).get("families") or _as_dict(files.get("tiling/families.yaml")).get("family_obligations")):
        family_ref = str(item.get("id") or item.get("stable_id") or item.get("family_id") or "")
        for path_ref in _as_list(item.get("kernel_path_refs") or item.get("path_refs") or item.get("paths")):
            add(str(path_ref), family_ref)
    cross = _as_dict(files.get("cross_layer/tiling_to_kernel.yaml"))
    for item in _iter_items(cross.get("edges") or cross.get("relations") or cross.get("mappings") or cross.get("links")):
        source = str(item.get("source") or item.get("source_ref") or item.get("family_ref") or "")
        target = str(item.get("target") or item.get("target_ref") or item.get("kernel_path_ref") or "")
        relation = str(item.get("relation") or item.get("type") or item.get("kind") or "").lower()
        if source.startswith("KPATH_") and target.startswith("FAM_"):
            source, target = target, source
        if source.startswith("FAM_") and target.startswith("KPATH_") and (not relation or relation in {"dispatches_to", "uses_path", "maps_to", "selects", "family_to_path"}):
            add(target, source)
    return index


def l0_score(item: dict[str, Any]) -> int:
    text = " ".join(str(item.get(key) or "").lower() for key in ("id", "name", "kind", "role", "status", "priority", "layout", "dtype", "reason"))
    score = 0
    if any(word in text for word in ("confirmed", "reachable", "main", "default", "normal", "fp16", "nd")):
        score += 10
    if any(word in text for word in ("varlen", "tail", "risk", "workspace", "extreme", "negative", "reject", "tnd", "nz")):
        score -= 8
    if item.get("default") is True or item.get("main") is True:
        score += 20
    if item.get("requires_optional_input") is True:
        score -= 15
    return score


def l0_compatible_refs(family_ref: str, path: dict[str, Any], family_path_index: dict[str, set[str]] | None = None) -> str:
    path_ref = str(_first_ref(path) or path.get("id") or path.get("stable_id") or "")
    refs = set(str(ref) for ref in _as_list(path.get("family_refs") or path.get("families") or path.get("family_ref")) if ref)
    if family_path_index and path_ref in family_path_index:
        refs.update(family_path_index[path_ref])
    if not refs or not family_ref:
        return "unknown"
    return "compatible" if family_ref in refs else "incompatible"


def compatible_l0_realizations(family_ref: str, path_ref: str, dtype_context: dict[str, Any], input_realizations: dict[str, Any]) -> list[str]:
    refs = []
    context = {
        "family_refs": [family_ref] if family_ref else [],
        "kernel_path_refs": [path_ref] if path_ref else [],
        "dtype": dtype_context.get("dtype") or "",
        "layout": dtype_context.get("layout") or "",
        "dtype_layout_class": dtype_context.get("dtype_layout_class") or "",
        "optional_inputs": {"present": [], "absent": []},
        "key_fields": {},
    }
    for rid, rule in sorted(input_realizations.items()):
        if isinstance(rule, dict) and match_input_realization_context(context, rule):
            refs.append(str(rid))
    return refs


def dtype_layout_context(item: dict[str, Any]) -> dict[str, str]:
    ref = str(item.get("id") or item.get("name") or item.get("class") or item.get("dtype_layout_class") or item.get("dtype") or "")
    dtype = str(item.get("dtype") or "")
    layout = str(item.get("layout") or "")
    if ref:
        tokens = [token for token in re.split(r"[_:/-]+", ref) if token]
        if not dtype:
            dtype = next((token for token in tokens if token.upper() in {"FP16", "BF16", "FP32", "INT8", "INT32"}), "")
        if not layout:
            layout = next((token for token in tokens if token.upper() in {"ND", "TND", "NZ", "NCHW", "NHWC"}), "")
    return {"dtype_layout_class": ref, "dtype": dtype.upper(), "layout": layout.upper()}


def _reachable_item(item: dict[str, Any]) -> bool:
    state = str(item.get("reachability") or item.get("status") or "").lower()
    return state not in UNREACHABLE


def _first_ref(item: dict[str, Any]) -> str:
    refs = _as_list(item.get("target_refs") or item.get("target_ref") or item.get("family_id") or item.get("id"))
    return str(refs[0]) if refs else ""


def make_obligation(kind: str, item: dict[str, Any], *, target_refs: list[str] | None = None, priority: str = "normal") -> dict[str, Any]:
    reachability = str(item.get("reachability") or item.get("reachable") or "").lower()
    if str(item.get("status") or "").lower() in UNREACHABLE:
        reachability = str(item.get("status")).lower()
    if reachability in UNREACHABLE:
        status = "proof_required"
    else:
        state = str(item.get("status") or item.get("state") or "").lower()
        if state in {"conflicting", "unresolved"}:
            status = state
        else:
            status = "pending"
    unresolved_reason = str(item.get("unresolved_reason") or item.get("unreachable_reason") or item.get("reason") or "")
    refs = [str(ref) for ref in (target_refs if target_refs is not None else _as_list(item.get("target_refs") or item.get("target_ref") or item.get("family_refs") or item.get("family_id") or item.get("id"))) if str(ref)]
    source_refs = [str(ref) for ref in _as_list(item.get("source_refs") or item.get("source_ref")) if str(ref)]
    evidence_refs = [str(ref) for ref in _as_list(item.get("evidence_refs") or item.get("evidence_ref")) if str(ref)]
    obligation = {
        "id": "",
        "kind": kind,
        "target_refs": sorted(dict.fromkeys(refs)),
        "source_refs": sorted(dict.fromkeys(source_refs)),
        "priority": normalize_priority(str(priority or item.get("priority") or "normal")),
        "status": status,
        "reachability": reachability if reachability else "reachable",
        "constraints": normalize_constraints(item),
        "realization_hints": normalize_hints(item),
        "evidence_refs": sorted(dict.fromkeys(evidence_refs)),
        "unresolved_reason": unresolved_reason,
    }
    for key in ("target_value", "target_state", "target_expr", "parent_obligation_id", "coverage_bucket", "optional_state"):
        if key in item:
            obligation[key] = item[key]
    return obligation


def deterministic_obligations(obligations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dedup: dict[str, dict[str, Any]] = {}
    for item in obligations:
        key = stable_hash({k: v for k, v in item.items() if k != "id"})
        dedup[key] = item
    ordered = sorted(
        dedup.values(),
        key=lambda item: (
            KIND_ORDER.get(item["kind"], 999),
            ",".join(item.get("target_refs") or []),
            str(item.get("target_value", "")),
            str(item.get("target_state", "")),
            item.get("priority", ""),
            stable_hash(item),
        ),
    )
    counters: Counter[str] = Counter()
    for item in ordered:
        if str(item.get("id", "")).startswith("L2_"):
            continue
        counters[item["kind"]] += 1
        item["id"] = f"COV_PLAN_{slug(item['kind'])}_{counters[item['kind']]:03d}"
    return ordered


def hard_blockers(obligations: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = [
        {
            "id": item["id"],
            "kind": item["kind"],
            "priority": item["priority"],
            "status": item["status"],
            "target_refs": item["target_refs"],
            "reason": item["unresolved_reason"],
        }
        for item in obligations
        if item["priority"] == "hard" and item["status"] in {"conflicting", "unresolved"}
    ]
    for item in _iter_items(contract.get("conflicts")) + _iter_items(contract.get("unresolved")):
        priority = normalize_priority(str(item.get("priority") or item.get("severity") or item.get("level") or "normal"))
        status = str(item.get("status") or item.get("type") or "unresolved").lower()
        if priority == "hard" or status in {"conflicting", "unresolved"} and priority == "hard":
            blockers.append(
                {
                    "id": str(item.get("id") or ""),
                    "kind": "contract_issue",
                    "priority": priority,
                    "status": status,
                    "target_refs": _as_list(item.get("target_refs")),
                    "reason": str(item.get("reason") or item.get("message") or ""),
                }
            )
    return sorted(blockers, key=lambda item: (item["kind"], item["id"], item["status"]))


def build_matrix(obligations: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, dict[str, Any]] = {}
    by_level: dict[str, dict[str, Any]] = {}
    priority_counts = {"hard": 0, "high": 0, "normal": 0}
    for kind in SUPPORTED_KINDS:
        items = [item for item in obligations if item["kind"] == kind]
        by_kind[kind] = {
            "total": len(items),
            "reachable": len([item for item in items if item["reachability"] in REACHABLE]),
            "unreachable": len([item for item in items if item["reachability"] in UNREACHABLE]),
            "pending": len([item for item in items if item["status"] == "pending"]),
            "proof_required": len([item for item in items if item["status"] == "proof_required"]),
        }
        for item in items:
            priority_counts[item["priority"]] = priority_counts.get(item["priority"], 0) + 1
    for level in TEST_LEVELS:
        items = [item for item in obligations if item.get("test_level") == level]
        by_level[level] = {
            "total": len(items),
            "success": len([item for item in items if item.get("expected_behavior") == "success"]),
            "reject": len([item for item in items if item.get("expected_behavior") == "reject"]),
            "pending": len([item for item in items if item.get("status") == "pending"]),
            "blocked": len([item for item in items if item.get("status") in {"unresolved", "conflicting"}]),
        }
    branch_items = [item for item in obligations if item.get("kind") == "kernel_branch"]
    boundary_items = [item for item in obligations if item.get("kind") in BOUNDARY_KIND_LEVELS or item.get("coverage_bucket") == "boundary_value"]
    negative_items = [item for item in obligations if item.get("expected_behavior") == "reject"]
    l2_key_items = [item for item in obligations if item.get("test_level") == "L2"]
    return {
        "by_kind": by_kind,
        "by_level": by_level,
        "priority_counts": priority_counts,
        "total": len(obligations),
        "unreachable": [item["id"] for item in obligations if item["reachability"] in UNREACHABLE],
        "runtime_branch_coverage": {
            "obligation_count": len(branch_items),
            "covered_refs": sorted({ref for item in branch_items for ref in item.get("target_refs") or []}),
            "states": sorted(dict.fromkeys(str(item.get("target_state") or item.get("target_value")) for item in branch_items)),
        },
        "boundary_coverage": {"obligation_count": len(boundary_items), "kinds": sorted({str(item.get("kind")) for item in boundary_items})},
        "negative_case_coverage": {"obligation_count": len(negative_items), "reject_stages": sorted({str(_as_dict(item.get("case_expectation")).get("reject_stage") or "") for item in negative_items})},
        "tiling_key_coverage": {
            "obligation_count": len([item for item in obligations if item.get("kind") in {"tiling_key_field_value", "tiling_key_relation"}]),
            "l2_reachable_key_obligations": len(l2_key_items),
            "unrealized_key_obligations": len([item for item in l2_key_items if item.get("status") == "unresolved"]),
        },
    }


def contract_gaps(level: str, contract: dict[str, Any], coverage: dict[str, Any], files: dict[str, Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    buckets = _as_dict(contract.get("coverage_obligations"))
    interface = _as_dict(contract.get("interface"))
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    if level == "L0":
        if not coverage.get("family_obligations") and not buckets.get("families"):
            gaps.append({"field": "family_obligations", "reason": "L0 needs at least one legal family"})
        if not buckets.get("kernel_paths") and not _as_dict(files.get("kernel/paths.yaml")).get("kernel_paths"):
            gaps.append({"field": "kernel_paths", "reason": "L0 needs at least one matching kernel path"})
        if not interface.get("dtype_layout_domains"):
            gaps.append({"field": "interface.dtype_layout_domains", "reason": "L0 needs one dtype/layout"})
        if not _as_dict(constraints.get("input_realization")):
            gaps.append({"field": "tiling/constraints.yaml.input_realization", "reason": "L0 needs input realization or minimal input construction information"})
    elif level == "L1":
        if "variables" not in _as_dict(files.get("tiling/variables.yaml")):
            gaps.append({"field": "tiling/variables.yaml.variables", "reason": "L1 needs tiling runtime variables"})
        if "runtime_variables" not in _as_dict(files.get("kernel/variables.yaml")):
            gaps.append({"field": "kernel/variables.yaml.runtime_variables", "reason": "L1 needs kernel runtime variables"})
        if "branches" not in _as_dict(files.get("kernel/branches.yaml")):
            gaps.append({"field": "kernel/branches.yaml.branches", "reason": "L1 needs runtime branches"})
        if not buckets and not coverage:
            gaps.append({"field": "coverage_obligations", "reason": "L1 needs main functional coverage contract"})
        if "relations" not in constraints:
            gaps.append({"field": "tiling/constraints.yaml.relations", "reason": "L1 needs constraints for boundary/reject planning"})
    elif level == "L2":
        exhaustive = _as_dict(files.get("tiling/exhaustive_key_space.yaml"))
        if not exhaustive.get("template_blocks"):
            gaps.append({"field": "tiling/exhaustive_key_space.yaml.template_blocks", "reason": "L2 needs exhaustive template blocks"})
        if "relations" not in constraints:
            gaps.append({"field": "tiling/constraints.yaml.relations", "reason": "L2 needs constraints"})
        pruning = _as_dict(constraints.get("tiling_key_pruning"))
        if "performed" not in pruning:
            gaps.append({"field": "tiling/constraints.yaml.tiling_key_pruning.performed", "reason": "L2 needs pruning status"})
        merging = _as_dict(constraints.get("tiling_key_merging"))
        if "performed" not in merging:
            gaps.append({"field": "tiling/constraints.yaml.tiling_key_merging.performed", "reason": "L2 needs merging status"})
        if not _as_dict(constraints.get("input_realization")) and not _as_dict(exhaustive.get("reverse_realization_index")):
            gaps.append({"field": "input_realization", "reason": "L2 needs reverse realization or input realization"})
    return gaps


def build_review(
    snapshot: dict[str, Any],
    obligations: list[dict[str, Any]],
    matrix: dict[str, Any],
    unresolved: dict[str, Any],
    *,
    level: str,
    semantic_focus: dict[str, Any],
) -> str:
    counts = matrix["priority_counts"]
    allow_smt = not unresolved["blocking_hard_obligations"] and not unresolved["contract_gaps"]
    allow_smt_text_cn = "\u662f" if allow_smt else "\u5426"
    key_stats = _as_dict(semantic_focus.get("tiling_key_coverage"))
    lines = [
        "# TestAgent Coverage Plan Review",
        "",
        f"- Operator: {snapshot.get('op_name')}",
        f"- Test Level: {level}",
        f"- Focus: {semantic_focus.get('original_query') or '<none>'}",
        f"- Snapshot Hash: `{snapshot.get('snapshot_hash')}`",
        f"- Total obligations: {len(obligations)}",
        f"- Hard / High / Normal: {counts.get('hard', 0)} / {counts.get('high', 0)} / {counts.get('normal', 0)}",
        f"- Runtime branch obligations: {matrix['runtime_branch_coverage']['obligation_count']}",
        f"- Boundary obligations: {matrix['boundary_coverage']['obligation_count']}",
        f"- Negative expected-reject obligations: {matrix['negative_case_coverage']['obligation_count']}",
        f"- tiling_key_field_value obligations: {matrix['by_kind'].get('tiling_key_field_value', {}).get('total', 0)}",
        f"- TilingKey \u539f\u5b50\u503c\u4e49\u52a1\u6570: {matrix['by_kind'].get('tiling_key_field_value', {}).get('total', 0)}",
        f"- L2 exhaustive reachable / unrealized keys: {key_stats.get('reachable_key_count', 0)} / {key_stats.get('unrealized_key_count', 0)}",
        f"- Contract gaps: {len(unresolved['contract_gaps'])}",
        f"- Allow solve: {'yes' if allow_smt else 'no'}",
        f"- \u662f\u5426\u5141\u8bb8\u8fdb\u5165 SMT \u9636\u6bb5: {allow_smt_text_cn}",
        "",
        "## Semantic Focus",
        f"- resolved_entities: {len(semantic_focus.get('resolved_entities') or [])}",
        f"- unresolved_terms: {len(semantic_focus.get('unresolved_terms') or [])}",
        f"- family_refs: {', '.join(semantic_focus.get('family_refs') or []) or '<none>'}",
        f"- kernel_path_refs: {', '.join(semantic_focus.get('kernel_path_refs') or []) or '<none>'}",
        f"- branch_refs: {', '.join(str(item.get('branch_ref')) for item in semantic_focus.get('branch_predicates') or []) or '<none>'}",
        "",
        "## Level Matrix",
    ]
    for lvl in TEST_LEVELS:
        row = _as_dict(matrix.get("by_level")).get(lvl, {})
        lines.append(f"- {lvl}: total={row.get('total', 0)} success={row.get('success', 0)} reject={row.get('reject', 0)} blocked={row.get('blocked', 0)}")
    lines.append("")
    lines.append("## Blocking Issues")
    if unresolved["blocking_hard_obligations"]:
        lines.extend(f"- `{item['id']}` {item['status']}: {item['reason'] or 'Hard obligation needs confirmation'}" for item in unresolved["blocking_hard_obligations"])
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Manual Review")
    lines.append("- Approve only after checking level, focus, structured selector, selected entities, and blockers.")
    lines.append("- Human supplements must be written to `plan/human_supplement.yaml`.")
    return "\n".join(lines) + "\n"


def write_plan_outputs(out_root: Path, plan: dict[str, Any], snapshot: dict[str, Any]) -> None:
    write_yaml(
        out_root / "plan" / "coverage_obligations.yaml",
        {
            "version": 1,
            "snapshot_hash": snapshot.get("snapshot_hash"),
            "test_level": plan["test_level"],
            "semantic_focus": plan["semantic_focus"],
            "obligations": plan["obligations"],
            "plan_hash": plan["plan_hash"],
        },
    )
    write_yaml(out_root / "plan" / "coverage_matrix.yaml", {"version": 1, "snapshot_hash": snapshot.get("snapshot_hash"), "test_level": plan["test_level"], **plan["matrix"], "plan_hash": plan["plan_hash"]})
    write_yaml(out_root / "plan" / "unresolved.yaml", {"version": 1, "snapshot_hash": snapshot.get("snapshot_hash"), "test_level": plan["test_level"], **plan["unresolved"], "plan_hash": plan["plan_hash"]})
    write_yaml(
        out_root / "plan" / "semantic_focus.yaml",
        {
            "version": 1,
            "snapshot_hash": snapshot.get("snapshot_hash"),
            "test_level": plan["test_level"],
            "semantic_focus": plan["semantic_focus"],
            "planning_context": plan["planning_context"],
            "plan_hash": plan["plan_hash"],
        },
    )
    (out_root / "plan" / "review.md").write_text(plan["review"], encoding="utf-8")
    supplement = out_root / "plan" / "human_supplement.yaml"
    if not supplement.exists():
        write_yaml(
            supplement,
            {
                "version": 1,
                "status": "pending",
                "decision": "",
                "approved_snapshot_hash": "",
                "approved_plan_hash": "",
                "approved_at": "",
                "options": ["approve", "revise", "supplement", "stop"],
                "supplements": [],
                "notes": "Human input is independent from Understand Canonical KB.",
            },
        )
    else:
        current = read_yaml(supplement)
        changed = (
            current.get("approved_snapshot_hash") not in {"", snapshot.get("snapshot_hash")}
            or current.get("approved_plan_hash") not in {"", plan["plan_hash"]}
        )
        current.setdefault("version", 1)
        current.setdefault("supplements", [])
        current.setdefault("notes", "")
        current.setdefault("approved_at", "")
        if changed:
            current["status"] = "reapproval_required"
            current["decision"] = ""
            current["approved_snapshot_hash"] = ""
            current["approved_plan_hash"] = ""
        else:
            current.setdefault("status", "pending")
            current.setdefault("decision", "")
            current.setdefault("approved_snapshot_hash", "")
            current.setdefault("approved_plan_hash", "")
        write_yaml(supplement, current)


def normalize_constraints(item: dict[str, Any]) -> dict[str, Any]:
    base = dict(item.get("constraints")) if isinstance(item.get("constraints"), dict) else {}
    for key in ("expr", "pattern", "key_pattern", "matches", "must_cover", "combinations", "fields", "values", "boundary_values", "relation_type", "linked_relations", "source", "target", "unreachable_values", "unreachable_combinations"):
        if key in item:
            base[key] = item[key]
    return base


def normalize_hints(item: dict[str, Any]) -> dict[str, Any]:
    keys = ("realization_hints", "linked_input_realization", "input_realization", "shape_intent", "dtype_layout_intent", "dimension_policy", "notes")
    return {key: item[key] for key in keys if key in item}


def is_derived_or_bound(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "").lower() for key in ("kind", "source_type", "role", "rule_kind"))
    return item.get("derived") is True or item.get("independent") is False or "derived" in text


def normalize_priority(priority: str) -> str:
    priority = priority.lower()
    if priority in {"hard", "blocking", "blocker", "must"}:
        return "hard"
    if priority in {"high", "important"}:
        return "high"
    return "normal"


def default_priority(kind: str) -> str:
    if kind in {"family", "kernel_path"}:
        return "hard"
    if kind in {"tiling_key_relation", "kernel_branch", "compile_template"}:
        return "high"
    return "normal"


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper() or "UNKNOWN"


def _iter_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [{"id": str(key), **item} if isinstance(item, dict) else {"id": str(key), "value": item} for key, item in sorted(value.items())]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _iter_dicts(value: Any, path: str = "$") -> list[tuple[dict[str, Any], str]]:
    found: list[tuple[dict[str, Any], str]] = []
    if isinstance(value, dict):
        found.append((value, path))
        for key, child in value.items():
            found.extend(_iter_dicts(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found.extend(_iter_dicts(child, f"{path}[{idx}]"))
    return found


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def _expr_eq(var_id: str, value: Any) -> dict[str, Any]:
    return {"expr": {"op": "eq", "var": var_id, "value": value}}


def _combo_expr(combo: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": "and",
        "args": [{"op": "eq", "var": _relation_var_id(str(key)), "value": value} for key, value in sorted(combo.items())],
    }


def _key_var_id(target_ref: str, field: str) -> str:
    if target_ref.startswith("KEY_"):
        return _var_id(target_ref)
    return _var_id(f"KEY_{field}")


def _branch_var_id(target_ref: str) -> str:
    if target_ref.startswith(("KBR_", "KDEC_")):
        return _var_id(target_ref)
    return _var_id(f"BRANCH_{target_ref}")


def _optional_ref(name: str) -> str:
    return name if name.startswith("VAR_OPTIONAL_") else _var_id(f"OPTIONAL_{name}")


def _var_id(name: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(name)).strip("_").upper()
    if text.startswith("VAR_"):
        return text
    return f"VAR_{text or 'UNKNOWN'}"


def _relation_var_id(ref: str) -> str:
    if ref.startswith("VAR_"):
        return ref
    if ref.startswith(("KEY_", "TDF_", "KVAR_", "KBR_", "KDEC_")):
        return _var_id(ref)
    return _var_id(ref)


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "true":
            return True
        if text == "false":
            return False
    return None


def normalize_literal(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "on", "present", "yes"}:
            return True
        if text in {"false", "0", "off", "absent", "no"}:
            return False
    return value


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
