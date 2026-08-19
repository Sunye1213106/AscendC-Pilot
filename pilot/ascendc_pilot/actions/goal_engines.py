# -*- coding: utf-8 -*-
"""Deterministic Harness engines: workspace pin + Goal/TaskPlan record. No Intent LLM."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

EngineFn = Callable[[Path, dict[str, Any]], dict[str, Any]]
GOAL_CONTRACT_SCHEMA = "pilot-goal-contract/v1"


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agent_root(project_root: Path, ctx: dict[str, Any]) -> Path:
    from ascendc_pilot.paths import agent_root

    arch = str(ctx.get("architecture") or "").strip() or None
    return agent_root(project_root, arch)


def _action_dir(project_root: Path, ctx: dict[str, Any], action_id: str) -> Path:
    rid = str(ctx.get("run_id") or "").strip()
    return _agent_root(project_root, ctx) / "runs" / rid / "actions" / action_id


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _dump_yaml(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _receipt(project_root: Path, ctx: dict[str, Any], name: str, payload: dict[str, Any]) -> Path:
    from ascendc_pilot.runs import receipts_dir

    rid = str(ctx.get("run_id") or "").strip()
    body = dict(payload)
    body.setdefault("kind", "receipt")
    body.setdefault("written_at", _now())
    out = receipts_dir(project_root, rid or None) / name
    _dump_yaml(out, body)
    return out


def _git_workspace():
    """PR-only adapter. Local workspace helpers keep using git_workspace.py unchanged."""
    import sys

    root = Path(__file__).resolve().parents[3]
    ws = root / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import pr_workspace as gw  # type: ignore[import-not-found]

    return gw


def _load_staging(project_root: Path, ctx: dict[str, Any], producer_action: str) -> dict[str, Any]:
    staging = _action_dir(project_root, ctx, producer_action) / "staging.yaml"
    return _load_yaml(staging)


def _intake_source(ctx: dict[str, Any], staging: dict[str, Any]) -> dict[str, Any]:
    raw = ctx.get("source") if isinstance(ctx.get("source"), dict) else {}
    if not raw:
        raw = staging.get("source") if isinstance(staging.get("source"), dict) else {}
    return dict(raw) if isinstance(raw, dict) else {}


def _parse_goal_contract(raw: str) -> dict[str, Any]:
    """Parse Primary-produced JSON Goal Contract. Never infer fields from prose."""
    text = str(raw or "").strip()
    if not text.startswith("{"):
        return {}
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(doc, dict) or str(doc.get("schema") or "") != GOAL_CONTRACT_SCHEMA:
        return {}
    return doc


def _contract_inputs(
    ctx: dict[str, Any], staging: dict[str, Any]
) -> tuple[str, dict[str, Any], list[str], list[str], dict[str, Any], str]:
    """Return user_text, source, workflows, capabilities, constraints, objective."""
    raw_intent = str(ctx.get("intent") or staging.get("intent_text") or "").strip()
    contract = _parse_goal_contract(raw_intent)
    if contract:
        source = contract.get("source") if isinstance(contract.get("source"), dict) else {}
        workflows = [
            str(w).strip()
            for w in (contract.get("needed_workflows") or [])
            if str(w).strip()
        ]
        capabilities = [
            str(c).strip()
            for c in (contract.get("needed_capabilities") or [])
            if str(c).strip()
        ]
        constraints = (
            dict(contract.get("constraints") or {})
            if isinstance(contract.get("constraints"), dict)
            else {}
        )
        user_text = str(
            contract.get("user_text")
            or contract.get("intent_text")
            or contract.get("objective_zh")
            or ""
        ).strip()
        objective = str(contract.get("objective_zh") or user_text or "完成用户目标").strip()
        return user_text, dict(source), workflows, capabilities, constraints, objective

    source = _intake_source(ctx, staging)
    workflows = [
        str(w).strip()
        for w in (staging.get("needed_workflows") or ctx.get("needed_workflows") or [])
        if str(w).strip()
    ]
    capabilities = [
        str(c).strip()
        for c in (staging.get("needed_capabilities") or ctx.get("needed_capabilities") or [])
        if str(c).strip()
    ]
    constraints = (
        dict(staging.get("constraints") or {})
        if isinstance(staging.get("constraints"), dict)
        else {}
    )
    objective = str(staging.get("objective_zh") or raw_intent or "完成用户目标").strip()
    return raw_intent, source, workflows, capabilities, constraints, objective


def _write_runtime_params(
    project_root: Path,
    *,
    architecture: str,
    op_name: str,
    constraints: dict[str, Any],
) -> str:
    """Bridge Goal constraints to the existing TG context resolver."""
    arch = str(architecture or "").strip()
    if not arch or arch == "goal":
        return ""
    from ascendc_pilot.paths import context_root

    params = {
        "op_name": str(op_name or project_root.name).strip(),
        "architecture": arch,
        "test_script_root": str(
            constraints.get("test_script_root")
            or constraints.get("test_repo")
            or constraints.get("test_repo_root")
            or ""
        ).strip(),
        "level": str(constraints.get("level") or "L0").strip() or "L0",
        "focus": str(constraints.get("focus") or "").strip(),
    }
    out = context_root(project_root, arch=arch) / "pilot_params.yaml"
    _dump_yaml(out, params)
    return out.as_posix()


def run_intent_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Promote a Primary-produced Goal Contract; pin PR source; persist TaskPlan."""
    from ascendc_pilot.harness.intent import validate_intent_staging
    from ascendc_pilot.planning.task_plan import (
        current_workflow_id,
        mark_step_passed,
        plan_for,
        public_plan_for,
        write_task_plan,
    )
    from ascendc_pilot.user_goal import create_user_goal, write_user_goal

    staging = _load_staging(project_root, ctx, "intent_promote")
    (
        intent_text,
        source,
        needed_workflows,
        needed_capabilities,
        constraints,
        objective_zh,
    ) = _contract_inputs(ctx, staging)

    if str(source.get("kind") or "") == "pull_request" and not source.get("url"):
        ref = str(source.get("ref") or "").strip()
        if ref:
            source["url"] = ref
    llm_intent = {
        "intent_text": intent_text,
        "objective_zh": objective_zh,
        "source": source or {"kind": "local"},
        "needed_workflows": needed_workflows,
        "needed_capabilities": needed_capabilities,
        "constraints": constraints,
    }
    if llm_intent["needed_workflows"] or llm_intent["needed_capabilities"] or source.get("kind") == "pull_request":
        checked = validate_intent_staging(
            {
                "objective_zh": llm_intent["objective_zh"],
                "intent_text": intent_text,
                "source": llm_intent["source"],
                "needed_workflows": llm_intent["needed_workflows"],
                "needed_capabilities": llm_intent["needed_capabilities"] or ["knowledge"],
                "constraints": llm_intent["constraints"],
            }
        )
        if not checked.get("ok"):
            return {
                "ok": False,
                "error": str(checked.get("error") or "GOAL_CONTRACT_INVALID"),
                "message_zh": str(checked.get("message_zh") or "Goal Contract 校验失败"),
                "reason_code": "GOAL_CONTRACT_INVALID",
            }
        llm_intent = dict(checked["intent"])
        llm_intent["intent_text"] = intent_text
        source = llm_intent.get("source") if isinstance(llm_intent.get("source"), dict) else {}
        constraints = (
            dict(llm_intent.get("constraints") or {})
            if isinstance(llm_intent.get("constraints"), dict)
            else constraints
        )

    if not list(llm_intent.get("needed_workflows") or []) and not list(
        llm_intent.get("needed_capabilities") or []
    ):
        return {
            "ok": False,
            "error": "GOAL_CONTRACT_WORKFLOWS_REQUIRED",
            "reason_code": "GOAL_CONTRACT_WORKFLOWS_REQUIRED",
            "message_zh": "Goal Contract 没有 deliverable/workflow；Primary 必须先完成一次语义规划，不能把原始自然语言交给 runtime 猜。",
        }

    acquire: dict[str, Any] = {}
    project_pin = Path(project_root).expanduser().resolve()
    arch_pin = str(ctx.get("architecture") or "").strip()
    run_id = str(ctx.get("run_id") or "").strip()
    if str(source.get("kind") or "") == "pull_request" and source.get("url"):
        try:
            gw = _git_workspace()
            acquire = gw.acquire_pull_request(
                str(source["url"]),
                run_id=run_id,
                workspace_root=str(Path(project_root).expanduser().resolve()),
            )
        except Exception as exc:  # noqa: BLE001
            acquire = {
                "ok": False,
                "error": "WORKSPACE_ACQUIRE_FAILED",
                "message_zh": str(exc)[:400],
            }
        if not acquire.get("ok"):
            return {
                "ok": False,
                "error": str(acquire.get("error") or "WORKSPACE_ACQUIRE_FAILED"),
                "message_zh": str(
                    acquire.get("message_zh")
                    or "无法获取 PR 代码。请检查鉴权（GITHUB_TOKEN / GITCODE_TOKEN），或改用本地算子目录。"
                ),
                "needs_human_decision": True,
                "decision_kind": "project",
                "ask_question": {
                    "prompt_zh": "获取 PR 失败。请重试或改用本地代码。",
                    "options": [
                        {"label": "重试获取 PR", "value": "retry"},
                        {"label": "改用本地代码", "value": "local"},
                    ],
                    "allow_free_text": True,
                    "field": "project",
                },
            }
        resolved = gw.resolve_targets_or_ask(
            acquire, workflow_id="goal-intake", host_root=Path(project_root)
        )
        if not resolved.get("ok"):
            payload = dict(resolved)
            payload.setdefault("error", str(resolved.get("reason_code") or "WORKSPACE_RESOLVE_FAILED"))
            return payload
        project_pin = Path(str(resolved["project"])).expanduser().resolve()
        arch_pin = str(resolved.get("architecture") or arch_pin).strip()
        targets = [t for t in (resolved.get("operator_targets") or []) if isinstance(t, dict)]
        source = dict(source)
        source.update(
            {
                "base_sha": str(acquire.get("base_sha") or ""),
                "head_sha": str(acquire.get("head_sha") or ""),
                "diff_digest": str(acquire.get("diff_digest") or ""),
                "materialization": "isolated_pr",
            }
        )
        llm_intent["source"] = source
        if targets:
            llm_intent["operator_targets"] = targets

    task_plan = plan_for(llm_intent)
    # PR acquisition is completed by this deterministic action, not a future workflow.
    if any(str(step.get("id") or "") == "workspace_acquire" for step in task_plan.get("steps") or [] if isinstance(step, dict)):
        task_plan = mark_step_passed(task_plan, "workspace_acquire")
    next_workflow = current_workflow_id(task_plan)
    if not next_workflow:
        return {
            "ok": False,
            "error": "GOAL_PLAN_EMPTY",
            "reason_code": "GOAL_PLAN_EMPTY",
            "message_zh": "Goal Contract 没有可执行 workflow step。",
        }

    goal_root = project_pin if project_pin.exists() else Path(project_root)
    public_plan = public_plan_for(
        list(task_plan.get("needed_capabilities") or []),
        workflows=list(task_plan.get("needed_workflows") or []),
    )
    goal = create_user_goal(
        goal_root,
        intent_text=intent_text,
        llm_intent=llm_intent,
        public_plan=public_plan,
        architecture=arch_pin,
        op_name=str(ctx.get("op_name") or project_pin.name or ""),
        kind=str(llm_intent.get("kind") or ""),
    )
    goal["project"] = project_pin.as_posix()
    if arch_pin:
        goal["architecture"] = arch_pin
    if acquire.get("changeset"):
        arts = dict(goal.get("artifacts") or {})
        arts["changeset"] = acquire["changeset"]
        arts["worktree_head"] = acquire.get("worktree_head") or ""
        arts["base_source"] = str((acquire.get("changeset") or {}).get("base_source") or "")
        arts["operator_targets"] = list(llm_intent.get("operator_targets") or [])
        goal["artifacts"] = arts
    params_path = _write_runtime_params(
        goal_root,
        architecture=arch_pin,
        op_name=str(goal.get("op_name") or project_pin.name),
        constraints=constraints,
    )
    if params_path:
        goal.setdefault("artifacts", {})["pilot_params"] = params_path
    write_user_goal(goal_root, goal)
    write_task_plan(goal_root, task_plan)

    launch_root = Path(project_root).expanduser().resolve()
    extra_roots = [project_pin]
    for target in llm_intent.get("operator_targets") or []:
        if not isinstance(target, dict):
            continue
        extra = Path(str(target.get("operator_root") or "")).expanduser()
        if extra.as_posix() and extra not in extra_roots:
            extra_roots.append(extra)
    if project_pin != launch_root:
        # goal-intake completes under the Host staging root; keep a control-plane
        # mirror there so complete_workflow can return the persisted next step.
        try:
            write_user_goal(launch_root, goal)
            write_task_plan(launch_root, task_plan)
        except Exception:  # noqa: BLE001
            pass
    for extra in extra_roots:
        if extra == launch_root or extra == project_pin:
            continue
        if extra.exists():
            try:
                write_user_goal(extra, goal)
                write_task_plan(extra, task_plan)
            except Exception:  # noqa: BLE001
                pass
    if project_pin.exists() and (acquire or project_pin == launch_root):
        try:
            from ascendc_pilot.intake import write_last_project_cache

            write_last_project_cache(project_pin)
        except Exception:  # noqa: BLE001
            pass

    receipt = {
        "ok": True,
        "engine": "intent_promote",
        "kind": goal.get("kind") or "",
        "needed_workflows": list(task_plan.get("needed_workflows") or []),
        "needed_capabilities": list(task_plan.get("needed_capabilities") or []),
        "next_workflow_id": next_workflow,
        "project": str(goal.get("project") or project_root),
        "architecture": str(goal.get("architecture") or arch_pin),
        "operator_roots": list(acquire.get("operator_roots") or []),
        "operator_targets": list(llm_intent.get("operator_targets") or []),
        "workspace_mode": str(acquire.get("workspace_mode") or ("local" if not acquire else "")),
        "head_sha": str(acquire.get("head_sha") or ""),
        "multi_operator": len(list(llm_intent.get("operator_targets") or [])) > 1,
        "next_project": str(goal.get("project") or project_root),
        "next_architecture": str(goal.get("architecture") or arch_pin),
        "message_zh": (
            f"Goal Contract 与 TaskPlan 已固定；下一步 {next_workflow}。"
            "后续只推进持久化计划，不重新解释原始自然语言。"
        ),
    }
    receipt_ctx = dict(ctx)
    if arch_pin:
        receipt_ctx["architecture"] = arch_pin
    receipt_root = project_pin if project_pin.exists() else launch_root
    try:
        _receipt(receipt_root, receipt_ctx, "intent_promoted.yaml", receipt)
    except Exception:  # noqa: BLE001
        pass
    if project_pin.exists() and project_pin != launch_root:
        try:
            _receipt(launch_root, receipt_ctx, "intent_promoted.yaml", receipt)
        except Exception:  # noqa: BLE001
            pass
    return receipt


def install(registry: dict[tuple[str, str], EngineFn]) -> None:
    registry[("goal-intake", "intent_promote")] = run_intent_promote
