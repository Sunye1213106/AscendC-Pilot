"""SSOT consistency checks for Workflow Spec ↔ skills ↔ contracts ↔ agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PRECONDITION_CONTRACTS = frozenset({"kb-answer-v1"})
_HARDCODED_WORKFLOW_IN_PROMPT = re.compile(
    r"workflow_id:\s*`(uo-init|uo-update|tg-init|tg-plan|tg-solve|ce-review|uo-query)`"
)


def _repo_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _prompt_path(prompts: Path, tpid: str) -> Path:
    if "/" in tpid:
        dom, name = tpid.split("/", 1)
        return prompts / "tasks" / dom / f"{name}.md"
    return prompts / "tasks" / f"{tpid}.md"


def _registered_gate_ids(project_root: Path) -> set[str]:
    """Read gate names from source without executing any gate.

    Consistency validation is a static control-plane check.  Executing gates
    here used to make a bare checkout unexpectedly probe CANN/operator sources,
    which made Skill/Prompt validation environment-dependent and side-effectful.
    """
    root = _repo_root(project_root)
    gate_source = root / "pilot" / "ascendc_pilot" / "gates" / "__init__.py"
    if not gate_source.is_file():
        return set()
    text = gate_source.read_text(encoding="utf-8")
    marker = "mapping = {"
    start = text.find(marker)
    if start < 0:
        return set()
    tail = text[start + len(marker) :]
    end = tail.find("\n    }")
    block = tail if end < 0 else tail[:end]
    return set(re.findall(r'(?m)^\s*"([A-Za-z0-9_-]+)"\s*:', block))


def _effective_write_scopes(agent_id: str, action_id: str, repo_root: Path) -> list[str]:
    del action_id
    from ascendc_pilot.agents_registry import load_agent_meta

    meta = load_agent_meta(agent_id, str(repo_root))
    return [str(x) for x in (meta.get("write_scopes") or [])]


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
    """Validate producer staging + deterministic/semantic merge ownership."""
    del formal_contract_id
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
            errors.append(f"{wid}/{aid}: staging path {rel!r} outside {agent_id} write scopes")

    if merge_id == aid:
        return errors

    merge_action = actions_by_id.get(merge_id)
    if not merge_action:
        errors.append(f"{wid}/{aid}: merge_action_id {merge_id!r} not found in Spec actions")
        return errors

    if aid in pipeline_order and merge_id in pipeline_order:
        if pipeline_order.index(merge_id) <= pipeline_order.index(aid):
            errors.append(f"{wid}/{aid}: merge_action_id {merge_id!r} must appear after producer in pipeline")
    elif aid in pipeline_order and merge_id not in pipeline_order:
        errors.append(f"{wid}/{aid}: merge_action_id {merge_id!r} missing from pipeline order")

    merge_role = str(merge_action.get("role_id") or "")
    merge_mode = str(merge_action.get("execution_mode") or "").strip().lower()
    if merge_role not in {"deterministic_engine", "producer", "referee"}:
        errors.append(f"{wid}/{aid}: merge action {merge_id} role {merge_role!r} cannot write formal contract")
        return errors

    if merge_role == "deterministic_engine" or merge_mode == "deterministic":
        merge_scopes = [str(x) for x in (merge_action.get("allowed_write_paths") or [])]
        if not merge_scopes:
            errors.append(f"{wid}/{aid}: deterministic merge action {merge_id} has empty allowed_write_paths")
            return errors
        for rel in formal_paths:
            if not path_matches_scope(rel, merge_scopes):
                errors.append(
                    f"{wid}/{aid}: formal contract path {rel!r} not writable by deterministic merge action {merge_id}"
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
                f"{wid}/{aid}: formal contract path {rel!r} not writable by merge action {merge_id} agent {merge_agent}"
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
            if tpid:
                usage.setdefault(tpid, set()).add(wid)
    return {key: value for key, value in usage.items() if len(value) > 1}


def _check_output_contract_unknown() -> list[str]:
    from ascendc_pilot.actions.runtime import _check_output_contract

    errors: list[str] = []
    bogus = "definitely-not-a-registered-contract-ssot-v1"
    result = _check_output_contract(Path("."), bogus)
    if result.get("ok"):
        errors.append("_check_output_contract must not succeed for unknown contract ids")
    elif result.get("error") != "unknown_contract":
        errors.append(
            f"_check_output_contract expected error=unknown_contract, got {result.get('error')!r}"
        )
    empty = _check_output_contract(Path("."), "")
    if empty.get("ok") or empty.get("error") != "missing_contract_id":
        errors.append("_check_output_contract must fail closed on empty contract id")
    return errors


def check_all(
    repo_root: Path | None = None,
    *,
    workflows: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Run fail-closed, side-effect-free SSOT checks."""
    root = _repo_root(repo_root)
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
                        f"{wid}/{phase}: Spec pipelines mismatch preferred_pipeline(): {pipe!r} vs {preferred_pipeline(wid, phase)!r}"
                    )
                for action_id in pipe:
                    if action_id not in spec_action_set:
                        errors.append(f"{wid}/{phase}: pipeline action {action_id!r} not in Spec actions")

        all_gate_refs: set[str] = set()
        for gates in (meta.get("phase_gates") or {}).values():
            all_gate_refs.update(str(g) for g in gates or [])
        all_gate_refs.update(str(g) for g in meta.get("complete_gates") or [])
        all_gate_refs.update(str(g) for g in meta.get("gates") or [])
        for gate in sorted(all_gate_refs):
            if gate and gate not in gate_ids:
                errors.append(f"{wid}: unregistered gate id {gate!r}")

        actions_by_id = {str(a.get("id") or ""): a for a in actions if a.get("id")}
        pipeline_order: list[str] = []
        for phase in meta.get("phases") or []:
            for action_id in [str(x) for x in ((meta.get("pipelines") or {}).get(phase) or [])]:
                if action_id and action_id not in pipeline_order:
                    pipeline_order.append(action_id)
        for action_id in action_ids:
            if action_id and action_id not in pipeline_order:
                pipeline_order.append(action_id)

        for action in actions:
            aid = str(action.get("id") or "")
            role = str(action.get("role_id") or "")
            agent_id = str(action.get("agent_id") or "").strip()
            method_id = str(action.get("action_method_id") or "")
            prompt_id = str(action.get("task_prompt_id") or "").strip()
            contract_id = str(action.get("output_contract_id") or "").strip()

            if method_id:
                # action_method_id is a logical Spec key only (no skills/actions tree).
                if "/" not in method_id:
                    errors.append(f"{wid}/{aid}: invalid action_method_id {method_id!r}")
            elif role in {"producer", "referee", "readonly_analyst", "deterministic_engine"}:
                errors.append(f"{wid}/{aid}: missing action_method_id")

            if prompt_id:
                prompt_path = _prompt_path(prompts, prompt_id)
                if not prompt_path.is_file():
                    errors.append(f"{wid}/{aid}: missing task prompt {prompt_id}")
                else:
                    text = prompt_path.read_text(encoding="utf-8")
                    if prompt_id in shared_prompts:
                        match = _HARDCODED_WORKFLOW_IN_PROMPT.search(text)
                        if match:
                            errors.append(
                                f"{wid}/{aid}: shared prompt {prompt_id} hardcodes workflow_id {match.group(1)!r}; use `<WORKFLOW_ID>`"
                            )
                        if "workflow_id:" in text and "`<WORKFLOW_ID>`" not in text:
                            errors.append(
                                f"{wid}/{aid}: shared prompt {prompt_id} must use workflow_id: `<WORKFLOW_ID>`"
                            )
            elif role in {"producer", "referee", "readonly_analyst"}:
                errors.append(f"{wid}/{aid}: semantic action missing task_prompt_id")

            if role in {"producer", "referee", "readonly_analyst"}:
                if not agent_id:
                    errors.append(f"{wid}/{aid}: missing agent_id for role {role}")
                elif not (agents_dir / f"{agent_id}.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing agent file {agent_id}.yaml")
                if not contract_id:
                    errors.append(f"{wid}/{aid}: missing output_contract_id")

            if contract_id:
                paths = OUTPUT_CONTRACT_PATHS.get(contract_id)
                if paths is None:
                    errors.append(f"{wid}/{aid}: unknown output_contract_id {contract_id!r}")
                elif (
                    agent_id
                    and agent_id not in {"", "ascendc-pilot"}
                    and role in {"producer", "referee"}
                    and contract_id not in _PRECONDITION_CONTRACTS
                ):
                    scopes = _effective_write_scopes(agent_id, aid, root)
                    if not scopes:
                        errors.append(f"{wid}/{aid}: agent {agent_id} has empty write_scopes")
                    rel_paths = [str(rel).replace("\\", "/") for rel in paths or []]
                    rel_paths = [rel for rel in rel_paths if not rel.startswith("runs/")]
                    if rel_paths:
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
                                    formal_contract_id=contract_id,
                                    formal_paths=rel_paths,
                                    root=root,
                                )
                            )
                        else:
                            in_scope = [rel for rel in rel_paths if scopes and path_matches_scope(rel, scopes)]
                            if not in_scope:
                                errors.append(
                                    f"{wid}/{aid}: agent has no writable output path for contract {contract_id}"
                                )
                            else:
                                for rel in rel_paths:
                                    if scopes and not path_matches_scope(rel, scopes):
                                        errors.append(
                                            f"{wid}/{aid}: contract path {rel!r} outside {agent_id} write scopes (action {aid})"
                                        )

            for gate in action.get("gates") or []:
                gate_id = str(gate)
                if gate_id and gate_id not in gate_ids:
                    errors.append(f"{wid}/{aid}: action gate {gate_id!r} not registered")

    if workflows is None:
        from ascendc_pilot.run_resume import action_owned_artifacts

        registered_paths = {path for paths in OUTPUT_CONTRACT_PATHS.values() for path in paths}
        for wid, meta in wf_map.items():
            if meta.get("reserved") or not meta.get("slash"):
                continue
            owned = action_owned_artifacts(wid)
            for aid, rels in owned.items():
                action = next(
                    (a for a in (meta.get("actions") or []) if isinstance(a, dict) and a.get("id") == aid),
                    None,
                )
                contract_id = str((action or {}).get("output_contract_id") or "")
                contract_paths = set(OUTPUT_CONTRACT_PATHS.get(contract_id) or [])
                for rel in rels:
                    if rel not in registered_paths:
                        errors.append(f"{wid}/{aid}: resume owned path {rel!r} not in OUTPUT_CONTRACT_PATHS")
                    if contract_paths and rel not in contract_paths:
                        errors.append(f"{wid}/{aid}: resume owned path {rel!r} not in contract {contract_id} paths")

    return errors


def check_all_raise(repo_root: Path | None = None) -> None:
    errors = check_all(repo_root)
    if errors:
        raise ValueError("SSOT consistency failed:\n" + "\n".join(f"- {error}" for error in errors))
