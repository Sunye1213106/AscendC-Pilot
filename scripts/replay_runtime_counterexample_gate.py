# -*- coding: utf-8 -*-
"""The gate that has to pass before any verdict is worth reading.

Coverage is only meaningful as two independent bounds: R, the keys a real host
produced, and U, the keys a sound over-approximation still allows. R ⊆ H ⊆ U
holds by construction, so D - U is proven unreachable and U - R is what is
genuinely unknown. Completion is U - R = 0.

All of that collapses if one rule excludes a key that really happens. This
checks that first and fails loudly.

Formerly named closure_gate. The rename matches what it actually checks: a
runtime counterexample to a proof rule, not "closure" of the gap.
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

from replay import corpus as C  # noqa: E402
from replay import rule_engine as RE  # noqa: E402
from replay import runner as R  # noqa: E402


def excluded_by(inst: dict, book: RE.RuleBook | None = None) -> list[str]:
    """Every rule claiming this instance cannot occur."""
    return (book or RE.default_book()).excluded_by(inst)


def load_runtime() -> dict[int, dict]:
    """Witnessed keys from every wide table under the run root."""
    seen: dict[int, dict] = {}
    for p in C.wide_tables():
        for k, v in _witnesses(p).items():
            seen.setdefault(k, v)
    return seen


def _witnesses(path: Path) -> dict[int, dict]:
    rows = path.read_text(encoding="utf-8").splitlines()
    if not rows:
        return {}
    head = rows[0].split(",")
    if "tiling_key" not in head or "ok" not in head:
        return {}
    pos = {n: i for i, n in enumerate(head)}
    out: dict[int, dict] = {}
    for line in rows[1:]:
        f = line.split(",")
        if len(f) != len(head) or f[pos["ok"]] != "1":
            continue
        key = int(f[pos["tiling_key"]])
        if key in out:
            continue
        row = {n: f[i] for i, n in enumerate(head)}
        row["source_file"] = path.name
        out[key] = row
    return out


def load_declared() -> dict[int, dict]:
    return {R.SCHEMA.encode_tiling_key({k: int(v) for k, v in i.items()}): i
            for i in expand_legal_instances(R.SCHEMA)}


def partition(seen: dict[int, dict], dec: dict[int, dict],
              book: RE.RuleBook | None = None):
    """Split the declared space into proven-unreachable, R, and the gap."""
    book = book or RE.default_book()
    excluded, in_r, gap = {}, {}, {}
    for key, inst in dec.items():
        rules = excluded_by(inst, book)
        if rules:
            excluded[key] = rules
        elif key in seen:
            in_r[key] = inst
        else:
            gap[key] = inst
    return excluded, in_r, gap


def counters(seen: dict[int, dict], dec: dict[int, dict],
             excluded: dict, in_r: dict, gap: dict) -> dict:
    """Runtime totals split so undeclared keys stop looking like R."""
    undeclared = {k: seen[k] for k in seen if k not in dec}
    return {
        "declared": len(dec),
        "runtime_total": len(seen),
        "R_declared": len(in_r),
        "undeclared_runtime": len(undeclared),
        "upper_U": len(dec) - len(excluded),
        "excluded": len(excluded),
        "open_gap": len(gap),
    }


def main() -> int:
    book = RE.default_book()
    if not book.hash_ok():
        print(f"derived_rules source_hash mismatch "
              f"(got {book.source_hash}, expected {book.expected_hash})")
        return 2

    seen = load_runtime()
    dec = load_declared()
    excluded, in_r, gap = partition(seen, dec, book)
    stats = counters(seen, dec, excluded, in_r, gap)
    conflicts = {k: excluded[k] for k in excluded if k in seen}

    out = R.CACHE / "coverage_closure.yaml"
    with out.open("w", encoding="utf-8") as f:
        for k, v in stats.items():
            f.write(f"{k}: {v}\n")
        # Backward-compatible alias used by older readers.
        f.write(f"runtime_R: {stats['runtime_total']}\n")
        f.write("soundness_gate:\n")
        f.write(f"  runtime_excluded_intersection: {len(conflicts)}\n")
        f.write(f"  passed: {'true' if not conflicts else 'false'}\n")
        f.write("closure:\n")
        f.write(f"  complete: {'true' if not gap else 'false'}\n")
        f.write(f"  gap: {len(gap)}\n")

    print(f"declared {stats['declared']}   runtime_total {stats['runtime_total']}   "
          f"R_declared {stats['R_declared']}   undeclared {stats['undeclared_runtime']}   "
          f"U {stats['upper_U']}   excluded {stats['excluded']}   U-R {stats['open_gap']}")
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
            print(f"  key {k} case={seen[k].get('case_id')} "
                  f"file={seen[k].get('source_file')} rules={conflicts[k]}")
        return 1

    print("gate PASS - no witnessed key is excluded by any rule")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
