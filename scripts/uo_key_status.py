# -*- coding: utf-8 -*-
"""Report how exactly each TilingKey field is derived.

`host_derivation.yaml` records a `status` per field, but "derived" spans both a
field pinned to its inputs and one whose guards were all replaced by free
booleans. This prints the finer `exactness` grade plus the over-approximation
variables still standing in each expression, which is the list that has to
reach zero.

    python scripts/uo_key_status.py <path-to-host_derivation.yaml>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

EXACTNESS_ORDER = ["exact", "constant", "overapproximated", "partial", "unresolved"]


def load(path: Path) -> dict[str, Any]:
    """Accept the workflow's YAML artifact or the probe script's JSON dump."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        doc = json.loads(text)
        return doc.get("host_derivation") or doc
    return yaml.safe_load(text) or {}


def free_vars_of(field: dict[str, Any]) -> list[str]:
    recorded = field.get("free_vars")
    if recorded:
        return sorted(str(v) for v in recorded)
    # Older artifacts predate the field; recover it from the variable list.
    prefixes = ("VAR_UNDECIDED_", "VAR_SCHED_", "VAR_REACHED_", "VAR_INIT_")
    return sorted(str(v) for v in field.get("variables") or [] if str(v).startswith(prefixes))


def derivable_of(field: dict[str, Any]) -> bool | None:
    """Closed *and* drivable, or None if the artifact predates the grading.

    Recomputing it here would mean copying `CONTROLLABLE_ROOTS` into a reporting
    script, so old artifacts read as unknown instead.
    """
    recorded = field.get("input_derivable")
    return bool(recorded) if recorded is not None else None


def exactness_of(field: dict[str, Any]) -> str:
    recorded = field.get("exactness")
    if recorded:
        return str(recorded)
    if field.get("value_expr") is None:
        return "unresolved"
    if field.get("unresolved"):
        return "partial"
    if free_vars_of(field):
        return "overapproximated"
    return "constant" if not field.get("variables") else "exact"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "derivation", type=Path, help="host_derivation.yaml, or the probe's fag_derive.json"
    )
    parser.add_argument("--verbose", action="store_true", help="list every free variable")
    args = parser.parse_args(argv)

    if not args.derivation.is_file():
        print(f"no such file: {args.derivation}", file=sys.stderr)
        return 2

    doc = load(args.derivation)
    fields = doc.get("fields") or []
    if not fields:
        print("no fields in derivation", file=sys.stderr)
        return 2

    print(f"op={doc.get('op_name') or '?'} arch={doc.get('architecture') or '?'} fields={len(fields)}")
    print()
    print(
        f"{'#':>3} {'field':<24} {'exactness':<17} {'closure':<15} "
        f"{'drivable':<9} {'vars':>5} {'free':>5}  note"
    )
    grades: Counter[str] = Counter()
    all_free: Counter[str] = Counter()
    for f in sorted(fields, key=lambda x: int(x.get("index") or 0)):
        grade = exactness_of(f)
        free = free_vars_of(f)
        grades[grade] += 1
        all_free.update(free)
        note = str(f.get("note") or "")[:44]
        drivable = derivable_of(f)
        print(
            f"{int(f.get('index') or 0):>3} {str(f.get('name') or ''):<24} {grade:<17} "
            f"{str(f.get('input_closure') or '-'):<15} "
            f"{('-' if drivable is None else str(drivable)):<9} "
            f"{len(f.get('variables') or []):>5} {len(free):>5}  {note}"
        )
        if args.verbose and free:
            for v in free:
                print(f"{'':>6}- {v}")

    print()
    summary = "  ".join(f"{g}={grades.get(g, 0)}" for g in EXACTNESS_ORDER)
    print(f"grades: {summary}")
    print(f"distinct free variables: {len(all_free)}")
    exact = grades.get("exact", 0) + grades.get("constant", 0)
    print(f"CLOSED {exact}/{len(fields)} fields, {len(all_free)} over-approximations remaining")

    # The number a generator should read. Lower than CLOSED whenever a field
    # closes onto host tiling state: the expression is exact, and nothing a case
    # can set reaches it.
    verdicts = [derivable_of(f) for f in fields]
    known = [v for v in verdicts if v is not None]
    if known:
        print(f"INPUT_DERIVABLE {sum(known)}/{len(fields)} fields (closed and drivable)")
    else:
        print("INPUT_DERIVABLE unknown: artifact predates the input_closure grading")

    # The template and the host disagree about what a dimension may hold.
    # Neither side is ours to change; it goes back to the operator.
    for f in fields:
        bad = f.get("domain_violations") or []
        if bad:
            print(
                f"  contract conflict: {f.get('name')} encodes {list(bad)}, "
                f"template declares {list(f.get('domain') or [])}"
            )

    # A free variable with no guard record cannot be escalated or closed, yet
    # still weakens the condition. It has to be zero.
    unrecorded: dict[str, list[str]] = {}
    for f in fields:
        recorded = {str(g.get("var_id")) for g in f.get("undecided_guards") or []}
        missing = [v for v in free_vars_of(f) if v not in recorded]
        if missing:
            unrecorded[str(f.get("name"))] = missing
    if unrecorded:
        total = len({v for vs in unrecorded.values() for v in vs})
        print(f"\nWARNING: {total} over-approximations have no guard record:")
        for name, missing in sorted(unrecorded.items()):
            print(f"  {name}: {', '.join(missing)}")
    else:
        print("every over-approximation has a guard record")

    # Not over-approximations, but assertions about declarations we never read.
    # An exact field resting on one of these is only exact if the assumption holds.
    assumed = {str(f.get("name")): len(f.get("implicit_defaults") or []) for f in fields}
    total_assumed = sum(assumed.values())
    if total_assumed:
        tainted = sorted(
            n for n, c in assumed.items() if c and exactness_of(next(f for f in fields if f.get("name") == n)) in ("exact", "constant")
        )
        print(f"\n{total_assumed} places assume a field defaults to zero")
        if tainted:
            print(f"  of which {len(tainted)} sit under a field graded exact: {', '.join(tainted)}")

    if all_free and args.verbose:
        print()
        print("free variables by frequency:")
        for var, count in all_free.most_common():
            print(f"  {count:>3}x {var}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
