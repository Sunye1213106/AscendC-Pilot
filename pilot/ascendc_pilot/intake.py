# -*- coding: utf-8 -*-
"""CLI intake gates: operator --project + architecture before uo/tg start.

Prevents:
- silent arch35 default / invented arch options
- prepare against AscendC-Pilot checkout or monorepo parent
- ``.ascendc-pilot/`` appearing under OpenCode cwd instead of the operator
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ascendc_pilot.paths import pilot_checkout_root

LAST_PROJECT_CACHE = Path.home() / ".config" / "opencode" / "ascendc-last-project"
HARNESS_BIN_CACHE = Path.home() / ".config" / "opencode" / "ascendc-harness-bin"

_WORKFLOWS_NEED_ARCH = frozenset({
    "uo-init",
    "uo-update",
    "tg-init",
    "tg-plan",
    "tg-solve",
})
_WORKFLOWS_NEED_OPERATOR = frozenset({
    "uo-init",
    "uo-update",
    "uo-query",
    "uo-investigate",
    "tg-init",
    "tg-plan",
    "tg-solve",
    "ce-review",
})


def looks_like_operator_package(root: Path | str | None) -> bool:
    """True when root has op_host / op_kernel style operator layout."""
    if root is None:
        return False
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        return False
    return (path / "op_host").is_dir() or (path / "op_kernel").is_dir()


def is_pilot_harness_root(root: Path | str | None) -> bool:
    """True when root is the AscendC-Pilot checkout (engines/pilot present)."""
    if root is None:
        return False
    path = Path(root).expanduser().resolve()
    try:
        if path == pilot_checkout_root():
            return True
    except Exception:
        pass
    return (path / "pilot" / "ascendc_pilot").is_dir() and (path / "engines").is_dir()


def _count_sources(dir_path: Path) -> int:
    if not dir_path.is_dir():
        return 0
    n = 0
    for p in dir_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".cpp", ".cc", ".cxx", ".h", ".hpp", ".c"}:
            n += 1
    return n


def discover_architectures(root: Path | str | None) -> list[str]:
    """List arch* dirs under op_host / op_kernel (no invented fallback names)."""
    if root is None:
        return []
    path = Path(root).expanduser().resolve()
    found: list[str] = []
    for side in ("op_host", "op_kernel"):
        base = path / side
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            name = child.name
            if child.is_dir() and re.fullmatch(r"arch\d+", name):
                if name not in found:
                    found.append(name)
    return found


def describe_architectures(root: Path | str | None) -> list[dict[str, str]]:
    """Structured AskQuestion options derived only from on-disk arch* folders."""
    path = Path(root).expanduser().resolve() if root else None
    names = discover_architectures(path) if path else []
    options: list[dict[str, str]] = []
    for name in names:
        bits: list[str] = []
        for side in ("op_host", "op_kernel"):
            d = path / side / name  # type: ignore[operator]
            if d.is_dir():
                bits.append(f"{side}/{name}: {_count_sources(d)} sources")
        # Shared sources outside arch* still matter for BuildVariant.
        for side in ("op_host", "op_kernel"):
            shared = 0
            base = path / side  # type: ignore[operator]
            if base.is_dir():
                for f in base.iterdir():
                    if f.is_file() and f.suffix.lower() in {".cpp", ".h", ".hpp", ".c"}:
                        shared += 1
            if shared:
                bits.append(f"{side}/* shared: {shared} files")
        options.append(
            {
                "label": name,
                "description": "; ".join(bits) if bits else f"found under op_host|op_kernel/{name}",
            }
        )
    return options


def read_last_project_cache() -> Path | None:
    try:
        if not LAST_PROJECT_CACHE.is_file():
            return None
        root = Path(LAST_PROJECT_CACHE.read_text(encoding="utf-8").strip())
        if looks_like_operator_package(root):
            return root.resolve()
    except Exception:
        return None
    return None


def write_last_project_cache(root: Path | str) -> None:
    path = Path(root).expanduser().resolve()
    if not looks_like_operator_package(path):
        return
    try:
        LAST_PROJECT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        LAST_PROJECT_CACHE.write_text(str(path), encoding="utf-8")
    except Exception:
        pass


def write_harness_bin_cache(acp_bin: Path | str) -> None:
    try:
        p = Path(acp_bin).expanduser().resolve()
        if not p.is_file():
            return
        HARNESS_BIN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        HARNESS_BIN_CACHE.write_text(str(p), encoding="utf-8")
    except Exception:
        pass


def architecture_from_env() -> str:
    for name in ("UO_ARCH", "ASCENDC_ARCH"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    return ""


def default_cli_project(explicit: Path | str | None = None) -> Path:
    """Resolve --project so OpenCode cwd ≠ artifact root.

    Order:
    1. explicit ``--project``
    2. ``ASCENDC_PROJECT_ROOT`` / ``UO_OP_DIR``
    3. cwd if it is already an operator package
    4. last-project cache (conversation-pinned operator) when cwd is anything else
       (monorepo parent, Pilot checkout, random folder)
    5. cwd (will fail intake if not an operator)
    """
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser().resolve()
    for name in ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if looks_like_operator_package(cwd):
        return cwd
    cached = read_last_project_cache()
    if cached is not None:
        return cached
    return cwd


def assert_operator_project(root: Path | str, *, action: str = "") -> dict[str, Any] | None:
    """Refuse creating/using ``.ascendc-pilot`` outside an operator package."""
    path = Path(root).expanduser().resolve()
    if looks_like_operator_package(path) and not is_pilot_harness_root(path):
        return None
    if looks_like_operator_package(path) and is_pilot_harness_root(path):
        # Synthetic tests may use checkout; allow only if op_host present under checkout tests.
        return None
    label = f" Action={action}" if action else ""
    return {
        "ok": False,
        "needs_human_decision": True,
        "decision_kind": "project",
        "reason_code": "OPERATOR_PROJECT_REQUIRED",
        "project": str(path),
        "message_zh": (
            f"拒绝在非算子目录创建/使用 .ascendc-pilot/{label}。\n"
            f"当前路径: {path}\n"
            "请把 --project 指到含 op_host/ 或 op_kernel/ 的算子目录"
            "（对话一开始指定的那个），不要用 OpenCode 启动目录或 monorepo 父目录。"
        ),
        "ask_question": {
            "prompt_zh": "请确认算子源码目录（含 op_host/ 或 op_kernel/）",
            "options": [],
            "allow_free_text": True,
            "field": "project",
        },
    }


def start_intake_gate(
    *,
    project: Path | str,
    workflow_id: str,
    architecture: str = "",
    project_explicit: bool = False,
) -> dict[str, Any] | None:
    """Return a needs_human_decision payload, or None when start may proceed.

    Rule for uo/tg: both operator ``--project`` and ``--architecture`` are
    required. Missing either → AskQuestion; both present and valid → start.
    """
    wf = (workflow_id or "").strip()
    root = Path(project).expanduser().resolve()
    arch = (architecture or "").strip() or architecture_from_env()

    if wf in _WORKFLOWS_NEED_OPERATOR:
        bad = assert_operator_project(root)
        if bad is not None:
            bad["workflow_id"] = wf
            bad["suggested_command"] = (
                f'acp start {wf} --project "<算子目录>" --architecture <arch*>'
            )
            return bad
        if not looks_like_operator_package(root) and not project_explicit:
            return {
                "ok": False,
                "needs_human_decision": True,
                "decision_kind": "project",
                "reason_code": "OPERATOR_PROJECT_UNCLEAR",
                "workflow_id": wf,
                "project": str(root),
                "message_zh": (
                    f"路径 {root} 不像算子包（缺少 op_host/ 或 op_kernel/）。"
                    "请用 AskQuestion 确认 --project，再与 --architecture 一起 start。"
                ),
                "ask_question": {
                    "prompt_zh": "请确认算子源码目录",
                    "options": [],
                    "allow_free_text": True,
                    "field": "project",
                },
            }

    if wf in _WORKFLOWS_NEED_ARCH and not arch:
        options = describe_architectures(root)
        labels = [o["label"] for o in options]
        if not options:
            return {
                "ok": False,
                "needs_human_decision": True,
                "decision_kind": "architecture",
                "reason_code": "ARCHITECTURE_NOT_FOUND",
                "workflow_id": wf,
                "project": str(root),
                "architecture_options": [],
                "message_zh": (
                    f"在 {root} 下未发现 op_host/arch* 或 op_kernel/arch*。"
                    "请检查算子目录，或 AskQuestion 手工指定 architecture。"
                ),
                "ask_question": {
                    "prompt_zh": "未扫到 arch* 目录，请手工输入 architecture",
                    "options": [],
                    "allow_free_text": True,
                    "field": "architecture",
                },
            }
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "architecture",
            "reason_code": "ARCHITECTURE_REQUIRED",
            "workflow_id": wf,
            "project": str(root),
            "architecture_options": labels,
            "architecture_option_details": options,
            "message_zh": (
                f"缺少 --architecture，不能启动。已扫描到: {', '.join(labels)}。\n"
                "AskQuestion 选完后，用 "
                f'`acp start {wf} --project "{root}" --architecture <选中>` '
                "一次启动（此前不会创建 run）。"
            ),
            "ask_question": {
                "prompt_zh": "请选择目标 architecture（选项来自算子仓 arch* 目录）",
                "options": options,
                "allow_free_text": False,
                "field": "architecture",
            },
            "suggested_command": (
                f'acp start {wf} --project "{root}" --architecture <{",".join(labels)}>'
            ),
            "primary_instruction_zh": (
                "先 AskQuestion；选项必须原样使用 architecture_option_details。"
                "选完后执行 suggested_command（带齐 --project 与 --architecture 的一次 start）。"
                "禁止编造仓内不存在的 arch。"
            ),
        }

    if wf in _WORKFLOWS_NEED_ARCH and arch and looks_like_operator_package(root):
        known = discover_architectures(root)
        if known and arch not in known:
            return {
                "ok": False,
                "needs_human_decision": True,
                "decision_kind": "architecture",
                "reason_code": "ARCHITECTURE_NOT_IN_TREE",
                "workflow_id": wf,
                "project": str(root),
                "architecture": arch,
                "architecture_options": known,
                "architecture_option_details": describe_architectures(root),
                "message_zh": (
                    f"指定的 architecture={arch} 不在算子仓 arch* 目录中。"
                    f"仓内仅有: {', '.join(known)}。请重新选择后再 start。"
                ),
                "ask_question": {
                    "prompt_zh": "请从算子仓实际 arch* 中选择",
                    "options": describe_architectures(root),
                    "allow_free_text": False,
                    "field": "architecture",
                },
                "suggested_command": (
                    f'acp start {wf} --project "{root}" --architecture <{",".join(known)}>'
                ),
            }

    return None
