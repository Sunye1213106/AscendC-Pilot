# -*- coding: utf-8 -*-
"""Per-key reachability report.

For every tiling key the kernel declares (expand_legal_instances), decide one
of three verdicts and attach the concrete replay case when one exists:

  reachable    a real host run produced exactly this key -> case attached
  unreachable  a proof rule excludes it (with the reason)
  unknown      still in U - R: no witness, and no rule excludes it

The point of the file is that "which keys are reachable" stops being a guess:
each of the 8705 declared keys gets a row, and each reachable row carries the
full input that triggers it.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "engines" / "understand-operator" / "src")
)

from replay import runner as R  # noqa: E402
from replay_closure_gate import excluded_by, load_declared, load_runtime, partition  # noqa: E402

INPUT_COLS = ["layout", "dtype", "b", "s1", "s2", "n2", "g", "d", "d1",
              "atten_mask", "pse", "rope", "keep_prob", "sparse_mode"]


def wide_cases() -> dict[str, dict]:
    """case_id -> the full input row of the first witness with that id."""
    m: dict[str, dict] = {}
    for p in sorted(R.CACHE.glob("fag_key_cases*.csv")):
        ls = p.read_text(encoding="utf-8").splitlines()
        h = ls[0].split(",")
        for line in ls[1:]:
            f = line.split(",")
            if len(f) == len(h):
                row = dict(zip(h, f))
                m.setdefault(row["case_id"], row)
    return m


def main() -> int:
    dec = load_declared()
    seen = load_runtime()
    excluded, in_r, gap = partition(seen, dec)
    undeclared = {k: seen[k] for k in seen if k not in dec}
    cases = wide_cases()
    dims = R.DIM_NAMES

    out = R.CACHE / "reachability_report.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tiling_key", "reachability"] + dims + ["case_id"] + INPUT_COLS + ["unreachable_reason"])
        for key, inst in sorted(dec.items()):
            vals = [inst[d] for d in dims]
            if key in in_r:
                cid = seen[key]["case_id"]
                c = cases.get(cid, {})
                w.writerow([key, "reachable"] + vals + [cid] + [c.get(x, "") for x in INPUT_COLS] + [""])
            elif key in excluded:
                w.writerow([key, "unreachable"] + vals + [""] + [""] * len(INPUT_COLS) + ["; ".join(excluded[key])])
            else:
                w.writerow([key, "unknown"] + vals + [""] + [""] * len(INPUT_COLS) + [""])
        for key, wrow in sorted(undeclared.items()):
            vals = [R.SCHEMA.decode_tiling_key(key)[d] for d in dims]
            cid = wrow["case_id"]
            c = cases.get(cid, {})
            w.writerow([key, "undeclared_runtime"] + [str(v) for v in vals] + [cid]
                       + [c.get(x, "") for x in INPUT_COLS] + ["host produced this key but the kernel declaration does not list it"])

    print(f"declared {len(dec)}  reachable {len(in_r)}  unreachable {len(excluded)}  unknown {len(gap)}  undeclared_runtime {len(undeclared)}")
    print(f"-> {out}")

    print("\n=== per-dimension reachability (value: reachable/unreachable/unknown) ===")
    for d in dims:
        rc = Counter(str(in_r[k][d]) for k in in_r)
        ec = Counter(str(dec[k][d]) for k in excluded)
        uc = Counter(str(gap[k][d]) for k in gap)
        vals = sorted(set(rc) | set(ec) | set(uc), key=lambda x: (len(x), x))
        print(f"  {d}: " + "  ".join(f"{v}:{rc.get(v,0)}/{ec.get(v,0)}/{uc.get(v,0)}" for v in vals))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
