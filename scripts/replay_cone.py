# -*- coding: utf-8 -*-
"""Close dist=1 gaps with joint input moves instead of a single knob.

replay_nudge changes only the input feeding the one differing dimension, and
hits 0%: inputs are shared, so moving one knob drags SplitAxis / IsDNoEqual /
the template numbers off the target. This script keeps the knob for the
differing dimension but adds a small compensation grid over s1/s2 (which feed
the coupling dimensions but not the knobbed one), so the side effects get a
few chances to be cancelled while the target dimension stays put.

Dimensions with no direct knob (SplitAxis, IsBn2MultiBlk, IsNzOut) get the
grid itself as the candidate set, around the nearest witness.
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import corpus as C  # noqa: E402
from replay import inputs as I  # noqa: E402
from replay import obligations as O  # noqa: E402
from replay import runner as R  # noqa: E402
from replay_nudge import _variants  # noqa: E402

#: Wall clock this search may spend probing the host. Deliberately short: the
#: search is run in a loop -- cover, measure, nudge, cone, measure again -- and
#: a long budget buys fewer keys per hour than a short one run more often,
#: because each round starts from the witnesses the last one found.
TIME_BUDGET_S = int(os.environ.get("UO_SEARCH_BUDGET_S", "100"))
MAX_PER_KEY = 12
CAP = 8192


def _base_case(row: dict) -> I.Case:
    """The case a recorded row came from.

    There were three copies of this, and they had drifted: two defaulted an
    absent pse shape to "full", which is not a shape the generator can build,
    so the probe was replayed as bnss under a name that never ran.
    """
    return C.case_of(row)


def _comp_grid(c: I.Case) -> list[tuple[int, int]]:
    ups1 = min(c.s1 * 2, CAP)
    ups2 = min(c.s2 * 2, CAP)
    grid = {(c.s1, c.s2), (ups1, c.s2), (c.s1, ups2), (ups1, ups2)}
    return sorted(grid)


def _candidates(base: I.Case, dim: str, want: str) -> list[I.Case]:
    from dataclasses import replace

    hints = O.load_hints()
    max_per = int(((hints.get("compensation") or {})
                   .get("grid_host_state") or {}).get("max_per_key") or MAX_PER_KEY)
    cap = int(((hints.get("compensation") or {}).get("s1_s2") or {}).get("cap")
              or CAP)

    if O.is_host_state(dim, hints):
        out = []
        for f1 in (max(1, base.s1 // 2), base.s1, min(base.s1 * 2, cap)):
            for f2 in (max(1, base.s2 // 2), base.s2, min(base.s2 * 2, cap)):
                if (f1, f2) != (base.s1, base.s2):
                    out.append(replace(base, s1=f1, s2=f2))
        return out[:max_per]

    knobs = _variants(base, dim, want)
    if not knobs:
        return []
    if not O.needs_compensation(dim, hints):
        return knobs[:max_per]

    out: list[I.Case] = []
    for k in knobs:
        for s1v, s2v in _comp_grid(k):
            out.append(replace(k, s1=s1v, s2=s2v))
    return out[:max_per]


def main() -> int:
    start = time.time()
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    queue = R.CACHE / "open_key_queue.csv"
    lines = queue.read_text(encoding="utf-8").splitlines()[1:]

    wide: dict[str, dict] = {}
    for p in C.wide_tables():
        rows = p.read_text(encoding="utf-8").splitlines()
        head = rows[0].split(",")
        for line in rows[1:]:
            f = line.split(",")
            if len(f) == len(head):
                wide.setdefault(f[0], dict(zip(head, f)))

    cases: dict[str, I.Case] = {}
    targets: dict[int, str] = {}
    skipped: Counter = Counter()
    for line in lines:
        key_s, dist, dim, _, wcase = line.split(",")[:5]
        if dist != "1":
            continue
        row = wide.get(wcase)
        if row is None:
            skipped["witness row missing"] += 1
            continue
        want = str(R.SCHEMA.decode_tiling_key(int(key_s))[dim])
        cands = _candidates(_base_case(row), dim, want)
        if not cands:
            skipped[f"no candidates for {dim}"] += 1
            continue
        targets[int(key_s)] = dim
        for j, v in enumerate(cands):
            cases[f"c{key_s[-9:]}_{j}"] = v
        if budget and len(targets) >= budget:
            break

    print(f"{len(targets)} target keys, {len(cases)} probe cases, "
          f"built in {time.time() - start:.0f}s")
    for why, n in skipped.most_common():
        print(f"  skipped {n}: {why}")

    found: dict[int, str] = {}
    bonus: set[int] = set()
    all_cases: dict[str, I.Case] = {}
    all_results: dict[str, R.Result] = {}
    items = list(cases.items())
    for i in range(0, len(items), 2000):
        if time.time() - start > TIME_BUDGET_S:
            print(f"  time budget hit at batch {i // 2000}, stopping early")
            break
        chunk = dict(items[i:i + 2000])
        res = R.run(chunk, tag=f"cone{i}")
        all_cases.update(chunk)
        all_results.update(res)
        for cid, r in res.items():
            if not r.ok:
                continue
            if r.key in targets and r.key not in found:
                found[r.key] = cid
            elif r.key not in targets:
                bonus.add(r.key)
        print(f"  batch {i // 2000}: {len(found)}/{len(targets)} targets hit "
              f"({time.time() - start:.0f}s)")

    print(f"\nhit {len(found)} of {len(targets)} targeted keys "
          f"({len(found) / max(1, len(targets)) * 100:.0f}%)")
    by_dim: Counter = Counter()
    miss: Counter = Counter()
    for k, dim in targets.items():
        (by_dim if k in found else miss)[dim] += 1
    for d in sorted(set(by_dim) | set(miss)):
        print(f"    {d:<16} {by_dim[d]:>4} hit, {miss[d]:>4} missed")

    wide_out = C.next_wide("key_cases_cone")
    R.write_wide(wide_out, all_cases, all_results)
    print(f"\nall probe results -> {wide_out} (feeds the witness pool)")

    if found:
        out = R.CACHE / "cone_hits.csv"
        with out.open("w", encoding="utf-8") as f:
            f.write("tiling_key,case_id,dimension\n")
            for k, cid in found.items():
                f.write(f"{k},{cid},{targets[k]}\n")
        print(f"hits -> {out}")
    print(f"total {time.time() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
