"""SSOT consistency checks for Workflow Spec ↔ skills ↔ contracts ↔ agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Contracts that only assert pre-existing readiness (no producer write_scopes).
# kb-answer-v1 is a real Action payload (runs/.../answer.yaml), not a precondition.
_PRECONDITION_CONTRACTS = frozenset()
_HARDCODED_WORKFLOW_IN_PROMPT = re.compile(
    r"workflow_id:\s*`(uo-init|uo-update|tg-init|tg-plan|tg-solve|ce-review|uo-query)`"
)

# KEY / confidence gates used by CLI ``run_key_gates`` (not WorkflowSpec phase gates).
KEY_GATE_ALLOWLIST = frozenset(
    {
        "key_triage_required",
        "key_resolve_receipt",
        "empty_only_producer",
        "key_report_quality",
        "confidence_closed_high",
        "confidence_reason_review",
        "kb_review_consistency",
        "confidence_gate",
        "kb_review",
    }
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
    # Only top-level mapping keys bound to lambdas (ignore nested dict literals).
    return set(re.findall(r'(?m)^        "([A-Za-z0-9_-]+)"\s*:\s*lambda', block))


def _collect_spec_gate_refs(workflows: dict[str, dict[str, Any]]) -> set[str]:
    from ascendc_pilot.workflows.specs import STATIC_OBLIGATION_GATE_MAP

    refs: set[str] = set(STATIC_OBLIGATION_GATE_MAP.values())

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in {"gates", "complete_gates", "complete_gates_diff_only"} and isinstance(
                    value, list
                ):
                    refs.update(str(g) for g in value if str(g).strip())
                elif key == "phase_gates" and isinstance(value, dict):
                    for gates in value.values():
                        if isinstance(gates, list):
                            refs.update(str(g) for g in gates if str(g).strip())
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(workflows)
    return {g for g in refs if g}


def _check_gate_registry_closure(
    *,
    workflows: dict[str, dict[str, Any]],
    gate_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    spec_refs = _collect_spec_gate_refs(workflows)
    for gate in sorted(spec_refs):
        if gate not in gate_ids:
            errors.append(f"unregistered Spec/obligation gate id {gate!r}")
    for gate in sorted(gate_ids):
        if gate in spec_refs or gate in KEY_GATE_ALLOWLIST:
            continue
        errors.append(
            f"unreferenced workflow gate {gate!r} "
            "(not in Spec/obligation map; add to Spec or KEY_GATE_ALLOWLIST)"
        )
    return errors


def _check_no_unreferenced_actions(
    *,
    workflows: dict[str, dict[str, Any]],
) -> list[str]:
    from ascendc_pilot.actions.engines import ENGINE_REGISTRY, OUTPUT_CONTRACT_PATHS

    errors: list[str] = []
    spec_actions: set[tuple[str, str]] = set()
    used_contracts: set[str] = set()
    for wid, meta in workflows.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "").strip()
            if aid:
                spec_actions.add((wid, aid))
            for field in ("output_contract_id", "staging_contract_id"):
                cid = str(action.get(field) or "").strip()
                if cid:
                    used_contracts.add(cid)

    for key in sorted(set(ENGINE_REGISTRY) - spec_actions):
        errors.append(f"orphan ENGINE_REGISTRY entry: {key[0]}/{key[1]}")
    for wid, aid in sorted(spec_actions):
        action = next(
            (
                a
                for a in (workflows[wid].get("actions") or [])
                if isinstance(a, dict) and str(a.get("id") or "") == aid
            ),
            None,
        )
        if not action:
            continue
        mode = str(action.get("execution_mode") or "")
        if mode == "deterministic" and (wid, aid) not in ENGINE_REGISTRY:
            errors.append(f"{wid}/{aid}: deterministic action missing ENGINE_REGISTRY entry")

    for cid in sorted(set(OUTPUT_CONTRACT_PATHS) - used_contracts):
        errors.append(f"orphan OUTPUT_CONTRACT_PATHS entry: {cid}")
    return errors


def _check_architecture_start_requirements(
    *,
    workflows: dict[str, dict[str, Any]] | None,
    root: Path,
) -> list[str]:
    """Spec start modes: uo-init/update choose arch*; consumers inherit from .uo."""
    del workflows
    errors: list[str] = []
    from ascendc_pilot.workflows import (
        workflow_requires_architecture,
        workflow_requires_uo_product,
        workflows_needing_architecture,
        workflows_needing_uo_product,
    )

    from ascendc_pilot.workflows.model_checker import MATRIX_WORKFLOWS

    if not workflow_requires_architecture("uo-update"):
        errors.append("workflow_requires_architecture('uo-update') must be True")
    if not workflow_requires_architecture("uo-init"):
        errors.append("workflow_requires_architecture('uo-init') must be True")

    arch_needed = set(workflows_needing_architecture())
    uo_needed = set(workflows_needing_uo_product())
    matrix = set(MATRIX_WORKFLOWS)
    if arch_needed | uo_needed != matrix:
        errors.append(
            "workflows_needing_architecture() | workflows_needing_uo_product() "
            "must equal MATRIX_WORKFLOWS; "
            f"missing={sorted(matrix - (arch_needed | uo_needed))} "
            f"extra={sorted((arch_needed | uo_needed) - matrix)}"
        )
    if arch_needed & uo_needed:
        errors.append(
            "architecture builders and uo-product consumers must be disjoint; "
            f"overlap={sorted(arch_needed & uo_needed)}"
        )
    for wid in ("uo-init", "uo-update"):
        if wid not in arch_needed:
            errors.append(f"{wid} must require architecture (tree arch*)")
        if workflow_requires_uo_product(wid):
            errors.append(f"{wid} must not require_uo_product")
    for wid in (
        "tg-init",
        "tg-plan",
        "tg-solve",
        "ce-review",
        "ce-intent",
        "ce-impact",
        "ce-verify",
        "uo-query",
        "uo-investigate",
    ):
        if wid not in uo_needed:
            errors.append(f"{wid} must require_uo_product (arch from .uo)")
        if workflow_requires_architecture(wid):
            errors.append(f"{wid} must not require_architecture (inherit from .uo)")

    inv = root / "pilot" / "policies" / "invariants" / "control-invariants.md"
    if inv.is_file():
        text_inv = inv.read_text(encoding="utf-8")
        item11 = ""
        for line in text_inv.splitlines():
            if line.startswith("11."):
                item11 = line
                break
        if "uo-update" not in item11:
            errors.append("control-invariants.md item 11 must mention uo-update")
        if ".uo" not in item11:
            errors.append(
                "control-invariants.md item 11 must mention .uo / UO-first for TG/CE consumers"
            )
    else:
        errors.append("missing pilot/policies/invariants/control-invariants.md")

    agent = root / "agents" / "ascendc-pilot.yaml"
    if agent.is_file():
        desc = agent.read_text(encoding="utf-8")
        if "必须带齐" in desc or (
            "--architecture" in desc and "uo-update" in desc and "tg-init" in desc
        ):
            errors.append(
                "agents/ascendc-pilot.yaml must not hardcode architecture start requirement lists"
            )
        if "acp" not in desc.lower():
            errors.append("agents/ascendc-pilot.yaml description must mention acp")
    else:
        errors.append("missing agents/ascendc-pilot.yaml")

    try:
        import sys

        scripts = root / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from compose_runtime import _start_requirements_line  # type: ignore

        line = _start_requirements_line(root)
        if "uo-update" not in line:
            errors.append("compose _start_requirements_line projection missing uo-update")
        if "uo-init" not in line or ".uo" not in line:
            errors.append(
                "compose _start_requirements_line must describe UO-first for TG/CE consumers"
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"compose projection helper check failed: {exc}")
    return errors


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
    # Staged producers are allowed to write only under runs/; those paths still
    # have to sit inside the producer write_scopes.
    check_staging = staging_rels or [str(rel).replace("\\", "/") for rel in staging_paths]
    if not check_staging:
        errors.append(f"{wid}/{aid}: staging contract {staging_id} has no checkable paths")
        return errors
    for rel in check_staging:
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


def _check_artifact_dag(
    *,
    workflows: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Producer/consumer DAG: every gate/explicit consume must have a producer."""
    from ascendc_pilot.workflows.artifact_dag import check_artifact_dag

    return list(check_artifact_dag(workflows))


def _check_workflow_model(
    *,
    workflows: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Phase/transition/obligation model checker for the user-facing workflow matrix."""
    from ascendc_pilot.workflows.model_checker import check_all_models

    return list(check_all_models(workflows))


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
    if workflows is None:
        # Full-repo closure: Spec ↔ registry ↔ ENGINE/OUTPUT ↔ start requirements.
        errors.extend(_check_gate_registry_closure(workflows=wf_map, gate_ids=gate_ids))
        errors.extend(_check_no_unreferenced_actions(workflows=wf_map))
        errors.extend(_check_architecture_start_requirements(workflows=wf_map, root=root))
        errors.extend(_check_artifact_dag())
        errors.extend(_check_workflow_model())
    else:
        errors.extend(_check_artifact_dag(workflows=wf_map))
        errors.extend(_check_workflow_model(workflows=wf_map))

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
        terminal = {str(x) for x in (meta.get("terminal_ready_states") or [])}
        if isinstance(pipes, dict):
            for phase in meta.get("phases") or []:
                if phase not in pipes:
                    errors.append(f"{wid}: phase {phase!r} missing pipelines entry (required)")
                pipe = [str(x) for x in (pipes.get(phase) or []) if str(x).strip()]
                if not pipe and str(phase) not in terminal:
                    errors.append(f"{wid}: phase {phase!r} must have non-empty pipeline")
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
                if "/" not in method_id:
                    errors.append(f"{wid}/{aid}: invalid action_method_id {method_id!r}")
            elif role in {"producer", "referee", "readonly_analyst", "deterministic_engine"}:
                errors.append(f"{wid}/{aid}: missing action_method_id")
            mode = str(action.get("execution_mode") or "")
            if mode == "subagent" and prompt_id:
                skill, _, cap = method_id.partition("/")
                mp = root / "skills" / skill / "capabilities" / cap / "METHOD.md"
                if not method_id or "/" not in method_id or not mp.is_file() or not mp.read_text(encoding="utf-8").strip():
                    errors.append(f"{wid}/{aid}: missing METHOD.md for {method_id!r}")

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
                    and role in {"producer", "referee", "readonly_analyst"}
                    and contract_id not in _PRECONDITION_CONTRACTS
                ):
                    scopes = _effective_write_scopes(agent_id, aid, root)
                    output_mode = str(action.get("output_mode") or "direct").strip().lower()
                    if output_mode == "return_value":
                        # Explorer may have write_scopes: []; Runtime materializes.
                        if role in {"producer", "referee"} and not scopes:
                            errors.append(f"{wid}/{aid}: agent {agent_id} has empty write_scopes")
                        # readonly_analyst + return_value: empty scopes are intentional.
                    else:
                        if not scopes:
                            errors.append(f"{wid}/{aid}: agent {agent_id} has empty write_scopes")
                        rel_paths = [str(rel).replace("\\", "/") for rel in paths or []]
                        # Historical: formal IR checks ignore runs/**. Action-local
                        # contracts (kb-answer-v1) must still be in agent scopes.
                        formal_paths = [rel for rel in rel_paths if not rel.startswith("runs/")]
                        local_paths = [rel for rel in rel_paths if rel.startswith("runs/")]
                        if formal_paths:
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
                                        formal_paths=formal_paths,
                                        root=root,
                                    )
                                )
                            else:
                                in_scope = [
                                    rel
                                    for rel in formal_paths
                                    if scopes and path_matches_scope(rel, scopes)
                                ]
                                if not in_scope:
                                    errors.append(
                                        f"{wid}/{aid}: agent has no writable output path for contract {contract_id}"
                                    )
                                else:
                                    for rel in formal_paths:
                                        if scopes and not path_matches_scope(rel, scopes):
                                            errors.append(
                                                f"{wid}/{aid}: contract path {rel!r} outside {agent_id} write scopes (action {aid})"
                                            )
                        for rel in local_paths:
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
