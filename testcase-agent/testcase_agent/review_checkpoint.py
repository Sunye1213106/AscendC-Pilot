from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import output_root, read_json, read_yaml, write_yaml

# Primary AskQuestion buttons (OpenCode question UI).
GATE_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "plan": [
        ("approve", "批准当前计划，并立即执行 tg-solve"),
        ("reject", "拒绝当前计划，结束本次流程"),
        ("suggest", "给出修改建议（调整后重跑 tg-plan 再审阅）"),
    ],
}

# Keep old names working so existing docs/tests do not break.
_ALIASES = {
    "stop": "reject",
    "revise": "suggest",
    "supplement": "suggest",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Human-review decision helper for tg-plan.")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--gate", default="plan", choices=sorted(GATE_OPTIONS))
    parser.add_argument("--decision", required=True, help="approve | reject | suggest")
    parser.add_argument("--notes", default="", help="Modification suggestions or reject reason")
    parser.add_argument("--level", default="", help="Approve archived level plan, e.g. L0,L1,L2. Omit for top-level plan.")
    parser.add_argument("--print-menu", action="store_true")
    args = parser.parse_args(argv)

    options = GATE_OPTIONS[args.gate]
    values = [value for value, _ in options]
    if args.print_menu:
        _print_menu(args.gate, args.op_name, options)
        print("TG_REVIEW_DECISION=pending")
        print("TG_REVIEW_MODE=chat")
        return 0

    raw = str(args.decision or "").strip().lower()
    choice = _ALIASES.get(raw, raw)
    if choice not in values:
        print(f"Invalid --decision {args.decision!r}. Allowed: {', '.join(values)}", file=sys.stderr)
        _print_menu(args.gate, args.op_name, options)
        return 2

    project_root = args.project_root.resolve()
    out_root = output_root(project_root, args.op_name)
    if not out_root.exists():
        print(f"Plan output not found: {out_root}", file=sys.stderr)
        return 2

    try:
        payload = _commit_plan_decision(
            out_root,
            op_name=args.op_name,
            choice=choice,
            notes=str(args.notes or "").strip(),
            level=str(args.level or "").strip().upper(),
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"TG_REVIEW_DECISION={choice}")
    return 0


def _commit_plan_decision(out_root: Path, *, op_name: str, choice: str, notes: str, level: str = "") -> dict[str, Any]:
    snapshot_path = out_root / "snapshot" / "understand_contract.json"
    plan_dir = out_root / "plan" / "levels" / level if level else out_root / "plan"
    obligations_path = plan_dir / "coverage_obligations.yaml"
    supplement_path = plan_dir / "human_supplement.yaml"
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Missing snapshot. Run tg-plan first: {snapshot_path}")
    if not obligations_path.exists():
        raise FileNotFoundError(f"Missing coverage plan. Run tg-plan first: {obligations_path}")

    snapshot = read_json(snapshot_path)
    obligations = read_yaml(obligations_path)
    current = read_yaml(supplement_path) if supplement_path.exists() else {}
    if not isinstance(current, dict):
        current = {}

    snapshot_hash = snapshot.get("snapshot_hash") or ""
    plan_hash = obligations.get("plan_hash") or ""
    if not snapshot_hash or not plan_hash:
        raise ValueError("PLAN_HASH_MISSING: snapshot_hash/plan_hash required before review commit")

    now = datetime.now(tz=timezone.utc).isoformat()
    current.setdefault("version", 1)
    current.setdefault("supplements", [])
    current["options"] = ["approve", "reject", "suggest"]
    current["decision"] = choice
    current["notes"] = notes or current.get("notes") or ""
    current["reviewed_at"] = now
    current["reviewer"] = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    current["ui"] = "chat_decision"
    current["op_name"] = op_name
    current["test_level"] = obligations.get("test_level") or current.get("test_level") or ""

    if choice == "approve":
        current["status"] = "approved"
        current["approved_snapshot_hash"] = snapshot_hash
        current["approved_plan_hash"] = plan_hash
        current["approved_at"] = now
    elif choice == "reject":
        current["status"] = "rejected"
        current["approved_snapshot_hash"] = ""
        current["approved_plan_hash"] = ""
        current["approved_at"] = ""
    else:
        # suggest: keep hashes empty so tg-solve cannot proceed
        current["status"] = "suggest_recorded"
        current["approved_snapshot_hash"] = ""
        current["approved_plan_hash"] = ""
        current["approved_at"] = ""

    write_yaml(supplement_path, current)
    return {
        "status": current["status"],
        "decision": choice,
        "path": str(supplement_path),
        "approved_snapshot_hash": current.get("approved_snapshot_hash") or "",
        "approved_plan_hash": current.get("approved_plan_hash") or "",
        "next": _next_hint(choice),
    }


def _next_hint(choice: str) -> str:
    if choice == "approve":
        return "immediately run tg-solve"
    if choice == "suggest":
        return "apply modification suggestions, re-run tg-plan, then AskQuestion again"
    return "workflow stopped"


def _print_menu(gate: str, op_name: str, options: list[tuple[str, str]]) -> None:
    print(f"TG_REVIEW_GATE={gate}")
    print(f"TG_REVIEW_OP={op_name}")
    print("Present AskQuestion / question UI buttons:")
    for value, help_text in options:
        print(f"- {value}: {help_text}")


if __name__ == "__main__":
    raise SystemExit(main())
