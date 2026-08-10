# -*- coding: utf-8 -*-
"""Candidate exclusion rules, ranked by how much of the gap each would close.

A pair (or triple) of dimension values that never co-occurs in thousands of
real runs is a *lead*, not a proof -- the search may simply never have gone
there. So this only proposes, and ranks by leverage, so that the source
reading that follows is spent on the combinations that would actually close
the gap.

Two guards keep the leads honest:

  support   how many real witnesses have each half (or each pair inside a
            triple) on its own. A combination whose halves are themselves
            rare says nothing.
  open      how many still-open declared keys the combination would account
            for.
"""

from __future__ import annotations

import collections
import csv
import itertools

from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W

MIN_PAIR_SUPPORT = 40


def mine_pairs(ws: W.Workspace | None = None, top: int = 0) -> list[dict]:
    """Pairs never co-occurring in R, both halves well supported."""
    ws = ws or W.default_workspace()
    Rset, E, D = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
    dims = W.dim_names()
    wit = W.decode_many(sorted(Rset))
    opn = W.decode_many(sorted(D - Rset - E))

    pairs = collections.Counter()
    for o in opn:
        for a, b in itertools.combinations(dims, 2):
            pairs[((a, o[a]), (b, o[b]))] += 1
    seen = set()
    half = collections.Counter()
    for w in wit:
        for a, b in itertools.combinations(dims, 2):
            seen.add(((a, w[a]), (b, w[b])))
        for d in dims:
            half[(d, w[d])] += 1

    leads = []
    for pair, n in pairs.items():
        if pair in seen:
            continue
        (da, va), (db, vb) = pair
        sa, sb = half[(da, va)], half[(db, vb)]
        if sa == 0 or sb == 0:
            continue
        leads.append({
            "kind": "pair",
            "when": {da: va, db: vb},
            "open": n,
            "min_support": min(sa, sb),
        })
    leads.sort(key=lambda x: (x["open"], x["min_support"]), reverse=True)
    if top:
        leads = leads[:top]

    path = ws.report("leads.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["dim_a", "value_a", "dim_b", "value_b", "open_keys",
                    "min_support"])
        for lead in leads:
            (da, va), (db, vb) = list(lead["when"].items())
            w.writerow([da, va, db, vb, lead["open"], lead["min_support"]])
    return leads


def mine_triples(ws: W.Workspace | None = None, top: int = 0,
                 min_support: int = MIN_PAIR_SUPPORT) -> list[dict]:
    """Triples absent from every witness, all three pairs supported.

    Some source conditions are disjunctions -- e.g.
    `keepProb >= 1 || (d <= 128 && keepProb < 1)` -- which forbid a triple,
    not a pair. A pair miner cannot see them.
    """
    ws = ws or W.default_workspace()
    Rset, E, D = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
    dims = W.dim_names()
    wit = W.decode_many(sorted(Rset))
    opn = [(k, inst) for k, inst in zip(
        sorted(D - Rset - E), W.decode_many(sorted(D - Rset - E)))]

    pair_support = collections.Counter()
    seen3 = set()
    for w in wit:
        for a, b in itertools.combinations(dims, 2):
            pair_support[((a, w[a]), (b, w[b]))] += 1
        for a, b, c in itertools.combinations(dims, 3):
            seen3.add(((a, w[a]), (b, w[b]), (c, w[c])))

    want = collections.Counter()
    for _, o in opn:
        for a, b, c in itertools.combinations(dims, 3):
            want[((a, o[a]), (b, o[b]), (c, o[c]))] += 1

    leads = []
    for tri, n in want.items():
        if tri in seen3:
            continue
        sup = min(pair_support[(tri[0], tri[1])],
                  pair_support[(tri[0], tri[2])],
                  pair_support[(tri[1], tri[2])])
        if sup < min_support:
            continue
        leads.append({
            "kind": "triple",
            "when": {d: v for d, v in tri},
            "open": n,
            "min_support": sup,
        })
    leads.sort(key=lambda x: (x["open"], x["min_support"]), reverse=True)
    if top:
        leads = leads[:top]

    path = ws.report("leads3.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["a_dim", "a_val", "b_dim", "b_val", "c_dim", "c_val",
                    "open_keys", "min_pair_support"])
        for lead in leads:
            items = list(lead["when"].items())
            w.writerow([items[0][0], items[0][1], items[1][0], items[1][1],
                        items[2][0], items[2][1], lead["open"],
                        lead["min_support"]])
    return leads


def singles_never_witnessed(ws: W.Workspace | None = None) -> list[dict]:
    """Dimension values required by open keys but never produced in R."""
    ws = ws or W.default_workspace()
    Rset, E, D = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
    dims = W.dim_names()
    wit = W.decode_many(sorted(Rset))
    opn = W.decode_many(sorted(D - Rset - E))
    out = []
    for d in dims:
        seen = {w[d] for w in wit}
        for v, n in collections.Counter(o[d] for o in opn).items():
            if v not in seen:
                out.append({"dim": d, "value": v, "open": n})
    out.sort(key=lambda x: x["open"], reverse=True)
    return out
