from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import operator_root, safe_op_name, write_text


GATE_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "macro_scope": [
        ("continue", "按当前范围进入 Phase 1 Macro Boundary"),
        ("revise", "调整 include/exclude/skip 后重新展示"),
        ("stop", "停止 workflow"),
        ("manual_supplement", "手工补充（在聊天里写补充内容）"),
    ],
    "boundary": [
        ("continue", "边界可接受，继续 Tiling / Compute-Dataflow"),
        ("revise", "修订 Macro Boundary 产物后重新审阅"),
        ("stop", "停止 workflow"),
        ("manual_supplement", "手工补充（在聊天里写补充内容）"),
    ],
    "kernel_dispatch": [
        ("dispatch_all", "分发全部可自动 dispatch 的 kernel tasks"),
        ("dispatch_subset", "只分发指定 task_id 子集"),
        ("revise", "修订 kernel/paths.yaml 后重新审阅"),
        ("stop", "停止 workflow，不分发"),
        ("manual_supplement", "手工补充（在聊天里写补充内容）"),
    ],
    "query_missing_kb": [
        ("init", "运行 /uo-init 构建完整 KB 后再查询"),
        ("source", "不建库，直接 CBM→源码回答本次问题"),
        ("stop", "取消本次查询"),
        ("manual_supplement", "手工补充（说明 KB 路径/op-name）"),
    ],
}

GATE_OUTPUT: dict[str, str] = {
    "macro_scope": "archive/runs/macro_scope_decision.json",
    "boundary": "archive/runs/boundary_decision.json",
    "kernel_dispatch": "human/kernel_dispatch_decision.json",
    "query_missing_kb": "archive/runs/query_missing_kb_decision.json",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Human-review decision helper for understand-operator. "
            "Default is chat-first (no stdin grab). Use --decision to record a choice."
        ),
    )
    parser.add_argument("repo", nargs="?", default=".", help="AscendC repository root")
    parser.add_argument("--op-name", help="Operator name")
    parser.add_argument(
        "--gate",
        required=True,
        choices=sorted(GATE_OPTIONS),
        help="Which review gate to present",
    )
    parser.add_argument("--title", default="", help="Optional menu title override")
    parser.add_argument(
        "--default",
        default=None,
        help="Default option value when printing the menu",
    )
    parser.add_argument(
        "--decision",
        default=None,
        help="Apply a decision without interactive stdin (continue|revise|stop|...).",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional notes / manual_supplement text (for --decision)",
    )
    parser.add_argument(
        "--approved-task-ids",
        default="",
        help="Comma/space separated task ids when decision=dispatch_subset",
    )
    parser.add_argument(
        "--print-menu",
        action="store_true",
        help="Only print the option list for chat; do not wait for stdin",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Opt-in terminal menu (numbered input). Avoid in OpenCode/agent shells.",
    )
    parser.add_argument(
        "--arrows",
        action="store_true",
        help="Opt-in arrow-key menu. ONLY in a real local terminal; breaks chat input if used in agent UI.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    base = operator_root(repo_root, op_name)
    if args.gate == "query_missing_kb":
        (base / "summary").mkdir(parents=True, exist_ok=True)
    elif not base.exists():
        print(f"KB not found: {base}", file=sys.stderr)
        print("Run /uo-init first.", file=sys.stderr)
        return 2

    options = GATE_OPTIONS[args.gate]
    values = [v for v, _ in options]
    default_idx = 0
    if args.default and args.default in values:
        default_idx = values.index(args.default)

    title = args.title or _default_title(args.gate)

    # --- Mode A: apply decision from chat / agent (preferred) ---
    if args.decision:
        choice = _normalize_choice(args.decision, values)
        if choice is None:
            print(f"Invalid --decision {args.decision!r}. Allowed: {', '.join(values)}", file=sys.stderr)
            _print_menu(title, args.gate, op_name, options, default_idx, chat_hint=True)
            return 2
        notes = str(args.notes or "").strip()
        approved_task_ids = [x for x in str(args.approved_task_ids or "").replace(",", " ").split() if x]
        if choice == "dispatch_subset" and not approved_task_ids:
            print("decision=dispatch_subset requires --approved-task-ids", file=sys.stderr)
            return 2
        return _commit(
            base,
            gate=args.gate,
            op_name=op_name,
            choice=choice,
            notes=notes,
            approved_task_ids=approved_task_ids,
            ui="chat_decision",
        )

    # --- Mode B: print menu for chat, exit (default for agent UX) ---
    if args.print_menu or (not args.interactive and not args.arrows):
        _print_menu(title, args.gate, op_name, options, default_idx, chat_hint=True)
        print("UO_REVIEW_DECISION=pending")
        print("UO_REVIEW_MODE=chat")
        return 0

    # --- Mode C: opt-in interactive terminal (may block stdin) ---
    print()
    print("=" * 60)
    print(title)
    print(f"gate: {args.gate}    op: {op_name}")
    print("=" * 60)

    use_arrows = bool(args.arrows) and sys.stdin.isatty() and sys.stdout.isatty()
    if use_arrows:
        print("操作: ↑/↓ 选择  Enter 确认  |  数字键快捷选")
        _enable_windows_ansi()
        choice = _arrow_menu(options, default_idx)
        ui = "arrow_menu"
    else:
        print("操作: 输入序号或选项名后回车")
        choice = _numbered_menu(options, default_idx)
        ui = "numbered_menu"

    notes = ""
    approved_task_ids: list[str] = []
    if choice == "manual_supplement":
        notes = _prompt_multiline(
            "请输入手工补充内容（空行结束；直接回车可跳过）：",
        )
    elif choice == "dispatch_subset":
        raw = input("请输入要分发的 task_id（逗号或空格分隔）: ").strip()
        approved_task_ids = [x for x in raw.replace(",", " ").split() if x]
        if not approved_task_ids:
            print("未提供 task_id，已改回 revise。")
            choice = "revise"
            notes = "dispatch_subset without task ids"

    return _commit(
        base,
        gate=args.gate,
        op_name=op_name,
        choice=choice,
        notes=notes,
        approved_task_ids=approved_task_ids,
        ui=ui,
    )


def _commit(
    base: Path,
    *,
    gate: str,
    op_name: str,
    choice: str,
    notes: str,
    approved_task_ids: list[str],
    ui: str,
) -> int:
    decision = {
        "gate": gate,
        "op_name": op_name,
        "decision": choice,
        "notes": notes,
        "approved_task_ids": approved_task_ids,
        "decided_at": datetime.now(tz=timezone.utc).isoformat(),
        "reviewer": os.environ.get("USERNAME") or os.environ.get("USER") or "user",
        "ui": ui,
    }
    out_path = base / GATE_OUTPUT[gate]
    write_text(out_path, json.dumps(decision, ensure_ascii=False, indent=2) + "\n")
    _patch_review_yaml(base, gate, decision)

    print()
    print(f"已选择: {choice}")
    if notes:
        print(f"手工补充: {notes[:200]}{'...' if len(notes) > 200 else ''}")
    if approved_task_ids:
        print(f"approved_task_ids: {', '.join(approved_task_ids)}")
    print(f"写入: {out_path}")
    print(f"UO_REVIEW_DECISION={choice}")
    return 0


def _normalize_choice(raw: str, values: list[str]) -> str | None:
    text = raw.strip().replace("-", "_")
    if text in values:
        return text
    # allow numeric index 1..N
    if text.isdigit():
        n = int(text)
        if 1 <= n <= len(values):
            return values[n - 1]
    aliases = {
        "yes": "continue",
        "ok": "continue",
        "y": "continue",
        "n": "stop",
        "cancel": "stop",
        "手工补充": "manual_supplement",
        "补充": "manual_supplement",
    }
    mapped = aliases.get(text.lower()) or aliases.get(raw.strip())
    if mapped and mapped in values:
        return mapped
    return None


def _print_menu(
    title: str,
    gate: str,
    op_name: str,
    options: list[tuple[str, str]],
    default_idx: int,
    *,
    chat_hint: bool,
) -> None:
    print()
    print("=" * 60)
    print(title)
    print(f"gate: {gate}    op: {op_name}")
    if chat_hint:
        print("请在聊天输入框直接回复选项名或序号（不要依赖终端弹窗）")
        print("例如: continue   或   1   或   manual_supplement: 只看 arch35")
    print("=" * 60)
    for i, (value, desc) in enumerate(options, start=1):
        mark = "*" if i - 1 == default_idx else " "
        print(f"  {mark} [{i}] {value}  —  {desc}")
    print()
    print("Agent 收到用户回复后执行:")
    print(
        f'  python review_checkpoint.py <repo> --op-name {op_name} --gate {gate} '
        f'--decision <choice> [--notes "..."]'
    )


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _default_title(gate: str) -> str:
    return {
        "macro_scope": "Phase 0.5 · Macro Scope 人工审阅",
        "boundary": "Phase 1.5 · Boundary 人工审阅",
        "kernel_dispatch": "Retired · Kernel Dispatch",
        "query_missing_kb": "uo-query · 未找到 KB",
    }[gate]


def _arrow_menu(options: list[tuple[str, str]], default_idx: int) -> str:
    idx = default_idx
    painted = False
    _hide_cursor()
    try:
        while True:
            if painted:
                sys.stdout.write(f"\x1b[{len(options)}A")
            for i, (value, desc) in enumerate(options):
                if i == idx:
                    line = f"  \x1b[7m❯ [{i + 1}] {value}\x1b[0m  —  {desc}"
                else:
                    line = f"    [{i + 1}] {value}  —  {desc}"
                sys.stdout.write("\x1b[2K" + line + "\n")
            sys.stdout.flush()
            painted = True
            key = _read_key()
            if key == "up":
                idx = (idx - 1) % len(options)
            elif key == "down":
                idx = (idx + 1) % len(options)
            elif key == "enter":
                return options[idx][0]
            elif key == "esc":
                for value, _ in options:
                    if value == "stop":
                        return "stop"
                return options[min(len(options) - 1, 2)][0]
            elif key.isdigit():
                n = int(key)
                if 1 <= n <= len(options):
                    return options[n - 1][0]
    finally:
        _show_cursor()
        print()


def _numbered_menu(options: list[tuple[str, str]], default_idx: int) -> str:
    for i, (value, desc) in enumerate(options, start=1):
        mark = "*" if i - 1 == default_idx else " "
        print(f"  {mark} [{i}] {value}  —  {desc}")
    print()
    default_value = options[default_idx][0]
    while True:
        raw = input(f"请输入序号 1-{len(options)}（默认 {default_idx + 1}={default_value}）: ").strip()
        if not raw:
            return default_value
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        for value, _ in options:
            if raw == value or raw.replace("-", "_") == value:
                return value
        print("无效输入，请重试。")


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            return "esc"
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H":
                return "up"
            if ch2 == "P":
                return "down"
            return ""
        if ch.isdigit():
            return ch
        if ch in ("k", "K"):
            return "up"
        if ch in ("j", "J"):
            return "down"
        return ""

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            rest = sys.stdin.read(2)
            if rest == "[A":
                return "up"
            if rest == "[B":
                return "down"
            return "esc"
        if ch.isdigit():
            return ch
        if ch in ("k", "K"):
            return "up"
        if ch in ("j", "J"):
            return "down"
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _hide_cursor() -> None:
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()


def _show_cursor() -> None:
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


def _prompt_multiline(header: str) -> str:
    print(header)
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _patch_review_yaml(base: Path, gate: str, decision: dict[str, Any]) -> None:
    if gate == "query_missing_kb":
        path = base / "archive" / "runs" / "query_missing_kb_review.yaml"
        write_text(
            path,
            (
                "checkpoint: query_missing_kb\n"
                f"status: {_status_for(decision['decision'])}\n"
                f"decision: {decision['decision']}\n"
                f"reviewer: {decision.get('reviewer') or 'user'}\n"
                f"reviewed_at: \"{decision['decided_at']}\"\n"
                f"comments: \"{_yaml_escape(str(decision.get('notes') or ''))}\"\n"
            ),
        )
        return

    mapping = {
        "macro_scope": base / "archive" / "runs" / "macro_scope_review.yaml",
        "boundary": base / "archive" / "runs" / "boundary_review.yaml",
        "kernel_dispatch": base / "human" / "kernel_dispatch_review.yaml",
    }
    path = mapping[gate]
    stamp = decision["decided_at"]
    value = decision["decision"]
    notes = str(decision.get("notes") or "").replace("\n", " ").strip()
    reviewer = decision.get("reviewer") or "user"

    if not path.exists():
        if gate == "macro_scope":
            body = (
                "phase: \"0.5\"\n"
                "status: decided\n"
                "decision:\n"
                f"  value: {value}\n"
                f"  decided_at: \"{stamp}\"\n"
                f"  notes: \"{_yaml_escape(notes)}\"\n"
                f"reviewer: {reviewer}\n"
            )
        elif gate == "boundary":
            body = (
                "checkpoint: boundary\n"
                f"status: {_status_for(value)}\n"
                f"decision: {value}\n"
                f"reviewer: {reviewer}\n"
                f"reviewed_at: \"{stamp}\"\n"
                f"comments: \"{_yaml_escape(notes)}\"\n"
            )
        else:
            ids = decision.get("approved_task_ids") or []
            id_lines = "\n".join(f"  - {x}" for x in ids) if ids else "  []"
            body = (
                "checkpoint: kernel_dispatch\n"
                f"status: {_status_for(value)}\n"
                f"decision: {value}\n"
                f"reviewer: {reviewer}\n"
                f"reviewed_at: \"{stamp}\"\n"
                f"comments: \"{_yaml_escape(notes)}\"\n"
                "approved_task_ids:\n"
                f"{id_lines}\n"
            )
        write_text(path, body)
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    if gate == "macro_scope":
        text = _upsert_block(
            text,
            "decision:",
            (
                "decision:\n"
                f"  value: {value}\n"
                f"  decided_at: \"{stamp}\"\n"
                f"  notes: \"{_yaml_escape(notes)}\"\n"
            ),
        )
        if "status:" in text:
            text = _replace_top_key(text, "status", "decided")
        else:
            text = f"status: decided\n{text}"
    else:
        text = _replace_top_key(text, "decision", value)
        text = _replace_top_key(text, "status", _status_for(value))
        text = _replace_top_key(text, "reviewed_at", f"\"{stamp}\"")
        text = _replace_top_key(text, "comments", f"\"{_yaml_escape(notes)}\"")
        if gate == "kernel_dispatch" and decision.get("approved_task_ids"):
            ids = decision["approved_task_ids"]
            block = "approved_task_ids:\n" + "\n".join(f"  - {x}" for x in ids) + "\n"
            text = _upsert_block(text, "approved_task_ids:", block)
    write_text(path, text if text.endswith("\n") else text + "\n")


def _status_for(value: str) -> str:
    if value in ("continue", "dispatch_all", "dispatch_subset", "init", "source"):
        return "approved"
    if value in ("revise", "manual_supplement"):
        return "revision_requested"
    if value == "stop":
        return "rejected"
    return "pending"


def _yaml_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _replace_top_key(text: str, key: str, value: str) -> str:
    import re

    pattern = rf"(?m)^({re.escape(key)}\s*:\s*).*$"
    if re.search(pattern, text):
        return re.sub(pattern, rf"\1{value}", text, count=1)
    return text.rstrip() + f"\n{key}: {value}\n"


def _upsert_block(text: str, header: str, block: str) -> str:
    import re

    pattern = rf"(?ms)^{re.escape(header)}.*?(?=^[A-Za-z_][\w-]*:|\Z)"
    if re.search(pattern, text):
        return re.sub(pattern, block, text, count=1)
    return text.rstrip() + "\n" + block


if __name__ == "__main__":
    raise SystemExit(main())
