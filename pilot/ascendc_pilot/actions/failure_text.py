"""Collect human-facing failure text from nested engine / drive payloads.

``pilot_run`` must never return only the stop_reason token
(``deterministic_action_failed``). Environment misses such as CANN belong on
``message_zh`` so the model can tell the user what to set, instead of probing
tools that containment will deny.
"""

from __future__ import annotations

from typing import Any

GENERIC_FAILURE_TOKENS = frozenset(
    {
        "",
        "deterministic_action_failed",
        "engine_failed",
        "APPLY_UPDATE_FAILED",
        "rebuild_action_failed",
        "Finalize 失败：Checker/Output Contract 未通过",
    }
)

_CANN_HINT_ZH = (
    "请设置环境变量 UO_CANN_ROOT 或 ASCEND_CANN_PACKAGE_PATH 为 CANN 根目录"
    "（解包后的 cann-asc-devkit/ 或官方安装的 ASCEND_HOME_PATH），"
    "或运行 scripts/cann_extract.py。"
    "官方包不缺头文件；配好 cann_root 后不要按单个相对路径判失败。"
    "修好后告诉我，再重试当前 workflow。"
)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def is_generic_failure_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if stripped in GENERIC_FAILURE_TOKENS:
        return True
    if stripped.startswith("确定性 Action ") and stripped.endswith("失败：deterministic_action_failed"):
        return True
    return False


def _looks_like_cann_failure(blob: str) -> bool:
    low = blob.lower()
    return (
        "cann_env_not_ready" in low
        or "uo_cann_root" in low
        or "ascend_cann_package_path" in low
        or "cann packages not found" in low
        or "cann 环境未就绪" in blob
        or "cann package" in low
    )


def collect_failure_texts(obj: Any, *, depth: int = 0) -> list[str]:
    """Walk engine / finalize / rebuild nests for error strings."""
    if depth > 5 or obj is None:
        return []
    if isinstance(obj, str):
        text = obj.strip()
        return [text] if text else []
    if isinstance(obj, list):
        out: list[str] = []
        for item in obj[:12]:
            out.extend(collect_failure_texts(item, depth=depth + 1))
        return out
    if not isinstance(obj, dict):
        return []
    out = []
    for key in (
        "message_zh",
        "hint_zh",
        "suggested_fix",
        "error",
        "message",
        "detail",
        "error_detail",
    ):
        text = str(obj.get(key) or "").strip()
        if text:
            out.append(text)
    issues = obj.get("issues")
    if isinstance(issues, list):
        out.extend(str(item).strip() for item in issues[:8] if str(item).strip())
    errors = obj.get("errors")
    if isinstance(errors, list):
        out.extend(str(item).strip() for item in errors[:12] if str(item).strip())
    for nested_key in (
        "engine",
        "failure",
        "finalize",
        "result",
        "receipt",
        "checker_result",
        "last_failure",
    ):
        nested = obj.get(nested_key)
        if isinstance(nested, dict):
            out.extend(collect_failure_texts(nested, depth=depth + 1))
    for row in obj.get("action_results") or []:
        if not isinstance(row, dict) or row.get("ok"):
            continue
        out.extend(collect_failure_texts(row, depth=depth + 1))
        inner = row.get("result")
        if isinstance(inner, dict):
            out.extend(collect_failure_texts(inner, depth=depth + 1))
    return out


def preferred_failure_text(
    obj: Any,
    *,
    fallback: str = "deterministic_action_failed",
) -> str:
    texts = collect_failure_texts(obj)
    ranked = [t for t in texts if _has_cjk(t)] + [t for t in texts if not _has_cjk(t)]
    seen: set[str] = set()
    unique: list[str] = []
    for text in ranked:
        if text in seen:
            continue
        seen.add(text)
        unique.append(text)
    for text in unique:
        if not is_generic_failure_text(text):
            return text[:1200]
    return fallback


def cann_hint_zh(obj: Any = None, *, blob: str = "") -> str:
    """Return a configure-CANN hint when the failure is a missing package tree."""
    sample = blob or preferred_failure_text(obj, fallback="")
    if not _looks_like_cann_failure(sample):
        return ""
    if "UO_CANN_ROOT" in sample and "cann-asc-devkit" in sample:
        return ""
    return _CANN_HINT_ZH


def with_failure_hint(detail: str, obj: Any = None) -> str:
    hint = cann_hint_zh(obj, blob=detail)
    if not hint:
        return detail
    if hint in detail:
        return detail
    if not detail or is_generic_failure_text(detail):
        return hint
    return f"{detail.rstrip()}\n{hint}"
