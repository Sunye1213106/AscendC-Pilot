# -*- coding: utf-8 -*-
"""Where a soft variable comes back from, and what type it is declared with.

A variable minted inside a derivation worker exists only in that process. The
parent re-declares it from whatever record came back, and if the record does
not carry the type, the type is guessed from the name. This prints both sides
so the guess can be compared with what the worker actually meant.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))


def walk(node, hits, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and v.startswith("VAR_SCHED_"):
                hits[v].add(f"{path}.{k}")
            walk(v, hits, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, hits, f"{path}[]")


def main() -> int:
    from collections import defaultdict

    blob = json.loads((ROOT / ".probe_cache" / "fag_derive.json").read_text("utf-8"))

    hits: dict[str, set[str]] = defaultdict(set)
    walk(blob, hits)
    sched = sorted(hits)
    print(f"VAR_SCHED_* mentioned: {len(sched)}")

    shapes = Counter()
    for name in sched:
        # A hashed guard is 12 hex characters; anything else was named after a
        # source symbol, which is how the two kinds can be told apart at all.
        tail = name[len("VAR_SCHED_"):]
        kind = "hashed guard" if len(tail) == 12 and all(
            c in "0123456789abcdef" for c in tail
        ) else "named symbol"
        shapes[kind] += 1
        if kind == "named symbol":
            print(f"  {name}")
            for where in sorted(hits[name])[:6]:
                print(f"      {where}")
    print(dict(shapes))

    # What the parent would declare each one as.
    from uo_init.host_derivation import _SOFT_VAR_KINDS, presort_guard

    for name in sched:
        tail = name[len("VAR_SCHED_"):]
        if len(tail) == 12 and all(c in "0123456789abcdef" for c in tail):
            continue
        bucket = presort_guard(name, "")
        kind = _SOFT_VAR_KINDS.get(bucket) or _SOFT_VAR_KINDS[""]
        print(f"{name}: presort={bucket} -> declared {kind['type']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
