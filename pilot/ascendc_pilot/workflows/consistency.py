"""SSOT consistency checks for Workflow Spec ↔ skills ↔ contracts ↔ agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PRECONDITION_CONTRACTS = frozenset({"kb-answer-v1", "uo-ready-v1"})
_HARDCODED_WORKFLOW_IN_PROMPT = re.compile(
    r"workflow_id:\s*`(uo-init|uo-update|tg-init|tg-plan|tg-solve|ce-review|uo-query)`"
)


def _repo_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _read_action_method(skills: Path, method_id: str) -> str:
    parts = method_id.split("/", 1)
    if len(parts) != 2:
        return ""
    d = skills / "actions" / parts[0] / parts[1]
    mp = d / "METHOD.md"
    return mp.read_text(encoding="utf-8") if mp.is_file() else ""


def _prompt_path(prompts: Path, tpid: str) -> Path:
    if "/" in tpid:
        dom, name = tpid.split("/", 1)
        return prompts / "tasks" / dom / f"{name}.md"
    return prompts / "tasks" / f"{tpid}.md"


def _load_action_yaml(skills: Path, method_id: str) -> dict[str, Any]:
    parts = method_id.split("/", 1)
    if len(parts) != 2:
        return {}
    p = skills / "actions" / parts[0] / parts[1] / "action.yaml"
    if not p.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _registered_gate_ids(project_root: Path) -> set[str]:
    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.workflows.specs import WORKFLOWS

    probe = project_root if project_root.is_dir() else Path.cwd()
    known: set[str] = set()
    unknown_msg = "unknown gate id:"
    candidates: set[str] = set()
    for meta in WORKFLOWS.values():
        for g in meta.get("gates") or []:
            candidates.add(str(g))
        for gs in (meta.get("phase_gates") or {}).values():
            for g in gs or []:
                candidates.add(str(g))
        for g in meta.get("complete_gates") or []:
            candidates.add(str(g))
        for a in meta.get("actions") or []:
            if isinstance(a, dict):
                for g in a.get("gates") or []:
                    candidates.add(str(g))
    for gid in sorted(candidates):
        res = run_named_gate(probe, gid)
        msg = str(res.get("message") or "")
        if unknown_msg in msg:
            continue
        known.add(gid)
    return known


def _effective_write_scopes(agent_id: str, action_id: str, repo_root: Path) -> list[str]:
    from ascendc_pilot.agents_registry import load_agent_meta

    meta = load_agent_meta(agent_id, str(repo_root))
    scopes = [str(x) for x in (meta.get("write_scopes") or [])]
    if agent_id == "uo-key-resolve":
        if action_id == "key_triage":
            return ["uo/ir/key_triage.yaml"]
        if action_id == "key_resolution":
            return ["uo/ir/input_derivable_patch.yaml", "uo/ir/key_shape_resolve/**"]
    return scopes


def _check_staged_output(
    *,
    wid: str,
    aid: str,
    action: dict[str, Any],
    actions_by_id: dict[str, dict[str, Any]],
    pipeline_order: list[str],
    agent_id: str,
    scopes: list[str],
    formal_contract_id: str,
    formal_paths: list[str],
    root: Path,
) -> list[str]:
    """Mode B: producer writes a staging contract; a later action writes formal output."""
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.agents_registry import path_matches_scope

    errors: list[str] = []
    staging_id = str(action.get("staging_contract_id") or "").strip()
    merge_id = str(action.get("merge_action_id") or "").strip()
    if not staging_id:
        errors.append(f"{wid}/{aid}: staged output_mode requires staging_contract_id")
        return errors
    if not merge_id:
        errors.append(f"{wid}/{aid}: staged output_mode requires merge_action_id")
        return errors

    staging_paths = OUTPUT_CONTRACT_PATHS.get(staging_id)
    if staging_paths is None:
        errors.append(f"{wid}/{aid}: unknown staging_contract_id {staging_id!r}")
        return errors
    staging_rels = [
        str(rel).replace("\\", "/")
        for rel in staging_paths
        if not str(rel).replace("\\", "/").startswith("runs/")
    ]
    if not staging_rels:
        errors.append(f"{wid}/{aid}: staging contract {staging_id} has no checkable paths")
        return errors
    for rel in staging_rels:
        if not scopes or not path_matches_scope(rel, scopes):
            errors.append(
                f"{wid}/{aid}: staging path {rel!r} outside {agent_id} write scopes"
            )

    if merge_id == aid:
        # Same-action finalize_engine merge: formal paths are not producer-written.
        return errors

    merge_action = actions_by_id.get(merge_id)
    if not merge_action:
        errors.append(f"{wid}/{aid}: merge_action_id {merge_id!r} not found in Spec actions")
        return errors

    if aid in pipeline_order and merge_id in pipeline_order:
        if pipeline_order.index(merge_id) <= pipeline_order.index(aid):
            errors.append(
                f"{wid}/{aid}: merge_action_id {merge_id!r} must appear after producer in pipeline"
            )
    elif aid in pipeline_order and merge_id not in pipeline_order:
        errors.append(f"{wid}/{aid}: merge_action_id {merge_id!r} missing from pipeline order")

    merge_role = str(merge_action.get("role_id") or "")
    merge_mode = str(merge_action.get("execution_mode") or "").strip().lower()
    if merge_role not in {"deterministic_engine", "producer", "referee"}:
        errors.append(
            f"{wid}/{aid}: merge action {merge_id} role {merge_role!r} cannot write formal contract"
        )
        return errors

    # Deterministic merge actions are engine calls, not model-selectable agents.
    # Validate their Action-owned write paths directly; requiring agent_id here
    # would force a fake deterministic subagent back into OpenCode/Cursor.
    if merge_role == "deterministic_engine" or merge_mode == "deterministic":
        merge_scopes = [str(x) for x in (merge_action.get("allowed_write_paths") or [])]
        if not merge_scopes:
            errors.append(
                f"{wid}/{aid}: deterministic merge action {merge_id} has empty allowed_write_paths"
            )
            return errors
        for rel in formal_paths:
            if not path_matches_scope(rel, merge_scopes):
                errors.append(
                    f"{wid}/{aid}: formal contract path {rel!r} not writable by "
                    f"deterministic merge action {merge_id}"
                )
        return errors

    merge_agent = str(merge_action.get("agent_id") or "").strip()
    if not merge_agent:
        errors.append(f"{wid}/{aid}: merge action {merge_id} missing agent_id")
        return errors
    merge_scopes = _effective_write_scopes(merge_agent, merge_id, root)
    if not merge_scopes:
        errors.append(f"{wid}/{aid}: merge agent {merge_agent} has empty write_scopes")
        return errors
    for rel in formal_paths:
        if not path_matches_scope(rel, merge_scopes):
            errors.append(
                f"{wid}/{aid}: formal contract path {rel!r} not writable by merge "
                f"action {merge_id} agent {merge_agent}"
            )
    return errors


def _collect_shared_task_prompts(workflows: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    usage: dict[str, set[str]] = {}
    for wid, meta in workflows.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            tpid = str(action.get("task_prompt_id") or "").strip()
            if not tpid:
                continue
            usage.setdefault(tpid, set()).add(wid)
    return {k: v for k, v in usage.items() if len(v) > 1}


def _check_output_contract_unknown() -> list[str]:
    from ascendc_pilot.actions.runtime import _check_output_contract

    errors: list[str] = []
    bogus = "definitely-not-a-registered-contract-ssot-v1"
    r = _check_output_contract(Path("."), bogus)
    if r.get("ok"):
        errors.append("_check_output_contract must not succeed for unknown contract ids")
    elif r.get("error") != "unknown_contract":
        errors.append(
            f"_check_output_contract expected error=unknown_contract, got {r.get('error')!r}"
        )
    r2 = _check_output_contract(Path("."), "")
    if r2.get("ok") or r2.get("error") != "missing_contract_id":
        errors.append("_check_output_contract must fail closed on empty contract id")
    return errors


def check_all(
    repo_root: Path | None = None,
    *,
    workflows: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Run fail-closed SSOT checks; return human-readable error strings."""
    root = _repo_root(repo_root)
    skills = root / "skills"
    prompts = root / "prompts"
    agents_dir = root / "agents"

    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.agents_registry import path_matches_scope
    from ascendc_pilot.workflows.pipeline import preferred_pipeline
    from ascendc_pilot.workflows.specs import WORKFLOWS as DEFAULT_WORKFLOWS

    wf_map = workflows if workflows is not None else DEFAULT_WORKFLOWS
    shared_prompts = _collect_shared_task_prompts(wf_map)
    gate_ids = _registered_gate_ids(root)
    errors: list[str] = []
    errors.extend(_check_output_contract_unknown())

    for wid, meta in wf_map.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue

        actions = [a for a in (meta.get("actions") or []) if isinstance(a, dict)]
        action_ids = [str(a.get("id") or "") for a in actions]
        seen: set[str] = set()
        for aid in action_ids:
            if not aid:
                errors.append(f"{wid}: action missing id")
                continue
            if not _ACTION_ID_RE.match(aid):
                errors.append(f"{wid}/{aid}: invalid action_id (use snake_case)")
            if aid in seen:
                errors.append(f"{wid}/{aid}: duplicate action_id")
            seen.add(aid)

        spec_action_set = set(action_ids)
        pipes = meta.get("pipelines") or {}
        if wid in {"uo-init", "uo-update"}:
            for phase in meta.get("phases") or []:
                if phase not in pipes:
                    errors.append(f"{wid}: phase {phase!r} missing pipelines entry (required)")
                pipe = [str(x) for x in (pipes.get(phase) or []) if str(x).strip()]
                if wid == "uo-init" and phase in {"extract", "resolve"} and not pipe:
                    errors.append(f"{wid}: phase {phase!r} must have non-empty pipeline")
                if wid == "uo-update" and phase == "resolve" and not pipe:
                    errors.append(f"{wid}: resolve phase must have non-empty pipeline")
                if workflows is None and pipe != preferred_pipeline(wid, phase):
                    errors.append(
                        f"{wid}/{phase}: Spec pipelines mismatch preferred_pipeline(): "
                        f"{pipe!r} vs {preferred_pipeline(wid, phase)!r}"
                    )
                for action_id in pipe:
                    if action_id not in spec_action_set:
                        errors.append(f"{wid}/{phase}: pipeline action {action_id!r} not in Spec actions")

        all_gate_refs: set[str] = set()
        for gs in (meta.get("phase_gates") or {}).values():
            all_gate_refs.update(str(g) for g in gs or [])
        all_gate_refs.update(str(g) for g in meta.get("complete_gates") or [])
        all_gate_refs.update(str(g) for g in meta.get("gates") or [])
        for g in sorted(all_gate_refs):
            if g and g not in gate_ids:
                errors.append(f"{wid}: unregistered gate id {g!r}")

        actions_by_id = {str(a.get("id") or ""): a for a in actions if a.get("id")}
        pipeline_order: list[str] = []
        for phase in meta.get("phases") or []:
            for action_id in [str(x) for x in ((meta.get("pipelines") or {}).get(phase) or [])]:
                if action_id and action_id not in pipeline_order:
                    pipeline_order.append(action_id)
        # Fallback: Spec action declaration order when pipelines sparse (e.g. tg-init)
        for action_id in action_ids:
            if action_id and action_id not in pipeline_order:
                pipeline_order.append(action_id)

        for action in actions:
            aid = str(action.get("id") or "")
            role = str(action.get("role_id") or "")
            agent_id = str(action.get("agent_id") or "").strip()
            mid = str(action.get("action_method_id") or "")
            tpid = str(action.get("task_prompt_id") or "").strip()
            cid = str(action.get("output_contract_id") or "").strip()

            if mid:
                method = _read_action_method(skills, mid)
                if not method.strip():
                    errors.append(f"{wid}/{aid}: missing METHOD for {mid}")
            elif role in {"producer", "referee", "readonly_analyst", "deterministic_engine"}:
                errors.append(f"{wid}/{aid}: missing action_method_id")

            if tpid:
                pp = _prompt_path(prompts, tpid)
                if not pp.is_file():
                    errors.append(f"{wid}/{aid}: missing task prompt {tpid}")
                else:
                    text = pp.read_text(encoding="utf-8")
                    if tpid in shared_prompts:
                        m = _HARDCODED_WORKFLOW_IN_PROMPT.search(text)
                        if m:
                            errors.append(
                                f"{wid}/{aid}: shared prompt {tpid} hardcodes workflow_id "
                                f"{m.group(1)!r}; use `<WORKFLOW_ID>`"
                            )
                        if "workflow_id:" in text and "`<WORKFLOW_ID>`" not in text:
                            errors.append(
                                f"{wid}/{aid}: shared prompt {tpid} must use workflow_id: `<WORKFLOW_ID>`"
                            )
            elif role in {"producer", "referee", "readonly_analyst"}:
                errors.append(f"{wid}/{aid}: semantic action missing task_prompt_id")

            if role in {"producer", "referee", "readonly_analyst"}:
                if not agent_id:
                    errors.append(f"{wid}/{aid}: missing agent_id for role {role}")
                elif not (agents_dir / f"{agent_id}.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing agent file {agent_id}.yaml")
                if not cid:
                    errors.append(f"{wid}/{aid}: missing output_contract_id")

            if cid:
                paths = OUTPUT_CONTRACT_PATHS.get(cid)
                if paths is None:
                    errors.append(f"{wid}/{aid}: unknown output_contract_id {cid!r}")
                elif (
                    agent_id
                    and agent_id not in {"", "ascendc-pilot"}
                    and role in {"producer", "referee"}
                    and cid not in _PRECONDITION_CONTRACTS
                ):
                    scopes = _effective_write_scopes(agent_id, aid, root)
                    if not scopes:
                        errors.append(f"{wid}/{aid}: agent {agent_id} has empty write_scopes")
                    rel_paths = [str(rel).replace("\\", "/") for rel in paths or []]
                    rel_paths = [r for r in rel_paths if not r.startswith("runs/")]
                    if not rel_paths:
                        continue
                    output_mode = str(action.get("output_mode") or "direct").strip().lower()
                    if output_mode == "staged":
                        errors.extend(
                            _check_staged_output(
                                wid=wid,
                                aid=aid,
                                action=action,
                                actions_by_id=actions_by_id,
                                pipeline_order=pipeline_order,
                                agent_id=agent_id,
                                scopes=scopes,
                                formal_contract_id=cid,
                                formal_paths=rel_paths,
                                root=root,
                            )
                        )
                    else:
                        in_scope = [r for r in rel_paths if scopes and path_matches_scope(r, scopes)]
                        if not in_scope:
                            errors.append(
                                f"{wid}/{aid}: agent has no writable output path for contract {cid}"
                            )
                        else:
                            for rel_s in rel_paths:
                                if scopes and not path_matches_scope(rel_s, scopes):
                                    errors.append(
                                        f"{wid}/{aid}: contract path {rel_s!r} outside "
                                        f"{agent_id} write scopes (action {aid})"
                                    )

            for g in action.get("gates") or []:
                gs = str(g)
                if gs and gs not in gate_ids:
                    errors.append(f"{wid}/{aid}: action gate {gs!r} not registered")

            if mid:
                ay = _load_action_yaml(skills, mid)
                if ay:
                    ay_cid = str(ay.get("output_contract_id") or "").strip()
                    if cid and ay_cid and ay_cid != cid:
                        errors.append(
                            f"{wid}/{aid}: action.yaml contract {ay_cid!r} != Spec {cid!r}"
                        )
                    ay_agent = str(ay.get("agent_id") or "").strip()
                    if agent_id and ay_agent and ay_agent != agent_id:
                        errors.append(
                            f"{wid}/{aid}: action.yaml agent {ay_agent!r} != Spec {agent_id!r}"
                        )

    if workflows is None:
        from ascendc_pilot.run_resume import action_owned_artifacts

        registered_paths = {p for ps in OUTPUT_CONTRACT_PATHS.values() for p in ps}
        for wid, meta in wf_map.items():
            if meta.get("reserved") or not meta.get("slash"):
                continue
            owned = action_owned_artifacts(wid)
            for aid, rels in owned.items():
                act = next(
                    (a for a in (meta.get("actions") or []) if isinstance(a, dict) and a.get("id") == aid),
                    None,
                )
                cid = str((act or {}).get("output_contract_id") or "")
                contract_paths = set(OUTPUT_CONTRACT_PATHS.get(cid) or [])
                for rel in rels:
                    if rel not in registered_paths:
                        errors.append(
                            f"{wid}/{aid}: resume owned path {rel!r} not in OUTPUT_CONTRACT_PATHS"
                        )
                    if contract_paths and rel not in contract_paths:
                        errors.append(
                            f"{wid}/{aid}: resume owned path {rel!r} not in contract {cid} paths"
                        )

    return errors


def check_all_raise(repo_root: Path | None = None) -> None:
    errs = check_all(repo_root)
    if errs:
        raise ValueError("SSOT consistency failed:\n" + "\n".join(f"- {e}" for e in errs))
