# -*- coding: utf-8 -*-
"""Deterministic Harness engines: workspace pin + Goal record. No Intent LLM."""

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


def _intake_source(ctx: dict[str, Any], staging: dict[str, Any]) -> dict[str, Any]:
    raw = ctx.get("source") if isinstance(ctx.get("source"), dict) else {}
    if not raw:
        raw = staging.get("source") if isinstance(staging.get("source"), dict) else {}
    return dict(raw) if isinstance(raw, dict) else {}


def run_intent_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Pin a PR worktree when SourceRef is already structured. Do not parse NL."""
    from ascendc_pilot.harness.intent import validate_intent_staging
    from ascendc_pilot.user_goal import create_user_goal, write_user_goal

    staging = _load_staging(project_root, ctx, "intent_promote")
    intent_text = str(ctx.get("intent") or staging.get("intent_text") or "").strip()
    source = _intake_source(ctx, staging)
    llm_intent = {
        "intent_text": intent_text,
        "objective_zh": str(staging.get("objective_zh") or intent_text or "完成用户目标"),
        "source": source or {"kind": "local"},
        "needed_workflows": list(staging.get("needed_workflows") or ctx.get("needed_workflows") or []),
        "needed_capabilities": list(
            staging.get("needed_capabilities") or ctx.get("needed_capabilities") or []
        ),
        "constraints": staging.get("constraints") if isinstance(staging.get("constraints"), dict) else {},
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
                "error": str(checked.get("error") or "INTENT_INVALID"),
                "message_zh": str(checked.get("message_zh") or "来源校验失败"),
                "reason_code": "INTENT_INVALID",
            }
        llm_intent = dict(checked["intent"])
        llm_intent["intent_text"] = intent_text
        source = llm_intent.get("source") if isinstance(llm_intent.get("source"), dict) else {}

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
            acquire = {"ok": False, "error": "WORKSPACE_ACQUIRE_FAILED", "message_zh": str(exc)[:400]}
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
        roots = [Path(p) for p in (acquire.get("operator_roots") or []) if str(p).strip()]
        if len(roots) == 0:
            return {
                "ok": False,
                "error": "OPERATOR_ROOTS_EMPTY",
                "message_zh": (
                    "这次 PR 改动没有落到含 op_host/ 或 op_kernel/ 的算子目录"
                    "（common/shared 也未能反推出受影响算子）。请选择算子，或改用本地代码。"
                ),
                "needs_human_decision": True,
                "decision_kind": "project",
                "changed_files": list(acquire.get("changed_files") or []),
                "ask_question": {
                    "prompt_zh": "请选择要生成用例的算子目录（含 op_host/ 或 op_kernel/）",
                    "options": [],
                    "allow_free_text": True,
                    "field": "project",
                },
            }
        if len(roots) > 1:
            return {
                "ok": False,
                "error": "MULTI_OPERATOR",
                "message_zh": "这次改动跨多个算子目录，请选择要生成用例的算子。",
                "needs_human_decision": True,
                "decision_kind": "project",
                "operator_roots": [str(p) for p in roots],
                "ask_question": {
                    "prompt_zh": "请选择要生成用例的算子",
                    "options": [
                        {"label": p.name, "value": str(p), "description": str(p)} for p in roots
                    ],
                    "allow_free_text": True,
                    "field": "project",
                },
            }
        project_pin = roots[0]
        arches = list(acquire.get("architectures") or [])
        if len(arches) == 1:
            arch_pin = str(arches[0])

    goal_root = project_pin if project_pin.exists() else Path(project_root)
    goal = create_user_goal(
        goal_root,
        intent_text=intent_text,
        llm_intent=llm_intent,
        architecture=arch_pin,
        op_name=str(ctx.get("op_name") or ""),
        kind=str(llm_intent.get("kind") or ""),
    )
    if project_pin.exists():
        goal["project"] = project_pin.as_posix()
        try:
            from ascendc_pilot.intake import write_last_project_cache

            write_last_project_cache(project_pin)
        except Exception:  # noqa: BLE001
            pass
    if arch_pin:
        goal["architecture"] = arch_pin
    if acquire.get("changeset"):
        arts = dict(goal.get("artifacts") or {})
        arts["changeset"] = acquire["changeset"]
        arts["worktree_head"] = acquire.get("worktree_head") or ""
        arts["base_source"] = str((acquire.get("changeset") or {}).get("base_source") or "")
        goal["artifacts"] = arts
    write_user_goal(goal_root, goal)
    if project_pin != Path(project_root).expanduser().resolve() and project_pin.exists():
        write_user_goal(project_root, goal)

    receipt = {
        "ok": True,
        "engine": "intent_promote",
        "kind": goal.get("kind") or "",
        "needed_workflows": list((goal.get("intent") or {}).get("needed_workflows") or []),
        "needed_capabilities": list((goal.get("intent") or {}).get("needed_capabilities") or []),
        "next_workflow_id": "",
        "project": str(goal.get("project") or project_root),
        "architecture": str(goal.get("architecture") or arch_pin),
        "operator_roots": list(acquire.get("operator_roots") or []),
        "multi_operator": False,
        "message_zh": "工作区已就绪。对照编排 skill 的 slash I/O 选择下一步，不要再用 workflow=auto 解析原文。",
    }
    _receipt(project_root, ctx, "intent_promoted.yaml", receipt)
    if project_pin.exists() and project_pin != Path(project_root).expanduser().resolve():
        _receipt(project_pin, ctx, "intent_promoted.yaml", receipt)
    return receipt


def install(registry: dict[tuple[str, str], EngineFn]) -> None:
    registry[("goal-intake", "intent_promote")] = run_intent_promote
