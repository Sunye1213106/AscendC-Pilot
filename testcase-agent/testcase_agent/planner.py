from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
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


class TgPlanError(RuntimeError):
    pass


def tg_plan(project_root: Path, op_name: str) -> dict[str, Any]:
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
    plan = build_plan(snapshot)
    write_plan_outputs(out_root, plan, snapshot)
    return plan


def build_plan(snapshot: dict[str, Any]) -> dict[str, Any]:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    contract = _as_dict(files.get("contracts/testcase.yaml"))
    coverage = _as_dict(files.get("tiling/coverage_model.yaml"))
    branches = _as_dict(files.get("kernel/branches.yaml"))
    impact = _as_dict(files.get("cross_layer/impact_graph.yaml"))

    obligations: list[dict[str, Any]] = []
    add_family_obligations(obligations, coverage, contract)
    add_key_field_obligations(obligations, coverage, contract)
    add_key_relation_obligations(obligations, coverage, contract)
    add_contract_bucket_obligations(obligations, contract)
    add_kernel_branch_obligations(obligations, branches)
    add_interface_dimension_obligations(obligations, contract)
    add_impact_resource_obligations(obligations, impact)

    obligations = deterministic_obligations(obligations)
    blockers = hard_blockers(obligations, contract)
    matrix = build_matrix(obligations)
    unresolved = {
        "status": "blocked" if blockers else "ready_for_manual_review",
        "blocking_hard_obligations": blockers,
        "unresolved_obligations": [item for item in obligations if item["status"] in {"unresolved", "conflicting"}],
        "contract_gaps": contract_gaps(contract, coverage),
    }
    review = build_review(snapshot, obligations, matrix, unresolved)
    plan_hash = semantic_plan_hash(snapshot.get("snapshot_hash"), obligations, matrix, unresolved)
    return {
        "version": 1,
        "created_at": _now(),
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "obligations": obligations,
        "matrix": matrix,
        "unresolved": unresolved,
        "review": review,
        "plan_hash": plan_hash,
    }


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
        if item.get("relation_type") or item.get("linked_relations"):
            continue
        if is_derived_or_bound(item):
            continue
        if item.get("field") or item.get("field_name") or item.get("values"):
            out.extend(expand_key_field_obligations(item, priority=item.get("priority") or "high"))


def add_key_relation_obligations(out: list[dict[str, Any]], coverage: dict[str, Any], contract: dict[str, Any]) -> None:
    for item in _iter_items(coverage.get("key_relation_obligations")):
        out.extend(expand_relation_obligations(item, priority=item.get("priority") or "high"))

    for item in _iter_items(_as_dict(contract.get("coverage_obligations")).get("tiling_keys")):
        kind = str(item.get("kind") or item.get("coverage_kind") or "").lower()
        if kind == "tiling_key_relation" or item.get("relation_type") or item.get("linked_relations") or item.get("must_cover"):
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


def add_kernel_branch_obligations(out: list[dict[str, Any]], branches: dict[str, Any]) -> None:
    for item in _iter_items(branches.get("branches")):
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
    relation_type = str(item.get("relation_type") or "").lower()
    combinations = item.get("combinations")
    constraints = _as_dict(item.get("constraints"))
    if combinations is None:
        combinations = item.get("must_cover", constraints.get("must_cover"))
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
        seen: set[str] = set()
        for combo in combinations:
            if not isinstance(combo, dict):
                return [
                    make_obligation(
                        "tiling_key_relation",
                        {**item, "status": "unresolved", "reason": "relation combination must be a mapping", "coverage_bucket": relation_type or "must_cover"},
                        priority=priority,
                    )
                ]
            signature = stable_hash(combo)
            if signature in seen:
                continue
            seen.add(signature)
            unreachable = str(combo.get("reachability") or combo.get("status") or "").lower() in UNREACHABLE
            combo_values = {key: value for key, value in combo.items() if key not in {"reachability", "status", "reason", "unreachable_reason"}}
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
    return {
        "by_kind": by_kind,
        "priority_counts": priority_counts,
        "total": len(obligations),
        "unreachable": [item["id"] for item in obligations if item["reachability"] in UNREACHABLE],
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


def build_review(snapshot: dict[str, Any], obligations: list[dict[str, Any]], matrix: dict[str, Any], unresolved: dict[str, Any]) -> str:
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
    write_yaml(out_root / "plan" / "coverage_obligations.yaml", {"version": 1, "snapshot_hash": snapshot.get("snapshot_hash"), "obligations": plan["obligations"], "plan_hash": plan["plan_hash"]})
    write_yaml(out_root / "plan" / "coverage_matrix.yaml", {"version": 1, "snapshot_hash": snapshot.get("snapshot_hash"), **plan["matrix"], "plan_hash": plan["plan_hash"]})
    write_yaml(out_root / "plan" / "unresolved.yaml", {"version": 1, "snapshot_hash": snapshot.get("snapshot_hash"), **plan["unresolved"], "plan_hash": plan["plan_hash"]})
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
    if isinstance(item.get("constraints"), dict) and "expr" in item["constraints"]:
        base = dict(item["constraints"])
        for key in ("must_cover", "combinations", "fields", "values", "boundary_values", "relation_type", "linked_relations"):
            if key in item:
                base[key] = item[key]
        return base
    keys = ("constraints", "must_cover", "combinations", "fields", "values", "boundary_values", "relation_type", "linked_relations")
    return {key: item[key] for key in keys if key in item}


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
