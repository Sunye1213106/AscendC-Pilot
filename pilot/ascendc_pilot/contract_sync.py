# -*- coding: utf-8 -*-
"""Single source of truth for the methodology a model window must follow.

A subagent that cannot find the schema in its own session will search the
machine and read whatever methodology copy it finds first. When an installed
plugin lags the checkout, that stale copy becomes the strongest few-shot and
the window produces a plan against retired semantics. This module makes the
drift detectable before the window opens, and names the file to refresh.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

DRIFT_REASON = "PLAN_CONTRACT_DRIFT"

# Repo-relative methodology files, paired with the relative path the installed
# runtime bundle uses for the same content ("" = repo-only, no installed twin).
CONTRACT_FILES: tuple[tuple[str, str], ...] = (
    (
        "skills/test-plan/references/coverage-ir.md",
        "cognitive-skills/test-plan/references/coverage-ir.md",
    ),
    (
        "skills/test-plan/references/target-planning.md",
        "cognitive-skills/test-plan/references/target-planning.md",
    ),
    (
        "skills/test-plan/references/evidence.md",
        "cognitive-skills/test-plan/references/evidence.md",
    ),
    ("skills/test-plan/SKILL.md", "cognitive-skills/test-plan/SKILL.md"),
    ("prompts/tasks/tg/plan-owner.md", ""),
)


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "skills").is_dir() and (parent / "prompts").is_dir():
            return parent
    return here.parents[2]


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def installed_roots() -> list[Path]:
    from ascendc_pilot.paths import opencode_plugin_root

    roots = [
        opencode_plugin_root(),
        Path.home() / ".cursor" / "ascendc-pilot-plugin",
        Path.home() / ".agents" / "ascendc-pilot-plugin",
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        if root.is_dir():
            out.append(root)
    return out


def contract_drift(root: Path | None = None) -> list[dict[str, Any]]:
    """Installed methodology copies whose bytes differ from the checkout.

    A missing installed copy is not drift: the window is told to read the
    session-local contract, so absence cannot mislead it. Divergent content can.
    """
    base = Path(root) if root is not None else repo_root()
    drift: list[dict[str, Any]] = []
    for repo_rel, installed_rel in CONTRACT_FILES:
        if not installed_rel:
            continue
        src = base / repo_rel
        if not src.is_file():
            continue
        want = _digest(src)
        for plugin in installed_roots():
            dst = plugin / installed_rel
            if not dst.is_file():
                continue
            got = _digest(dst)
            if got and got != want:
                drift.append(
                    {
                        "repo": repo_rel,
                        "installed": dst.as_posix(),
                        "repo_sha256": want[:16],
                        "installed_sha256": got[:16],
                    }
                )
    return drift


def contract_drift_gate(root: Path | None = None) -> dict[str, Any] | None:
    """Block a model window when an installed copy could out-vote the checkout."""
    drift = contract_drift(root)
    if not drift:
        return None
    lines = [f"- {row['repo']} != {row['installed']}" for row in drift]
    return {
        "ok": False,
        "engine": "plan_precheck",
        "error": DRIFT_REASON,
        "reason_code": DRIFT_REASON,
        "ask": "human",
        "drift": drift,
        "message_zh": (
            "已安装的 runtime bundle 与当前 checkout 的 Plan 合同不一致，"
            "Plan Owner 可能读到过期方法论并按旧语义交卷（Guard 极性、L2 形态）。\n"
            + "\n".join(lines)
            + "\n先完全退出 Host，再跑 `.\\refresh-opencode.ps1`"
            "（Linux/macOS：`./uninstall.sh && ./install.sh opencode`）重装 bundle，"
            "或直接删掉上面这些过期副本，然后重跑 /tg-plan。"
        ),
    }
