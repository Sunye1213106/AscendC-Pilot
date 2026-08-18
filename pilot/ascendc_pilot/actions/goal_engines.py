# -*- coding: utf-8 -*-
"""Deterministic Harness engines: Intent promote, impact/obligations, workspace."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

EngineFn = Callable[[Path, dict[str, Any]], dict[str, Any]]


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
    import sys

    root = Path(__file__).resolve().parents[3]
    ws = root / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # type: ignore[import-not-found]

    return gw


def _load_staging(project_root: Path, ctx: dict[str, Any], producer_action: str) -> dict[str, Any]:
    staging = _action_dir(project_root, ctx, producer_action) / "staging.yaml"
    return _load_yaml(staging)


def run_intent_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.harness.intent import validate_intent_staging
    from ascendc_pilot.planning.prerequisites import available_state
    from ascendc_pilot.planning.task_plan import plan_for, write_task_plan
    from ascendc_pilot.user_goal import create_user_goal, write_user_goal

    staging = _load_staging(project_root, ctx, "parse_intent")
    if not staging:
        return {
            "ok": False,
            "error": "INTENT_STAGING_EMPTY",
            "message_zh": "意图解析没有写出 staging.yaml",
        }
    intent_text = str(ctx.get("intent") or staging.get("intent_text") or "").strip()
    staging.setdefault("intent_text", intent_text)
    checked = validate_intent_staging(staging)
    if not checked.get("ok"):
        return {
            "ok": False,
            "error": str(checked.get("error") or "INTENT_INVALID"),
            "message_zh": str(checked.get("message_zh") or "意图校验失败"),
            "reason_code": "INTENT_INVALID",
        }
    llm_intent = dict(checked["intent"])
    llm_intent["intent_text"] = intent_text
    avail = available_state(project_root, architecture=str(ctx.get("architecture") or ""))
    plan = plan_for(llm_intent, avail)

    source = llm_intent.get("source") if isinstance(llm_intent.get("source"), dict) else {}
    if str(source.get("kind") or "") != "pull_request":
        for step in plan.get("steps") or []:
            if isinstance(step, dict) and str(step.get("id")) == "workspace_acquire":
                step["status"] = "skipped"
        for step in plan.get("steps") or []:
            if isinstance(step, dict) and str(step.get("status")) == "pending":
                step["status"] = "in_progress"
                break
    acquire: dict[str, Any] = {}
    project_pin = Path(project_root).expanduser().resolve()
    arch_pin = str(ctx.get("architecture") or "").strip()
    if str(source.get("kind") or "") == "pull_request" and source.get("url"):
        try:
            gw = _git_workspace()
            acquire = gw.acquire_pull_request(
                str(source["url"]),
                goal_id=str(plan.get("kind") or "goal"),
            )
        except Exception as exc:  # noqa: BLE001
            acquire = {"ok": False, "error": "WORKSPACE_ACQUIRE_FAILED", "message_zh": str(exc)[:400]}
        if acquire.get("ok"):
            roots = list(acquire.get("operator_roots") or [])
            if len(roots) == 1:
                project_pin = Path(str(roots[0]))
                arches = list(acquire.get("architectures") or [])
                if len(arches) == 1:
                    arch_pin = str(arches[0])
            for step in plan.get("steps") or []:
                if isinstance(step, dict) and str(step.get("id")) == "workspace_acquire":
                    step["status"] = "passed"
            # Next pending becomes in_progress.
            for step in plan.get("steps") or []:
                if isinstance(step, dict) and str(step.get("status")) == "pending":
                    step["status"] = "in_progress"
                    break
        elif not avail.get("has_project"):
            return {
                "ok": False,
                "error": str(acquire.get("error") or "WORKSPACE_ACQUIRE_FAILED"),
                "message_zh": str(
                    acquire.get("message_zh")
                    or "无法获取 PR 代码。请检查鉴权，或提供本地算子目录。"
                ),
                "needs_human_decision": True,
                "decision_kind": "project",
            }

    goal = create_user_goal(
        project_pin if project_pin.exists() else project_root,
        intent_text=intent_text,
        llm_intent=llm_intent,
        architecture=arch_pin,
        op_name=str(ctx.get("op_name") or ""),
        kind=str(plan.get("kind") or ""),
    )
    if acquire.get("changeset"):
        arts = dict(goal.get("artifacts") or {})
        arts["changeset"] = acquire["changeset"]
        arts["worktree_head"] = acquire.get("worktree_head") or ""
        goal["artifacts"] = arts
        if project_pin.exists():
            goal["project"] = project_pin.as_posix()
        if arch_pin:
            goal["architecture"] = arch_pin
        write_user_goal(project_pin if project_pin.exists() else project_root, goal)

    write_task_plan(project_root, plan)
    if project_pin != Path(project_root).resolve() and project_pin.exists():
        write_task_plan(project_pin, plan)
        # Mirror goal onto the original start root so Driver continue_goal can read it
        # before switching project.
        from ascendc_pilot.user_goal import write_user_goal as _write_goal

        _write_goal(project_root, goal)

    receipt = {
        "ok": True,
        "engine": "intent_promote",
        "kind": plan.get("kind"),
        "needed_capabilities": list(plan.get("needed_capabilities") or []),
        "next_workflow_id": "",
        "project": str(goal.get("project") or project_root),
        "architecture": str(goal.get("architecture") or arch_pin),
        "operator_roots": list(acquire.get("operator_roots") or []),
        "multi_operator": len(list(acquire.get("operator_roots") or [])) > 1,
    }
    from ascendc_pilot.planning.task_plan import current_workflow_id

    receipt["next_workflow_id"] = current_workflow_id(plan)
    _receipt(project_root, ctx, "intent_promoted.yaml", receipt)
    if len(list(acquire.get("operator_roots") or [])) > 1:
        return {
            "ok": False,
            "error": "MULTI_OPERATOR",
            "message_zh": "这次改动跨多个算子目录，请选择要生成用例的算子。",
            "needs_human_decision": True,
            "decision_kind": "project",
            "operator_roots": acquire.get("operator_roots"),
            **receipt,
        }
    return receipt


def run_impact_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.user_goal import load_user_goal, write_user_goal

    staging = _load_staging(project_root, ctx, "change_impact")
    if not staging:
        return {"ok": False, "error": "IMPACT_STAGING_EMPTY", "reason_code": "IMPACT_INVALID"}
    affected = staging.get("affected") or staging.get("affected_symbols") or []
    goal = load_user_goal(project_root) or {}
    findings = list(goal.get("findings") or [])
    summary = str(staging.get("summary_zh") or staging.get("finding") or "").strip()
    if summary:
        findings.append({"summary_zh": summary, "at": _now()})
    arts = dict(goal.get("artifacts") or {})
    arts["impact"] = {
        "affected": affected,
        "changed_paths": list(staging.get("changed_paths") or []),
        "contrast": staging.get("contrast") or [],
    }
    if goal:
        goal["findings"] = findings
        goal["artifacts"] = arts
        write_user_goal(project_root, goal)
    _dump_yaml(_action_dir(project_root, ctx, "impact_promote") / "impact.yaml", arts["impact"])
    _receipt(project_root, ctx, "change_impact.yaml", {"ok": True, "affected": affected})
    return {"ok": True, "engine": "impact_promote", "affected_count": len(list(affected))}


def run_obligations_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.user_goal import load_user_goal, write_user_goal

    staging = _load_staging(project_root, ctx, "derive_obligations")
    items = staging.get("obligations") or staging.get("items") or []
    if not isinstance(items, list) or not items:
        return {
            "ok": False,
            "error": "OBLIGATION_STAGING_EMPTY",
            "reason_code": "OBLIGATION_INVALID",
            "message_zh": "没有推导出测试义务。",
        }
    cleaned = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        cleaned.append(
            {
                "change": str(raw.get("change") or "").strip(),
                "condition": str(raw.get("condition") or "").strip(),
                "affected": raw.get("affected") or [],
                "contrast": raw.get("contrast") or [],
                "boundaries": raw.get("boundaries") or [],
                "required_hits": raw.get("required_hits") or [],
            }
        )
    if not cleaned:
        return {"ok": False, "error": "OBLIGATION_INVALID", "reason_code": "OBLIGATION_INVALID"}
    goal = load_user_goal(project_root) or {}
    arts = dict(goal.get("artifacts") or {})
    arts["obligations"] = cleaned
    if goal:
        goal["artifacts"] = arts
        write_user_goal(project_root, goal)
    _dump_yaml(
        _action_dir(project_root, ctx, "obligations_promote") / "obligations.yaml",
        {"obligations": cleaned},
    )
    _receipt(project_root, ctx, "test_obligations.yaml", {"ok": True, "count": len(cleaned)})
    return {"ok": True, "engine": "obligations_promote", "count": len(cleaned)}


def install(registry: dict[tuple[str, str], EngineFn]) -> None:
    registry[("goal-intake", "intent_promote")] = run_intent_promote
    registry[("goal-impact", "impact_promote")] = run_impact_promote
    registry[("goal-impact", "obligations_promote")] = run_obligations_promote
