# -*- coding: utf-8 -*-
"""Search for reachable tiling keys and write the case-to-key table.

Output is one CSV row per case: what was fed in, the key that came out, and
every one of the 19 dimensions that key decodes to, alongside the intermediates
the tiling logged. That table is the deliverable -- for any key it names an
input that produces it, and for any dimension it shows which cases move it.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import inputs as I
from replay import runner as R
from replay import search as S


def _report(cov: S.Coverage, tag: str) -> None:
    print(f"\n--- {tag}: {len(cov.keys)} distinct keys ---")
    for d in R.SCHEMA.dims:
        seen = sorted(cov.dim_values[d.name], key=str)
        declared = [S._norm(v) for v in d.value_domain]
        extra = [v for v in seen if S._norm(v) not in declared]
        mark = "" if len(seen) >= len(declared) else f"  (of {len(declared)} declared)"
        note = f"  EXTRA={extra}" if extra else ""
        print(f"  {d.name:<18} {len(seen)} value(s): {seen}{mark}{note}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--per-round", type=int, default=600)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="key_cases.csv")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    cov = S.Coverage()
    all_cases: dict[str, I.Case] = {}
    all_results: dict[str, R.Result] = {}
    interesting: list[I.Case] = []

    t0 = time.time()
    batch = S.seeds()
    print(f"seed batch: {len(batch)} cases")
    res = R.run(batch, tag="seed")
    for cid, c in batch.items():
        all_cases[cid], all_results[cid] = c, res[cid]
        if cov.offer(cid, res[cid]):
            interesting.append(c)
    ok = sum(1 for r in res.values() if r.ok)
    print(f"  accepted {ok}/{len(batch)}, {len(cov.keys)} keys, "
          f"{len(interesting)} kept  [{time.time() - t0:.1f}s]")
    _report(cov, "after seeds")

    for rnd in range(args.rounds):
        if not interesting:
            print("nothing left to mutate")
            break
        batch = {}
        for i in range(args.per_round):
            parent = rng.choice(interesting)
            batch[f"r{rnd}_{i}"] = S.mutate(parent, rng)
        t1 = time.time()
        res = R.run(batch, tag=f"round{rnd}")
        fresh = 0
        for cid, c in batch.items():
            all_cases[cid], all_results[cid] = c, res[cid]
            if cov.offer(cid, res[cid]):
                interesting.append(c)
                fresh += 1
        ok = sum(1 for r in res.values() if r.ok)
        print(f"round {rnd}: accepted {ok}/{len(batch)}, +{fresh} novel, "
              f"{len(cov.keys)} keys total  [{time.time() - t1:.1f}s]")

    _report(cov, "final")

    print("\n--- rejections ---")
    for msg, n in cov.rejects.most_common(12):
        print(f"  {n:>5}  {msg}")

    gaps = cov.missing(R.SCHEMA)
    print("\n--- declared but never produced ---")
    if not gaps:
        print("  none: every declared value was reached")
    for name, vals in gaps.items():
        print(f"  {name:<18} {vals}")

    out = R.CACHE / args.out
    R.write_wide(out, all_cases, all_results)
    print(f"\n{len(all_cases)} cases -> {out}")

    keyed = R.CACHE / "fag_key_witness.csv"
    lines = [",".join(["tiling_key"] + [f"dim_{n}" for n in R.DIM_NAMES]
                      + ["witness_case", "layout", "dtype", "b", "s1", "s2",
                         "n2", "g", "d", "d1", "seq_q", "seq_kv"])]
    for key, cid in sorted(cov.keys.items()):
        r, c = all_results[cid], all_cases[cid].normalised()
        desc = I.describe(c)
        lines.append(",".join(
            [str(key)] + [str(r.dims.get(n, "")) for n in R.DIM_NAMES]
            + [cid] + [str(desc[k]) for k in
                       ("layout", "dtype", "b", "s1", "s2", "n2", "g", "d", "d1",
                        "seq_q", "seq_kv")]
        ))
    keyed.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(cov.keys)} keys with witnesses -> {keyed}")
    print(f"total {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
