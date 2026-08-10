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


def _drop1(t: tuple, i: int) -> tuple:
    return t[:i] + t[i + 1:]


def _drop2(t: tuple, i: int, j: int) -> tuple:
    return t[:i] + t[i + 1:j] + t[j + 1:]


def _projection_indexes(witnesses: set[tuple], ndims: int) -> tuple[list[dict], dict[tuple[int, int], dict]]:
    one = [dict() for _ in range(ndims)]
    two: dict[tuple[int, int], dict] = {}
    for w in witnesses:
        for i in range(ndims):
            one[i].setdefault(_drop1(w, i), w)
        for i in range(ndims):
            for j in range(i + 1, ndims):
                two.setdefault((i, j), {}).setdefault(_drop2(w, i, j), w)
    return one, two


def _focus_dims(
    blame: Iterable[tuple],
    dims: list[str],
    *,
    coverage: float = 0.9,
    hard_cap: int = 8,
) -> list[str]:
    """Dimensions the residue actually disagrees on, most blamed first.

    The count adapts to the blame distribution rather than being fixed: take
    dimensions until ``coverage`` of the blamed mass is accounted for. An
    operator with 4 dimensions and one with 40 both get the set that explains
    its own residue, and neither inherits a constant tuned on the other.
    """
    weight: collections.Counter = collections.Counter()
    order: list[str] = []
    for combo, n in blame:
        for d in str(combo).split("|"):
            if not d or d not in dims:
                continue
            if d not in weight:
                order.append(d)
            weight[d] += int(n or 0)
    if not weight:
        return list(dims)[:hard_cap]

    ranked = sorted(order, key=lambda d: (-weight[d], order.index(d)))
    total = sum(weight.values())
    picked: list[str] = []
    acc = 0
    for d in ranked:
        picked.append(d)
        acc += weight[d]
        if total and acc / total >= coverage:
            break
        if len(picked) >= hard_cap:
            break
    return picked


def _open_patterns(
    open_tuples: list[tuple],
    wit_set: set[tuple],
    dims: list[str],
    blame: Iterable[tuple],
    *,
    top: int = 32,
) -> tuple[list[dict], list[str]]:
    """Value-combination signatures over the residue, scored against R.

    ``r_support == 0`` means no reachable key shares the combination, which is
    the shape a source lemma has to justify. Without this, a lemma author only
    sees per-dimension blame counts and has to rediscover the combinations.

    Nothing here knows any operator's dimension names or values: the focus set
    comes from this run's blame counts and the values from key decoding.
    """
    focus = _focus_dims(blame, dims)
    idx = [dims.index(d) for d in focus]
    if not idx:
        return [], focus

    open_sig: collections.Counter = collections.Counter()
    for o in open_tuples:
        open_sig[tuple(o[i] for i in idx)] += 1
    r_sig: collections.Counter = collections.Counter()
    for w in wit_set:
        r_sig[tuple(w[i] for i in idx)] += 1

    patterns: list[dict] = []
    for sig, n in open_sig.most_common(top):
        support = r_sig.get(sig, 0)
        patterns.append(
            {
                "when": {focus[j]: sig[j] for j in range(len(idx))},
                "open_count": n,
                "r_support": support,
                "exclusive_to_open": support == 0,
            }
        )
    return patterns, focus


def _r_witness_values(
    wit_set: set[tuple],
    open_tuples: list[tuple],
    dims: list[str],
    *,
    cap: int = 32,
) -> dict[str, dict]:
    """Per-dimension values seen in R vs values only the residue asks for.

    A candidate lemma that excludes a value listed under ``in_R`` is refuted by
    construction, so mining can reject it before it is ever proposed.
    """
    out: dict[str, dict] = {}
    for i, d in enumerate(dims):
        r_vals = sorted({w[i] for w in wit_set}, key=str)
        o_vals = sorted({o[i] for o in open_tuples}, key=str)
        r_seen = set(r_vals)
        out[d] = {
            "in_R": r_vals[:cap],
            "open_only": [v for v in o_vals if v not in r_seen][:cap],
        }
    return out


def analyse(ws: W.Workspace | None = None, *, max_rows: int | None = None) -> dict:
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
    one_index, two_index = _projection_indexes(wit_set, len(dims)) if wit_set else ([], {})

    dist = collections.Counter()
    blame = collections.Counter()
    near: dict[int, tuple] = {}
    rows = []
    all_rows = []
    open_tuples: list[tuple] = []
    row_count = 0
    for k in open_keys:
        o = tuple(W.decode(int(k))[d] for d in dims)
        open_tuples.append(o)
        best, bestdiff = 99, None
        if o in wit_set:
            best, bestdiff = 0, o
        elif wit_set:
            for i in range(len(dims)):
                w = one_index[i].get(_drop1(o, i))
                if w is not None:
                    best, bestdiff = 1, w
                    break
        if best > 1 and wit_set:
            for i in range(len(dims)):
                if best <= 2:
                    break
                for j in range(i + 1, len(dims)):
                    w = two_index.get((i, j), {}).get(_drop2(o, i, j))
                    if w is not None:
                        best, bestdiff = 2, w
                        break
        if best > 2 and wit_set:
            for w in wit_set:
                n = sum(1 for a, b in zip(o, w) if a != b)
                if n < best:
                    best, bestdiff = n, w
                    if n == 3:
                        break
        dist[best] += 1
        near[k] = (best, bestdiff)
        diff = ""
        if bestdiff:
            diff = "|".join(
                dims[i] for i in range(len(dims)) if o[i] != bestdiff[i])
            blame[diff] += 1
        row = {
            "key": k,
            "distance": best,
            "differing_dims": diff,
            **{f"dim_{d}": o[i] for i, d in enumerate(dims)},
        }
        row_count += 1
        all_rows.append(row)
        if max_rows is None or len(rows) < max_rows:
            rows.append(row)

    path = ws.report("residual.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["key", "distance", "differing_dims"]
            + [f"dim_{d}" for d in dims])
        w.writeheader()
        for row in all_rows:
            w.writerow(row)

    mostly_d1 = dist.get(1, 0) >= max(1, int(0.8 * len(open_keys))) if open_keys else False
    blame_top = blame.most_common(20)
    patterns, focus = _open_patterns(open_tuples, wit_set, dims, blame_top)
    return {
        "open": len(open_keys),
        "distance": dict(sorted(dist.items())),
        "blame": blame_top,
        "mostly_distance_1": mostly_d1,
        "open_patterns": patterns,
        "pattern_dims": focus,
        "r_witness_values": _r_witness_values(wit_set, open_tuples, dims),
        "row_count": row_count,
        "rows_truncated": max_rows is not None and row_count > max_rows,
        "rows": rows,
        "path": str(path),
    }


def distance_one_targets(residual: dict) -> list[dict]:
    """Open keys whose nearest witness differs in exactly one dimension."""
    return [r for r in residual.get("rows") or [] if r.get("distance") == 1]
