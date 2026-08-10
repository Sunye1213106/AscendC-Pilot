# -*- coding: utf-8 -*-
"""Ask for a key, see what the host gives instead, and name the dimension.

Construction that is accepted but never produces the asked-for key is not a
failure to search -- it is the host disagreeing about a specific dimension.
The dimension it disagrees about is the next lemma, or the next thing to learn.
"""

from __future__ import annotations

import collections
import csv
from typing import Any, Callable, Mapping

from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W


def explain(results: Mapping[str, Any],
            targets: Mapping[str, tuple[int, Mapping[str, str]]],
            cases: Mapping[str, Any] | None = None,
            ws: W.Workspace | None = None) -> dict:
    """Compare asked-for dims against what the host returned.

    `targets` maps case_id -> (target_key, wanted_instance).
    `results` maps case_id -> Result-like objects with `.ok`, `.key`.
    """
    ws = ws or W.default_workspace()
    dims = W.dim_names()
    disagree = collections.Counter()
    swap = collections.Counter()
    best: dict[int, tuple] = {}
    rows = []

    for cid, (target_key, want) in targets.items():
        r = results.get(cid)
        if r is None:
            continue
        ok = bool(getattr(r, "ok", False))
        key = int(getattr(r, "key", 0) or 0)
        got = W.decode(key) if ok and key else {d: "" for d in dims}
        diff = [d for d in dims if str(got.get(d, "")) != str(want.get(d, ""))]
        if ok and key:
            disagree[tuple(diff)] += 1
            for d in diff:
                swap[(d, want[d], got[d])] += 1
            if target_key not in best or len(diff) < best[target_key][0]:
                best[target_key] = (len(diff), diff, cid)
        rows.append({
            "target": target_key,
            "case": cid,
            "ok": int(ok),
            "actual_key": key,
            "differing_dims": "|".join(diff),
            **{f"want_{d}": want.get(d, "") for d in dims},
            **{f"got_{d}": got.get(d, "") for d in dims},
        })

    path = ws.report("why.csv")
    if rows:
        fieldnames = list(rows[0].keys())
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fieldnames)
            w.writeheader()
            for row in rows:
                w.writerow(row)

    return {
        "accepted": sum(1 for r in rows if r["ok"]),
        "disagree": [
            {"dims": "|".join(k) or "(exact)", "count": n}
            for k, n in disagree.most_common(12)
        ],
        "substitutions": [
            {"dim": d, "asked": wv, "got": gv, "count": n}
            for (d, wv, gv), n in swap.most_common(18)
        ],
        "closest": [
            {"key": k, "off_by": n, "dims": "|".join(diff)}
            for k, (n, diff, _) in list(best.items())[:20]
        ],
        "path": str(path),
    }


def run_explain(build_fn: Callable[[Mapping[str, str]], list],
                open_limit: int = 60, per_target: int = 24,
                tag: str = "tg_why",
                ws: W.Workspace | None = None) -> dict:
    """Send constructed spellings for open keys and explain the disagreements."""
    ws = ws or W.default_workspace()
    Rset, E, D = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
    open_keys = sorted(D - Rset - E)[:open_limit]
    batch, meta = {}, {}
    for k in open_keys:
        want = W.decode(int(k))
        for j, case in enumerate(build_fn(want)[:per_target]):
            cid = "W_%d_%d" % (k % 1000000, j)
            batch[cid] = case
            meta[cid] = (k, want)
    if not batch:
        return {"accepted": 0, "disagree": [], "substitutions": [],
                "closest": [], "path": ""}
    runner = W.replay_runner()
    results = runner.run(batch, tag=tag, check=False)
    return explain(results, meta, cases=batch, ws=ws)
