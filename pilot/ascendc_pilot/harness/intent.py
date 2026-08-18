# -*- coding: utf-8 -*-
"""Validate LLM Intent staging. Does not parse the user prompt.

The user ``intent`` text goes to the LLM Action unchanged. This module only
checks the staging the LLM wrote: known capabilities, SourceRef shape, and
allowlisted PR hosts. It must not extract URLs or classify phrases itself.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

KNOWN_CAPABILITIES = (
    "knowledge",
    "change_analysis",
    "test_generation",
    "code_review",
    "implement",
)

SOURCE_KINDS = ("pull_request", "git_diff", "commit_range", "local", "none")

ALLOWED_PR_HOSTS = frozenset({"gitcode.com", "github.com", "gitcode.net"})


def _pr_host_ok(url: str) -> bool:
    try:
        host = (urlparse(str(url or "").strip()).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if host.startswith("www."):
        host = host[4:]
    return host in ALLOWED_PR_HOSTS


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
    raw_caps = doc.get("needed_capabilities") or doc.get("capabilities") or []
    if isinstance(raw_caps, str):
        caps = [raw_caps.strip()]
    elif isinstance(raw_caps, list):
        caps = [str(c).strip() for c in raw_caps if str(c).strip()]
    else:
        caps = []

    unknown = [c for c in caps if c not in KNOWN_CAPABILITIES]
    if unknown:
        return {
            "ok": False,
            "error": "UNKNOWN_CAPABILITY",
            "message_zh": "无法识别要做的事：" + "、".join(unknown),
            "unknown_capabilities": unknown,
        }
    if not caps:
        return {
            "ok": False,
            "error": "NO_CAPABILITIES",
            "message_zh": "还没有判断出要做哪些事，请把目标说具体一些。",
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

    # URL-only prompt is not an intent. LLM must have named real work.
    raw_text = str(doc.get("intent_text") or "").strip()
    if url and raw_text and raw_text.rstrip("/").endswith(url.rstrip("/")) and len(caps) == 0:
        return {
            "ok": False,
            "error": "URL_IS_NOT_INTENT",
            "message_zh": "链接只是输入，请说明要审查、生成用例还是改代码。",
        }

    constraints = doc.get("constraints") if isinstance(doc.get("constraints"), dict) else {}
    intent = {
        "objective_zh": objective or "完成用户目标",
        "source": source,
        "needed_capabilities": caps,
        "constraints": constraints,
        "intent_text": raw_text,
    }
    return {"ok": True, "intent": intent}
