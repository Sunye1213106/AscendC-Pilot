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
TEST_LEVELS = ("L0", "L1", "L2", "L3")
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
        add_l2_obligations(obligations, files, coverage, contract, impact, semantic_focus)
    elif level == "L3":
        add_l3_obligations(obligations, files, contract, semantic_focus)
    else:
        add_l1_obligations(obligations, files, coverage, contract, branches, impact, semantic_focus)
    obligations = filter_obligations_by_focus(obligations, semantic_focus)
    obligations = deterministic_obligations(obligations)
    level_blockers = level_specific_blockers(level, obligations, semantic_focus)
    blockers = hard_blockers(obligations, contract) + level_blockers
    matrix = build_matrix(obligations)
    planning_context = {
        "test_level": level,
        "semantic_focus": semantic_focus,
        "exhaustive_scope": semantic_focus.get("exhaustive_within_scope") is True,
        "boundary_policy": boundary_policy(level),
        "negative_case_policy": negative_case_policy(level),
    }
    unresolved = {
        "status": "blocked" if blockers else "ready_for_manual_review",
        "blocking_hard_obligations": blockers,
        "unresolved_obligations": [item for item in obligations if item["status"] in {"unresolved", "conflicting"}],
        "contract_gaps": contract_gaps(contract, coverage),
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
    for item in out[before:]:
        decorate_obligation(item, "L1", default_origin_for(item, files), "main runtime and functional coverage", semantic_focus)


def add_l0_obligations(out: list[dict[str, Any]], files: dict[str, Any], coverage: dict[str, Any], contract: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    families = [item for item in _iter_items(coverage.get("family_obligations")) if _reachable_item(item)]
    buckets = _as_dict(contract.get("coverage_obligations"))
    families.extend(item for item in _iter_items(buckets.get("families")) if _reachable_item(item))
    paths = [item for item in _iter_items(buckets.get("kernel_paths")) if _reachable_item(item)]
    dtypes = [item for item in _iter_items(_as_dict(contract.get("interface")).get("dtype_layout_domains")) if _reachable_item(item)]

    selected_family = first_by_id(families)
    selected_path = first_by_id(paths)
    selected_dtype = first_by_id(dtypes)
    if selected_family:
        family_ref = str(selected_family.get("family_id") or selected_family.get("target_ref") or _first_ref(selected_family) or selected_family.get("id"))
        item = make_obligation("family", selected_family, target_refs=[family_ref], priority=selected_family.get("priority") or "hard")
        decorate_obligation(item, "L0", {"artifact": "tiling/coverage_model.yaml", "entity_ref": family_ref, "reason": "minimal_reachable_family"}, "minimal legal smoke family", semantic_focus)
        out.append(item)
    if selected_path:
        item = make_obligation("kernel_path", selected_path, priority=selected_path.get("priority") or "hard")
        decorate_obligation(item, "L0", {"artifact": "contracts/testcase.yaml", "entity_ref": _first_ref(item), "reason": "minimal_main_kernel_path"}, "minimal legal smoke kernel path", semantic_focus)
        out.append(item)
    if selected_dtype:
        name = str(selected_dtype.get("id") or selected_dtype.get("name") or selected_dtype.get("class") or selected_dtype.get("dtype") or "")
        if name:
            item = make_obligation("dtype_layout_class", selected_dtype, target_refs=[name], priority=selected_dtype.get("priority") or "normal")
            decorate_obligation(item, "L0", {"artifact": "contracts/testcase.yaml", "entity_ref": name, "reason": "mainstream_dtype_layout"}, "one mainstream dtype/layout", semantic_focus)
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


def add_l2_obligations(
    out: list[dict[str, Any]],
    files: dict[str, Any],
    coverage: dict[str, Any],
    contract: dict[str, Any],
    impact: dict[str, Any],
    semantic_focus: dict[str, Any],
) -> None:
    before = len(out)
    add_contract_bucket_obligations(out, contract)
    add_interface_dimension_obligations(out, contract)
    add_impact_resource_obligations(out, impact)
    add_boundary_value_obligations(out, files, semantic_focus)
    add_negative_obligations(out, files, contract, semantic_focus)
    for item in out[before:]:
        if item.get("test_level"):
            continue
        reason = "legal boundary coverage" if item["kind"] in BOUNDARY_KIND_LEVELS else "boundary or negative scenario"
        decorate_obligation(item, "L2", default_origin_for(item, files), reason, semantic_focus)


def add_l3_obligations(out: list[dict[str, Any]], files: dict[str, Any], contract: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    exhaustive = _as_dict(files.get("tiling/exhaustive_key_space.yaml"))
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    blocks = _iter_items(exhaustive.get("template_blocks"))
    if not blocks:
        blocker = make_obligation(
            "tiling_key_field_value",
            {
                "id": "L3_EXHAUSTIVE_KEY_SPACE_BLOCKED",
                "status": "unresolved",
                "reason": "exhaustive_key_space_unavailable",
                "constraints": {},
            },
            target_refs=[],
            priority="hard",
        )
        decorate_obligation(blocker, "L3", {"artifact": "tiling/exhaustive_key_space.yaml", "entity_ref": "", "reason": "exhaustive_key_space_unavailable"}, "block L3 when exhaustive key space is unavailable", semantic_focus)
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

    keys, stats = expand_l3_tiling_keys(exhaustive, constraints, semantic_focus)
    input_realization = _as_dict(constraints.get("input_realization"))
    for idx, key in enumerate(keys, start=1):
        realized = bool(input_realization or key.get("reverse_realization"))
        status = "pending" if realized else "unresolved"
        item = make_obligation(
            "tiling_key_field_value",
            {
                "id": f"L3_KEY_{idx:04d}",
                "status": status,
                "reason": "" if realized else "tiling key has no input realization witness",
                "target_value": key["fields"],
                "target_expr": _combo_expr(key["fields"]),
                "constraints": {"expr": _combo_expr(key["fields"])},
                "realization_hints": {
                    "expected_tiling_key": key["fields"],
                    "realization_source": key.get("realization_source"),
                    "realization_confidence": "medium" if realized else "none",
                },
            },
            target_refs=sorted(key["fields"]),
            priority="high",
        )
        item["expected_tiling_key"] = key["fields"]
        item["realization_source"] = key.get("realization_source")
        item["audit"] = {"expected_tiling_key": key["fields"], "observed_tiling_key": None, "mismatch_policy": "fail"}
        decorate_obligation(item, "L3", {"artifact": "tiling/exhaustive_key_space.yaml", "entity_ref": str(key.get("block_id") or ""), "reason": "reachable_exhaustive_tiling_key"}, "one witness for reachable TilingKey", semantic_focus)
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
        "exhaustive_within_scope": level == "L3",
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
        result["branch_predicates"].append({"branch_ref": ref, "state": True})
    elif ref.startswith("KEY_"):
        result["tiling_key_predicates"].append({"field_ref": ref})
    elif ref.startswith("VAR_"):
        result["variable_predicates"].append({"var_ref": ref})
    result["resolved_entities"].append(_resolved(term, ref, "high", source))


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
        item["semantic_scope_refs"] = sorted(set(item.get("semantic_scope_refs") or []) | family_refs | path_refs | branch_refs)
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
            decorate_obligation(obligation, "L2", {"artifact": "tiling/constraints.yaml", "entity_ref": var, "reason": "declared_boundary_value"}, "declared legal boundary value", semantic_focus)
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
                decorate_obligation(obligation, "L2", {"artifact": rel, "entity_ref": _first_ref(obligation), "reason": "declared_boundary_value"}, "declared legal boundary value", semantic_focus)
                out.append(obligation)


def add_negative_obligations(out: list[dict[str, Any]], files: dict[str, Any], contract: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    sources = [
        ("tiling/constraints.yaml", "key_unreachable", constraints.get("key_unreachable")),
        ("tiling/constraints.yaml", "tiling_key_pruning", constraints.get("tiling_key_pruning")),
        ("contracts/testcase.yaml", "negative", _as_dict(contract.get("coverage_obligations")).get("negative")),
    ]
    for artifact, reason, values in sources:
        for item in _iter_items(values):
            payload = {**item, "status": "pending", "coverage_bucket": reason}
            obligation = make_obligation("tiling_key_relation", payload, priority=item.get("priority") or "high")
            decorate_obligation(obligation, "L2", {"artifact": artifact, "entity_ref": str(item.get("id") or ""), "reason": reason}, "expected reject negative scenario", semantic_focus, expected_behavior="reject")
            out.append(obligation)


def expand_l3_tiling_keys(exhaustive: dict[str, Any], constraints: dict[str, Any], semantic_focus: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    field_order = [str(item) for item in _as_list(exhaustive.get("field_order"))]
    raw_count = 0
    reachable: list[dict[str, Any]] = []
    pruned_count = 0
    merged: dict[str, dict[str, Any]] = {}
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
        raw_count += declared
        for combo_values in product(*domain_lists) if domain_lists else [()]:
            combo = dict(fixed)
            combo.update(dict(zip(varying_fields, combo_values)))
            if focus_excludes_key(combo, semantic_focus):
                continue
            if is_pruned_key(combo, constraints, block):
                pruned_count += 1
                continue
            signature = stable_hash(combo)
            merged.setdefault(
                signature,
                {
                    "fields": combo,
                    "block_id": block.get("id"),
                    "realization_source": "reverse_realization_index" if exhaustive.get("reverse_realization_index") else "constraints.input_realization",
                    "reverse_realization": _as_dict(exhaustive.get("reverse_realization_index")).get(signature) or _as_dict(exhaustive.get("reverse_realization_index")).get(str(block.get("id") or "")),
                },
            )
    reachable = [merged[key] for key in sorted(merged)]
    stats = {
        "raw_expanded_count": raw_count,
        "pruned_count": pruned_count,
        "merged_count": len(merged),
        "reachable_key_count": len(reachable),
        "realized_key_count": 0,
        "unrealized_key_count": 0,
    }
    input_realization = _as_dict(constraints.get("input_realization"))
    stats["realized_key_count"] = len([key for key in reachable if input_realization or key.get("reverse_realization")])
    stats["unrealized_key_count"] = stats["reachable_key_count"] - stats["realized_key_count"]
    return reachable, stats


def focus_excludes_key(combo: dict[str, Any], semantic_focus: dict[str, Any]) -> bool:
    includes = set(semantic_focus.get("layout_predicates", {}).get("include") or [])
    if includes:
        blob = " ".join(str(value).upper() for value in combo.values())
        if not any(value in blob for value in includes):
            return True
    for pred in semantic_focus.get("branch_predicates") or []:
        branch_ref = str(pred.get("branch_ref") or "")
        wanted = pred.get("state")
        suffix = re.sub(r"^(KBR|KDEC)_", "", branch_ref).lower()
        suffix = re.sub(r"[^a-z0-9]+", "", suffix)
        for field, value in combo.items():
            field_key = re.sub(r"[^a-z0-9]+", "", str(field).lower())
            if suffix and (suffix in field_key or field_key in suffix):
                if bool(value) != bool(wanted):
                    return True
    return False


def is_pruned_key(combo: dict[str, Any], constraints: dict[str, Any], block: dict[str, Any]) -> bool:
    for item in _iter_items(constraints.get("key_unreachable")) + _iter_items(constraints.get("tiling_key_pruning")):
        predicate = _as_dict(item.get("fields") or item.get("key") or item.get("combo") or item.get("matches"))
        if predicate and all(combo.get(key) == value for key, value in predicate.items()):
            return True
    for ref in _as_list(block.get("pruning_refs")):
        for item in _iter_items(constraints.get("tiling_key_pruning")):
            if str(item.get("id")) == str(ref):
                predicate = _as_dict(item.get("fields") or item.get("key") or item.get("combo") or item.get("matches"))
                if predicate and all(combo.get(key) == value for key, value in predicate.items()):
                    return True
    return False


def level_specific_blockers(level: str, obligations: list[dict[str, Any]], semantic_focus: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if level == "L3":
        stats = _as_dict(semantic_focus.get("tiling_key_coverage"))
        if semantic_focus.get("level_status") == "blocked":
            blockers.append({"id": "L3_EXHAUSTIVE_KEY_SPACE_BLOCKED", "kind": "tiling_key_coverage", "priority": "hard", "status": "unresolved", "target_refs": [], "reason": "exhaustive_key_space_unavailable"})
        elif stats.get("unrealized_key_count", 0):
            blockers.append({"id": "L3_UNREALIZED_KEYS", "kind": "tiling_key_coverage", "priority": "hard", "status": "unresolved", "target_refs": [], "reason": "some reachable TilingKeys have no realization witness"})
    return blockers


def boundary_policy(level: str) -> dict[str, Any]:
    return {"enabled": level == "L2", "source": "KB declared boundary values only"}


def negative_case_policy(level: str) -> dict[str, Any]:
    return {"enabled": level == "L2", "expectation_schema": "case_expectation"}


def first_by_id(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    ordered = sorted(items, key=lambda item: str(item.get("id") or item.get("family_id") or item.get("target_ref") or ""))
    return ordered[0] if ordered else None


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
    l3_items = [item for item in obligations if item.get("test_level") == "L3"]
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
            "l3_reachable_key_obligations": len(l3_items),
            "unrealized_key_obligations": len([item for item in l3_items if item.get("status") == "unresolved"]),
        },
    }


def contract_gaps(contract: dict[str, Any], coverage: dict[str, Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if not _as_dict(contract.get("coverage_obligations")):
        gaps.append({"field": "coverage_obligations", "reason": "empty coverage obligation buckets"})
    if "family_obligations" not in coverage:
        gaps.append({"field": "tiling/coverage_model.yaml.family_obligations", "reason": "family obligations not exported"})
    if "key_relation_obligations" not in coverage:
        gaps.append({"field": "tiling/coverage_model.yaml.key_relation_obligations", "reason": "key relation obligations not exported"})
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
        f"- TilingKey 原子值义务数: {matrix['by_kind'].get('tiling_key_field_value', {}).get('total', 0)}",
        f"- L3 reachable / unrealized keys: {key_stats.get('reachable_key_count', 0)} / {key_stats.get('unrealized_key_count', 0)}",
        f"- Contract gaps: {len(unresolved['contract_gaps'])}",
        f"- Allow solve: {'yes' if allow_smt else 'no'}",
        f"- 是否允许进入 SMT 阶段: {'是' if allow_smt else '否'}",
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
    horizontal = [
        kind
        for kind in ("family", "tiling_key_field_value", "tiling_key_relation", "compile_template", "kernel_path", "kernel_branch")
        if matrix["by_kind"].get(kind, {}).get("total", 0)
    ]
    vertical = [
        kind
        for kind in ("optional_input_mode", "dtype_layout_class", "tilingdata_boundary", "core_split_boundary", "tail_boundary", "workspace_boundary", "pipeline_resource_mode", "numerical_mode")
        if matrix["by_kind"].get(kind, {}).get("total", 0)
    ]
    counts = matrix["priority_counts"]
    unreachable = [item for item in obligations if item["reachability"] in UNREACHABLE]
    allow_smt = not unresolved["blocking_hard_obligations"] and not unresolved["contract_gaps"]
    lines = [
        "# TestAgent 覆盖计划审核",
        "",
        f"- 算子: {snapshot.get('op_name')}",
        f"- Snapshot Hash: `{snapshot.get('snapshot_hash')}`",
        f"- 横向覆盖对象: {', '.join(horizontal) if horizontal else '无'}",
        f"- 纵向覆盖对象: {', '.join(vertical) if vertical else '无'}",
        f"- Hard / High / Normal 数量: {counts.get('hard', 0)} / {counts.get('high', 0)} / {counts.get('normal', 0)}",
        f"- TilingKey 字段数: {len({ref for item in obligations if item['kind'] == 'tiling_key_field_value' for ref in item.get('target_refs') or []})}",
        f"- TilingKey 原子值义务数: {matrix['by_kind'].get('tiling_key_field_value', {}).get('total', 0)}",
        f"- Branch true/false 义务数: {matrix['by_kind'].get('kernel_branch', {}).get('total', 0)}",
        f"- Optional present/absent 义务数: {matrix['by_kind'].get('optional_input_mode', {}).get('total', 0)}",
        f"- Relation Combination 义务数: {len([item for item in obligations if item['kind'] == 'tiling_key_relation' and item.get('coverage_bucket') in {'compatible_set', 'must_cover'}])}",
        f"- 不可达对象: {len(unreachable)}",
        f"- 未解决问题: {len(unresolved['blocking_hard_obligations']) + len(unresolved['unresolved_obligations'])}",
        f"- Contract 信息缺口: {len(unresolved['contract_gaps'])}",
        f"- 是否允许进入 SMT 阶段: {'是' if allow_smt else '否'}",
        "",
        "## 不可达对象",
    ]
    if unreachable:
        lines.extend(f"- `{item['id']}` {item['kind']} {', '.join(item['target_refs'])}: {item['unresolved_reason'] or '需要保留证明义务'}" for item in unreachable)
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## 未解决问题")
    if unresolved["blocking_hard_obligations"]:
        lines.extend(f"- `{item['id']}` {item['status']}: {item['reason'] or 'Hard obligation needs confirmation'}" for item in unresolved["blocking_hard_obligations"])
    else:
        lines.append("- 无阻塞级 Hard 问题")
    lines.append("")
    lines.append("## 人工审核")
    lines.append("- `/tg-plan` 到此停止。OpenCode 中请使用 question 选择框：approve / revise / supplement / stop。")
    lines.append("- 人工补充只写入 `plan/human_supplement.yaml`，不得修改 Understand Canonical KB。")
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
    for key in ("must_cover", "combinations", "fields", "values", "boundary_values", "relation_type", "linked_relations", "source", "target", "unreachable_values", "unreachable_combinations"):
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


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
