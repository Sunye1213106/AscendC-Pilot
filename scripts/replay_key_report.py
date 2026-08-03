# -*- coding: utf-8 -*-
"""Per-key reachability report.

For every tiling key the kernel declares (expand_legal_instances), decide one
of three verdicts and attach the concrete replay case when one exists:

  reachable    a real host run produced exactly this key -> case attached
  unreachable  a proof rule excludes it (with the reason)
  unknown      still in U - R: no witness, and no rule excludes it

Witness identity is (source_file, case_id): the same case_id in two runs is
two witnesses, not one.
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

from replay import corpus as C  # noqa: E402
from replay import inputs as I  # noqa: E402
from replay import runner as R  # noqa: E402
from replay_runtime_counterexample_gate import (  # noqa: E402
    excluded_by, load_declared, load_runtime, partition,
)

#: Columns taken from the case description rather than hard-coded, so a
#: second operator's report picks up its own fields.
INPUT_COLS = list(I.describe(I.Case()).keys())


def wide_cases() -> dict[tuple[str, str], dict]:
    """(source_file, case_id) -> the full input row."""
    m: dict[tuple[str, str], dict] = {}
    for p in C.wide_tables():
        ls = p.read_text(encoding="utf-8").splitlines()
        if not ls:
            continue
        h = ls[0].split(",")
        for line in ls[1:]:
            f = line.split(",")
            if len(f) == len(h):
                row = dict(zip(h, f))
                row["source_file"] = p.name
                m.setdefault((p.name, row["case_id"]), row)
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
        w.writerow(["tiling_key", "reachability"] + dims
                   + ["source_file", "case_id"] + INPUT_COLS
                   + ["unreachable_reason"])
        for key, inst in sorted(dec.items()):
            vals = [inst[d] for d in dims]
            if key in in_r:
                wrow = seen[key]
                cid = wrow["case_id"]
                src = wrow.get("source_file", "")
                c = cases.get((src, cid), {})
                w.writerow([key, "reachable"] + vals + [src, cid]
                           + [c.get(x, "") for x in INPUT_COLS] + [""])
            elif key in excluded:
                w.writerow([key, "unreachable"] + vals + ["", ""]
                           + [""] * len(INPUT_COLS)
                           + ["; ".join(excluded[key])])
            else:
                w.writerow([key, "unknown"] + vals + ["", ""]
                           + [""] * len(INPUT_COLS) + [""])
        for key, wrow in sorted(undeclared.items()):
            vals = [R.SCHEMA.decode_tiling_key(key)[d] for d in dims]
            cid = wrow["case_id"]
            src = wrow.get("source_file", "")
            c = cases.get((src, cid), {})
            w.writerow(
                [key, "undeclared_runtime"] + [str(v) for v in vals]
                + [src, cid] + [c.get(x, "") for x in INPUT_COLS]
                + ["host produced this key but the kernel declaration does not list it"])

    print(f"declared {len(dec)}  reachable {len(in_r)}  unreachable {len(excluded)}  "
          f"unknown {len(gap)}  undeclared_runtime {len(undeclared)}")
    print(f"-> {out}")

    by = Counter()
    for key in in_r:
        by["reachable"] += 1
    for key in excluded:
        by["unreachable"] += 1
    for key in gap:
        by["unknown"] += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
