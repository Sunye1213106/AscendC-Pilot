"""Intent → unique workflow_id."""

from __future__ import annotations

import re
from typing import Any

from ascendc_harness.workflows import WORKFLOWS, list_user_workflows

SLASH_MAP = {
    "/uo-init": "uo-init",
    "/uo-update": "uo-update",
    "/uo-query": "uo-query",
    "/uo-code-review": "uo-code-review",
    "/uo-diff": "uo-update",  # diff is update-facing read; route to update skill family
    "/tg-init": "tg-init",
    "/tg-plan": "tg-plan",
    "/tg-solve": "tg-solve",
}

KEYWORD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(建库|初始化知识库|uo[- ]?init|build\s+kb)", re.I), "uo-init"),
    (re.compile(r"(增量更新|刷新\s*kb|uo[- ]?update)", re.I), "uo-update"),
    (re.compile(r"(查询|问答|这个\s*key|uo[- ]?query)", re.I), "uo-query"),
    (re.compile(r"(代码审查|code\s*review|查\s*bug)", re.I), "uo-code-review"),
    (re.compile(r"(测例契约|tg[- ]?init|测试工具)", re.I), "tg-init"),
    (re.compile(r"(覆盖规划|tg[- ]?plan|coverage)", re.I), "tg-plan"),
    (re.compile(r"(求解|z3|tg[- ]?solve|生成\s*csv)", re.I), "tg-solve"),
]


def route(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "workflow_id": None, "error": "empty_input", "candidates": list_user_workflows()}

    # Exact slash (first token)
    first = raw.split()[0]
    if first in SLASH_MAP:
        wid = SLASH_MAP[first]
        return {"ok": True, "workflow_id": wid, "slash": WORKFLOWS[wid].get("slash"), "method": "slash"}

    hits: list[str] = []
    for pattern, wid in KEYWORD_RULES:
        if pattern.search(raw):
            if wid not in hits:
                hits.append(wid)

    if len(hits) == 1:
        wid = hits[0]
        return {"ok": True, "workflow_id": wid, "slash": WORKFLOWS[wid].get("slash"), "method": "keyword"}
    if len(hits) > 1:
        return {"ok": False, "workflow_id": None, "error": "ambiguous", "candidates": hits}
    return {"ok": False, "workflow_id": None, "error": "unmatched", "candidates": list_user_workflows()}
