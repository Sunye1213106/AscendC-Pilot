"""Workflow registry — sole authority for phases, transitions, actions, gates."""

from __future__ import annotations

from typing import Any

from ascendc_pilot.workflows.specs import WORKFLOWS


_TG_PIPELINES: dict[str, dict[str, list[str]]] = {
    "tg-init": {
        # Default = tilingkey_full_coverage (no CSV merge/nest).
        "intent": ["init_intent"],
        "kb_ready": ["kb_check"],
        "contract": ["contract_build"],
        "bind": ["semantic_bind"],
        "gate": ["integrity_gate", "init_audit"],
        "confirm": ["human_confirm"],
        # csv_consumer overlay reintroduces these phases.
        "merge": ["bind_merge"],
        "nest": ["mid_nest"],
    },
    "tg-plan": {
        "intent": ["plan_intent"],
        "scope": ["plan_scope"],
        "gate": ["plan_precheck"],
        # plan_build performs generation, filtering, and review materialization
        # in one deterministic engine invocation. Reusing the same receipt in
        # the following two states prevents skipping the build while avoiding
        # duplicate planner execution.
        "build": ["plan_build"],
        "filter": ["plan_build"],
        "review": ["plan_build"],
        "approve": ["plan_approve"],
    },
    "tg-solve": {
        # Default = tilingkey_full_coverage closure loop.
        "gate": ["solve_precheck"],
        "oracle": ["oracle_probe"],
        "ledger": ["closure_ledger"],
        "search": ["closure_search"],
        "residual": ["closure_residual"],
        "construct": ["closure_construct", "closure_explain"],
        "lemma": ["lemma_leads", "lemma_evidence", "lemma_mine", "lemma_review", "lemma_apply"],
        "audit": ["closure_audit"],
        "certify": ["closure_certify"],
        # csv_consumer compatibility (selected when mode=csv_consumer via overlay).
        "encode": ["z3_solve"],
        "solve": ["z3_solve"],
        "project": ["z3_solve"],
        "cover": ["cover_confirm"],
    },
}

_TG_ACTION_IO: dict[str, dict[str, dict[str, list[str]]]] = {
    "tg-init": {
        "init_intent": {
            "read": ["uo/manifest.yaml", "context/**"],
            "write": ["tg/init/init_intent.yaml"],
        },
        "kb_check": {
            "read": ["uo/manifest.yaml", "uo/checks/integrity.yaml"],
            "write": [],
        },
        "contract_build": {
            "read": ["uo/**", "context/**"],
            "write": [
                "tg/intake/**",
                "tg/snapshot/**",
                "tg/realization/**",
                "tg/contract/**",
                "tg/plan/coverage_obligations.yaml",
                "tg/run.yaml",
                "context/pilot_params.yaml",
            ],
        },
        "semantic_bind": {
            "read": [
                "uo/ir/tg_host_view.yaml",
                "uo/ir/operator_graph.yaml",
                "tg/contract/**",
                "tg/realization/llm_bind_prompt_bundle.yaml",
                "tg/realization/binding_inventory.yaml",
                "tg/realization/binding_gaps.yaml",
                "tg/realization/unresolved.yaml",
            ],
            "write": [
                "tg/realization/binding_inventory.yaml",
                "tg/realization/semantic_bind_patch.yaml",
            ],
        },
        "bind_merge": {
            "read": ["tg/snapshot/**", "tg/realization/**"],
            "write": ["tg/realization/**"],
        },
        "mid_nest": {
            "read": ["tg/realization/**"],
            "write": ["tg/realization/mid_symbol_queue.yaml"],
        },
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
            "write": [
                "tg/init/status.yaml",
                "tg/init/kb_fingerprint.yaml",
                "tg/init/confirmation.yaml",
            ],
        },
    },
    "tg-plan": {
        "plan_intent": {
            "read": ["tg/init/**", "context/**", "uo/manifest.yaml"],
            "write": ["tg/plan/plan_intent.yaml"],
        },
        "plan_scope": {
            "read": [
                "tg/init/**",
                "tg/plan/plan_intent.yaml",
                "tg/snapshot/**",
                "tg/realization/**",
                "context/**",
            ],
            "write": ["tg/plan/levels/*/plan_scope.yaml", "tg/plan/plan_intent.yaml"],
        },
        "plan_precheck": {
            "read": ["tg/init/status.yaml", "tg/snapshot/**", "uo/manifest.yaml"],
            "write": [],
        },
        "plan_build": {
            "read": [
                "tg/init/**",
                "tg/plan/plan_intent.yaml",
                "tg/snapshot/**",
                "tg/realization/**",
                "tg/contract/**",
                "context/**",
            ],
            "write": ["tg/plan/**", "tg/extract/**", "tg/realization/**", "tg/contract/**", "tg/run.yaml"],
        },
        "plan_approve": {
            "read": ["tg/plan/levels/*/**", "tg/plan/plan_intent.yaml"],
            "write": ["tg/plan/levels/*/human_supplement.yaml"],
        },
    },
    "tg-solve": {
        "solve_precheck": {
            "read": ["tg/init/**", "tg/plan/**", "tg/snapshot/**", "uo/manifest.yaml"],
            "write": [],
        },
        "oracle_probe": {
            "read": ["uo/**", "tg/init/**", "operators/**"],
            "write": ["tg/closure/oracle_probe.yaml"],
        },
        "closure_ledger": {
            "read": ["tg/closure/**", "uo/**"],
            "write": [
                "tg/closure/R.txt",
                "tg/closure/open.txt",
                "tg/closure/excluded.txt",
                "tg/closure/excluded_why.csv",
            ],
        },
        "closure_search": {
            "read": ["tg/closure/**", "uo/ir/tg_host_view.yaml", "uo/ir/host_codemap.yaml"],
            "write": ["tg/closure/rounds/**", "tg/closure/models/**"],
        },
        "closure_residual": {
            "read": ["tg/closure/**"],
            "write": ["tg/closure/residual/**", "tg/closure/route.yaml"],
        },
        "closure_construct": {
            "read": ["tg/closure/**", "uo/**"],
            "write": ["tg/closure/construct/**"],
        },
        "closure_explain": {
            "read": ["tg/closure/**"],
            "write": ["tg/closure/why.csv", "tg/closure/construct/**"],
        },
        "lemma_leads": {
            "read": ["tg/closure/**"],
            "write": ["tg/closure/lemmas/leads.yaml", "tg/closure/leads.csv", "tg/closure/leads3.csv"],
        },
        "lemma_evidence": {
            "read": ["tg/closure/lemmas/leads.yaml", "uo/ir/**", "uo/tiling/**"],
            "write": [
                "tg/closure/lemmas/evidence/**",
                "tg/closure/lemmas/evidence_receipt.yaml",
                "tg/closure/lemmas/leads.yaml",
            ],
        },
        "lemma_mine": {
            "read": [
                "tg/closure/lemmas/leads.yaml",
                "tg/closure/lemmas/evidence/**",
                "uo/ir/**",
                "uo/tiling/**",
                "runs/**/actions/lemma_mine/**",
            ],
            "write": [
                "runs/{run_id}/actions/lemma_mine/parts/**",
                "runs/{run_id}/actions/lemma_mine/scratch/**",
                "runs/{run_id}/actions/lemma_mine/staging.yaml",
            ],
        },
        "lemma_review": {
            "read": [
                "runs/**/actions/lemma_mine/**",
                "tg/closure/lemmas/**",
                "uo/ir/**",
            ],
            "write": [
                "runs/{run_id}/actions/lemma_review/review.yaml",
            ],
        },
        "lemma_apply": {
            "read": [
                "runs/**/actions/lemma_review/review.yaml",
                "tg/closure/lemmas/**",
                "operators/**/proof_rules.yaml",
            ],
            "write": [
                "tg/closure/excluded.txt",
                "tg/closure/excluded_why.csv",
                "tg/closure/open.txt",
                "tg/closure/lemmas/active_rules.yaml",
                "tg/closure/lemmas/revoked_rules.yaml",
                "tg/closure/lemmas/reviews.yaml",
            ],
        },
        "closure_audit": {
            "read": ["tg/closure/**", "uo/ir/**", "uo/tiling/**"],
            "write": [
                "runs/{run_id}/actions/closure_audit/review.yaml",
            ],
        },
        "closure_certify": {
            "read": [
                "tg/closure/**",
                "runs/**/actions/closure_audit/review.yaml",
            ],
            "write": [
                "tg/closure/closure.csv",
                "tg/closure/certificate.yaml",
                "tg/closure/audit_report.yaml",
            ],
        },
        "z3_solve": {
            "read": [
                "tg/init/**",
                "tg/plan/**",
                "tg/snapshot/**",
                "tg/realization/**",
                "tg/contract/**",
                "tg/extract/**",
                "context/**",
            ],
            "write": ["tg/solve/**", "tg/cases/**", "tg/realization/**"],
        },
        "cover_confirm": {
            "read": ["tg/solve/**", "tg/cases/**", "tg/plan/**"],
            "write": [],
        },
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


def _apply_tg_control_plane_contracts() -> None:
    """Close TG ordering, ownership, and reset-policy gaps at registry load."""

    for workflow_id, pipelines in _TG_PIPELINES.items():
        meta = WORKFLOWS.get(workflow_id)
        if not isinstance(meta, dict):
            continue
        # Keep the union for discovery; mode_overlays (if present) select the
        # active pipeline at get_workflow() time.
        meta["pipelines"] = {phase: list(actions) for phase, actions in pipelines.items()}
        overlays = meta.get("mode_overlays")
        if isinstance(overlays, dict):
            for _mode, overlay in overlays.items():
                if not isinstance(overlay, dict):
                    continue
                # Fill missing pipeline keys from the overlay only — do not
                # reintroduce the opposite mode's phases.
                if "pipelines" not in overlay:
                    continue

        for action_id, io in _TG_ACTION_IO.get(workflow_id, {}).items():
            row = _action(meta, action_id)
            if row is None:
                continue
            row["allowed_read_paths"] = list(io.get("read") or [])
            row["allowed_write_paths"] = list(io.get("write") or [])

    # Human decisions execute in the current primary session; they are never
    # anonymous actors and must not inherit the UO scope-confirmation recipe.
    for workflow_id, action_id in (
        ("tg-init", "human_confirm"),
        ("tg-plan", "plan_intent"),
        ("tg-plan", "plan_approve"),
    ):
        meta = WORKFLOWS.get(workflow_id) or {}
        row = _action(meta, action_id)
        if row is None:
            continue
        row["agent_id"] = "ascendc-pilot"
        row["role_id"] = "controller"
        row["execution_mode"] = "primary_interactive"
        row["actors"] = ["ascendc-pilot"]
        _ensure_agent(meta, "ascendc-pilot", "controller")

    # Reinitializing a downstream TG workflow must preserve its upstream
    # contracts. Only products owned by that workflow and its descendants are
    # invalidated.
    upstream = [
        "uo",
        "tg/intake",
        "tg/snapshot",
        "tg/contract",
        "tg/realization",
        "tg/init",
        "tg/run.yaml",
    ]
    plan = WORKFLOWS.get("tg-plan") or {}
    plan["reset_policy"] = {
        "reinit_delete": ["tg/plan", "tg/solve", "tg/cases", "tg/extract"],
        "reinit_preserve": upstream,
        "reinit_wipe_runs": "current",
        "continue_scrub": "from_contracts",
    }
    solve = WORKFLOWS.get("tg-solve") or {}
    solve["reset_policy"] = {
        "reinit_delete": ["tg/solve", "tg/cases", "tg/closure"],
        "reinit_preserve": [*upstream, "tg/plan", "tg/extract"],
        "reinit_wipe_runs": "current",
        "continue_scrub": "from_contracts",
    }


_apply_tg_control_plane_contracts()


def resolve_workflow_id(workflow_id: str) -> str:
    """Follow ``alias_of`` chains when present."""
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
    """Read frozen plan/init intent mode when available."""
    if project_root is None:
        return default
    try:
        from pathlib import Path

        from ascendc_pilot.paths import tg_root

        root = Path(project_root)
        tg = tg_root(root)
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
    """Re-derive what ``_act`` computed from ``agent_id`` / ``role_id``.

    ``actors`` and ``execution_mode`` are derived at spec-build time, so an
    overlay that hands an action to a different agent has to refresh them.
    Leaving the base ``actors`` behind is not cosmetic: authorize matches the
    calling agent against that list, so the overlay's own producer gets
    ``ACTOR_MISMATCH`` on the paths the overlay just granted it.
    """
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
    for key in (
        "pipelines",
        "transitions",
        "phase_gates",
        "complete_gates",
        "terminal_ready_states",
        "phases",
        "states",
        "gates",
    ):
        if key in overlay:
            out[key] = overlay[key]
    # Per-action contract / gate / actor overrides (e.g. full-mode Output Contracts).
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
                for k, v in patch.items():
                    if v is None:
                        merged.pop(k, None)
                    else:
                        merged[k] = v
                _rederive_actor_fields(merged, patch)
                actions.append(merged)
            else:
                actions.append(dict(row))
        out["actions"] = actions
    out["_active_mode"] = chosen
    return out


def get_workflow(
    workflow_id: str,
    *,
    project_root: Any | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    wid = resolve_workflow_id(workflow_id)
    if wid not in WORKFLOWS:
        raise KeyError(f"Unknown workflow: {workflow_id}")
    meta = dict(WORKFLOWS[wid])
    if meta.get("mode_overlays"):
        resolved = mode or resolve_tg_mode(project_root)
        meta = _apply_mode_overlay(meta, resolved)
    return meta


def list_user_workflows() -> list[str]:
    return [
        wid
        for wid, meta in WORKFLOWS.items()
        if meta.get("slash") and not meta.get("reserved") and not meta.get("alias_of")
    ]


def state_ids(workflow_id: str) -> list[str]:
    meta = get_workflow(workflow_id)
    states = meta.get("states") or []
    if states:
        return [str(s["id"]) for s in states if isinstance(s, dict) and s.get("id")]
    return list(meta.get("phases") or [])


def label_zh_for(workflow_id: str, phase: str) -> str:
    meta = get_workflow(workflow_id)
    for s in meta.get("states") or []:
        if isinstance(s, dict) and s.get("id") == phase:
            return str(s.get("label_zh") or phase)
    return phase


def entry_state(workflow_id: str) -> str:
    meta = get_workflow(workflow_id)
    if meta.get("entry_state"):
        return str(meta["entry_state"])
    ids = state_ids(workflow_id)
    if not ids:
        raise ValueError(f"workflow {workflow_id} has no entry_state")
    return ids[0]


def allowed_transition(
    workflow_id: str,
    frm: str,
    to: str,
    *,
    kind: str = "forward",
    project_root: Any | None = None,
    mode: str | None = None,
) -> bool:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    for edge in meta.get("transitions") or []:
        if not isinstance(edge, dict):
            continue
        if edge.get("from") == frm and edge.get("to") == to and str(edge.get("kind") or "forward") == kind:
            return True
    return False


def rework_targets(
    workflow_id: str,
    frm: str,
    *,
    reason_code: str = "",
    project_root: Any | None = None,
    mode: str | None = None,
) -> list[str]:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    out: list[str] = []
    for edge in meta.get("transitions") or []:
        if not isinstance(edge, dict):
            continue
        if edge.get("from") != frm or str(edge.get("kind") or "") != "rework":
            continue
        codes = edge.get("reason_codes") or []
        if reason_code and codes and reason_code not in codes:
            continue
        to = str(edge.get("to") or "")
        if to and to not in out:
            out.append(to)
    return out


def actions_for_phase(
    workflow_id: str,
    phase: str,
    *,
    project_root: Any | None = None,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """Return actions explicitly bound to ``phase`` via action.phases."""
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    actions = [a for a in (meta.get("actions") or []) if isinstance(a, dict)]
    return [a for a in actions if phase in set(a.get("phases") or [])]


def phase_pipeline(
    workflow_id: str,
    phase: str,
    *,
    project_root: Any | None = None,
    mode: str | None = None,
) -> list[str]:
    """Ordered mandatory actions for a phase (Spec ``pipelines`` is the sole authority)."""
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    pipes = meta.get("pipelines") or {}
    raw = pipes.get(phase) if isinstance(pipes, dict) else None
    if isinstance(raw, list):
        return [str(a) for a in raw if str(a).strip()]
    return []


def action_by_id(
    workflow_id: str,
    action_id: str,
    *,
    project_root: Any | None = None,
    mode: str | None = None,
) -> dict[str, Any] | None:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    for a in meta.get("actions") or []:
        if isinstance(a, dict) and str(a.get("id") or "") == action_id:
            return dict(a)
    return None
