#!/usr/bin/env python3
"""Validate Obligation Ledger monotonicity and evidence pointers.

Usage:
  python scripts/check_obligation_ledger.py [--root PATH]
  python scripts/check_obligation_ledger.py --self-test
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


def _ensure_path() -> None:
    repo = Path(__file__).resolve().parents[1]
    pilot = repo / "pilot"
    if str(pilot) not in sys.path:
        sys.path.insert(0, str(pilot))


def self_test() -> list[str]:
    _ensure_path()
    from ascendc_pilot.obligations.ledger import (
        can_transition,
        load_ledger,
        save_ledger,
        upsert_item,
        validate_ledger,
    )
    from ascendc_pilot.paths import ensure_agent_layout

    errors: list[str] = []
    if not can_transition("open", "verified"):
        errors.append("open→verified should be allowed")
    if can_transition("verified", "open"):
        errors.append("verified→open should require explicit revert")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ensure_agent_layout(root, arch="arch0")
        # Force arch for state_root via env-less default: write under arch0 by setting state.
        # ensure_agent_layout creates .ascendc-pilot/<arch>/…
        ledger = load_ledger(root)
        upsert_item(ledger, oid="OBL_A", status="open", reason="seed")
        upsert_item(ledger, oid="OBL_A", status="candidate", reason="progress")
        upsert_item(ledger, oid="OBL_A", status="verified", settled_by_gate="g1",
                    evidence=[{"gate_id": "g1", "run_id": "R1"}], reason="gate")
        save_ledger(root, ledger)
        loaded = load_ledger(root)
        errs = validate_ledger(loaded)
        errors.extend(errs)
        item = (loaded.get("items") or {}).get("OBL_A") or {}
        if item.get("status") != "verified":
            errors.append(f"expected verified, got {item.get('status')}")
        # Illegal silent downgrade must be refused.
        upsert_item(ledger, oid="OBL_A", status="open", reason="bad_downgrade", allow_revert=False)
        if (ledger.get("items") or {}).get("OBL_A", {}).get("status") != "verified":
            errors.append("silent downgrade should be refused")
    return errors


def check_root(root: Path) -> list[str]:
    _ensure_path()
    from ascendc_pilot.obligations.ledger import load_ledger, validate_ledger
    from ascendc_pilot.paths import state_root

    # If no ledger yet, that is OK (not every operator has started a run).
    path = state_root(root) / "obligation_ledger.yaml"
    if not path.is_file():
        return []
    return validate_ledger(load_ledger(root))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=None, help="operator project root")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        errors = self_test()
        print({"ok": not errors, "errors": errors})
        return 0 if not errors else 1
    if args.root is None:
        # Default: self-test in CI when no operator root is provided.
        errors = self_test()
        print({"ok": not errors, "mode": "self-test", "errors": errors})
        return 0 if not errors else 1
    errors = check_root(args.root)
    print({"ok": not errors, "root": str(args.root), "errors": errors})
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
