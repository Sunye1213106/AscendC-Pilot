# -*- coding: utf-8 -*-
"""The gate that has to pass before any verdict is worth reading.

Coverage is only meaningful as two independent bounds: R, the keys a real host
produced, and U, the keys a sound over-approximation still allows. R ⊆ H ⊆ U
holds by construction, so D - U is proven unreachable and U - R is what is
genuinely unknown. Completion is U - R = 0.

U_sound counts only solver-derived / source-lemma rules. Human and LLM rules
feed U_reviewed but do not shrink the sound upper bound by default.

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


def excluded_by(
    inst: dict,
    book: RE.RuleBook | None = None,
    *,
    grades: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Every rule claiming this instance cannot occur.

    ``grades=None`` is the reviewed view (all rules). Pass ``RE.SOUND_GRADES``
    for the sound upper bound.
    """
    return (book or RE.default_book()).excluded_by(inst, grades=grades)


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


def partition(
    seen: dict[int, dict],
    dec: dict[int, dict],
    book: RE.RuleBook | None = None,
    *,
    grades: frozenset[str] | set[str] | None = None,
):
    """Split the declared space into proven-unreachable, R, and the gap."""
    book = book or RE.default_book()
    excluded, in_r, gap = {}, {}, {}
    for key, inst in dec.items():
        rules = excluded_by(inst, book, grades=grades)
        if rules:
            excluded[key] = rules
        elif key in seen:
            in_r[key] = inst
        else:
            gap[key] = inst
    return excluded, in_r, gap


def excluded_by_grade(dec: dict[int, dict], book: RE.RuleBook) -> dict[str, int]:
    """Keys excluded by at least one rule of each grade."""
    known = {r.grade for r in book.rules}
    counts = {g: 0 for g in sorted(known)}
    for inst in dec.values():
        for grade in known:
            if book.excluded_by(inst, grades={grade}):
                counts[grade] += 1
    return counts


def counters(
    seen: dict[int, dict],
    dec: dict[int, dict],
    excluded_sound: dict,
    excluded_reviewed: dict,
    gap_sound: dict,
    gap_reviewed: dict,
    *,
    in_r: dict | None = None,
) -> dict:
    """Runtime totals split so undeclared keys stop looking like R."""
    undeclared = {k: seen[k] for k in seen if k not in dec}
    r_declared = len(in_r) if in_r is not None else sum(1 for k in dec if k in seen)
    return {
        "declared": len(dec),
        "runtime_total": len(seen),
        "R_declared": r_declared,
        "undeclared_runtime": len(undeclared),
        "upper_U_sound": len(dec) - len(excluded_sound),
        "upper_U_reviewed": len(dec) - len(excluded_reviewed),
        "excluded_sound": len(excluded_sound),
        "excluded_reviewed": len(excluded_reviewed),
        "open_gap_sound": len(gap_sound),
        "open_gap_reviewed": len(gap_reviewed),
        # Backward-compatible aliases (reviewed view).
        "upper_U": len(dec) - len(excluded_reviewed),
        "excluded": len(excluded_reviewed),
        "open_gap": len(gap_reviewed),
    }


def main() -> int:
    book = RE.default_book()
    if not book.hash_ok():
        print(f"derived_rules source_hash mismatch "
              f"(got {book.source_hash}, expected {book.expected_hash})")
        return 2

    seen = load_runtime()
    dec = load_declared()
    excluded_sound, in_r, gap_sound = partition(
        seen, dec, book, grades=RE.SOUND_GRADES)
    excluded_reviewed, _, gap_reviewed = partition(seen, dec, book, grades=None)
    stats = counters(
        seen, dec, excluded_sound, excluded_reviewed, gap_sound, gap_reviewed,
        in_r=in_r)
    by_grade = excluded_by_grade(dec, book)
    conflicts = {k: excluded_reviewed[k] for k in excluded_reviewed if k in seen}

    out = R.CACHE / "coverage_closure.yaml"
    with out.open("w", encoding="utf-8") as f:
        for k, v in stats.items():
            f.write(f"{k}: {v}\n")
        f.write("excluded_by_grade:\n")
        for grade, n in sorted(by_grade.items()):
            f.write(f"  {grade}: {n}\n")
        # Backward-compatible alias used by older readers.
        f.write(f"runtime_R: {stats['runtime_total']}\n")
        f.write("soundness_gate:\n")
        f.write(f"  runtime_excluded_intersection: {len(conflicts)}\n")
        f.write(f"  passed: {'true' if not conflicts else 'false'}\n")
        f.write("closure:\n")
        f.write(f"  complete: {'true' if not gap_sound else 'false'}\n")
        f.write(f"  gap: {len(gap_sound)}\n")
        f.write(f"  gap_reviewed: {len(gap_reviewed)}\n")

    print(
        f"declared {stats['declared']}   runtime_total {stats['runtime_total']}   "
        f"R_declared {stats['R_declared']}   undeclared {stats['undeclared_runtime']}   "
        f"U_sound {stats['upper_U_sound']}   excluded_sound {stats['excluded_sound']}   "
        f"U_sound-R {stats['open_gap_sound']}   "
        f"U_reviewed {stats['upper_U_reviewed']}   excluded_reviewed {stats['excluded_reviewed']}   "
        f"U_reviewed-R {stats['open_gap_reviewed']}")
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
