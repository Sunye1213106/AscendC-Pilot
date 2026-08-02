# -*- coding: utf-8 -*-
"""Ask how much of the key space the search can actually claim.

"No new keys for 15 rounds" is evidence of saturation, not proof of coverage.
This measures what can be measured: single-value coverage, pair coverage against
the kernel's own declared instances, and how much of the untouched remainder is
explained by pairs that never co-occur. What is left over is the honest gap.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "engines" / "understand-operator" / "src")
)

from uo_init.tpl_dsl import expand_legal_instances  # noqa: E402

from replay import runner as R  # noqa: E402


def _pairs(dims: dict) -> set:
    names = [n for n in R.DIM_NAMES if n in dims]
    return {(a, str(dims[a]), b, str(dims[b]))
            for a, b in combinations(names, 2)}


def _keys_from(path: Path) -> set[int]:
    rows = path.read_text(encoding="utf-8").splitlines()
    head = rows[0].split(",")
    idx = {n: i for i, n in enumerate(head)}
    out = set()
    for line in rows[1:]:
        f = line.split(",")
        if len(f) == len(head) and f[idx["ok"]] == "1":
            out.add(int(f[idx["tiling_key"]]))
    return out


def main() -> int:
    produced = _keys_from(R.CACHE / "fag_key_cases_full.csv")
    declared = expand_legal_instances(R.SCHEMA)
    dec_key = {R.SCHEMA.encode_tiling_key({k: int(v) for k, v in i.items()}): i
               for i in declared}
    confirmed = produced & set(dec_key)

    print(f"produced {len(produced)} keys; declared {len(dec_key)} instances; "
          f"confirmed {len(confirmed)}")

    # 1-wise: every value of every dimension.
    dec_vals: dict[str, set] = defaultdict(set)
    got_vals: dict[str, set] = defaultdict(set)
    for inst in declared:
        for d, v in inst.items():
            dec_vals[d].add(str(v))
    for key in produced:
        for d, v in R.SCHEMA.decode_tiling_key(key).items():
            got_vals[d].add(str(v))

    print("\n=== 1-wise: dimension values ===")
    miss1 = 0
    for d in R.DIM_NAMES:
        gap = dec_vals[d] - got_vals[d]
        miss1 += len(gap)
        flag = f"  MISSING {sorted(gap)}" if gap else ""
        print(f"  {d:<18} declared {len(dec_vals[d])}, produced "
              f"{len(dec_vals[d] & got_vals[d])}{flag}")
    print(f"  -> {miss1} declared value(s) never produced")

    # 2-wise: every pair of values the kernel declares together.
    dec_pairs: set = set()
    for inst in declared:
        dec_pairs |= _pairs(inst)
    got_pairs: set = set()
    for key in produced:
        got_pairs |= _pairs(R.SCHEMA.decode_tiling_key(key))

    hit = dec_pairs & got_pairs
    miss = dec_pairs - got_pairs
    print("\n=== 2-wise: value pairs declared by the kernel ===")
    print(f"  declared pairs {len(dec_pairs)}, produced {len(hit)} "
          f"({len(hit) / len(dec_pairs) * 100:.1f}%), missing {len(miss)}")

    by_dims: Counter = Counter()
    for a, av, b, bv in miss:
        by_dims[f"{a} x {b}"] += 1
    print("\n  missing pairs, by dimension pair:")
    for name, n in by_dims.most_common(15):
        print(f"    {name:<44} {n:>4}")

    # How many untouched instances does each missing pair account for? A pair
    # that blocks a lot is worth either an input or a proof.
    untouched = [i for k, i in dec_key.items() if k not in confirmed]
    blame: Counter = Counter()
    unexplained = 0
    for inst in untouched:
        bad = _pairs(inst) - got_pairs
        if bad:
            a, av, b, bv = sorted(bad)[0]
            blame[f"{a}={av} + {b}={bv}"] += 1
        else:
            unexplained += 1
    print(f"\n=== the {len(untouched)} untouched declared instances ===")
    print(f"  explained by a never-produced pair: {len(untouched) - unexplained}")
    print(f"  every pair produced, whole instance not: {unexplained}")
    print("\n  top blocking pairs:")
    for name, n in blame.most_common(12):
        print(f"    {name:<46} {n:>5}")

    # Saturation across independent searches, when a second run exists.
    other = R.CACHE / "fag_key_cases_seedB.csv"
    if other.exists():
        b = _keys_from(other)
        print("\n=== independent run with a different seed ===")
        print(f"  run A {len(produced)} keys, run B {len(b)} keys")
        print(f"  shared {len(produced & b)}, only-A {len(produced - b)}, "
              f"only-B {len(b - produced)}")
        if b - produced:
            print("  run B found keys run A missed -> run A was NOT saturated")
    else:
        print(f"\n(no second run yet at {other.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
