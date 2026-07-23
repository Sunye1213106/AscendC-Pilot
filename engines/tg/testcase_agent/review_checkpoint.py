from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import output_root, read_json, read_yaml, resolve_plan_dir, write_yaml

# Primary AskQuestion buttons (OpenCode question UI).
GATE_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "plan": [
        ("approve", "批准当前计划并立即 tg-solve（仅当 Allow solve: yes）"),
        ("confirm_domain", "域/绑定未确认：回 tg-init（含绑定/uo-query）再 plan"),
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
    parser.add_argument(
        "--decision",
        required=True,
        help="approve | confirm_domain | reject | suggest",
    )
    parser.add_argument("--notes", default="", help="Modification suggestions or reject reason")
    parser.add_argument(
        "--level",
        default="",
        help="Approve archived level plan, e.g. L0. Omit to use plan/latest_level.yaml.",
    )
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
    plan_dir = resolve_plan_dir(out_root, level)
    obligations_path = plan_dir / "coverage_obligations.yaml"
    supplement_path = plan_dir / "human_supplement.yaml"
    unresolved_path = plan_dir / "unresolved.yaml"
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Missing snapshot. Run tg-plan first: {snapshot_path}")

    snapshot = read_json(snapshot_path)
    obligations = read_yaml(obligations_path)
    unresolved = read_yaml(unresolved_path) if unresolved_path.is_file() else {}
    if not isinstance(unresolved, dict):
        unresolved = {}

    if choice == "approve":
        blocked = _approve_block_reason(out_root, unresolved)
        if blocked:
            raise ValueError(blocked)

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
    current["options"] = [value for value, _ in GATE_OPTIONS["plan"]]
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
    elif choice == "confirm_domain":
        current["status"] = "domain_review_required"
        current["approved_snapshot_hash"] = ""
        current["approved_plan_hash"] = ""
        current["approved_at"] = ""
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
        "test_level": current.get("test_level") or "",
        "approved_snapshot_hash": current.get("approved_snapshot_hash") or "",
        "approved_plan_hash": current.get("approved_plan_hash") or "",
        "next": _next_hint(choice),
    }


def _approve_block_reason(out_root: Path, unresolved: dict[str, Any]) -> str | None:
    """Hard-fail approve when Allow solve is no / domain·binding gaps remain."""
    if unresolved.get("allow_solve") is False:
        reason = unresolved.get("allow_solve_reason") or "allow_solve_no"
        return (
            f"APPROVE_BLOCKED: Allow solve: no ({reason}). "
            "Run tg-init --merge-uo-resolve / fix KEY bindings or reject empty L1-REJECT; do not force approve."
        )
    # Also parse review.md Allow solve line if flag missing (legacy plans).
    status = str(unresolved.get("status") or "").strip().lower()
    blocking = unresolved.get("blocking_hard_obligations") or []
    gaps = [g for g in (unresolved.get("contract_gaps") or []) if isinstance(g, dict)]
    if status == "blocked" or blocking:
        return (
            "APPROVE_BLOCKED: unresolved.status=blocked or hard blockers present "
            "(Allow solve: no). Fix blockers / re-run tg-plan; do not forge gaps."
        )
    for gap in gaps:
        reason = str(gap.get("reason") or "")
        if "DOMAIN_REVIEW_REQUIRED" in reason or "BINDING_REVIEW_REQUIRED" in reason:
            return (
                f"APPROVE_BLOCKED: {reason} "
                "Run tg-init (bind + confirm) / AskQuestion confirm_domain first; "
                "do not clear contract_gaps by hand."
            )
    if gaps:
        return (
            "APPROVE_BLOCKED: contract_gaps present (Allow solve: no). "
            "Resolve gaps via domain-review/hints; do not force approve."
        )

    # Defense in depth: also read realization/ even if plan gates were skipped.
    realization = out_root / "realization"
    review_path = realization / "domain_review.yaml"
    if review_path.is_file():
        review = read_yaml(review_path)
        pending = list(review.get("pending_columns") or [])
        rstatus = str(review.get("status") or "").lower()
        if rstatus not in {"confirmed", "human", "llm_confirmed"} and pending:
            sample = ", ".join(str(c) for c in pending[:6])
            return (
                f"APPROVE_BLOCKED: DOMAIN_REVIEW_REQUIRED ({len(pending)} columns, e.g. {sample}). "
                "Run tg-init; do not forge domain_review.status=confirmed."
            )
    unresolved_path = realization / "unresolved.yaml"
    if unresolved_path.is_file():
        doc = read_yaml(unresolved_path)
        binding_gaps = [g for g in (doc.get("binding_gaps") or []) if isinstance(g, dict)]
        hard = [g for g in binding_gaps if str(g.get("code") or "") in {"MISSING_CSV_REF", "UNBOUND_KEY"}]
        if hard:
            lexicon_path = realization / "binding_lexicon.yaml"
            lexicon = read_yaml(lexicon_path) if lexicon_path.is_file() else {}
            locked = {
                str(item.get("id") or "")
                for item in (lexicon.get("key_derivations") or [])
                if isinstance(item, dict)
                and (
                    item.get("locked") is True
                    or str(item.get("status") or "").lower() in {"locked", "confirmed", "human"}
                )
            }
            still = [g for g in hard if str(g.get("variable_id") or "") not in locked]
            if still:
                return (
                    f"APPROVE_BLOCKED: BINDING_REVIEW_REQUIRED ({len(still)} KEY↔CSV gaps). "
                    "Lock lexicon via tg-init; do not clear binding_gaps by hand."
                )
    return None


def _next_hint(choice: str) -> str:
    if choice == "approve":
        return "immediately run tg-solve"
    if choice == "confirm_domain":
        return "run tg-init / AskQuestion, then re-run tg-plan"
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
