# -*- coding: utf-8 -*-
"""Diagnose why the cone search missed: knob broken, or side effects?

For every dist=1 target, look at its probe rows in fag_key_cases_cone.csv:
- knob_ok: target dimension actually took the wanted value
- clean: among knob_ok rows, how far the produced key still is from the target
If knob_ok is rare, the input->dimension map is wrong. If knob_ok is common
but distance stays >0, the coupling is what needs modelling.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import runner as R  # noqa: E402


def main() -> int:
    queue = R.CACHE / "open_key_queue.csv"
    targets: dict[str, tuple[int, str, str]] = {}  # short-id -> (key, dim, want)
    for line in queue.read_text(encoding="utf-8").splitlines()[1:]:
        key_s, dist, dim = line.split(",")[:3]
        if dist != "1":
            continue
        want = str(R.SCHEMA.decode_tiling_key(int(key_s))[dim])
        targets[key_s[-9:]] = (int(key_s), dim, want)

    rows = (R.CACHE / "fag_key_cases_cone.csv").read_text(encoding="utf-8").splitlines()
    head = rows[0].split(",")
    idx = {n: i for i, n in enumerate(head)}
    dim_cols = {n: idx[f"dim_{n}"] for n in R.DIM_NAMES}

    stats: dict[str, Counter] = defaultdict(Counter)
    dist_after_flip: dict[str, Counter] = defaultdict(Counter)
    rejects: Counter = Counter()
    for line in rows[1:]:
        f = line.split(",")
        if len(f) != len(head):
            continue
        cid = f[idx["case_id"]]
        short = cid[1:cid.rfind("_")]
        tgt = targets.get(short)
        if tgt is None:
            continue
        key, dim, want = tgt
        if f[idx["ok"]] != "1":
            rejects[f[idx["reject"]][:60] or "host reject"] += 1
            stats[dim]["rejected"] += 1
            continue
        got = f[dim_cols[dim]]
        if got != want:
            stats[dim]["knob_failed"] += 1
            continue
        stats[dim]["knob_ok"] += 1
        want_dims = R.SCHEMA.decode_tiling_key(key)
        d = sum(1 for n in R.DIM_NAMES if str(want_dims[n]) != f[dim_cols[n]])
        dist_after_flip[dim][d] += 1

    print(f"{'dimension':<16} {'knob_ok':>8} {'knob_fail':>9} {'rejected':>8}  "
          "distance-from-target after the dimension flipped")
    for dim in sorted(stats):
        c = stats[dim]
        dists = " ".join(f"d{k}:{v}" for k, v in sorted(dist_after_flip[dim].items()))
        print(f"{dim:<16} {c['knob_ok']:>8} {c['knob_failed']:>9} {c['rejected']:>8}  {dists}")
    if rejects:
        print("\ntop reject reasons:")
        for why, n in rejects.most_common(5):
            print(f"  {n:>5}  {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
