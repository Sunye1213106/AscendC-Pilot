# -*- coding: utf-8 -*-
"""The gate that has to pass before any verdict is worth reading.

Coverage is only meaningful as two independent bounds: R, the keys a real host
produced, and U, the keys a sound over-approximation still allows. R (subset of)
H (subset of) U holds by construction, so D - U is proven unreachable and U - R
is what is genuinely unknown. Completion is U - R = 0.

All of that collapses if one rule excludes a key that really happens. This
checks that first and fails loudly, because replay_verdict.py decides
`confirmed` before it looks at the rules and would hide the contradiction.
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
from replay_verdict import UNREACHABLE, UNREACHABLE_COMBOS, _witnesses  # noqa: E402


def excluded_by(inst: dict) -> list[str]:
    """Every rule claiming this instance cannot occur."""
    out = [f"{d}={v}" for d, v in inst.items() if (d, str(v)) in UNREACHABLE]
    for combo, _ in UNREACHABLE_COMBOS:
        if all(str(inst.get(d)) == v for d, v in combo.items()):
            out.append(" + ".join(f"{d}={v}" for d, v in combo.items()))
    return out


def load_runtime() -> dict[int, dict]:
    seen: dict[int, dict] = {}
    for p in sorted(R.CACHE.glob("fag_key_cases*.csv")):
        for k, v in _witnesses(p).items():
            seen.setdefault(k, v)
    return seen


def load_declared() -> dict[int, dict]:
    return {R.SCHEMA.encode_tiling_key({k: int(v) for k, v in i.items()}): i
            for i in expand_legal_instances(R.SCHEMA)}


def partition(seen: dict[int, dict], dec: dict[int, dict]):
    """Split the declared space into proven-unreachable, R, and the gap."""
    excluded, in_r, gap = {}, {}, {}
    for key, inst in dec.items():
        rules = excluded_by(inst)
        if rules:
            excluded[key] = rules
        elif key in seen:
            in_r[key] = inst
        else:
            gap[key] = inst
    return excluded, in_r, gap


def main() -> int:
    seen = load_runtime()
    dec = load_declared()
    excluded, in_r, gap = partition(seen, dec)

    conflicts = {k: excluded[k] for k in excluded if k in seen}

    out = R.CACHE / "coverage_closure.yaml"
    with out.open("w", encoding="utf-8") as f:
        f.write(f"declared: {len(dec)}\n")
        f.write(f"runtime_R: {len(seen)}\n")
        f.write(f"upper_U: {len(dec) - len(excluded)}\n")
        f.write(f"excluded: {len(excluded)}\n")
        f.write(f"open_gap: {len(gap)}\n")
        f.write("soundness_gate:\n")
        f.write(f"  runtime_excluded_intersection: {len(conflicts)}\n")
        f.write(f"  passed: {'true' if not conflicts else 'false'}\n")
        f.write("closure:\n")
        f.write(f"  complete: {'true' if not gap else 'false'}\n")
        f.write(f"  gap: {len(gap)}\n")

    print(f"declared {len(dec)}   R {len(seen)}   U {len(dec) - len(excluded)}   "
          f"excluded {len(excluded)}   U-R {len(gap)}")
    print(f"-> {out}")

    if conflicts:
        print("\nPROOF_RULE_KILLS_RUNTIME_WITNESS")
        by_rule: Counter = Counter()
        for rules in conflicts.values():
            for r in rules:
                by_rule[r] += 1
        for rule, n in by_rule.most_common():
            print(f"  rule '{rule}' contradicted by {n} real witnesses")
        for k in list(conflicts)[:5]:
            print(f"  key {k} case={seen[k]['case_id']} rules={conflicts[k]}")
        return 1

    print("gate PASS - no witnessed key is excluded by any rule")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
