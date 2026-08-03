# -*- coding: utf-8 -*-
"""Take a witness and push exactly one dimension toward an unreached key.

89% of the keys in U - R sit one dimension away from something already
produced. Random mutation never lands on them because it moves several inputs
at once and drifts off the ledge it is standing on. This walks the other way:
start from the witness's exact inputs, change only what feeds the one dimension
that differs, and keep everything else fixed.

Which mutations to try comes from search_hints.yaml via obligations.variants,
not from an if-ladder over dimension names.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import corpus as C  # noqa: E402
from replay import inputs as I  # noqa: E402
from replay import obligations as O  # noqa: E402
from replay import runner as R  # noqa: E402


def _variants(c: I.Case, dim: str, want: str) -> list[I.Case]:
    """Kept as the historical name cone/cone2 import."""
    return O.variants(c, dim, want)


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0

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
        key_s, dist, dims, _, wcase = line.split(",")[:5]
        if dist != "1":
            continue
        row = wide.get(wcase)
        if row is None:
            skipped["witness row missing"] += 1
            continue
        dim = dims
        want = str(R.SCHEMA.decode_tiling_key(int(key_s))[dim])
        vs = _variants(C.case_of(row), dim, want)
        if not vs:
            skipped[f"no knob for {dim}"] += 1
            continue
        targets[int(key_s)] = dim
        for j, v in enumerate(vs):
            cases[f"n{key_s[-9:]}_{j}"] = v
        if limit and len(targets) >= limit:
            break

    print(f"{len(targets)} target keys, {len(cases)} probe cases")
    for why, n in skipped.most_common():
        print(f"  skipped {n}: {why}")

    found: dict[int, str] = {}
    other: set[int] = set()
    results: dict = {}
    items = list(cases.items())
    for i in range(0, len(items), 2000):
        chunk = dict(items[i:i + 2000])
        res = R.run(chunk, tag=f"nudge{i}")
        results.update(res)
        for cid, r in res.items():
            if not r.ok:
                continue
            if r.key in targets and r.key not in found:
                found[r.key] = cid
            else:
                other.add(r.key)
        print(f"  batch {i // 2000}: {len(found)}/{len(targets)} targets hit")

    print(f"\nhit {len(found)} of {len(targets)} targeted keys "
          f"({len(found) / max(1, len(targets)) * 100:.0f}%)")
    by_dim: Counter = Counter()
    miss: Counter = Counter()
    for k, dim in targets.items():
        (by_dim if k in found else miss)[dim] += 1
    print("\n  hit by dimension:")
    for d in sorted(set(by_dim) | set(miss)):
        print(f"    {d:<16} {by_dim[d]:>4} hit, {miss[d]:>4} missed")

    if found:
        out = R.CACHE / "nudge_hits.csv"
        with out.open("w", encoding="utf-8") as f:
            f.write("tiling_key,case_id,dimension\n")
            for k, cid in found.items():
                f.write(f"{k},{cid},{targets[k]}\n")
        print(f"\nhits -> {out}")

    # Also as a wide table, under a name the corpus glob picks up. The hit list
    # alone records which keys were reached but not the inputs that reached
    # them, so every key this search found stayed outside the witness set and
    # the next run went looking for it again.
    wide = C.next_wide("key_cases_nudge")
    R.write_wide(wide, cases, results)
    print(f"{len(cases)} cases -> {wide}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
