"""SSOT consistency checks for Workflow Spec ↔ skills ↔ contracts ↔ agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Contracts that only assert pre-existing readiness (no producer write_scopes).
# Dialogue contracts such as kb-answer-v1 / code-review-v1 are registered with
# empty OUTPUT_CONTRACT_PATHS and are not listed here.
_PRECONDITION_CONTRACTS = frozenset(
    {
        "plan-precheck-v1",
        "solve-precheck-v1",
        "ce-kb-check-v1",
        "intent-grill-v1",
        "ce-plan-grilled-v1",
        "ce-plan-confirmed-v1",
        "apply-gate-v1",
        "apply-patch-guard-v1",
        "apply-plan-revise-check-v1",
        "codemap-refresh-v1",
        "apply-report-v1",
        "review-capture-v1",
        "code-review-v1",
        "review-report-v1",
    }
)
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


def action_task_prompt_ids(action: dict[str, Any]) -> list[str]:
    """Action-level prompt plus optional ``fanout_axes[].task_prompt_id``."""
    ids: list[str] = []
    seen: set[str] = set()
    tpid = str(action.get("task_prompt_id") or "").strip()
    if tpid:
        ids.append(tpid)
        seen.add(tpid)
    for axis in action.get("fanout_axes") or []:
        if not isinstance(axis, dict):
            continue
        axis_tpid = str(axis.get("task_prompt_id") or "").strip()
        if axis_tpid and axis_tpid not in seen:
            ids.append(axis_tpid)
            seen.add(axis_tpid)
    return ids


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
        if gate in spec_refs:
            continue
        errors.append(
            f"unreferenced workflow gate {gate!r} "
            "(not in Spec/obligation map; add to Spec)"
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
        if meta.get("alias_of"):
            continue
        if not (meta.get("actions") or []):
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
        "ce-plan",
        "ce-apply",
        "handoff",
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
        item6 = ""
        for line in text_inv.splitlines():
            if line.startswith("6."):
                item6 = line
                break
        if "uo-update" not in item6:
            errors.append("control-invariants.md item 6 must mention uo-update")
        if ".uo" not in item6:
            errors.append(
                "control-invariants.md item 6 must mention .uo / UO-first for TG/CE consumers"
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
        if "pilot_run" not in desc.lower() or "pilot_cli" not in desc.lower():
            errors.append("agents/ascendc-pilot.yaml description must mention pilot_run and pilot_cli")
        if re.search(r"\bacp\b", desc):
            errors.append("agents/ascendc-pilot.yaml must not mention acp")
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
            for tpid in action_task_prompt_ids(action):
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
        from ascendc_pilot.workflows.artifact_dag import check_artifact_usage

        errors.extend(check_artifact_usage(root))
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
        for action in actions:
            if isinstance(action, dict):
                all_gate_refs.update(str(g) for g in (action.get("pre_gates") or []))
                all_gate_refs.update(str(g) for g in (action.get("post_gates") or []))
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
            method_id = str(action.get("skill_id") or action.get("action_method_id") or "").strip()
            prompt_id = str(action.get("task_prompt_id") or "").strip()
            prompt_ids = action_task_prompt_ids(action)
            contract_id = str(action.get("output_contract_id") or "").strip()
            mode = str(action.get("execution_mode") or "")

            if method_id and "/" in method_id:
                method_id = method_id.rsplit("/", 1)[-1].strip()
            mp = root / "skills" / method_id / "SKILL.md" if method_id else None
            if mode == "subagent" and prompt_id:
                if not method_id or mp is None or not mp.is_file() or not mp.read_text(encoding="utf-8").strip():
                    errors.append(f"{wid}/{aid}: missing SKILL.md for {method_id!r}")
            elif mode in {"deterministic", "primary_interactive"} and method_id:
                errors.append(f"{wid}/{aid}: {mode} Action must omit skill_id")
            elif mode == "primary_review" and prompt_id:
                if not method_id or mp is None or not mp.is_file() or not mp.read_text(encoding="utf-8").strip():
                    errors.append(f"{wid}/{aid}: missing SKILL.md for {method_id!r}")

            if prompt_ids:
                for pid in prompt_ids:
                    prompt_path = _prompt_path(prompts, pid)
                    if not prompt_path.is_file():
                        errors.append(f"{wid}/{aid}: missing task prompt {pid}")
                        continue
                    text = prompt_path.read_text(encoding="utf-8")
                    if pid in shared_prompts:
                        match = _HARDCODED_WORKFLOW_IN_PROMPT.search(text)
                        if match:
                            errors.append(
                                f"{wid}/{aid}: shared prompt {pid} hardcodes workflow_id {match.group(1)!r}; use `<WORKFLOW_ID>`"
                            )
                        if "workflow_id:" in text and "`<WORKFLOW_ID>`" not in text:
                            errors.append(
                                f"{wid}/{aid}: shared prompt {pid} must use workflow_id: `<WORKFLOW_ID>`"
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
                else:
                    omode = str(action.get("output_mode") or "direct").strip().lower()
                    if (
                        omode not in {"return_value", "return"}
                        and mode != "primary_interactive"
                        and contract_id not in _PRECONDITION_CONTRACTS
                    ):
                        check_id = (
                            str(action.get("staging_contract_id") or contract_id)
                            if omode == "staged"
                            else contract_id
                        )
                        check_paths = list(OUTPUT_CONTRACT_PATHS.get(check_id) or paths or [])
                        writes = [
                            str(p).replace("\\", "/")
                            for p in (action.get("allowed_write_paths") or [])
                        ]
                        for rel in check_paths:
                            norm = str(rel).replace("\\", "/")
                            if not writes or not path_matches_scope(norm, writes):
                                errors.append(
                                    f"{wid}/{aid}: contract path {norm!r} not covered by "
                                    f"allowed_write_paths={writes}"
                                )
                if (
                    paths is not None
                    and agent_id
                    and agent_id not in {"", "ascendc-pilot"}
                    and role in {
                        "producer",
                        "referee",
                        "readonly_analyst",
                        "readonly_reviewer",
                    }
                    and contract_id not in _PRECONDITION_CONTRACTS
                ):
                    scopes = _effective_write_scopes(agent_id, aid, root)
                    output_mode = str(action.get("output_mode") or "direct").strip().lower()
                    if output_mode == "return_value":
                        # Dialogue contracts: Explorer / reviewer write_scopes may be empty.
                        if role in {"producer", "referee"} and not scopes:
                            errors.append(f"{wid}/{aid}: agent {agent_id} has empty write_scopes")
                        # readonly_analyst / readonly_reviewer + return_value: empty scopes are intentional.
                    else:
                        if not scopes:
                            errors.append(f"{wid}/{aid}: agent {agent_id} has empty write_scopes")
                        check_id = (
                            str(action.get("staging_contract_id") or contract_id)
                            if output_mode == "staged"
                            else contract_id
                        )
                        check_paths = list(OUTPUT_CONTRACT_PATHS.get(check_id) or paths or [])
                        rel_paths = [str(rel).replace("\\", "/") for rel in check_paths]
                        # Historical: formal IR checks ignore runs/**. Action-local
                        # contracts (kb-answer-v1) must still be in agent scopes.
                        formal_paths = [rel for rel in rel_paths if not rel.startswith("runs/")]
                        local_paths = [rel for rel in rel_paths if rel.startswith("runs/")]
                        if output_mode == "staged":
                            canonical_formal = [
                                str(rel).replace("\\", "/")
                                for rel in (paths or [])
                                if not str(rel).replace("\\", "/").startswith("runs/")
                            ]
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
                                    formal_paths=canonical_formal,
                                    root=root,
                                )
                            )
                        elif formal_paths:
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

            for gate in list(action.get("pre_gates") or []) + list(action.get("post_gates") or []):
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

        errors.extend(_check_method_skill_docs_ssot(root, wf_map))

    return errors


def _check_method_skill_docs_ssot(root: Path, wf_map: dict[str, dict[str, Any]]) -> list[str]:
    """Action skill files and module docs stay aligned."""
    errors: list[str] = []
    for wid, meta in wf_map.items():
        if meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            mid = str(action.get("skill_id") or action.get("action_method_id") or "").strip()
            if not mid:
                continue
            if "/" in mid:
                mid = mid.rsplit("/", 1)[-1]
            skill = root / "skills" / mid / "SKILL.md"
            if not skill.is_file():
                errors.append(f"{wid}/{action.get('id')}: missing skills/{mid}/SKILL.md")
    docs = {
        "docs/modules/uo.md": ("uo-init", "uo-query"),
        "docs/modules/tg.md": ("tg-init", "tg-plan", "tg-solve"),
        "docs/modules/ce.md": ("ce-plan", "ce-apply", "ce-review"),
    }
    for rel, needles in docs.items():
        path = root / rel
        if not path.is_file():
            errors.append(f"missing {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text and f"/{needle}" not in text:
                errors.append(f"{rel} must mention {needle}")
    apply_skill = root / "skills" / "ce-apply" / "SKILL.md"
    if apply_skill.is_file():
        text = apply_skill.read_text(encoding="utf-8")
        if "不查图" not in text:
            errors.append("ce-apply SKILL must say 不查图")
    try:
        from ascendc_pilot.harness.intent import validate_intent_staging
        from ascendc_pilot.planning.task_plan import plan_for
        from ascendc_pilot.router import route
        from ascendc_pilot.workflows import WORKFLOWS, list_user_workflows

        hit = route("审 https://gitcode.com/cann/ops-transformer/pulls/1")
        if hit.get("ok") and hit.get("method") in {"slash", "workflow_id", "goal_router"}:
            errors.append("NL PR URL must not be script-routed to a workflow")
        if hit.get("workflow_id") == "ce-review":
            errors.append("NL PR URL must not map to ce-review")
        if str(hit.get("error") or "") != "primary_agent_route_required":
            errors.append("unmatched NL must return primary_agent_route_required")
        for slash_id in ("uo-init", "tg-plan", "ce-review", "ce-plan", "tg-solve"):
            if slash_id not in list_user_workflows():
                errors.append(f"user slash workflow {slash_id} missing from list_user_workflows()")
        if "goal-impact" in WORKFLOWS:
            errors.append("reserved goal-impact must not remain as a live workflow")
        orch = root / "skills" / "workflow-orchestration"
        if orch.exists():
            errors.append("skills/workflow-orchestration/ must not be resurrected")
        checked = validate_intent_staging(
            {
                "objective_zh": "为这个 PR 生成针对性测试用例",
                "source": {
                    "kind": "pull_request",
                    "url": "https://gitcode.com/cann/ops-transformer/pulls/1",
                },
                "needed_workflows": [
                    "tg-plan",
                    "tg-solve",
                ],
            }
        )
        if not checked.get("ok"):
            errors.append(f"intent staging contract failed: {checked}")
        planned = plan_for(checked.get("intent") or {}, {"has_uo": False, "uo_stale": False})
        wids = [
            str(s.get("workflow_id") or s.get("id"))
            for s in (planned.get("steps") or [])
            if isinstance(s, dict)
        ]
        if "ce-review" in wids:
            errors.append("PR + tg-plan/tg-solve must not invent ce-review")
        if "uo-init" in wids:
            errors.append("plan_for must not invent uo-init")
        if "goal-impact" in wids:
            errors.append("plan_for must not insert goal-impact")
        if "tg-plan" not in wids or "tg-solve" not in wids:
            errors.append("listed tg-plan/tg-solve must remain in the recorded plan")
        ordered = plan_for(
            {
                "needed_workflows": ["ce-review", "tg-init", "tg-plan"],
                "source": {"kind": "none"},
            }
        )
        ordered_wids = [
            str(s.get("workflow_id") or s.get("id"))
            for s in (ordered.get("steps") or [])
            if isinstance(s, dict)
        ]
        if "tg-init" not in ordered_wids or "ce-review" not in ordered_wids:
            errors.append("listed tg-init/ce-review must remain in the recorded plan")
        elif ordered_wids.index("tg-init") > ordered_wids.index("ce-review"):
            errors.append("tg-init must precede ce-review")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"task harness SSOT check failed: {exc}")
    return errors


def check_all_raise(repo_root: Path | None = None) -> None:
    errors = check_all(repo_root)
    if errors:
        raise ValueError("SSOT consistency failed:\n" + "\n".join(f"- {error}" for error in errors))
