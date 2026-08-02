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

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import inputs as I  # noqa: E402
from replay import runner as R  # noqa: E402
from replay_nudge import _variants  # noqa: E402

TIME_BUDGET_S = 240
MAX_PER_KEY = 12
GRID_DIMS = {"SplitAxis", "IsBn2MultiBlk", "IsNzOut"}
NO_COMP_DIMS = GRID_DIMS | {"S1TemplateNum", "S2TemplateNum"}
CAP = 8192


def _base_case(row: dict) -> I.Case:
    def s(name, dflt=""):
        v = row.get(name, dflt)
        return dflt if v in ("", "None") else v

    return I.Case(
        layout=s("layout", "BSND"), dtype=s("dtype", "FLOAT16"),
        b=int(s("b", 1)), s1=int(s("s1", 128)), s2=int(s("s2", 128)),
        n2=int(s("n2", 1)), g=int(s("g", 1)), d=int(s("d", 128)),
        d1=int(s("d1")) if s("d1") else None,
        atten_mask=s("atten_mask", "none"), pse=s("pse", "0") == "1",
        pse_shape=s("pse_shape", "full"),
        pse_type=int(s("pse_type", 1)), rope=s("rope", "0") == "1",
        keep_prob=float(s("keep_prob", 1.0)),
        sparse_mode=int(s("sparse_mode", 0)),
        pre_tokens=int(s("pre_tokens", 65536)),
        next_tokens=int(s("next_tokens", 65536)),
        out_dtype=int(s("out_dtype", 0)),
        deterministic=int(s("deterministic", 0)),
        seq_q=[int(x) for x in s("seq_q").split("/") if x] or None,
        seq_kv=[int(x) for x in s("seq_kv").split("/") if x] or None,
    )


def _comp_grid(c: I.Case) -> list[tuple[int, int]]:
    ups1 = min(c.s1 * 2, CAP)
    ups2 = min(c.s2 * 2, CAP)
    grid = {(c.s1, c.s2), (ups1, c.s2), (c.s1, ups2), (ups1, ups2)}
    return sorted(grid)


def _candidates(base: I.Case, dim: str, want: str) -> list[I.Case]:
    from dataclasses import replace

    if dim in GRID_DIMS:
        out = []
        for f1 in (max(1, base.s1 // 2), base.s1, min(base.s1 * 2, CAP)):
            for f2 in (max(1, base.s2 // 2), base.s2, min(base.s2 * 2, CAP)):
                if (f1, f2) != (base.s1, base.s2):
                    out.append(replace(base, s1=f1, s2=f2))
        return out[:MAX_PER_KEY]

    knobs = _variants(base, dim, want)
    if not knobs:
        return []
    if dim in NO_COMP_DIMS:
        return knobs[:MAX_PER_KEY]

    out: list[I.Case] = []
    for k in knobs:
        for s1v, s2v in _comp_grid(k):
            out.append(replace(k, s1=s1v, s2=s2v))
    return out[:MAX_PER_KEY]


def main() -> int:
    start = time.time()
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    queue = R.CACHE / "open_key_queue.csv"
    lines = queue.read_text(encoding="utf-8").splitlines()[1:]

    wide: dict[str, dict] = {}
    for p in sorted(R.CACHE.glob("fag_key_cases*.csv")):
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

    wide_out = R.CACHE / "fag_key_cases_cone.csv"
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
