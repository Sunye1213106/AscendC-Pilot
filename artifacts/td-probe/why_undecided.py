# -*- coding: utf-8 -*-
"""Why a branch stayed undecided: which symbol the evaluator could not resolve.

Ranked by how many branches each missing symbol blocks, because that is the
order in which resolving them buys coverage.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = json.loads((HERE / "pilot_result.json").read_text(encoding="utf-8"))
branches = json.loads((HERE / "steerable_branches.json").read_text(encoding="utf-8"))
by_site = {(b["file"], b["line"]): b for b in branches}

blocked: Counter = Counter()
sites: dict[str, set] = defaultdict(set)
detail_by_site: dict[tuple, set] = defaultdict(set)

for r in rows:
    for d in r.get("detail") or []:
        if d["state"] != "undecided":
            continue
        site = (d["file"], d["line"])
        detail_by_site[site].add(d["detail"])
        for u in d["unknown"]:
            blocked[u] += 1
            sites[u].add(f"{d['file']}:{d['line']}")

print("== unresolved symbols, by branches blocked ==")
for sym, n in blocked.most_common(40):
    print(f"  [{n:4d}] {sym:34s} {len(sites[sym])} sites")

print("\n== undecided sites, with the condition and what is missing ==")
seen = set()
for r in rows:
    for d in r.get("detail") or []:
        if d["state"] != "undecided":
            continue
        site = (d["file"], d["line"])
        if site in seen:
            continue
        seen.add(site)
        b = by_site.get(site) or {}
        print(f"\n  {site[0]}:{site[1]}   missing={d['unknown']}")
        print(f"      {str(b.get('condition',''))[:150]}")
        print(f"      detail: {d['detail']}")
print(f"\ndistinct undecided sites: {len(seen)} / {len(branches)}")
