# -*- coding: utf-8 -*-
"""Validate structured intake staging. Does not parse the user prompt.

Primary selects slashes via have→want Todos. This module only checks
already-structured SourceRef / workflow ids / allowlisted PR hosts.
It must not extract URLs, classify phrases, or invent workflows from
capability labels. ``needed_capabilities`` is a legacy label, not intake.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# Derived labels for Goal kind / Public Plan. Not the intake ontology.
KNOWN_CAPABILITIES = (
    "knowledge",
    "change_analysis",
    "test_generation",
    "code_review",
    "implement",
)

SOURCE_KINDS = ("pull_request", "git_diff", "commit_range", "local", "none")

ALLOWED_PR_HOSTS = frozenset({"gitcode.com", "github.com", "gitcode.net"})

# Slash workflows that are not Goal steps (query is pilot_cli / Task).
NON_GOAL_USER_WORKFLOWS = frozenset({"uo-query"})

WORKFLOW_SUMMARY_ZH = {
    "uo-init": "按算子目录与架构建立 CodeMap",
    "uo-update": "按变更增量更新已有 CodeMap",
    "uo-query": "查询 CodeMap 语义",
    "uo-investigate": "调查 CodeMap 未闭合项",
    "tg-init": "绑定测试变量并写前置 yaml",
    "tg-plan": "把测试意图收成有限覆盖计划",
    "tg-solve": "定向构造并回放生成用例",
    "ce-plan": "grill 需求并写出带 todo 的改码计划",
    "ce-apply": "按计划改算子或测试脚本",
    "ce-review": "审查 diff：意图、改动、问题与应测点",
    "handoff": "会话交接",
}

_CAPS_TO_WORKFLOWS = {
    "test_generation": ("tg-plan", "tg-solve"),
    "code_review": ("ce-review",),
    "implement": ("ce-plan", "ce-apply"),
}


def _pr_host_ok(url: str) -> bool:
    try:
        host = (urlparse(str(url or "").strip()).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if host.startswith("www."):
        host = host[4:]
    return host in ALLOWED_PR_HOSTS


def _as_id_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if str(c).strip()]
    return []


def list_goal_workflows() -> list[str]:
    from ascendc_pilot.workflows import list_user_workflows

    return [w for w in list_user_workflows() if w not in NON_GOAL_USER_WORKFLOWS]


def workflow_catalog() -> list[dict[str, Any]]:
    from ascendc_pilot.workflows import WORKFLOWS, list_user_workflows

    rows: list[dict[str, Any]] = []
    for wid in list_user_workflows():
        meta = WORKFLOWS.get(wid) if isinstance(WORKFLOWS.get(wid), dict) else {}
        rows.append(
            {
                "id": wid,
                "slash": str((meta or {}).get("slash") or f"/{wid}"),
                "summary_zh": WORKFLOW_SUMMARY_ZH.get(wid, wid),
                "goal_step": wid not in NON_GOAL_USER_WORKFLOWS,
            }
        )
    return rows


def render_workflow_catalog() -> str:
    lines = [
        "# 用户工作流目录",
        "",
        "从下面选出用户要交付的工作流 id（并集、无序）。",
        "不要发明目录外的 id。执行顺序由 Primary Todo 决定，不由本目录脚本补链。",
        "",
    ]
    for row in workflow_catalog():
        extra = (
            ""
            if row["goal_step"]
            else " **不是 Goal 步骤**（稍后 `pilot_cli` / Task，不进任务计划）"
        )
        lines.append(
            f"- `{row['id']}` ({row['slash']})：{row['summary_zh']}{extra}"
        )
    return "\n".join(lines) + "\n"


def workflows_from_capabilities(caps: list[str]) -> list[str]:
    """Legacy mapping so old staging still expands. Not the intake ontology."""
    out: list[str] = []
    bag = {str(c).strip() for c in caps if str(c).strip()}
    for cap, wids in _CAPS_TO_WORKFLOWS.items():
        if cap not in bag:
            continue
        for wid in wids:
            if wid not in out:
                out.append(wid)
    if "knowledge" in bag and not out:
        out.append("uo-init")
    return out


def capabilities_from_workflows(wids: list[str]) -> list[str]:
    bag = {str(w).strip() for w in wids if str(w).strip()}
    caps: list[str] = []
    if bag & {"uo-init", "uo-update", "uo-investigate"}:
        caps.append("knowledge")
    if "ce-review" in bag:
        caps.append("code_review")
    if bag & {"tg-init", "tg-plan", "tg-solve"}:
        caps.append("test_generation")
    if bag & {"ce-plan", "ce-apply"}:
        caps.append("implement")
    return caps


def validate_intent_staging(staging: dict[str, Any] | None) -> dict[str, Any]:
    """Return ``{ok, intent}`` or ``{ok: False, error, message_zh}``."""
    doc = dict(staging or {})
    if not doc:
        return {
            "ok": False,
            "error": "INTENT_STAGING_EMPTY",
            "message_zh": "意图解析没有写出结果，请重试。",
        }

    objective = str(doc.get("objective_zh") or doc.get("objective") or "").strip()
    from ascendc_pilot.workflows import list_user_workflows

    legal = set(list_user_workflows())
    raw_wfs = _as_id_list(doc.get("needed_workflows") or doc.get("workflows"))
    raw_caps = _as_id_list(doc.get("needed_capabilities") or doc.get("capabilities"))

    if raw_wfs:
        unknown = [w for w in raw_wfs if w not in legal]
        if unknown:
            return {
                "ok": False,
                "error": "UNKNOWN_WORKFLOW",
                "message_zh": "无法识别要跑的工作流：" + "、".join(unknown),
                "unknown_workflows": unknown,
            }
        wfs = list(raw_wfs)
    else:
        return {
            "ok": False,
            "error": "NO_WORKFLOWS",
            "message_zh": "还没有判断出要跑哪些工作流。Intake 不得从 capability 标签补 slash。",
        }

    query_requested = any(w in NON_GOAL_USER_WORKFLOWS for w in wfs)
    goal_wfs = [w for w in wfs if w not in NON_GOAL_USER_WORKFLOWS]
    if not goal_wfs and not query_requested:
        return {
            "ok": False,
            "error": "NO_WORKFLOWS",
            "message_zh": "还没有判断出要跑哪些工作流，请把目标说具体一些。",
        }

    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    kind = str(source.get("kind") or "none").strip() or "none"
    if kind not in SOURCE_KINDS:
        return {
            "ok": False,
            "error": "UNKNOWN_SOURCE_KIND",
            "message_zh": f"无法识别输入来源 {kind}",
        }
    url = str(source.get("url") or "").strip()
    if kind == "pull_request":
        if not url:
            return {
                "ok": False,
                "error": "PR_URL_MISSING",
                "message_zh": "需要审查或按 PR 生成用例时，请给出 GitCode / GitHub 的 PR 链接。",
            }
        if not _pr_host_ok(url):
            return {
                "ok": False,
                "error": "PR_HOST_NOT_ALLOWED",
                "message_zh": "只支持 gitcode.com / github.com / gitcode.net 上的 PR。",
            }
        source = {"kind": "pull_request", "url": url}
    else:
        source = {"kind": kind, **({k: v for k, v in source.items() if k != "kind"})}

    raw_text = str(doc.get("intent_text") or "").strip()
    if url and raw_text and raw_text.rstrip("/").endswith(url.rstrip("/")) and not goal_wfs:
        return {
            "ok": False,
            "error": "URL_IS_NOT_INTENT",
            "message_zh": "链接只是输入，请说明要审查、生成用例还是改代码。",
        }

    constraints = doc.get("constraints") if isinstance(doc.get("constraints"), dict) else {}
    caps = capabilities_from_workflows(goal_wfs) or list(raw_caps)
    intent = {
        "objective_zh": objective or "完成用户目标",
        "source": source,
        "needed_workflows": goal_wfs,
        "needed_capabilities": caps,
        "query_requested": query_requested,
        "constraints": constraints,
        "intent_text": raw_text,
    }
    return {"ok": True, "intent": intent}
