# -*- coding: utf-8 -*-
"""Where the implicit-initial-value variables come from, and what they cost.

`_chain` walks an if/else-if chain of writes. When no unguarded write closes it
and the declaration could not be read, the value on the fallthrough path is
whatever the variable held before -- unknown. `_init_var` mints a `VAR_INIT_*`
free variable to say so honestly rather than assuming zero.

Honest, but not free: each one is an unconstrained integer, so it keeps its
dimension off `exact`, and multiplying two of them is what makes the solver's
job nonlinear. This says which assignments produce them, so the ones worth
closing can be picked by how many dimensions they block rather than by guess.

Read-only. Reads what `_probe_derive.py` cached.

    python scripts/_probe_init.py            # grouped by the variable assigned
    python scripts/_probe_init.py --sites    # one line per site
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / ".probe_cache" / "fag_derive.json"


def load() -> list[dict[str, Any]]:
    if not RESULT.is_file():
        raise SystemExit("no cached derivation; run scripts/_probe_derive.py first")
    return json.loads(RESULT.read_text(encoding="utf-8"))["fields"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sites", action="store_true", help="one line per site")
    args = ap.parse_args()

    fields = load()

    # variable -> dimensions whose expression still carries it. A record whose
    # variable simplified out of every expression cost nothing and should not
    # be ranked alongside one that blocks five dimensions.
    blocks: dict[str, set[str]] = defaultdict(set)
    for f in fields:
        for var in f.get("free_vars") or []:
            blocks[var].add(f["name"])

    records: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    seen_by: dict[tuple[str, str, str, int], set[str]] = defaultdict(set)
    for f in fields:
        for rec in f.get("implicit_defaults") or []:
            key = (
                str(rec.get("field") or ""),
                str(rec.get("function") or ""),
                str(rec.get("file") or ""),
                int(rec.get("line") or 0),
            )
            records.setdefault(key, rec)
            seen_by[key].add(f["name"])

    live = {v for v, dims in blocks.items() if dims and v.startswith("VAR_INIT_")}
    print(f"implicit-default sites : {len(records)}")
    print(f"VAR_INIT_ variables    : {len({r.get('variable') for r in records.values()})}")
    print(f"  still in an expression: {len(live)}")
    print(f"  simplified away       : {len(records) - len(live)}")

    # Grouped by the variable being assigned: one local assigned in six places
    # is one thing to fix, not six.
    by_name: dict[str, list[tuple[tuple, dict[str, Any]]]] = defaultdict(list)
    for key, rec in records.items():
        by_name[key[0]].append((key, rec))

    def cost(name: str) -> tuple[int, int]:
        dims: set[str] = set()
        for key, rec in by_name[name]:
            dims |= blocks.get(str(rec.get("variable") or ""), set())
        return len(dims), len(by_name[name])

    print("\nby variable assigned, worst first:")
    print(f"  {'variable':34} {'dims':>4} {'sites':>5}  functions")
    for name in sorted(by_name, key=lambda n: (-cost(n)[0], -cost(n)[1], n)):
        dims, sites = cost(name)
        fns = sorted({str(r.get("function") or "?") for _, r in by_name[name]})
        shown = ", ".join(fns[:3]) + (f" +{len(fns) - 3}" if len(fns) > 3 else "")
        print(f"  {name[:34]:34} {dims:>4} {sites:>5}  {shown}")

    if args.sites:
        print("\nper site:")
        for name in sorted(by_name):
            for key, rec in sorted(by_name[name], key=lambda kv: kv[0][2:]):
                var = str(rec.get("variable") or "")
                where = f"{Path(key[2]).name}:{key[3]}"
                dims = sorted(blocks.get(var, ()))
                print(f"  {name[:28]:28} {where:44} {var}")
                print(f"      guard  {str(rec.get('guard') or '')[:100]}")
                print(f"      blocks {', '.join(dims) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
