# -*- coding: utf-8 -*-
"""What is actually left in U - R, and what would it take to reach it.

The counters say how many keys are unresolved. They do not say whether the
search is one knob short or has never once produced a value the target needs.
This separates the two, because they want opposite work: a value no witness
has ever carried is a generator problem, while a combination of values each
seen separately is a joint-search problem.

    python scripts/_probe_gap_anatomy.py
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))


def main() -> int:
    from replay import rule_engine as RE
    from replay import runner as R
    from replay_runtime_counterexample_gate import (
        load_declared,
        load_runtime,
        partition,
    )

    dims = list(R.DIM_NAMES)
    book = RE.default_book()
    seen = load_runtime()
    dec = load_declared()

    proof_only = RE.load_proof(R.default().manifest.package / "proof_rules.yaml")
    excluded, in_r, gap = partition(seen, dec, book)
    ex_proof, _in_p, gap_proof = partition(seen, dec, proof_only)

    print(f"declared U {len(dec)}   witness R {len(in_r)}   "
          f"excluded {len(excluded)}   unknown {len(gap)}")
    print(f"solver rules exclude {len(excluded) - len(ex_proof)} keys the "
          f"human rules do not ({len(gap_proof) - len(gap)} fewer unknown)")

    print("\n=== which rule excludes what ===")
    by_rule: Counter = Counter()
    for labels in excluded.values():
        for lab in labels:
            by_rule[lab] += 1
    overlap = sum(1 for labels in excluded.values() if len(labels) > 1)
    grade = {r.label: r.grade for r in book.rules}
    for lab, n in by_rule.most_common(40):
        print(f"  {n:>5}  [{grade.get(lab, '?'):<14}] {lab}")
    print(f"  ({overlap} keys are excluded by more than one rule)")

    # Values each dimension takes, in the declared space and among witnesses.
    dec_vals: dict[str, set] = defaultdict(set)
    wit_vals: dict[str, set] = defaultdict(set)
    for inst in dec.values():
        for d in dims:
            dec_vals[d].add(str(inst.get(d)))
    for key in in_r:
        for d in dims:
            dec_vals[d].add(str(dec[key].get(d)))
            wit_vals[d].add(str(dec[key].get(d)))

    print("\n=== declared values never witnessed ===")
    never: dict[str, set] = {}
    for d in dims:
        missing = dec_vals[d] - wit_vals[d]
        if missing:
            never[d] = missing
            print(f"  {d:<16} witnessed {sorted(wit_vals[d])}  "
                  f"NEVER {sorted(missing)}")
    if not never:
        print("  none: every declared value of every dimension has a witness")

    # An unknown key is out of reach of any recombination of what we have seen
    # if even one of its values has never been produced at all.
    print("\n=== unknown keys, by why they are unreached ===")
    blocked: Counter = Counter()
    reachable_by_recombination = 0
    for key, inst in gap.items():
        need = [(d, str(inst.get(d))) for d in dims
                if str(inst.get(d)) in never.get(d, ())]
        if need:
            for pair in need:
                blocked[pair] += 1
        else:
            reachable_by_recombination += 1
    print(f"  {reachable_by_recombination} need only a new COMBINATION of "
          f"values that have each been produced before")
    print(f"  {len(gap) - reachable_by_recombination} need a value that has "
          f"NEVER been produced by any input")
    for (d, v), n in blocked.most_common(25):
        print(f"      {n:>5}  {d}={v}")

    # For the recombination-reachable ones, which dimension pairs never co-occur.
    print("\n=== value pairs never seen together (top blockers) ===")
    pair_seen: set = set()
    for key in in_r:
        inst = dec[key]
        vals = [(d, str(inst.get(d))) for d in dims]
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                pair_seen.add((vals[i], vals[j]))
    pair_need: Counter = Counter()
    for key, inst in gap.items():
        if any(str(inst.get(d)) in never.get(d, ()) for d in dims):
            continue
        vals = [(d, str(inst.get(d))) for d in dims]
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                if (vals[i], vals[j]) not in pair_seen:
                    pair_need[(vals[i], vals[j])] += 1
    for (a, b), n in pair_need.most_common(20):
        print(f"  {n:>5}  {a[0]}={a[1]}  x  {b[0]}={b[1]}")
    if not pair_need:
        print("  none: every pair in every unknown key has co-occurred somewhere")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
