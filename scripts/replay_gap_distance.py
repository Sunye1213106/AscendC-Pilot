# -*- coding: utf-8 -*-
"""How far is each unresolved key from something we already produced?

A key that differs from a real witness in one dimension is a search problem:
take the witness's inputs and push that one dimension. A key that differs in
six is more likely structurally impossible and wants a proof instead. The
distribution of that distance says whether closing U - R is days or quarters.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "engines" / "understand-operator" / "src")
)

from uo_init.tpl_dsl import expand_legal_instances  # noqa: E402

from replay import corpus as C  # noqa: E402
from replay import runner as R  # noqa: E402
from replay_closure_gate import excluded_by as _excluded_by  # noqa: E402
from replay import rule_engine as RE  # noqa: E402
from replay_verdict import _witnesses  # noqa: E402


def main() -> int:
    seen: dict[int, dict] = {}
    for p in C.wide_tables():
        for k, v in _witnesses(p).items():
            seen.setdefault(k, v)

    declared = expand_legal_instances(R.SCHEMA)
    dec_key = {R.SCHEMA.encode_tiling_key({k: int(v) for k, v in i.items()}): i
               for i in declared}

    wit = [(k, R.SCHEMA.decode_tiling_key(k)) for k in seen if k in dec_key]
    gap = [(k, i) for k, i in dec_key.items()
           if k not in seen and not _excluded_by(i, grades=RE.SOUND_GRADES)]
    print(f"{len(gap)} keys in U - R, {len(wit)} witnesses to measure against")

    # Every gap is measured against every witness, which is millions of
    # comparisons. Encode each instance once as a row of small integers -- one
    # column per dimension -- so the inner loop is an array compare instead of
    # re-formatting nineteen values as strings on every pair.
    dims = list(R.DIM_NAMES)
    codes: dict[tuple[str, str], int] = {}

    def _row(inst) -> list[int]:
        out = []
        for d in dims:
            key = (d, str(inst.get(d)))
            code = codes.get(key)
            if code is None:
                code = codes[key] = len(codes)
            out.append(code)
        return out

    gap_rows = [_row(inst) for _k, inst in gap]
    wit_rows = [_row(wd) for _wk, wd in wit]
    wit_keys = [wk for wk, _wd in wit]

    dist: Counter = Counter()
    which: Counter = Counter()
    nearest: dict[int, tuple[int, int, tuple]] = {}

    ceiling = len(dims) + 1
    for (k, _inst), row in zip(gap, gap_rows):
        best, bestj = ceiling, 0
        for j, wrow in enumerate(wit_rows):
            n = 0
            for a, b in zip(row, wrow):
                if a != b:
                    n += 1
                    # Already no better than the best so far, so how much
                    # worse it gets does not matter. Most witnesses differ
                    # in many dimensions and are dismissed in two or three
                    # comparisons once a close one has been found.
                    if n >= best:
                        break
            else:
                if n < best:
                    best, bestj = n, j
                    if best == 1:
                        break
        wrow = wit_rows[bestj]
        bestdiff = tuple(d for i, d in enumerate(dims) if row[i] != wrow[i])
        dist[best] += 1
        which[bestdiff] += 1
        nearest[k] = (wit_keys[bestj], best, bestdiff)

    print("\n=== distance to the nearest witness ===")
    for d in sorted(dist):
        print(f"  {d} dimension(s) differ: {dist[d]:>5} keys")

    print("\n=== which dimensions have to move ===")
    for combo, n in which.most_common(15):
        print(f"  {n:>5}  {', '.join(combo)}")

    single = [c for c in which if len(c) == 1]
    tot = sum(which[c] for c in single)
    print(f"\n  {tot} keys are one dimension away, over {len(single)} distinct "
          f"dimensions: {sorted({c[0] for c in single})}")

    out = R.CACHE / "open_key_queue.csv"
    with out.open("w", encoding="utf-8") as f:
        f.write("key,distance,differing_dims,nearest_witness,witness_case\n")
        for k, (wk, d, diff) in sorted(nearest.items(), key=lambda x: x[1][1]):
            f.write(f"{k},{d},{'|'.join(diff)},{wk},{seen[wk]['case_id']}\n")
    print(f"\nwork queue -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
