# -*- coding: utf-8 -*-
"""Show the source text behind each over-approximation, worst offenders first.

`uo_key_status.py` counts what is still unresolved; this says what each one
actually is, so the guards blocking the most key fields can be attacked first.

    python scripts/uo_key_blockers.py <path-to-host_derivation.yaml>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

PREFIXES = ("VAR_UNDECIDED_", "VAR_SCHED_", "VAR_REACHED_", "VAR_INIT_")


def load(path: Path) -> dict[str, Any]:
    """Accept the workflow's YAML artifact or the probe script's JSON dump."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        doc = json.loads(text)
        return doc.get("host_derivation") or doc
    return yaml.safe_load(text) or {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("derivation", type=Path)
    parser.add_argument("--width", type=int, default=150, help="guard text width")
    args = parser.parse_args(argv)

    if not args.derivation.is_file():
        print(f"no such file: {args.derivation}", file=sys.stderr)
        return 2
    doc = load(args.derivation)

    affected: dict[str, set[str]] = defaultdict(set)
    detail: dict[str, dict[str, Any]] = {}
    for f in doc.get("fields") or []:
        name = str(f.get("name") or "")
        for var in f.get("variables") or []:
            if str(var).startswith(PREFIXES):
                affected[str(var)].add(name)
        for guard in f.get("undecided_guards") or []:
            var = str(guard.get("var_id") or "")
            if var:
                detail.setdefault(var, guard)

    if not affected:
        print("no over-approximations: every field is exact")
        return 0

    print(f"{len(affected)} over-approximations across {len(doc.get('fields') or [])} fields\n")
    for var, fields in sorted(affected.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        info = detail.get(var) or {}
        reason = str(info.get("reason") or "?")
        presort = str(info.get("presort") or "?")
        text = " ".join(str(info.get("text") or "").split())
        print(f"[{len(fields)} fields] {var}  reason={reason} presort={presort}")
        print(f"    fields: {', '.join(sorted(fields))}")
        blocked = str(info.get("blocked_on") or "")
        if blocked:
            # The one symbol that defeated it. For a deeply expanded guard this
            # is the only actionable part of the record.
            print(f"    ON    : {blocked}")
        print(f"    guard : {text[:args.width]}")
        evidence = info.get("evidence")
        if isinstance(evidence, dict) and evidence:
            loc = f"{evidence.get('file') or '?'}:{evidence.get('line') or '?'}"
            print(f"    source: {loc}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
