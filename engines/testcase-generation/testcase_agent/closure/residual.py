# -*- coding: utf-8 -*-
"""What is left of the gap, and which way each leftover leans.

A key one dimension away from something the host already produced is most
likely reachable and merely unfound; a key far from everything is where a
missing lemma would be. Sorting the residue that way says whether to keep
replaying or go back to the source.
"""

from __future__ import annotations

import collections
import csv
from typing import Iterable

from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W


def analyse(ws: W.Workspace | None = None) -> dict:
    """Hamming distance of each open key from the nearest witness."""
    ws = ws or W.default_workspace()
    Rset, E, D = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
    open_keys = sorted(D - Rset - E)
    dims = W.dim_names()
    wit = []
    for k in Rset:
        try:
            inst = W.decode(int(k))
            wit.append(tuple(inst[d] for d in dims))
        except Exception:
            continue
    wit_set = set(wit)

    dist = collections.Counter()
    blame = collections.Counter()
    near: dict[int, tuple] = {}
    rows = []
    for k in open_keys:
        o = tuple(W.decode(int(k))[d] for d in dims)
        best, bestdiff = 99, None
        for w in wit_set:
            n = sum(1 for a, b in zip(o, w) if a != b)
            if n < best:
                best, bestdiff = n, w
                if n == 1:
                    break
        dist[best] += 1
        near[k] = (best, bestdiff)
        diff = ""
        if bestdiff:
            diff = "|".join(
                dims[i] for i in range(len(dims)) if o[i] != bestdiff[i])
            blame[diff] += 1
        rows.append({
            "key": k,
            "distance": best,
            "differing_dims": diff,
            **{f"dim_{d}": o[i] for i, d in enumerate(dims)},
        })

    path = ws.report("residual.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["key", "distance", "differing_dims"]
            + [f"dim_{d}" for d in dims])
        w.writeheader()
        for row in rows:
            w.writerow(row)

    mostly_d1 = dist.get(1, 0) >= max(1, int(0.8 * len(open_keys))) if open_keys else False
    return {
        "open": len(open_keys),
        "distance": dict(sorted(dist.items())),
        "blame": blame.most_common(20),
        "mostly_distance_1": mostly_d1,
        "rows": rows,
        "path": str(path),
    }


def distance_one_targets(residual: dict) -> list[dict]:
    """Open keys whose nearest witness differs in exactly one dimension."""
    return [r for r in residual.get("rows") or [] if r.get("distance") == 1]
