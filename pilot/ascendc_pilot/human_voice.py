# -*- coding: utf-8 -*-
"""Human-voice contract: intent + action + decision consequences for user exits.

Machine fields may live in payloads / reason_code. User-facing strings must
use templates here and must not paste banned jargon as the sole explanation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Banned as raw user-facing tokens (AskQuestion body/labels, Primary narration,
# ACP message_zh that Host shows to humans, failure user_summary_zh).
BANNED_JARGON: tuple[str, ...] = (
    "conditional_pass",
    "binding_inventory",
    "OUTPUT_CONTRACT_",
    "HumanDecisionReceipt",
    "semantic_bind",
    "entity_id",
    "status=None",
    "exactness",
    "GAP-00",
    "reads",
)

# Whole-word / field-name bans (avoid matching Chinese compounds accidentally).
_BANNED_WORD_RE = re.compile(
    r"(?i)\b("
    r"reads|exactness|binding_inventory|conditional_pass|"
    r"semantic_bind|entity_id|HumanDecisionReceipt|"
    r"OUTPUT_CONTRACT_[A-Za-z0-9_]+|"
    r"GAP-00\d+"
    r")\b"
)

_STATUS_NONE_RE = re.compile(r"(?i)status\s*=\s*None")


def contains_banned_jargon(text: str) -> list[str]:
    """Return list of banned tokens found in ``text`` (empty if clean)."""
    found: list[str] = []
    s = str(text or "")
    if not s.strip():
        return found
    if _STATUS_NONE_RE.search(s):
        found.append("status=None")
    for m in _BANNED_WORD_RE.finditer(s):
        tok = m.group(1)
        if tok not in found:
            found.append(tok)
    return found


def assert_human_voice(text: str, *, context: str = "") -> None:
    hits = contains_banned_jargon(text)
    if hits:
        where = f" ({context})" if context else ""
        raise ValueError(f"human-voice jargon banned{where}: {hits}")


def progress_zh(
    *,
    goal: str,
    just_done: str,
    next_step: str = "",
    need_you: str = "",
) -> str:
    """三句式进度 / 总结（agent → 用户）。"""
    lines = [
        f"【目标】{goal.strip()}",
        f"【刚完成】{just_done.strip()}",
    ]
    if need_you.strip():
        lines.append(f"【需要你】{need_you.strip()}")
    elif next_step.strip():
        lines.append(f"【下一步】{next_step.strip()}")
    return "\n".join(lines)


def decision_question(
    *,
    header: str,
    goal: str,
    background: str,
    decide: str,
    consequences: dict[str, str],
    options: list[dict[str, str]],
) -> dict[str, Any]:
    """Build AskQuestion payload with intent + background + consequences."""
    cons_lines = []
    for key, text in consequences.items():
        cons_lines.append(f"- 选「{key}」→ {text}")
    body = (
        f"目标：{goal.strip()}\n"
        f"背景：{background.strip()}\n"
        f"请你决定：{decide.strip()}\n"
        + "\n".join(cons_lines)
    )
    ask = {
        "header": header.strip(),
        "question": body,
        "options": options,
    }
    for opt in options:
        assert_human_voice(str(opt.get("label") or ""), context="option.label")
    assert_human_voice(header, context="ask.header")
    assert_human_voice(body, context="ask.question")
    return ask


def _declared_key_count(project_root: Path) -> int | None:
    """Best-effort |D| from TG products for human summaries."""
    try:
        from ascendc_pilot.paths import tg_root
        from ascendc_pilot.state import load_state
        import yaml

        state = load_state(project_root) or {}
        arch = str(state.get("architecture") or "").strip()
        if not arch:
            return None
        root = tg_root(project_root, arch=arch)
        for rel in (
            "init/declared_set.yaml",
            "realization/declared_set.yaml",
            "init/tilingkey_contract.yaml",
            "contract/tilingkey_contract.yaml",
        ):
            path = root / rel
            if not path.is_file():
                continue
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(doc, dict):
                continue
            for key in ("declared_keys", "keys", "tiling_keys", "key_ids"):
                val = doc.get(key)
                if isinstance(val, list) and val:
                    return len(val)
            n = doc.get("declared_count") or doc.get("key_count") or doc.get("size")
            if isinstance(n, int) and n > 0:
                return n
            ds = doc.get("declared_set")
            if isinstance(ds, list) and ds:
                return len(ds)
            if isinstance(ds, dict):
                keys = ds.get("keys") or ds.get("items")
                if isinstance(keys, list) and keys:
                    return len(keys)
    except Exception:  # noqa: BLE001
        return None
    return None


def _goal_context(project_root: Path) -> dict[str, Any]:
    try:
        from ascendc_pilot.user_goal import load_user_goal, progress_line_zh

        goal = load_user_goal(project_root)
        if not goal:
            return {}
        return {
            "goal": goal,
            "progress_line": progress_line_zh(goal),
            "label_zh": str(goal.get("label_zh") or ""),
        }
    except Exception:  # noqa: BLE001
        return {}


def build_human_confirm_ask(project_root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    from ascendc_pilot.human_confirm import build_ask

    return build_ask(project_root, state, action_id="human_confirm")


def build_plan_approve_ask(project_root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    from ascendc_pilot.human_confirm import build_ask

    return build_ask(project_root, state, action_id="plan_approve")


def build_generic_interactive_ask(action_id: str) -> dict[str, Any]:
    _ = action_id  # reserved for future action-specific copy
    return decision_question(
        header="请确认是否继续",
        goal="完成本步人工确认后继续当前工作流",
        background="当前步骤需要你确认后才能写入正式结果。",
        decide="是否继续完成本步？",
        consequences={
            "继续": "写入确认并推进",
            "返工": "不写入确认，回到可重做状态",
            "停止": "结束本次运行",
        },
        options=[
            {"label": "继续", "value": "confirm"},
            {"label": "返工", "value": "rework"},
            {"label": "停止", "value": "stop"},
        ],
    )


def user_summary_from_failure(state: dict[str, Any], observation: dict[str, Any] | None = None) -> str:
    """Plain-language one-liner for humans; keep structured fields elsewhere."""
    lf = state.get("last_failure") if isinstance(state.get("last_failure"), dict) else {}
    obs = observation or {}
    msg = str(lf.get("message_zh") or obs.get("message_zh") or "").strip()
    code = str(lf.get("reason_code") or lf.get("error_code") or obs.get("error_code") or "").strip()
    phase = str(state.get("phase_label_zh") or state.get("phase") or "").strip()
    if msg and not contains_banned_jargon(msg):
        head = msg
    elif code:
        head = f"当前步骤未通过（{code}），需要按提示处理后重试。"
    else:
        head = "当前步骤未通过，请查看失败项并选择合法后续。"
    if phase and phase not in head:
        return f"阶段「{phase}」：{head}"
    return head


def attach_user_facing_fields(payload: dict[str, Any], *, user_summary_zh: str = "") -> dict[str, Any]:
    """Ensure Host-visible summary exists without stripping machine fields."""
    out = dict(payload)
    summary = (user_summary_zh or str(out.get("user_summary_zh") or "")).strip()
    if summary:
        assert_human_voice(summary, context="user_summary_zh")
        out["user_summary_zh"] = summary
    return out
