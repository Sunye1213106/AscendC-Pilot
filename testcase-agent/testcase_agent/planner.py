from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

from .extract import extract_generation_conditions
from .hashing import semantic_plan_hash, semantic_snapshot_hash, stable_hash
from .init import TgInitError, tg_init
from .io import ensure_output_dirs, output_root, read_json, read_yaml, write_yaml
from .llm_complete import apply_llm_completion, build_llm_prompt_bundle, load_llm_patches
from .topics import filter_obligations_for_topic, load_topic_manifest
from .contract import TgContractError, load_realization_for_plan, refresh_contract_plan_hash, tg_contract
from .reachability import abstract_branch_ids, is_value_reachable, mapped_branch_ids
from .atom_bind import is_out_of_scope_runtime_entity


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


def tg_plan(
    project_root: Path,
    op_name: str,
    *,
    level: str = "L1",
    focus: str = "",
    topic: str = "",
    reuse_snapshot: bool = False,
    csv_consumer_root: Path | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    out_root = output_root(project_root, op_name)
    ensure_output_dirs(out_root)
    snapshot_path = out_root / "snapshot" / "understand_contract.json"

    if reuse_snapshot and snapshot_path.exists():
        snapshot = read_json(snapshot_path)
        expected_hash = semantic_snapshot_hash(snapshot)
        if snapshot.get("snapshot_hash") != expected_hash:
            raise TgPlanError("SNAPSHOT_HASH_MISMATCH: snapshot_hash does not match snapshot contents")
    else:
        try:
            init_result = tg_init(project_root, op_name)
        except TgInitError as exc:
            raise TgPlanError(str(exc)) from exc
        snapshot = init_result["snapshot"]
        # Retag run metadata as tg-plan intake
        run_path = out_root / "run.yaml"
        if run_path.exists():
            run = read_yaml(run_path)
            run["command"] = "tg-plan"
            run["phase"] = "plan_with_intake"
            run["next_command"] = "tg-solve"
            write_yaml(run_path, run)

    # Realization contract must exist before planning so obligations are CSV-realizable.
    try:
        if csv_consumer_root is not None:
            tg_contract(project_root, op_name, csv_consumer_root=csv_consumer_root, reuse_snapshot=True)
        realization_map = load_realization_for_plan(out_root)
    except TgContractError as exc:
        raise TgPlanError(str(exc)) from exc

    extract_doc = extract_generation_conditions(snapshot, level=normalize_level(level), topic=topic)
    declared_vars = {
        str(item.get("id"))
        for item in _iter_items(_as_dict(snapshot.get("files", {}).get("contracts/testcase.yaml")).get("variables"))
        if item.get("id")
    }
    patches = load_llm_patches(out_root)
    extract_doc = apply_llm_completion(extract_doc, patches, declared_variables=declared_vars or None)
    write_yaml(out_root / "extract" / "generation_conditions.yaml", extract_doc)
    if extract_doc.get("needs_llm_completion"):
        write_yaml(out_root / "extract" / "llm_prompt_bundle.yaml", build_llm_prompt_bundle(extract_doc, snapshot))
        write_yaml(
            out_root / "extract" / "EXTRACT_GAP.yaml",
            {
                "version": 1,
                "gaps": [item for item in extract_doc.get("gaps") or [] if item.get("code") == "EXTRACT_GAP"],
                "hint": "Write LogicExpr patches to extract/llm_patches.yaml then re-run tg-plan",
            },
        )

    topic_manifest = None
    if normalize_level(level) == "L3":
        topic_manifest = load_topic_manifest(out_root, topic or focus, project_root=project_root)

    plan = build_plan(
        snapshot,
        level=level,
        focus=focus,
        topic=topic,
        topic_manifest=topic_manifest,
        extract_doc=extract_doc,
        realization_map=realization_map,
    )
    write_plan_outputs(out_root, plan, snapshot)
    refresh_contract_plan_hash(out_root, str(plan.get("plan_hash") or ""), str(snapshot.get("snapshot_hash") or ""))
    return plan


def build_plan(
    snapshot: dict[str, Any],
    *,
    level: str = "L1",
    focus: str = "",
    topic: str = "",
    topic_manifest: dict[str, Any] | None = None,
    extract_doc: dict[str, Any] | None = None,
    realization_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    level = normalize_level(level)
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    contract = _as_dict(files.get("contracts/testcase.yaml"))
    coverage = _as_dict(files.get("tiling/coverage_model.yaml"))
    branches = _as_dict(files.get("kernel/branches.yaml"))
    impact = _as_dict(files.get("cross_layer/impact_graph.yaml"))
    semantic_focus = build_semantic_focus(files, level, focus)
    if topic:
        semantic_focus["topic"] = topic
    if topic_manifest:
        semantic_focus["topic_manifest"] = {"topic_id": topic_manifest.get("topic_id"), "seed_entities": topic_manifest.get("seed_entities")}

    obligations: list[dict[str, Any]] = []
    if level == "L0":
        add_l0_obligations(obligations, files, coverage, contract, semantic_focus)
    elif level == "L2":
        add_l2_exhaustive_key_obligations(obligations, files, contract, semantic_focus)
    elif level == "L3":
        add_l3_topic_obligations(obligations, files, coverage, contract, branches, impact, semantic_focus, topic_manifest or {})
    else:
        add_l1_obligations(obligations, files, coverage, contract, branches, impact, semantic_focus)
    obligations = filter_obligations_by_focus(obligations, semantic_focus)
    if level == "L3" and topic_manifest:
        obligations = filter_obligations_for_topic(obligations, topic_manifest, files)
        if not obligations:
            blocker = make_obligation(
                "tiling_key_field_value",
                {"id": "L3_TOPIC_EMPTY", "status": "unresolved", "reason": f"no obligations matched topic {topic_manifest.get('topic_id')}"},
                target_refs=[],
                priority="hard",
            )
            decorate_obligation(blocker, "L3", {"artifact": "topics", "entity_ref": str(topic_manifest.get("topic_id") or ""), "reason": "topic_empty"}, "topic produced zero obligations", semantic_focus)
            obligations.append(blocker)
    if realization_map:
        obligations = apply_realization_filters(obligations, realization_map)
    obligations = deterministic_obligations(obligations)
    validate_unique_obligation_ids(obligations)
    if realization_map:
        semantic_focus["csv_realization"] = realization_filter_summary(obligations, realization_map)
        semantic_focus["csv_unreachability_report"] = build_csv_unreachability_report(obligations, realization_map)
    level_blockers = level_specific_blockers(level, obligations, semantic_focus)
    blockers = hard_blockers(obligations, contract) + level_blockers
    matrix = build_matrix(obligations)
    planning_context = {
        "test_level": level,
        "topic": topic or "",
        "semantic_focus": semantic_focus,
        "selected_semantic_subgraph": semantic_focus.get("selected_semantic_subgraph", {}),
        "exhaustive_key_scope": semantic_focus.get("exhaustive_within_scope") is True,
        "boundary_policy": boundary_policy(level),
        "negative_case_policy": negative_case_policy(level),
        "extract_hash": _as_dict(extract_doc).get("extract_hash"),
        "needs_llm_completion": bool(_as_dict(extract_doc).get("needs_llm_completion")),
        "pruning_result": _as_dict(semantic_focus.get("tiling_key_coverage")).get("pruned_count"),
        "merging_result": _as_dict(semantic_focus.get("tiling_key_coverage")).get("semantic_merge_group_count"),
        "realization_result": {
            key: _as_dict(semantic_focus.get("tiling_key_coverage")).get(key)
            for key in ("realized_key_count", "unrealized_key_count", "ambiguous_key_count")
        },
        "csv_realization": semantic_focus.get("csv_realization"),
    }
    gaps = contract_gaps(level, contract, coverage, files, topic=topic)
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
        "topic": topic or "",
        "semantic_focus": semantic_focus,
        "planning_context": planning_context,
        "realization_map_ref": {
            "mapped_branch_count": len(mapped_branch_ids(realization_map)) if realization_map else 0,
            "abstract_branch_count": len(abstract_branch_ids(realization_map)) if realization_map else 0,
        },
        "extract": {
            "extract_hash": _as_dict(extract_doc).get("extract_hash"),
            "condition_count": len(_as_dict(extract_doc).get("conditions") or []),
            "gap_count": len(_as_dict(extract_doc).get("gaps") or []),
            "needs_llm_completion": bool(_as_dict(extract_doc).get("needs_llm_completion")),
        },
        "obligations": obligations,
        "matrix": matrix,
        "unresolved": unresolved,
        "review": review,
        "plan_hash": plan_hash,
        "_realization_map": realization_map,
    }


def add_l3_topic_obligations(
    out: list[dict[str, Any]],
    files: dict[str, Any],
    coverage: dict[str, Any],
    contract: dict[str, Any],
    branches: dict[str, Any],
    impact: dict[str, Any],
    semantic_focus: dict[str, Any],
    topic_manifest: dict[str, Any],
) -> None:
    """L3: seed from L1-like sources then topic-filter (caller filters again for safety)."""
    before = len(out)
    add_key_field_obligations(out, coverage, contract)
    add_key_relation_obligations(out, coverage, contract)
    add_kernel_branch_obligations(out, branches)
    add_runtime_variable_obligations(out, files, semantic_focus)
    add_interface_dimension_obligations(out, contract)
    # Also expand seed key domains from key cards / variables
    seeds = [str(item) for item in topic_manifest.get("seed_entities") or []]
    key_fields = _as_dict(topic_manifest.get("expand_policy")).get("key_fields") or []
    for seed in seeds:
        field = seed.removeprefix("KEY_").removeprefix("VAR_KEY_")
        card = _as_dict(files.get(f"tiling/key_cards/{seed}.yaml")) or _as_dict(files.get(f"tiling/key_cards/KEY_{field}.yaml"))
        domain = card.get("domain") or []
        if not domain:
            for var in _iter_items(_as_dict(files.get("tiling/variables.yaml")).get("variables")):
                if str(var.get("id") or "").upper() in {seed.upper(), f"VAR_KEY_{field}".upper(), f"VAR_{seed}".upper()}:
                    domain = var.get("domain") or var.get("values") or []
                    if isinstance(domain, dict):
                        domain = domain.get("values") or []
                    break
        for value in _as_list(domain):
            payload = {
                "field": field,
                "target_value": value,
                "constraints": _expr_eq(_var_id(f"KEY_{field}"), value),
                "coverage_bucket": "topic_seed_value",
            }
            obligation = make_obligation("tiling_key_field_value", payload, target_refs=[seed if seed.startswith("KEY_") else f"KEY_{field}"], priority="high")
            decorate_obligation(obligation, "L3", {"artifact": "topics", "entity_ref": seed, "reason": "topic_seed_domain"}, "L3 topic seed value", semantic_focus)
            out.append(obligation)
    for field in key_fields:
        specs = _as_dict(coverage.get("key_field_obligations"))
        matched = specs.get(field) or specs.get(str(field).upper()) or specs.get(f"KEY_{field}")
        if isinstance(matched, dict):
            out.extend(expand_key_field_obligations({"field": field, **matched}, priority="high"))
    for item in out[before:]:
        if not item.get("test_level"):
            decorate_obligation(item, "L3", default_origin_for(item, files), "L3 topic-related coverage", semantic_focus)


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
    add_contract_kernel_branch_obligations(out, contract)
    add_kernel_branch_obligations(out, branches)
    # Runtime-variable domain coverage (CSV-reachable only; loop/platform vars dropped at source).
    add_runtime_variable_obligations(out, files, semantic_focus)
    if len(out) == before:
        add_key_relation_obligations(out, coverage, contract)
    for item in out[before:]:
        if item.get("test_level"):
            continue
        reason = "runtime branch coverage" if item.get("kind") == "kernel_branch" else "runtime variable coverage"
        decorate_obligation(item, "L1", default_origin_for(item, files), reason, semantic_focus)


def add_l0_obligations(out: list[dict[str, Any]], files: dict[str, Any], coverage: dict[str, Any], contract: dict[str, Any], semantic_focus: dict[str, Any]) -> None:
    """L0: functional-attribute smoke — feature/optional-input values only.

    Not a single-case smoke. Covers:
    - optional inputs present+absent
    - all independent tiling-key functional attribute values
      (for example IsRope / IsAttenMask / mask-type fields when declared)
    Does NOT expand full runtime branch cartesian product (that is L1).
    """
    def _l0_reason(design: str) -> dict[str, Any]:
        return {"design": design, "scope": "feature_optional_value_coverage"}

    # 1) Optional inputs present + absent.
    for item in _iter_items(_as_dict(contract.get("interface")).get("optional_inputs")):
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
            obligation = make_obligation("optional_input_mode", payload, target_refs=[_optional_ref(name)], priority=item.get("priority") or "normal")
            decorate_obligation(
                obligation,
                "L0",
                {"artifact": "contracts/testcase.yaml", "entity_ref": _optional_ref(name), "reason": "l0_optional_input"},
                _l0_reason(f"l0_optional_input_{state}"),
                semantic_focus,
            )
            out.append(obligation)

    # 2) All independent functional tiling-key attribute values.
    fields = _as_dict(coverage.get("key_field_obligations"))
    for field_name, item in sorted(fields.items()):
        item = item if isinstance(item, dict) else {"values": item}
        if is_derived_or_bound(item):
            continue
        payload = {"field": field_name, **item}
        for obligation in expand_key_field_obligations(payload, priority=item.get("priority") or "high"):
            decorate_obligation(
                obligation,
                "L0",
                {"artifact": "tiling/coverage_model.yaml", "entity_ref": str(item.get("id") or field_name), "reason": "l0_functional_key_attribute"},
                _l0_reason(f"l0_functional_key_attribute:{field_name}"),
                semantic_focus,
            )
            out.append(obligation)


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


def add_contract_kernel_branch_obligations(out: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    buckets = _as_dict(contract.get("coverage_obligations"))
    for item in _iter_items(buckets.get("kernel_branches")):
        if is_out_of_scope_runtime_entity(
            name=str(item.get("id") or item.get("name") or ""),
            condition=str(item.get("condition") or ""),
            determinant_source=str(item.get("determinant_source") or ""),
        ):
            continue
        out.extend(expand_kernel_branch_obligations(item, priority=item.get("priority") or default_priority("kernel_branch")))
    for item in _iter_items(contract.get("kernel_branch_obligations")):
        if is_out_of_scope_runtime_entity(
            name=str(item.get("id") or item.get("name") or ""),
            condition=str(item.get("condition") or ""),
            determinant_source=str(item.get("determinant_source") or ""),
        ):
            continue
        out.extend(expand_kernel_branch_obligations(item, priority=item.get("priority") or "high"))


def add_kernel_branch_obligations(out: list[dict[str, Any]], branches: dict[str, Any]) -> None:
    for item in _iter_items(branches.get("branches")):
        if is_derived_or_bound(item) or item.get("compile_time_fixed") is True or item.get("runtime") is False:
            continue
        # Drop loop-local / platform branches at generation time (never enter L1 set).
        if is_out_of_scope_runtime_entity(
            name=str(item.get("id") or item.get("name") or ""),
            condition=str(item.get("condition") or ""),
            determinant_source=str(item.get("determinant_source") or ""),
        ):
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
            # Never generate CSV coverage for loop-local / platform runtime entities.
            if is_out_of_scope_runtime_entity(
                name=var_id,
                condition=str(item.get("name") or ""),
                determinant_source=str(item.get("binding_time") or ""),
            ):
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


# Abstract reasons that must never become CSV free vars / L1 pending cases.
OUT_OF_SCOPE_CSV_REASONS = {
    "LOOP_LOCAL": "核内循环/运行态变量（如 taskId、isLastLoop），禁止做成 CSV 自由列假覆盖",
    "PLATFORM_MACRO": "平台/头文件守卫宏，无法由 CSV 控制",
}

# LLM+/tg-csv-contract + 源码能否补齐绑定（相对 CSV 全覆盖目标）
LLM_RESOLVABILITY = {
    "UNBOUND_ATOM": {
        "llm_plus_source": "likely",
        "note": "可查源码别名/KEY 定义，补 atom_bindings；禁止发明无证据 CSV 列",
    },
    "UNBOUND_CMP": {
        "llm_plus_source": "likely",
        "note": "可从 Host/tiling 赋值链证明 lhs→CSV/KEY；证不出则保持 abstract",
    },
    "UNBOUND_DTYPE": {
        "llm_plus_source": "likely",
        "note": "可把 ORIG_DTYPE/IsSameType 等绑到 Dtype/INPUTDTYPE",
    },
    "UNBOUND_CALL": {
        "llm_plus_source": "likely",
        "note": "可剥壳或映射 IS_DETER_* 等到已有 KEY/KVAR derived",
    },
    "SUBSTITUTE_FAIL": {
        "llm_plus_source": "likely",
        "note": "解析/绑定管线缺陷，修 binder 或补丁后可进 mapped",
    },
    "KEY_DERIVATION_MISSING": {
        "llm_plus_source": "likely",
        "note": "分支已绑到 VAR_KEY_*，但 binding_lexicon.yaml 缺 key_derivations；补 CSV→KEY 表达式后可 mapped",
    },
    "PARSE_FAIL": {
        "llm_plus_source": "partial",
        "note": "KB 截断需回源码补全条件；复杂 C++（模板/算术）只能部分支持，不能靠 LLM 硬编解析器",
    },
    "UNBOUND_TEMPLATE": {
        "llm_plus_source": "partial",
        "note": "若模板参数由 KEY/CSV 决定可补；纯编译期常量则不可 CSV 覆盖",
    },
    "UNBOUND_KVAR": {
        "llm_plus_source": "partial",
        "note": "有 Host/set_by 证据可绑 derived；仅核内赋值则不可解",
    },
    "NO_HOST_PRODUCER": {
        "llm_plus_source": "unlikely",
        "note": "KB 已诊断缺 Host producer；除非改算子 Host，否则 CSV 写不进",
    },
    "BRANCH_SIDE_NOT_IN_IMAGE": {
        "llm_plus_source": "partial",
        "note": "可扩大 CSV domain/修正 KEY derived；若数学上不可达则保持过滤",
    },
    "LOOP_LOCAL": {
        "llm_plus_source": "impossible",
        "note": "核内循环态，禁止假覆盖；生成时直接去除",
    },
    "PLATFORM_MACRO": {
        "llm_plus_source": "impossible",
        "note": "平台/头文件守卫，禁止假覆盖；生成时直接去除",
    },
}

ABSTRACT_REASON_HINTS = {
    "PARSE_FAIL": "条件字符串无法解析（KB 截断或不支持的 C++ 语法）",
    "NO_HOST_PRODUCER": "TilingData 字段无 Host producer，CSV 无法写入",
    "UNBOUND_KVAR": "KernelVariable 无法溯源到 CSV/KEY/tiling",
    "UNBOUND_TEMPLATE": "模板常量/枚举（如 SPLIT_AXIS、HEAD_DIM_ALIGN）无 CSV 根",
    "UNBOUND_CMP": "比较原子左侧无法绑定到 CSV/KEY",
    "UNBOUND_ATOM": "布尔原子无法绑定到 CSV/KEY",
    "UNBOUND_DTYPE": "dtype 相关原子缺少可证映射",
    "UNBOUND_CALL": "函数调用原子无法绑定",
    "SUBSTITUTE_FAIL": "原子均已标记但规范表达式替换失败",
    "KEY_DERIVATION_MISSING": "缺少 binding_lexicon.key_derivations，禁止用 constant-0 KEY stub 假覆盖",
    "PLATFORM_MACRO": OUT_OF_SCOPE_CSV_REASONS["PLATFORM_MACRO"],
    "LOOP_LOCAL": OUT_OF_SCOPE_CSV_REASONS["LOOP_LOCAL"],
}


def apply_realization_filters(obligations: list[dict[str, Any]], realization_map: dict[str, Any]) -> list[dict[str, Any]]:
    """Mark or drop obligations that cannot be realized via CSV consumer."""
    abstract = abstract_branch_ids(realization_map)
    mapped = mapped_branch_ids(realization_map)
    abstract_by_ref = {
        str(item.get("branch_ref") or ""): item
        for item in realization_map.get("abstract_branches") or []
        if isinstance(item, dict) and item.get("branch_ref")
    }
    branch_var_by_ref = {
        str(item.get("branch_ref") or ""): str(item.get("var") or "")
        for item in realization_map.get("branch_mappings") or []
        if isinstance(item, dict) and item.get("branch_ref")
    }
    out: list[dict[str, Any]] = []
    dropped_out_of_scope: list[dict[str, Any]] = []
    for item in obligations:
        obligation = dict(item)
        kind = str(obligation.get("kind") or "")
        if kind == "tiling_key_field_value":
            var_id = _key_var_from_obligation(obligation)
            target = obligation.get("target_value")
            reachable = is_value_reachable(realization_map, var_id, target) if var_id else None
            if reachable is False:
                obligation["reachability"] = "unreachable"
                obligation["status"] = "proof_required"
                obligation["csv_unreachability_code"] = "KEY_VALUE_NOT_IN_IMAGE"
                obligation["unresolved_reason"] = (
                    f"NOT_CSV_REALIZABLE[KEY_VALUE_NOT_IN_IMAGE]: {var_id}={target} not in derived image over CSV domains"
                )
                obligation["reason"] = obligation["unresolved_reason"]
        elif kind in {"kernel_branch", "runtime_variable_state"}:
            refs = [str(ref) for ref in obligation.get("target_refs") or []]
            branch_ref = refs[0] if refs else ""
            # Drop loop/platform runtime vars even if they slipped into the list.
            if kind == "runtime_variable_state":
                scope = is_out_of_scope_runtime_entity(name=branch_ref, condition=str(obligation.get("name") or ""))
                if scope:
                    dropped_out_of_scope.append(
                        {
                            "id": obligation.get("id"),
                            "target_ref": branch_ref,
                            "code": scope,
                            "reason": OUT_OF_SCOPE_CSV_REASONS.get(scope, scope),
                        }
                    )
                    continue
            if kind == "kernel_branch" and branch_ref and branch_ref in abstract:
                abs_item = abstract_by_ref.get(branch_ref) or {}
                code = str(abs_item.get("reason") or "ABSTRACT_UNMAPPED")
                hint = ABSTRACT_REASON_HINTS.get(code, "分支无法经 CSV/KEY 追溯，不进入 L1 pending")
                if code in OUT_OF_SCOPE_CSV_REASONS:
                    dropped_out_of_scope.append(
                        {
                            "id": obligation.get("id"),
                            "branch_ref": branch_ref,
                            "condition": abs_item.get("condition") or obligation.get("condition"),
                            "code": code,
                            "reason": hint,
                        }
                    )
                    continue
                obligation["csv_unreachability_code"] = code
                obligation["abstract_reasons"] = abs_item.get("reasons") or [code]
                obligation["condition"] = abs_item.get("condition") or obligation.get("condition")
                obligation["reachability"] = "unreachable"
                obligation["status"] = "proof_required"
                obligation["unresolved_reason"] = f"NOT_CSV_REALIZABLE[{code}]: {hint} (branch {branch_ref})"
                obligation["reason"] = obligation["unresolved_reason"]
            elif kind == "kernel_branch" and branch_ref and mapped and branch_ref not in mapped:
                obligation["reachability"] = "unreachable"
                obligation["status"] = "proof_required"
                obligation["csv_unreachability_code"] = "NO_CSV_MAPPING"
                obligation["unresolved_reason"] = f"NOT_CSV_REALIZABLE[NO_CSV_MAPPING]: branch {branch_ref} has no CSV mapping"
                obligation["reason"] = obligation["unresolved_reason"]
            elif kind == "kernel_branch":
                var_id = branch_var_by_ref.get(branch_ref) or ""
                target = obligation.get("target_value")
                if var_id:
                    side_ok = is_value_reachable(realization_map, var_id, target)
                    if side_ok is False:
                        obligation["reachability"] = "unreachable"
                        obligation["status"] = "proof_required"
                        obligation["csv_unreachability_code"] = "BRANCH_SIDE_NOT_IN_IMAGE"
                        obligation["unresolved_reason"] = (
                            f"NOT_CSV_REALIZABLE[BRANCH_SIDE_NOT_IN_IMAGE]: branch {branch_ref} side {target} "
                            f"not reachable by any CSV assignment"
                        )
                        obligation["reason"] = obligation["unresolved_reason"]
        out.append(obligation)
    # Stash drop list on first obligation's carrier via closure — attach to map summary later.
    apply_realization_filters.last_dropped = dropped_out_of_scope  # type: ignore[attr-defined]
    return out


def realization_filter_summary(obligations: list[dict[str, Any]], realization_map: dict[str, Any]) -> dict[str, Any]:
    pending = [item for item in obligations if item.get("status") == "pending"]
    unreachable = [item for item in obligations if str(item.get("reachability") or "") in UNREACHABLE]
    not_csv = [
        item
        for item in obligations
        if "NOT_CSV_REALIZABLE" in str(item.get("unresolved_reason") or item.get("reason") or "")
    ]
    by_code: dict[str, int] = {}
    seen_ids: set[str] = set()
    for item in obligations:
        oid = str(item.get("id") or "")
        code = str(item.get("csv_unreachability_code") or "")
        if not code or oid in seen_ids:
            continue
        seen_ids.add(oid)
        by_code[code] = by_code.get(code, 0) + 1
    dropped = list(getattr(apply_realization_filters, "last_dropped", []) or [])
    dropped_by_code: dict[str, int] = {}
    for item in dropped:
        code = str(item.get("code") or "UNKNOWN")
        dropped_by_code[code] = dropped_by_code.get(code, 0) + 1
    alignment = realization_map.get("alignment_report") if isinstance(realization_map.get("alignment_report"), dict) else {}
    out_of_scope_in_map = sum(
        1
        for item in realization_map.get("abstract_branches") or []
        if isinstance(item, dict) and str(item.get("reason") or "") in OUT_OF_SCOPE_CSV_REASONS
    )
    return {
        "mapped_branch_count": len(mapped_branch_ids(realization_map)),
        "abstract_branch_count": len(abstract_branch_ids(realization_map)),
        "pending_count": len(pending),
        "dropped_out_of_scope_count": len(dropped),
        "dropped_out_of_scope_by_code": dropped_by_code,
        "out_of_scope_abstract_branches_in_map": out_of_scope_in_map,
        "unreachable_count": len(unreachable),
        "not_csv_realizable_count": len(not_csv),
        "by_unreachability_code": dict(sorted(by_code.items(), key=lambda kv: (-kv[1], kv[0]))),
        "code_hints": {code: ABSTRACT_REASON_HINTS.get(code, "") for code in by_code},
        "llm_resolvability": LLM_RESOLVABILITY,
        "alignment_totals": alignment.get("totals") or {},
        "alignment_by_source": alignment.get("by_determinant_source") or {},
    }


def build_csv_unreachability_report(obligations: list[dict[str, Any]], realization_map: dict[str, Any]) -> dict[str, Any]:
    """Human-auditable breakdown of why L1 obligations are not CSV-pending."""
    summary = realization_filter_summary(obligations, realization_map)
    examples: dict[str, list[dict[str, Any]]] = {}
    for item in obligations:
        code = str(item.get("csv_unreachability_code") or "")
        if not code:
            continue
        bucket = examples.setdefault(code, [])
        if len(bucket) >= 5:
            continue
        bucket.append(
            {
                "id": item.get("id"),
                "branch_ref": (item.get("target_refs") or [None])[0],
                "condition": item.get("condition"),
                "target_value": item.get("target_value"),
                "status": item.get("status"),
                "reason": item.get("unresolved_reason") or item.get("reason"),
                "llm_plus_source": (LLM_RESOLVABILITY.get(code) or {}).get("llm_plus_source"),
            }
        )
    dropped = list(getattr(apply_realization_filters, "last_dropped", []) or [])
    dropped_catalog = []
    for abs_item in realization_map.get("abstract_branches") or []:
        if not isinstance(abs_item, dict):
            continue
        code = str(abs_item.get("reason") or "")
        if code not in OUT_OF_SCOPE_CSV_REASONS:
            continue
        dropped_catalog.append(
            {
                "branch_ref": abs_item.get("branch_ref"),
                "condition": abs_item.get("condition"),
                "code": code,
                "reason": OUT_OF_SCOPE_CSV_REASONS[code],
                "llm_plus_source": "impossible",
            }
        )
    return {
        "version": 1,
        "policy": {
            "no_fake_csv_loop_locals": True,
            "drop_out_of_scope_at_generation": True,
            "out_of_scope_codes": sorted(OUT_OF_SCOPE_CSV_REASONS),
            "notes": (
                "LOOP_LOCAL / PLATFORM_MACRO 在生成运行期全覆盖时直接去除，不进入义务表；"
                "其余 abstract 原因进入 proof_required，可审计但不进 pending。"
            ),
        },
        "llm_resolvability": LLM_RESOLVABILITY,
        "summary": summary,
        "examples_by_code": examples,
        "dropped_out_of_scope_examples": (dropped or dropped_catalog)[:20],
        "dropped_out_of_scope_catalog_count": len(dropped_catalog),
    }


def _key_var_from_obligation(obligation: dict[str, Any]) -> str:
    refs = [str(ref) for ref in obligation.get("target_refs") or [] if str(ref)]
    field = str(obligation.get("field") or "")
    if refs:
        ref = refs[0]
        if ref.startswith("VAR_"):
            return ref
        if ref.startswith("KEY_"):
            return f"VAR_{ref}"
        return f"VAR_KEY_{ref.upper()}"
    if field:
        text = field.upper() if not field.upper().startswith("KEY_") else field.upper()
        if text.startswith("KEY_"):
            return f"VAR_{text}"
        return f"VAR_KEY_{text}"
    return ""


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
    for key in ("target_value", "target_state", "target_expr", "parent_obligation_id", "coverage_bucket", "optional_state", "field"):
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
            "skipped": len([item for item in items if item["status"] == "skipped"]),
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
        "test_points": build_test_points(obligations),
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


def contract_gaps(level: str, contract: dict[str, Any], coverage: dict[str, Any], files: dict[str, Any], *, topic: str = "") -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    buckets = _as_dict(contract.get("coverage_obligations"))
    interface = _as_dict(contract.get("interface"))
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    if level == "L0":
        pass
    elif level == "L1":
        if "branches" not in _as_dict(files.get("kernel/branches.yaml")) and not buckets.get("kernel_branches") and not contract.get("kernel_branch_obligations"):
            gaps.append({"field": "kernel/branches.yaml.branches", "reason": "L1 needs runtime branches"})
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
    elif level == "L3":
        if not str(topic or "").strip():
            gaps.append({"field": "topic", "reason": "L3 requires --topic"})
    return gaps


LEVEL_DESIGN = {
    "L0": (
        "功能属性冒烟（Functional-attribute smoke）",
        [
            "目标：覆盖功能开关和可选输入的声明取值，例如 Rope 是否开启、Mask 是否存在、Mask 类型等。",
            "覆盖范围：可选输入 present/absent、全部独立 TilingKey 功能字段离散取值。",
            "不覆盖：family/kernel_path 基线、运行时分支、边界/拒绝用例、穷尽 TilingKey 组合（分别属于其他层级）。",
            "设计意图：用较少义务把功能开关面铺满，作为后续 L1/L2 扩展前的属性取值基线。",
        ],
    ),
    "L1": (
        "运行时功能与分支覆盖（Runtime functional / branch coverage）",
        [
            "目标：覆盖可达 kernel 运行时分支的各可达侧。",
            "覆盖范围：kernel_branch true/false 或声明变体。",
            "不覆盖：L0 功能字段取值、L2 穷尽 TilingKey 空间、主题定制套件（L3）。",
            "设计意图：在 L0 功能取值基线之上，只展开运行时控制流覆盖面。",
        ],
    ),
    "L2": (
        "穷尽可达 TilingKey（Exhaustive reachable TilingKey）",
        [
            "目标：对 exhaustive_key_space 中可达且可反向实现的 TilingKey 做穷尽覆盖。",
            "不覆盖：不可达/未实现 key、主题定制（L3）。",
        ],
    ),
    "L3": (
        "主题定制套件（Topic-scoped suite）",
        [
            "目标：仅生成与 --topic 相关的义务（如 determinism），不扩展无关分支。",
        ],
    ),
}

KIND_LABELS_CN = {
    "family": "入口场景基线",
    "tiling_key_field_value": "TilingKey 功能字段取值",
    "tiling_key_field": "TilingKey 字段",
    "tiling_key_relation": "TilingKey 关系约束",
    "compile_template": "编译模板",
    "kernel_path": "执行路径基线",
    "kernel_branch": "运行时分支/功能判断",
    "runtime_variable_state": "运行时变量状态",
    "optional_input_mode": "可选输入 present/absent",
    "dtype_layout_class": "dtype/layout 类",
    "tilingdata_boundary": "TilingData 边界",
    "core_split_boundary": "核切分边界",
    "tail_boundary": "尾块边界",
    "workspace_boundary": "Workspace 边界",
    "pipeline_resource_mode": "流水/资源模式",
    "numerical_mode": "数值模式",
}


def build_test_points(obligations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Human-readable coverage buckets: what is covered and how many obligations."""
    points: list[dict[str, Any]] = []
    by_kind = Counter(str(item.get("kind") or "") for item in obligations)
    for kind in SUPPORTED_KINDS:
        total = by_kind.get(kind, 0)
        if not total:
            continue
        items = [item for item in obligations if item.get("kind") == kind]
        sample_refs = sorted({ref for item in items for ref in (item.get("target_refs") or []) if ref})[:8]
        field_names: list[str] = []
        if kind == "tiling_key_field_value":
            field_names = sorted({_obligation_field_name(item) for item in items if _obligation_field_name(item) != "unknown"})
        points.append(
            {
                "kind": kind,
                "label": KIND_LABELS_CN.get(kind, kind),
                "count": total,
                "sample_refs": sample_refs,
                "fields": field_names,
                "priority_breakdown": dict(Counter(str(item.get("priority") or "normal") for item in items)),
            }
        )
    # Attribute-level rollup for L0/L1 key fields
    key_items = [item for item in obligations if item.get("kind") == "tiling_key_field_value"]
    if key_items:
        by_field = Counter(_obligation_field_name(item) for item in key_items)
        points.append(
            {
                "kind": "tiling_key_field_value__by_field",
                "label": "TilingKey 字段分项（每字段取值条数）",
                "count": len(key_items),
                "by_field": dict(sorted(by_field.items())),
            }
        )
    return points


def _obligation_field_name(item: dict[str, Any]) -> str:
    if item.get("field"):
        return str(item["field"])
    reason = item.get("selection_reason")
    if isinstance(reason, dict):
        design = str(reason.get("design") or "")
        if "l0_functional_key_attribute:" in design:
            return design.split(":", 1)[1]
        if ":" in design and "key_attribute" in design:
            return design.rsplit(":", 1)[-1]
    origin = item.get("coverage_origin")
    if isinstance(origin, dict) and origin.get("entity_ref"):
        ref = str(origin["entity_ref"])
        for prefix in ("KEY_", "COV_KEY_"):
            if ref.startswith(prefix):
                return ref[len(prefix) :]
        return ref
    refs = item.get("target_refs") or []
    if refs:
        ref = str(refs[0])
        for prefix in ("KEY_", "COV_KEY_"):
            if ref.startswith(prefix):
                return ref[len(prefix) :]
        return ref
    return "unknown"


def build_review_design_lines(obligations: list[dict[str, Any]]) -> list[str]:
    """Write review text as test-design intent instead of raw schema buckets."""
    by_kind = Counter(str(item.get("kind") or "") for item in obligations)
    lines: list[str] = []
    baseline_count = by_kind.get("family", 0) + by_kind.get("kernel_path", 0)
    if baseline_count:
        lines.append(f"- 设计 **{baseline_count}** 个入口/执行路径基线用例点，用来确认主调度入口和可达执行路径有见证。")

    key_items = [item for item in obligations if item.get("kind") == "tiling_key_field_value"]
    if key_items:
        by_field: dict[str, list[Any]] = {}
        for item in key_items:
            by_field.setdefault(_obligation_field_name(item), []).append(item.get("target_value"))
        lines.append(
            f"- 设计 **{len(key_items)}** 个 TilingKey 字段取值用例点，覆盖 **{len(by_field)}** 个变量：{_format_field_values(by_field)}。"
        )

    runtime_items = [item for item in obligations if item.get("kind") == "runtime_variable_state"]
    if runtime_items:
        by_var: dict[str, list[Any]] = {}
        for item in runtime_items:
            ref = str((item.get("target_refs") or ["runtime_variable"])[0])
            by_var.setdefault(ref, []).append(item.get("target_value"))
        lines.append(
            f"- 设计 **{len(runtime_items)}** 个运行时变量状态用例点，覆盖 **{len(by_var)}** 个变量：{_format_field_values(by_var)}。"
        )

    branch_items = [item for item in obligations if item.get("kind") == "kernel_branch"]
    if branch_items:
        branch_refs = sorted({str((item.get("target_refs") or ["branch"])[0]) for item in branch_items})
        sample = "、".join(branch_refs[:6])
        suffix = "；数量较多，仅展示样例，不逐项展开" if len(branch_refs) > 6 else ""
        lines.append(
            f"- 设计 **{len(branch_items)}** 个运行时分支侧用例点，覆盖 **{len(branch_refs)}** 个功能判断的 true/false 或可达侧；样例：{sample or '<none>'}{suffix}。"
        )

    optional_items = [item for item in obligations if item.get("kind") == "optional_input_mode"]
    if optional_items:
        states = sorted({str(item.get("target_state") or item.get("target_value")) for item in optional_items})
        lines.append(f"- 设计 **{len(optional_items)}** 个可选输入用例点，覆盖输入状态：{', '.join(states)}。")

    dtype_items = [item for item in obligations if item.get("kind") == "dtype_layout_class"]
    if dtype_items:
        refs = sorted({str(ref) for item in dtype_items for ref in (item.get("target_refs") or [])})
        lines.append(f"- 设计 **{len(dtype_items)}** 个 dtype/layout 类用例点，覆盖：{_compact_list(refs)}。")

    boundary_items = [item for item in obligations if item.get("kind") in BOUNDARY_KIND_LEVELS or item.get("coverage_bucket") == "boundary_value"]
    if boundary_items:
        names = sorted({KIND_LABELS_CN.get(str(item.get("kind")), str(item.get("kind"))) for item in boundary_items})
        lines.append(f"- 设计 **{len(boundary_items)}** 个边界类用例点，覆盖：{_compact_list(names)}。")

    negative_items = [item for item in obligations if item.get("expected_behavior") == "reject"]
    if negative_items:
        lines.append(f"- 设计 **{len(negative_items)}** 个拒绝/异常期望用例点，用来覆盖非法输入或合同声明的 reject 场景。")

    if not lines:
        lines.append("- 当前计划没有可展示的覆盖义务，请检查 coverage contract 或 topic 裁剪条件。")
    return lines


def build_review_coverage_index(obligations: list[dict[str, Any]], *, level: str, files: dict[str, Any] | None = None) -> list[str]:
    """Add a human-readable index so review can trace counts back to obligations."""
    if level == "L1":
        return _build_l1_branch_coverage_index(obligations, files=files or {})
    if level == "L0":
        return _build_l0_value_coverage_index(obligations)
    if level == "L2":
        return _build_l2_key_coverage_index(obligations)
    return []


def _obligation_first_ref(item: dict[str, Any], fallback: str = "unknown") -> str:
    refs = item.get("target_refs") or []
    return str(refs[0]) if refs else fallback


def _obligation_target_state(item: dict[str, Any]) -> str:
    value = item.get("target_state")
    if value is None:
        value = item.get("target_value")
    return str(value) if value is not None else "unspecified"


def _branch_ref_group(ref: str) -> str:
    for prefix in ("KBR_CONSTEXPR", "KBR_RUNTIME", "KBR_DECLARED", "KBR"):
        if ref.startswith(prefix):
            return prefix
    parts = ref.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else ref


def _build_branch_catalog(files: dict[str, Any]) -> dict[str, dict[str, Any]]:
    branches = _as_dict(files.get("kernel/branches.yaml")).get("branches") or []
    catalog: dict[str, dict[str, Any]] = {}
    for item in _iter_items(branches):
        branch_id = str(item.get("id") or "")
        if branch_id:
            catalog[branch_id] = item
    return catalog


def _determinant_source_cn(source: Any) -> str:
    mapping = {
        "TilingDataField": "tilingData 字段",
        "TemplateArg": "模板参数",
        "CompileMacro": "编译宏",
        "RuntimeValue": "运行时变量",
        "Input": "输入属性",
    }
    text = str(source or "")
    return mapping.get(text, text or "未知来源")


def _branch_human_group(ref: str, info: dict[str, Any] | None = None) -> str:
    info = info or {}
    binding = str(info.get("binding_time") or "")
    source = str(info.get("determinant_source") or "")
    if binding == "runtime":
        return f"运行时分支（{_determinant_source_cn(source)}）"
    if binding == "compile_time":
        return f"编译期分支（{_determinant_source_cn(source)}）"
    if "RUNTIME" in ref:
        return "运行时分支"
    if "CONSTEXPR" in ref or "MACRO" in ref:
        return "编译期分支"
    return "声明分支/其他"


def _compact_review_text(value: Any, *, max_len: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "<未提取>"
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _branch_human_summary(ref: str, info: dict[str, Any] | None = None) -> str:
    info = info or {}
    condition = _compact_review_text(info.get("condition") or info.get("determinant_ref") or ref)
    determinant = _compact_review_text(info.get("determinant_ref"), max_len=72)
    source = _determinant_source_cn(info.get("determinant_source"))
    if determinant and determinant != "<未提取>" and determinant != condition:
        return f"判断条件：`{condition}`；决定因素：{source} `{determinant}`"
    return f"判断条件：`{condition}`；决定因素：{source}"


def _branch_location(info: dict[str, Any] | None = None) -> str:
    info = info or {}
    path = str(info.get("file_path") or "<unknown>")
    line = info.get("start_line")
    if line not in (None, ""):
        return f"`{path}:{line}`"
    return f"`{path}`"


def _build_l1_branch_coverage_index(obligations: list[dict[str, Any]], *, files: dict[str, Any]) -> list[str]:
    branch_items = [item for item in obligations if item.get("kind") == "kernel_branch"]
    if not branch_items:
        return []

    branch_catalog = _build_branch_catalog(files)
    by_ref: dict[str, list[dict[str, Any]]] = {}
    source_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    for item in branch_items:
        ref = _obligation_first_ref(item, "branch")
        branch_info = branch_catalog.get(ref, {})
        by_ref.setdefault(ref, []).append(item)
        group_counts[_branch_human_group(ref, branch_info)] += 1
        state_counts[_obligation_target_state(item)] += 1
        origin = item.get("coverage_origin")
        if isinstance(origin, dict):
            if origin.get("artifact"):
                source_counts[str(origin.get("artifact"))] += 1
            if origin.get("reason"):
                reason_counts[str(origin.get("reason"))] += 1

    true_false_refs = sum(
        1
        for items in by_ref.values()
        if {"true", "false"}.issubset({_obligation_target_state(item).lower() for item in items})
    )
    missing_pair_refs = len(by_ref) - true_false_refs
    formula = f"{len(branch_items)} = {len(by_ref)} 个 branch_ref"
    if missing_pair_refs == 0 and len(branch_items) == len(by_ref) * 2:
        formula += " × 2 个状态（true / false）"
    else:
        formula += f" 的状态侧累计；其中 {true_false_refs} 个具备 true/false 成对覆盖，{missing_pair_refs} 个不是完整二值对"

    lines = [
        "",
        "## 覆盖索引（数字从哪里来）",
        f"- L1 只统计 `kernel_branch` 覆盖义务，本次共有 **{len(branch_items)}** 条。",
        f"- 计数口径：**{formula}**。",
        f"- 分支来源：从 `kernel/branches.yaml` 中纳入 **{len(by_ref)}** 个可覆盖判断点；该文件当前共记录 **{len(branch_catalog)}** 个分支条目，未纳入的通常是宏保护、不可求解或未进入本级别范围的条目。",
        f"- 状态分布：{_format_counter_for_review(state_counts, max_items=8)}。",
        f"- 人工可读分组：{_format_counter_for_review(group_counts, max_items=8)}。",
    ]
    if source_counts:
        lines.append(f"- 来源文件/制品：{_format_counter_for_review(source_counts, max_items=8)}。")
    if reason_counts:
        lines.append(f"- 生成原因：{_format_counter_for_review(reason_counts, max_items=8)}。")

    lines.extend(
        [
            "",
            "### branch_ref 抽查索引",
            "- 下表展示前 30 个判断点。`追踪ID` 只是机器索引，人工 review 主要看“功能判断”和“来源位置”；完整列表见同目录 `coverage_obligations.yaml`。",
            "",
            "| # | 功能判断（人工可读） | 来源位置 | 覆盖侧 / obligation_id | 追踪ID |",
            "|---:|---|---|---|---|",
        ]
    )
    for idx, ref in enumerate(sorted(by_ref)[:30], start=1):
        branch_info = branch_catalog.get(ref, {})
        entries = []
        for item in sorted(by_ref[ref], key=lambda candidate: (_obligation_target_state(candidate), str(candidate.get("id") or ""))):
            entries.append(f"`{_obligation_target_state(item)}` -> `{item.get('id')}`")
        lines.append(f"| {idx} | {_branch_human_summary(ref, branch_info)} | {_branch_location(branch_info)} | {'；'.join(entries)} | `{ref}` |")
    remaining = max(0, len(by_ref) - 30)
    if remaining:
        lines.append(f"| ... | ... | ... | 另 {remaining} 个判断点未在 review 中展开，避免报告过长 | ... |")
    return lines


def _build_l0_value_coverage_index(obligations: list[dict[str, Any]]) -> list[str]:
    value_items = [
        item
        for item in obligations
        if item.get("kind") in {"optional_input_mode", "tiling_key_field_value"}
    ]
    if not value_items:
        return []
    by_field: dict[str, list[dict[str, Any]]] = {}
    for item in value_items:
        by_field.setdefault(_obligation_field_name(item), []).append(item)
    lines = [
        "",
        "## 覆盖索引（数字从哪里来）",
        f"- L0 统计可选输入状态和关键字段取值，本次共有 **{len(value_items)}** 条覆盖义务，覆盖 **{len(by_field)}** 个变量/输入。",
        f"- 变量取值摘要：{_format_field_values({name: [item.get('target_value') or item.get('target_state') for item in items] for name, items in by_field.items()}, max_fields=20, max_values=8)}。",
    ]
    return lines


def _build_l2_key_coverage_index(obligations: list[dict[str, Any]]) -> list[str]:
    key_items = [item for item in obligations if item.get("kind") == "tiling_key_value"]
    if not key_items:
        return []
    reason_counts = Counter(str(item.get("coverage_bucket") or "tiling_key") for item in key_items)
    return [
        "",
        "## 覆盖索引（数字从哪里来）",
        f"- L2 统计可达 TilingKey 取值，本次共有 **{len(key_items)}** 条覆盖义务。",
        f"- 覆盖桶分布：{_format_counter_for_review(reason_counts, max_items=8)}。",
    ]


def _format_counter_for_review(counter: Counter[str], *, max_items: int = 8) -> str:
    if not counter:
        return "<none>"
    chunks = [f"`{key}`={value}" for key, value in counter.most_common(max_items)]
    remaining = max(0, len(counter) - max_items)
    if remaining:
        chunks.append(f"...另 {remaining} 类")
    return "；".join(chunks)


def _format_field_values(by_field: dict[str, list[Any]], *, max_fields: int = 12, max_values: int = 8) -> str:
    chunks: list[str] = []
    for field in sorted(by_field)[:max_fields]:
        values = sorted({str(value) for value in by_field[field] if value is not None})
        chunks.append(f"`{field}`={_compact_list(values, max_items=max_values)}")
    remaining = max(0, len(by_field) - max_fields)
    if remaining:
        chunks.append(f"...另 {remaining} 个变量不展开")
    return "；".join(chunks) if chunks else "<none>"


def _compact_list(values: list[Any], *, max_items: int = 8) -> str:
    text = [str(value) for value in values]
    if len(text) <= max_items:
        return ", ".join(text) if text else "<none>"
    return ", ".join(text[:max_items]) + f", ...另 {len(text) - max_items} 项"


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
    allow_smt_text_cn = "是" if allow_smt else "否"
    key_stats = _as_dict(semantic_focus.get("tiling_key_coverage"))
    design_title, design_bullets = LEVEL_DESIGN.get(level, ("未定义级别", []))
    test_points = matrix.get("test_points") or build_test_points(obligations)
    l0_warning = semantic_focus.get("l0_warning")

    lines = [
        "# TestAgent Coverage Plan Review",
        "",
        "## 摘要",
        f"- 算子 / Operator: `{snapshot.get('op_name')}`",
        f"- 测试级别 / Test Level: **{level}** — {design_title}",
        f"- Focus: {semantic_focus.get('original_query') or '<none>'}",
        f"- Topic: {semantic_focus.get('topic') or '<none>'}",
        f"- Snapshot Hash: `{snapshot.get('snapshot_hash')}`",
        f"- 义务总数 / Total obligations: **{len(obligations)}**",
        f"- 优先级 Hard / High / Normal: {counts.get('hard', 0)} / {counts.get('high', 0)} / {counts.get('normal', 0)}",
        f"- Contract gaps: {len(unresolved['contract_gaps'])}",
        f"- 是否允许进入 solve / Allow solve: {'yes' if allow_smt else 'no'}（{allow_smt_text_cn}）",
    ]
    csv_stats = _as_dict(semantic_focus.get("csv_realization"))
    if csv_stats:
        lines.extend(
            [
                f"- CSV realizable pending: **{csv_stats.get('pending_count', 0)}**",
                f"- Out-of-scope dropped (LOOP_LOCAL/PLATFORM_MACRO，生成时直接去除): **{csv_stats.get('dropped_out_of_scope_count', csv_stats.get('skipped_out_of_scope_count', 0))}**",
                f"- Not CSV-realizable (blocked): **{csv_stats.get('not_csv_realizable_count', 0)}** "
                f"(mapped branches={csv_stats.get('mapped_branch_count', 0)}, abstract={csv_stats.get('abstract_branch_count', 0)})",
            ]
        )
        by_code = _as_dict(csv_stats.get("by_unreachability_code"))
        hints = _as_dict(csv_stats.get("code_hints"))
        resolvability = _as_dict(csv_stats.get("llm_resolvability"))
        if by_code:
            lines.append("- 不可达原因码分布（及 LLM+源码是否可解）:")
            for code, count in by_code.items():
                hint = hints.get(code) or ABSTRACT_REASON_HINTS.get(code) or ""
                llm = (_as_dict(resolvability.get(code)).get("llm_plus_source") if resolvability else "") or ""
                extra = f" [{llm}]" if llm else ""
                lines.append(f"  - `{code}` × {count}{extra}" + (f" — {hint}" if hint else ""))
    lines.extend(
        [
        "",
        "## 级别设计说明（本计划如何设计）",
    ]
    )
    lines.extend(f"- {bullet}" for bullet in design_bullets)
    lines.extend(
        [
            "",
            "### 级别对照（本仓库约定）",
            "- **L0**：功能开关/可选输入取值 — 例如 Rope、Mask、Mask 类型等字段值覆盖。",
            "- **L1**：运行时分支 — kernel_branch true/false 或声明变体覆盖。",
            "- **L2**：穷尽可达 TilingKey。",
            "- **L3**：按 `--topic` 裁剪的主题套件。",
            "",
            "## 测试设计覆盖说明（覆盖什么 / 为什么这样设计）",
        ]
    )
    lines.extend(build_review_design_lines(obligations))
    lines.extend(build_review_coverage_index(obligations, level=level, files=_as_dict(snapshot.get("files"))))

    lines.extend(
        [
            "",
            "## 关键统计",
            f"- Runtime branch obligations: {matrix['runtime_branch_coverage']['obligation_count']}",
            f"- Boundary obligations: {matrix['boundary_coverage']['obligation_count']}",
            f"- Negative expected-reject obligations: {matrix['negative_case_coverage']['obligation_count']}",
            f"- tiling_key_field_value: {matrix['by_kind'].get('tiling_key_field_value', {}).get('total', 0)}",
            f"- L2 exhaustive reachable / unrealized keys: {key_stats.get('reachable_key_count', 0)} / {key_stats.get('unrealized_key_count', 0)}",
        ]
    )
    if l0_warning:
        lines.extend(["", "## L0 说明", f"- warning: {l0_warning}"])

    lines.extend(
        [
            "",
            "## 规划上下文",
            f"- resolved_entities: {len(semantic_focus.get('resolved_entities') or [])}",
            f"- unresolved_terms: {len(semantic_focus.get('unresolved_terms') or [])}",
            f"- branch_predicates: {len(semantic_focus.get('branch_predicates') or [])}",
            "",
            "## Level Matrix（本计划义务按 test_level 计数）",
        ]
    )
    for lvl in TEST_LEVELS:
        row = _as_dict(matrix.get("by_level")).get(lvl, {})
        lines.append(f"- {lvl}: total={row.get('total', 0)} success={row.get('success', 0)} reject={row.get('reject', 0)} blocked={row.get('blocked', 0)}")
    lines.append("")
    lines.append("## Blocking Issues")
    if unresolved["blocking_hard_obligations"]:
        lines.extend(f"- `{item['id']}` {item.get('status')}: {item.get('reason') or 'Hard obligation needs confirmation'}" for item in unresolved["blocking_hard_obligations"])
    else:
        lines.append("- none")
    if unresolved["contract_gaps"]:
        lines.append("")
        lines.append("## Contract Gaps")
        lines.extend(f"- `{item.get('field')}`: {item.get('reason')}" for item in unresolved["contract_gaps"])
    lines.append("")
    lines.append("## Manual Review")
    lines.append("- 请核对：级别设计是否符合预期、测试点条数是否合理、样例 refs 是否落在正确功能属性上、有无 blockers。")
    lines.append("- OpenCode AskQuestion 按钮：`approve`（批准并立即 tg-solve）/ `reject`（拒绝）/ `suggest`（给出修改建议）。")
    lines.append("- 同级别归档副本：`plan/levels/<L0|L1|...>/`（避免 L0/L1 互相覆盖）。")
    return "\n".join(lines) + "\n"


def write_plan_outputs(out_root: Path, plan: dict[str, Any], snapshot: dict[str, Any]) -> None:
    level = str(plan.get("test_level") or "L1")
    plan_payload = {
        "version": 1,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "test_level": level,
        "semantic_focus": plan["semantic_focus"],
        "obligations": plan["obligations"],
        "plan_hash": plan["plan_hash"],
    }
    matrix_payload = {"version": 1, "snapshot_hash": snapshot.get("snapshot_hash"), "test_level": level, **plan["matrix"], "plan_hash": plan["plan_hash"]}
    unresolved_payload = {"version": 1, "snapshot_hash": snapshot.get("snapshot_hash"), "test_level": level, **plan["unresolved"], "plan_hash": plan["plan_hash"]}
    focus_payload = {
        "version": 1,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "test_level": level,
        "semantic_focus": plan["semantic_focus"],
        "planning_context": plan["planning_context"],
        "plan_hash": plan["plan_hash"],
    }

    write_yaml(out_root / "plan" / "coverage_obligations.yaml", plan_payload)
    write_yaml(out_root / "plan" / "coverage_matrix.yaml", matrix_payload)
    write_yaml(out_root / "plan" / "unresolved.yaml", unresolved_payload)
    write_yaml(out_root / "plan" / "semantic_focus.yaml", focus_payload)
    (out_root / "plan" / "review.md").write_text(plan["review"], encoding="utf-8")

    # Per-level archive so L0/L1 runs do not overwrite each other for human review.
    level_dir = out_root / "plan" / "levels" / level
    level_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(level_dir / "coverage_obligations.yaml", plan_payload)
    write_yaml(level_dir / "coverage_matrix.yaml", matrix_payload)
    write_yaml(level_dir / "unresolved.yaml", unresolved_payload)
    write_yaml(level_dir / "semantic_focus.yaml", focus_payload)
    (level_dir / "review.md").write_text(plan["review"], encoding="utf-8")
    write_yaml(
        level_dir / "summary.yaml",
        {
            "version": 1,
            "test_level": level,
            "status": plan.get("status") or unresolved_payload.get("status"),
            "plan_hash": plan["plan_hash"],
            "snapshot_hash": snapshot.get("snapshot_hash"),
            "obligation_count": len(plan["obligations"]),
            "priority_counts": plan["matrix"].get("priority_counts"),
            "test_points": plan["matrix"].get("test_points"),
            "csv_realization": plan.get("semantic_focus", {}).get("csv_realization"),
        },
    )
    csv_report = plan.get("semantic_focus", {}).get("csv_unreachability_report")
    if not isinstance(csv_report, dict):
        csv_report = build_csv_unreachability_report(plan["obligations"], plan.get("_realization_map") or {})
    write_yaml(level_dir / "csv_unreachability_report.yaml", csv_report)
    write_yaml(out_root / "plan" / "csv_unreachability_report.yaml", csv_report)
    _ensure_supplement(level_dir / "human_supplement.yaml", snapshot, plan)

    supplement = out_root / "plan" / "human_supplement.yaml"
    _ensure_supplement(supplement, snapshot, plan)


def _ensure_supplement(path: Path, snapshot: dict[str, Any], plan: dict[str, Any]) -> None:
    if not path.exists():
        write_yaml(
            path,
            {
                "version": 1,
                "status": "pending",
                "decision": "",
                "approved_snapshot_hash": "",
                "approved_plan_hash": "",
                "approved_at": "",
                "options": ["approve", "reject", "suggest"],
                "supplements": [],
                "notes": "Human input is independent from Understand Canonical KB.",
                "test_level": str(plan.get("test_level") or ""),
            },
        )
        return
    current = read_yaml(path)
    changed = (
        current.get("approved_snapshot_hash") not in {"", snapshot.get("snapshot_hash")}
        or current.get("approved_plan_hash") not in {"", plan["plan_hash"]}
    )
    current.setdefault("version", 1)
    current.setdefault("supplements", [])
    current.setdefault("notes", "")
    current.setdefault("approved_at", "")
    current["test_level"] = str(plan.get("test_level") or current.get("test_level") or "")
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
    write_yaml(path, current)


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
