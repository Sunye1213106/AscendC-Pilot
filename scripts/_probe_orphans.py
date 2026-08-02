# -*- coding: utf-8 -*-
"""How many functions still write state with nothing recorded calling them?

Every one of those is a place where dropping a write, or assuming a function
ran, rests on a call graph we know to be incomplete.
"""
from __future__ import annotations

import pickle
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
CACHE = ROOT / ".probe_cache"


def main() -> int:
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        ir = pickle.load(fh)["host_ir"]

    writers: Counter[str] = Counter()
    for w in (*ir.writes, *getattr(ir, "local_writes", ())):
        if w.function:
            writers[w.function] += 1

    called = {s.callee for s in ir.call_sites}
    orphans = sorted(fn for fn in writers if fn not in called)

    print(f"functions with writes:            {len(writers)}")
    print(f"of those, nothing calls them:     {len(orphans)}")
    print(f"total recorded call sites:        {len(ir.call_sites)}")
    print(f"distinct callees:                 {len(called)}\n")

    print("the 25 orphans that write the most state:")
    for fn in sorted(orphans, key=lambda f: -writers[f])[:25]:
        print(f"  {writers[fn]:5d} writes  {fn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
