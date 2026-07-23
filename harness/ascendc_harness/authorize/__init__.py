"""Authorize tool invocations for AscendC Agent (OpenCode plugin hook)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Direct domain CLIs that must go through Harness wrappers
_DENY_BASH = [
    re.compile(r"\bpython(?:3)?\b.*\bbuild_layered_kb\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bcheck_final_confidence\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bprepare_operator\.py\b", re.I),
    re.compile(r"\btg-solve\b", re.I),
    re.compile(r"\btg-plan\b", re.I),
    re.compile(r"\btg-init\b", re.I),
    re.compile(r"\buo-init\b", re.I),
]

_ALLOW_BASH = [
    re.compile(r"^\s*harness(\s|$)"),
    re.compile(r"^\s*python(?:3)?\s+-m\s+ascendc_harness(\s|$)"),
]

# Paths primary agent must not freely write (require harness / engine)
_DENY_WRITE_SUFFIXES = (
    "/ir/",
    "\\ir\\",
    "/summary/confidence_report.md",
    "\\summary\\confidence_report.md",
    "/checks/confidence_gate.yaml",
    "\\checks\\confidence_gate.yaml",
    "/checks/integrity.yaml",
    "\\checks\\integrity.yaml",
    "/review/kb_product_review.yaml",
    "\\review\\kb_product_review.yaml",
    "/review/confidence_reason_review.yaml",
    "\\review\\confidence_reason_review.yaml",
)


def authorize(
    project_root: Path | None = None,
    *,
    tool: str,
    command: str = "",
    path: str = "",
    agent: str = "",
    action: str = "",
) -> dict[str, Any]:
    """Return {ok, decision, reason_zh, reason_code}.

    Soft control-plane gate — not OS-level security. Bypass via other tabs/terminals
    still cannot obtain harness `passed` without receipts + complete.
    """
    del project_root  # reserved for future state-aware checks
    tool_l = (tool or "").strip().lower()
    cmd = (command or "").strip()
    path_s = path or ""
    agent_l = (agent or "").strip().lower()

    if tool_l in {"bash", "shell", "terminal"}:
        for pat in _ALLOW_BASH:
            if pat.search(cmd):
                return {
                    "ok": True,
                    "decision": "allow",
                    "reason_code": "HARNESS_CLI",
                    "reason_zh": "允许 harness CLI",
                }
        for pat in _DENY_BASH:
            if pat.search(cmd):
                return {
                    "ok": False,
                    "decision": "deny",
                    "reason_code": "DOMAIN_CLI_BYPASS",
                    "reason_zh": "禁止直调领域脚本/CLI；请经 harness 包装执行",
                    "command": cmd[:200],
                }
        # Primary agent: anything else is ask (plugin may treat as deny)
        if agent_l in {"ascendc-agent", "ascendc_agent", ""}:
            return {
                "ok": False,
                "decision": "ask",
                "reason_code": "BASH_NOT_HARNESS",
                "reason_zh": "AscendC Agent 默认仅允许 harness *；其他 bash 需人工确认",
                "command": cmd[:200],
            }
        return {"ok": True, "decision": "allow", "reason_code": "NON_PRIMARY", "reason_zh": "非 primary 代理放行"}

    if tool_l in {"write", "edit", "apply_patch", "strreplace"}:
        norm = path_s.replace("\\", "/")
        for marker in _DENY_WRITE_SUFFIXES:
            m = marker.replace("\\", "/")
            if m in norm or norm.endswith(m.strip("/").split("/")[-1]):
                if any(x in norm for x in ("/ir/", "/summary/", "/checks/", "/review/")):
                    return {
                        "ok": False,
                        "decision": "deny",
                        "reason_code": "PROTECTED_WRITE",
                        "reason_zh": "正式 IR/summary/checks/review 须经 Harness 授权的 producer/engine/referee 写入",
                        "path": path_s,
                        "action": action,
                    }
        return {"ok": True, "decision": "allow", "reason_code": "WRITE_OK", "reason_zh": "写路径未命中保护面"}

    return {"ok": True, "decision": "allow", "reason_code": "TOOL_DEFAULT", "reason_zh": "默认放行"}
