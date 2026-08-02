# -*- coding: utf-8 -*-
"""What is left free, and what would it take to close it?

Reads the last derivation and traces every free variable back to the record
that minted it: an implicit default (a read with no write proven before it),
an undecided guard (a condition the normaliser could not compile), or a loop
element (a value produced inside a loop).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
CACHE = ROOT / ".probe_cache"


def main() -> int:
    blob = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    fields = blob["fields"]

    where: dict[str, set[str]] = defaultdict(set)
    for f in fields:
        for v in f.get("free_vars") or []:
            where[v].add(f["name"])

    minted: dict[str, dict] = {}
    for f in fields:
        for rec in f.get("implicit_defaults") or []:
            minted.setdefault(rec.get("variable") or "", {}).update(
                {
                    "kind": "implicit_default",
                    "field": rec.get("field"),
                    "function": rec.get("function"),
                    "line": rec.get("line"),
                    "reason": rec.get("reason"),
                }
            )
        for rec in f.get("undecided_guards") or []:
            minted.setdefault(rec.get("variable") or "", {}).update(
                {
                    "kind": "undecided_guard",
                    "field": rec.get("text") or rec.get("guard"),
                    "function": rec.get("function"),
                    "line": rec.get("line"),
                    "reason": rec.get("blocked_on") or rec.get("reason"),
                }
            )

    print(f"{len(where)} distinct free variables\n")
    for var in sorted(where, key=lambda v: (-len(where[v]), v)):
        rec = minted.get(var, {})
        dims = sorted(where[var])
        print(f"{var}")
        print(f"    blocks {len(dims)} dims: {', '.join(dims)}")
        if rec:
            site = f"{rec.get('function') or '?'}:{rec.get('line') or 0}"
            print(f"    minted as {rec.get('kind')} at {site}")
            print(f"    for       {rec.get('field')}")
            if rec.get("reason"):
                print(f"    because   {rec.get('reason')}")
        else:
            print("    no minting record found")
        print()

    print("--- per dimension ---")
    for f in fields:
        free = f.get("free_vars") or []
        if free:
            print(f"  {f['name']:16} {len(free)} free: {', '.join(sorted(free))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
