"""Workflow registry — normalized runtime authority for phases/actions/gates."""

from __future__ import annotations

from typing import Any

from ascendc_pilot.workflows.specs import WORKFLOWS


_TG_PIPELINES: dict[str, dict[str, list[str]]] = {
    "tg-init": {
        "intent": ["init_intent"],
        "kb_ready": ["kb_check"],
        "contract": ["contract_build"],
        "bind": ["semantic_bind"],
        "gate": ["integrity_gate", "init_audit"],
        "confirm": ["human_confirm"],
        "merge": ["bind_merge"],
        "nest": ["mid_nest"],
    },
    "tg-plan": {
        "intent": ["plan_intent"],
        "scope": ["plan_scope"],
        "gate": ["plan_precheck"],
        "build": ["plan_build"],
        "filter": ["plan_build"],
        "review": ["plan_build"],
        "approve": ["plan_approve"],
    },
    "tg-solve": {
        "gate": ["solve_precheck"],
        "oracle": ["oracle_probe"],
        "ledger": ["closure_ledger"],
        "search": ["closure_search"],
        "residual": ["closure_residual"],
        "construct": ["closure_construct", "closure_explain"],
        "lemma": ["lemma_leads", "lemma_evidence", "lemma_mine", "lemma_verify", "lemma_review", "lemma_apply", "lemma_loop"],
        "audit": ["closure_audit"],
        "certify": ["closure_certify"],
        "encode": ["z3_solve"],
        "solve": ["z3_solve"],
        "project": ["z3_solve"],
        "cover": ["cover_confirm"],
    },
}

_TG_ACTION_IO: dict[str, dict[str, dict[str, list[str]]]] = {
    "tg-init": {
        "init_intent": {"read": ["context/**"], "write": ["tg/init/init_intent.yaml"]},
        "kb_check": {
            "read": ["../uo/*.uo"],
            "write": ["tg/init/uo_ready.yaml"],
        },
        "contract_build": {
            "read": ["../uo/*.uo", "tg/init/uo_ready.yaml", "context/**"],
            "write": [
                "tg/intake/**", "tg/snapshot/**", "tg/realization/**", "tg/contract/**",
                "tg/plan/coverage_obligations.yaml", "tg/run.yaml", "context/pilot_params.yaml",
            ],
        },
        "semantic_bind": {
            "read": [
                "../uo/*.uo", "tg/contract/**",
                "tg/realization/llm_bind_prompt_bundle.yaml", "tg/realization/binding_inventory.yaml",
                "tg/realization/binding_gaps.yaml", "tg/realization/unresolved.yaml",
            ],
            "write": ["tg/realization/binding_inventory.yaml", "tg/realization/semantic_bind_patch.yaml"],
        },
        "bind_merge": {"read": ["tg/snapshot/**", "tg/realization/**"], "write": ["tg/realization/**"]},
        "mid_nest": {"read": ["tg/realization/**"], "write": ["tg/realization/mid_symbol_queue.yaml"]},
        "integrity_gate": {
            "read": ["tg/snapshot/**", "tg/realization/**", "tg/contract/**"],
            "write": ["tg/contract/integrity_gate.yaml"],
        },
        "init_audit": {
            "read": ["tg/snapshot/**", "tg/contract/**", "tg/realization/**", "tg/init/**"],
            "write": ["tg/init/audit_report.yaml"],
        },
        "human_confirm": {
            "read": ["tg/init/**", "tg/realization/**", "tg/snapshot/**", "tg/contract/**"],
            "write": ["tg/init/status.yaml", "tg/init/kb_fingerprint.yaml", "tg/init/confirmation.yaml"],
        },
    },
    "tg-plan": {
        "plan_intent": {"read": ["../uo/*.uo", "tg/init/**", "context/**"], "write": ["tg/plan/plan_intent.yaml"]},
        "plan_scope": {
            "read": ["../uo/*.uo", "tg/init/**", "tg/plan/plan_intent.yaml", "tg/snapshot/**", "tg/realization/**", "context/**"],
            "write": ["tg/plan/levels/*/plan_scope.yaml", "tg/plan/plan_intent.yaml"],
        },
        "plan_precheck": {"read": ["../uo/*.uo", "tg/init/status.yaml", "tg/snapshot/**"], "write": []},
        "plan_build": {
            "read": ["../uo/*.uo", "tg/init/**", "tg/plan/plan_intent.yaml", "tg/snapshot/**", "tg/realization/**", "tg/contract/**", "context/**"],
            "write": ["tg/plan/**", "tg/extract/**", "tg/realization/**", "tg/contract/**", "tg/run.yaml"],
        },
        "plan_approve": {"read": ["tg/plan/levels/*/**", "tg/plan/plan_intent.yaml"], "write": ["tg/plan/levels/*/human_supplement.yaml"]},
    },
    "tg-solve": {
        "solve_precheck": {"read": ["../uo/*.uo", "tg/init/**", "tg/plan/**", "tg/snapshot/**"], "write": []},
        "oracle_probe": {"read": ["../uo/*.uo", "tg/init/**", "operators/**"], "write": ["tg/closure/oracle_probe.yaml"]},
        "closure_ledger": {
            "read": ["../uo/*.uo", "tg/closure/**"],
            "write": ["tg/closure/R.txt", "tg/closure/open.txt", "tg/closure/excluded.txt", "tg/closure/excluded_why.csv"],
        },
        "closure_search": {"read": ["../uo/*.uo", "tg/closure/**"], "write": ["tg/closure/rounds/**", "tg/closure/models/**"]},
        "closure_residual": {"read": ["tg/closure/**"], "write": ["tg/closure/residual/**", "tg/closure/route.yaml"]},
        "closure_construct": {"read": ["../uo/*.uo", "tg/closure/**"], "write": ["tg/closure/construct/**"]},
        "closure_explain": {"read": ["tg/closure/**"], "write": ["tg/closure/why.csv", "tg/closure/construct/**"]},
        "lemma_leads": {"read": ["tg/closure/**"], "write": ["tg/closure/lemmas/leads.yaml", "tg/closure/leads.csv", "tg/closure/leads3.csv"]},
        "lemma_evidence": {
            "read": ["../uo/*.uo", "tg/closure/lemmas/leads.yaml"],
            "write": ["tg/closure/lemmas/evidence/**", "tg/closure/lemmas/evidence_receipt.yaml", "tg/closure/lemmas/leads.yaml"],
        },
        "lemma_mine": {
            "read": ["../uo/*.uo", "tg/closure/lemmas/leads.yaml", "tg/closure/lemmas/evidence/**", "runs/**/actions/lemma_mine/**"],
            "write": ["runs/{run_id}/actions/lemma_mine/parts/**", "runs/{run_id}/actions/lemma_mine/scratch/**", "runs/{run_id}/actions/lemma_mine/staging.yaml"],
        },
        "lemma_verify": {
            "read": ["runs/**/actions/lemma_mine/**", "tg/closure/**"],
            "write": ["runs/{run_id}/actions/lemma_verify/verify.yaml", "tg/closure/lemmas/verify.yaml"],
        },
        "lemma_review": {"read": ["../uo/*.uo", "runs/**/actions/lemma_mine/**", "runs/**/actions/lemma_verify/**", "tg/closure/lemmas/**"], "write": ["runs/{run_id}/actions/lemma_review/review.yaml"]},
        "lemma_apply": {
            "read": ["runs/**/actions/lemma_review/review.yaml", "tg/closure/lemmas/**", "operators/**/proof_rules.yaml"],
            "write": ["tg/closure/excluded.txt", "tg/closure/excluded_why.csv", "tg/closure/open.txt", "tg/closure/lemmas/active_rules.yaml", "tg/closure/lemmas/revoked_rules.yaml", "tg/closure/lemmas/reviews.yaml"],
        },
        "lemma_loop": {
            "read": [
                "../uo/*.uo",
                "tg/closure/**",
                "runs/**/actions/lemma_mine/**",
                "runs/**/actions/lemma_review/**",
            ],
            "write": [
                "tg/closure/lemma_loop.yaml",
                "tg/closure/rounds/**/lemma.yaml",
                "runs/{run_id}/actions/lemma_mine/staging.yaml",
                "runs/{run_id}/actions/lemma_review/review.yaml",
                "tg/closure/excluded.txt",
                "tg/closure/excluded_why.csv",
                "tg/closure/open.txt",
                "tg/closure/lemmas/active_rules.yaml",
                "tg/closure/lemmas/reviews.yaml",
            ],
        },
        "closure_audit": {"read": ["../uo/*.uo", "tg/closure/**"], "write": ["runs/{run_id}/actions/closure_audit/review.yaml"]},
        "closure_certify": {
            "read": ["tg/closure/**", "runs/**/actions/closure_audit/review.yaml"],
            "write": ["tg/closure/closure.csv", "tg/closure/certificate.yaml", "tg/closure/audit_report.yaml"],
        },
        "z3_solve": {
            "read": ["tg/init/**", "tg/plan/**", "tg/snapshot/**", "tg/realization/**", "tg/contract/**", "tg/extract/**", "context/**"],
            "write": ["tg/solve/**", "tg/cases/**", "tg/realization/**"],
        },
        "cover_confirm": {"read": ["tg/solve/**", "tg/cases/**", "tg/plan/**"], "write": []},
    },
}


def _action(meta: dict[str, Any], action_id: str) -> dict[str, Any] | None:
    for row in meta.get("actions") or []:
        if isinstance(row, dict) and str(row.get("id") or "") == action_id:
            return row
    return None


def _ensure_agent(meta: dict[str, Any], agent_id: str, role_id: str) -> None:
    agents = [row for row in (meta.get("agents") or []) if isinstance(row, dict)]
    if not any(str(row.get("id") or "") == agent_id for row in agents):
        agents.append({"id": agent_id, "role": role_id})
    meta["agents"] = agents


def _make_deterministic(row: dict[str, Any]) -> None:
    row["agent_id"] = None
    row["role_id"] = "deterministic_engine"
    row["execution_mode"] = "deterministic"
    row["actors"] = []
    row["task_prompt_id"] = None
    row["capability_ids"] = []


def _apply_uo_control_plane_contracts() -> None:
    """Expose the six-stage `.uo` compiler without legacy KB control gates."""
    init = WORKFLOWS.get("uo-init") or {}
    for action_id in ("prepare", "extract", "analyze", "apply_gap_patch", "commit", "review"):
        row = _action(init, action_id)
        if row is not None:
            _make_deterministic(row)

    init["phase_gates"] = {
        "prepare": ["layout_receipt"],
        "extract": ["extract_receipt"],
        "analyze": [],
        "resolve": ["gap_patch_evidence"],
        "commit": ["uo_product_ready"],
        "review": [],
    }
    init["complete_gates"] = ["uo_product_ready"]
    init["gates"] = ["layout_receipt", "extract_receipt", "gap_patch_evidence", "uo_product_ready"]
    action_gates = {
        "prepare": ["layout_receipt"], "extract": ["extract_receipt"], "analyze": [],
        "resolve": ["gap_patch_evidence"], "apply_gap_patch": [], "commit": ["uo_product_ready"], "review": [],
    }
    for action_id, gates in action_gates.items():
        row = _action(init, action_id)
        if row is not None:
            row["gates"] = list(gates)

    init["agents"] = [
        {"id": "ascendc-pilot", "role": "controller"},
        {"id": "uo-semantic-resolver", "role": "producer"},
    ]
    init["static_obligations"] = [
        {"id": "scope_confirmed", "label_zh": "范围已校验"},
        {"id": "uo_product_ready", "label_zh": ".uo CodeMap 已写入"},
    ]
    meta = init.setdefault("meta", {})
    recovery = meta.setdefault("recovery_by_reason", {})
    recovery.pop("KB_REVIEW_REWORK", None)
    recovery["CODEMAP_REVIEW_REWORK"] = {"type": "action", "action_id": "review"}
    for edge in init.get("transitions") or []:
        if not isinstance(edge, dict):
            continue
        codes = [str(code) for code in (edge.get("reason_codes") or [])]
        edge["reason_codes"] = ["CODEMAP_REVIEW_REWORK" if code == "KB_REVIEW_REWORK" else code for code in codes]

    update = WORKFLOWS.get("uo-update") or {}
    for row in update.get("actions") or []:
        if isinstance(row, dict):
            _make_deterministic(row)
    update["agents"] = []
    labels = {
        "detect_changes": "检测源码变更", "plan_update": "规划 CodeMap 增量更新",
        "apply_update": "应用 CodeMap 增量更新", "key_triage": "分类受影响语义关系",
        "key_resolution": "重建受影响语义关系", "confidence_report": "生成更新质量报告",
        "confidence_review": "审查更新一致性", "export_integrity": "校验 CodeMap 完整性",
        "diff_summary": "CodeMap 差异摘要", "diff_only": "仅生成 CodeMap 差异摘要",
    }
    for action_id, label in labels.items():
        row = _action(update, action_id)
        if row is not None:
            row["label_zh"] = label

    query = WORKFLOWS.get("uo-query") or {}
    query["phase_gates"] = {}
    query["complete_gates"] = []
    query["gates"] = []
    query["static_obligations"] = []
    lookup = _action(query, "kb_lookup")
    if lookup is not None:
        lookup["label_zh"] = "CodeMap 查询"
        lookup["task_prompt_id"] = "uo/codemap-query"
        lookup["gates"] = []


def _apply_tg_control_plane_contracts() -> None:
    for workflow_id, pipelines in _TG_PIPELINES.items():
        meta = WORKFLOWS.get(workflow_id)
        if not isinstance(meta, dict):
            continue
        meta["pipelines"] = {phase: list(actions) for phase, actions in pipelines.items()}
        for action_id, io in _TG_ACTION_IO.get(workflow_id, {}).items():
            row = _action(meta, action_id)
            if row is not None:
                row["allowed_read_paths"] = list(io.get("read") or [])
                row["allowed_write_paths"] = list(io.get("write") or [])

    # Human approval stays on human_confirm / plan_approve only.
    # plan_intent is deterministic: default T=D unless CLI/context supplies a selector.
    for workflow_id, action_id in (("tg-init", "human_confirm"), ("tg-plan", "plan_approve")):
        meta = WORKFLOWS.get(workflow_id) or {}
        row = _action(meta, action_id)
        if row is None:
            continue
        row["agent_id"] = "ascendc-pilot"
        row["role_id"] = "controller"
        row["execution_mode"] = "primary_interactive"
        row["actors"] = ["ascendc-pilot"]
        _ensure_agent(meta, "ascendc-pilot", "controller")

    plan_meta = WORKFLOWS.get("tg-plan") or {}
    plan_intent = _action(plan_meta, "plan_intent")
    if plan_intent is not None:
        plan_intent["agent_id"] = "deterministic-tg-engine"
        plan_intent["role_id"] = "deterministic_engine"
        plan_intent["execution_mode"] = "deterministic"
        plan_intent["actors"] = ["deterministic-tg-engine"]

    upstream = ["uo", "tg/intake", "tg/snapshot", "tg/contract", "tg/realization", "tg/init", "tg/run.yaml"]
    plan = WORKFLOWS.get("tg-plan") or {}
    plan["reset_policy"] = {
        "reinit_delete": ["tg/plan", "tg/solve", "tg/cases", "tg/extract"],
        "reinit_preserve": upstream, "reinit_wipe_runs": "current", "continue_scrub": "from_contracts",
    }
    solve = WORKFLOWS.get("tg-solve") or {}
    solve["reset_policy"] = {
        "reinit_delete": ["tg/solve", "tg/cases", "tg/closure"],
        "reinit_preserve": [*upstream, "tg/plan", "tg/extract"],
        "reinit_wipe_runs": "current", "continue_scrub": "from_contracts",
    }


_apply_uo_control_plane_contracts()
_apply_tg_control_plane_contracts()


def resolve_workflow_id(workflow_id: str) -> str:
    seen: set[str] = set()
    wid = str(workflow_id or "").strip()
    while wid and wid not in seen:
        seen.add(wid)
        meta = WORKFLOWS.get(wid)
        if not isinstance(meta, dict):
            break
        alias = str(meta.get("alias_of") or "").strip()
        if not alias:
            break
        wid = alias
    return wid


def resolve_tg_mode(project_root: Any | None = None, *, default: str = "tilingkey_full_coverage") -> str:
    if project_root is None:
        return default
    try:
        from pathlib import Path
        from ascendc_pilot.paths import tg_root
        tg = tg_root(Path(project_root))
        for rel in ("plan/plan_intent.yaml", "init/init_intent.yaml"):
            path = tg / rel
            if not path.is_file():
                continue
            try:
                import yaml
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            mode = str((doc or {}).get("mode") or "").strip()
            if mode:
                return mode
    except Exception:
        return default
    return default


def _rederive_actor_fields(merged: dict[str, Any], patch: dict[str, Any]) -> None:
    if "agent_id" not in patch and "role_id" not in patch:
        return
    agent_id = str(merged.get("agent_id") or "")
    merged["actors"] = [agent_id] if agent_id else []
    try:
        from ascendc_pilot.ownership import infer_execution_mode
        merged["execution_mode"] = infer_execution_mode(
            agent_id=agent_id or None,
            role_id=str(merged.get("role_id") or "") or None,
            execution_mode=None,
        )
    except Exception:
        pass


def _apply_mode_overlay(meta: dict[str, Any], mode: str | None) -> dict[str, Any]:
    overlays = meta.get("mode_overlays") if isinstance(meta.get("mode_overlays"), dict) else {}
    if not overlays:
        return meta
    default = str((meta.get("meta") or {}).get("default_mode") or "tilingkey_full_coverage")
    chosen = mode or default
    overlay = overlays.get(chosen) or overlays.get(default) or {}
    if not isinstance(overlay, dict):
        return meta
    out = dict(meta)
    for key in ("pipelines", "transitions", "phase_gates", "complete_gates", "terminal_ready_states", "phases", "states", "gates"):
        if key in overlay:
            out[key] = overlay[key]
    overrides = overlay.get("action_overrides")
    if isinstance(overrides, dict) and overrides:
        actions: list[dict[str, Any]] = []
        for row in out.get("actions") or []:
            if not isinstance(row, dict):
                continue
            aid = str(row.get("id") or "")
            patch = overrides.get(aid)
            if isinstance(patch, dict) and patch:
                merged = dict(row)
                for key, value in patch.items():
                    if value is None:
                        merged.pop(key, None)
                    else:
                        merged[key] = value
                _rederive_actor_fields(merged, patch)
                actions.append(merged)
            else:
                actions.append(dict(row))
        out["actions"] = actions
    out["_active_mode"] = chosen
    return out


def get_workflow(workflow_id: str, *, project_root: Any | None = None, mode: str | None = None) -> dict[str, Any]:
    wid = resolve_workflow_id(workflow_id)
    if wid not in WORKFLOWS:
        raise KeyError(f"Unknown workflow: {workflow_id}")
    meta = dict(WORKFLOWS[wid])
    if meta.get("mode_overlays"):
        meta = _apply_mode_overlay(meta, mode or resolve_tg_mode(project_root))
    return meta


def list_user_workflows() -> list[str]:
    return [wid for wid, meta in WORKFLOWS.items() if meta.get("slash") and not meta.get("reserved") and not meta.get("alias_of")]


def state_ids(workflow_id: str) -> list[str]:
    meta = get_workflow(workflow_id)
    states = meta.get("states") or []
    if states:
        return [str(state["id"]) for state in states if isinstance(state, dict) and state.get("id")]
    return list(meta.get("phases") or [])


def label_zh_for(workflow_id: str, phase: str) -> str:
    meta = get_workflow(workflow_id)
    for state in meta.get("states") or []:
        if isinstance(state, dict) and state.get("id") == phase:
            return str(state.get("label_zh") or phase)
    return phase


def entry_state(workflow_id: str) -> str:
    meta = get_workflow(workflow_id)
    if meta.get("entry_state"):
        return str(meta["entry_state"])
    ids = state_ids(workflow_id)
    if not ids:
        raise ValueError(f"workflow {workflow_id} has no entry_state")
    return ids[0]


def allowed_transition(workflow_id: str, frm: str, to: str, *, kind: str = "forward", project_root: Any | None = None, mode: str | None = None) -> bool:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    return any(
        isinstance(edge, dict)
        and edge.get("from") == frm
        and edge.get("to") == to
        and str(edge.get("kind") or "forward") == kind
        for edge in meta.get("transitions") or []
    )


def rework_targets(workflow_id: str, frm: str, *, reason_code: str = "", project_root: Any | None = None, mode: str | None = None) -> list[str]:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    out: list[str] = []
    for edge in meta.get("transitions") or []:
        if not isinstance(edge, dict) or edge.get("from") != frm or str(edge.get("kind") or "") != "rework":
            continue
        codes = edge.get("reason_codes") or []
        if reason_code and codes and reason_code not in codes:
            continue
        target = str(edge.get("to") or "")
        if target and target not in out:
            out.append(target)
    return out


def actions_for_phase(workflow_id: str, phase: str, *, project_root: Any | None = None, mode: str | None = None) -> list[dict[str, Any]]:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    return [action for action in (meta.get("actions") or []) if isinstance(action, dict) and phase in set(action.get("phases") or [])]


def phase_pipeline(workflow_id: str, phase: str, *, project_root: Any | None = None, mode: str | None = None) -> list[str]:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    pipes = meta.get("pipelines") or {}
    raw = pipes.get(phase) if isinstance(pipes, dict) else None
    return [str(action) for action in raw if str(action).strip()] if isinstance(raw, list) else []


def action_by_id(workflow_id: str, action_id: str, *, project_root: Any | None = None, mode: str | None = None) -> dict[str, Any] | None:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    for action in meta.get("actions") or []:
        if isinstance(action, dict) and str(action.get("id") or "") == action_id:
            return dict(action)
    return None
