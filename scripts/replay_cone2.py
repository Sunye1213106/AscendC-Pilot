# -*- coding: utf-8 -*-
"""Second cone iteration: climb from near-misses instead of the old witnesses.

The first cone run produced thousands of probes that flipped the target
dimension but sat 1-2 dimensions away from the goal key. Those probes are
closer than anything in the old witness pool, so this round treats the best
near-miss per target as the new base case and knobs the *remaining* differing
dimension. SplitAxis / IsBn2MultiBlk / IsNzOut, which the s1/s2 grid could
not move at all, additionally get n2/b in the grid.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import corpus as C  # noqa: E402
from replay import inputs as I  # noqa: E402
from replay import obligations as O  # noqa: E402
from replay import runner as R  # noqa: E402
from replay_cone import MAX_PER_KEY, TIME_BUDGET_S, _base_case, _comp_grid
from replay_nudge import _variants  # noqa: E402

CAP = 8192


def _wide_pool() -> dict[str, dict]:
    wide: dict[str, dict] = {}
    for p in C.wide_tables():
        rows = p.read_text(encoding="utf-8").splitlines()
        head = rows[0].split(",")
        for line in rows[1:]:
            f = line.split(",")
            if len(f) == len(head):
                wide.setdefault(f[0], dict(zip(head, f)))
    return wide


def _targets() -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for line in (R.CACHE / "open_key_queue.csv").read_text(encoding="utf-8").splitlines()[1:]:
        key_s, dist, dim, _, wcase = line.split(",")[:5]
        if dist != "1":
            continue
        want = str(R.SCHEMA.decode_tiling_key(int(key_s))[dim])
        out[int(key_s)] = (dim, wcase)
    return out


def _best_base(key: int, rows: list[dict]) -> dict | None:
    """Nearest produced row to the goal key among this target's own probes."""
    want_dims = R.SCHEMA.decode_tiling_key(key)
    best, best_d = None, len(R.DIM_NAMES) + 1
    for row in rows:
        if row.get("ok") != "1":
            continue
        d = sum(1 for n in R.DIM_NAMES
                if row.get(f"dim_{n}", "") != str(want_dims[n]))
        if d < best_d:
            best, best_d = row, d
    return best


def _remaining_dim(key: int, row: dict, skip: str) -> str | None:
    want_dims = R.SCHEMA.decode_tiling_key(key)
    for n in R.DIM_NAMES:
        if n != skip and row.get(f"dim_{n}", "") != str(want_dims[n]):
            return n
    return None


def _grid2(base: I.Case) -> list[I.Case]:
    out = []
    for n2 in {base.n2, min(base.n2 * 2, 64)}:
        for b in {base.b, min(base.b * 2, 512)}:
            for s2 in {base.s2, min(base.s2 * 2, CAP), 128, 256}:
                c = replace(base, n2=n2, b=b, s2=s2)
                if c != base:
                    out.append(c)
    return out


def _candidates(base: I.Case, key: int, row: dict) -> list[I.Case]:
    dims = R.SCHEMA.decode_tiling_key(key)
    diffs = [n for n in R.DIM_NAMES if row.get(f"dim_{n}", "") != str(dims[n])]
    if not diffs:
        return []

    first = diffs[0]
    if O.is_host_state(first):
        out = _grid2(base)
    else:
        knobs = _variants(base, first, str(dims[first]))
        out = []
        for k in knobs:
            for s1v, s2v in _comp_grid(k):
                out.append(replace(k, s1=s1v, s2=s2v))
    if len(diffs) > 1:
        second = diffs[1]
        if not O.is_host_state(second):
            extra: list[I.Case] = []
            for c in out[:4]:
                extra.extend(_variants(c, second, str(dims[second])))
            out.extend(extra)
    return out[:MAX_PER_KEY]


def main() -> int:
    start = time.time()
    wide = _wide_pool()
    targets = _targets()

    # Group produced rows per target: the target's own first-round probes plus
    # its original witness. Probe ids are c<key tail>_<n>; one pass indexes
    # them by tail so this stays O(pool) instead of O(pool x targets).
    probes_by_tail: dict[str, list[dict]] = {}
    for cid, row in wide.items():
        if cid.startswith("c") and "_" in cid:
            probes_by_tail.setdefault(cid[1:cid.rfind("_")], []).append(row)
    per_target: dict[int, list[dict]] = {}
    for key, (_, wcase) in targets.items():
        rows = list(probes_by_tail.get(str(key)[-9:], []))
        old = wide.get(wcase)
        if old is not None:
            rows.append(old)
        per_target[key] = rows

    cases: dict[str, I.Case] = {}
    tgt_dim: dict[int, str] = {}
    skipped: Counter = Counter()
    for key, (dim, wcase) in targets.items():
        row = _best_base(key, per_target[key])
        if row is None:
            skipped["no usable base"] += 1
            continue
        cands = _candidates(_base_case(row), key, row)
        if not cands:
            skipped["no candidates"] += 1
            continue
        tgt_dim[key] = dim
        for j, v in enumerate(cands):
            cases[f"d{str(key)[-9:]}_{j}"] = v

    print(f"{len(tgt_dim)} target keys, {len(cases)} probe cases, "
          f"built in {time.time() - start:.0f}s")
    for why, n in skipped.most_common():
        print(f"  skipped {n}: {why}")

    found: dict[int, str] = {}
    all_cases: dict[str, I.Case] = {}
    all_results: dict[str, R.Result] = {}
    items = list(cases.items())
    for i in range(0, len(items), 2000):
        if time.time() - start > TIME_BUDGET_S:
            print(f"  time budget hit at batch {i // 2000}, stopping early")
            break
        chunk = dict(items[i:i + 2000])
        res = R.run(chunk, tag=f"cone2_{i}")
        all_cases.update(chunk)
        all_results.update(res)
        for cid, r in res.items():
            if r.ok and r.key in tgt_dim and r.key not in found:
                found[r.key] = cid
        print(f"  batch {i // 2000}: {len(found)}/{len(tgt_dim)} targets hit "
              f"({time.time() - start:.0f}s)")

    print(f"\nhit {len(found)} of {len(tgt_dim)} targeted keys "
          f"({len(found) / max(1, len(tgt_dim)) * 100:.0f}%)")
    by_dim: Counter = Counter()
    miss: Counter = Counter()
    for k, dim in tgt_dim.items():
        (by_dim if k in found else miss)[dim] += 1
    for d in sorted(set(by_dim) | set(miss)):
        print(f"    {d:<16} {by_dim[d]:>4} hit, {miss[d]:>4} missed")

    wide_out = R.CACHE / "key_cases_cone2.csv"
    R.write_wide(wide_out, all_cases, all_results)
    print(f"\nall probe results -> {wide_out} (feeds the witness pool)")

    if found:
        out = R.CACHE / "cone2_hits.csv"
        with out.open("w", encoding="utf-8") as f:
            f.write("tiling_key,case_id,dimension\n")
            for k, cid in found.items():
                f.write(f"{k},{cid},{tgt_dim[k]}\n")
        print(f"hits -> {out}")
    print(f"total {time.time() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
