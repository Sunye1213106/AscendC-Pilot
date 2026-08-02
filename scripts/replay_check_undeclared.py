# -*- coding: utf-8 -*-
"""Explain the keys the host produced that no declared instance matches.

Either the kernel is missing a template the host can ask for, or the TPL parse
dropped a selection group. Finding the nearest declared instance and naming the
dimensions that differ tells the two apart.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "engines" / "understand-operator" / "src")
)

from uo_init.tpl_dsl import expand_legal_instances  # noqa: E402

from replay import runner as R  # noqa: E402


def main() -> int:
    rows = (R.CACHE / "key_reachability.csv").read_text(encoding="utf-8").splitlines()
    head = rows[0].split(",")
    idx = {n: i for i, n in enumerate(head)}
    undeclared = []
    for line in rows[1:]:
        f = line.split(",")
        if len(f) == len(head) and f[idx["verdict"]] == "undeclared_runtime":
            undeclared.append({n: f[idx["dim_" + n]] for n in R.DIM_NAMES}
                              | {"_key": f[0], "_case": f[idx["evidence"]]})
    print(f"{len(undeclared)} keys produced with no declared instance")
    if not undeclared:
        return 0

    inst = expand_legal_instances(R.SCHEMA)
    diff_names: Counter = Counter()
    for target in undeclared:
        best, best_diff = None, None
        for cand in inst:
            diff = [n for n in R.DIM_NAMES if cand.get(n) != target[n]]
            if best_diff is None or len(diff) < len(best_diff):
                best, best_diff = cand, diff
                if not diff:
                    break
        diff_names["+".join(best_diff)] += 1
        if len(diff_names) <= 3 and diff_names["+".join(best_diff)] == 1:
            print(f"\nkey={target['_key']} case={target['_case']}")
            print(f"  nearest declared instance differs on: {best_diff}")
            for n in best_diff:
                print(f"    {n}: declared={best[n]}  produced={target[n]}")

    print("\n--- differing dimension sets, by frequency ---")
    for name, n in diff_names.most_common():
        print(f"  {n:>4}  {name}")

    # If every miss trips the same dimension, look at what the kernel allows
    # there before calling it a bug.
    lone = [name for name in diff_names if "+" not in name]
    for name in lone:
        allowed = Counter(i[name] for i in inst)
        got = Counter(t[name] for t in undeclared)
        print(f"\n  {name}: kernel declares {dict(allowed)}; host produced "
              f"{dict(got)} in these keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
