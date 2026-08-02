# -*- coding: utf-8 -*-
"""Before/after diff of the derived fields, for the GetDimNum identity fix."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"

VAR_RE = re.compile(r"VAR_[A-Z0-9_]+")


def load(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {f["name"]: f for f in doc["host_derivation"]["fields"]}


def vars_of(field: dict) -> set[str]:
    return set(VAR_RE.findall(json.dumps(field.get("value_expr"), ensure_ascii=False)))


def main() -> None:
    old = load(CACHE / "fag_derive.baseline.json")
    new = load(CACHE / "fag_derive.json")

    print("==== fields whose variables changed ====")
    for name, f in new.items():
        a, b = vars_of(old.get(name, {})), vars_of(f)
        if a == b:
            continue
        print(f"\n### {name}  [{old[name]['exactness']} -> {f['exactness']}]")
        for v in sorted(a - b):
            print(f"  - {v}")
        for v in sorted(b - a):
            print(f"  + {v}")

    print("\n==== VAR_SHAPE_GETDIMNUM / GETDIM users ====")
    for label, doc in (("before", old), ("after", new)):
        users = {
            n: sorted(v for v in vars_of(f) if "GETDIM" in v)
            for n, f in doc.items()
            if any("GETDIM" in v for v in vars_of(f))
        }
        print(f"  {label}: {len(users)} fields")
        for n, vs in sorted(users.items()):
            print(f"    {n}: {vs}")

    print("\n==== IsRope / IsPse / IsAttenMask expressions ====")
    for name in ("IsRope", "IsPse", "IsAttenMask", "IsEmptyTensor"):
        for label, doc in (("before", old), ("after", new)):
            f = doc.get(name)
            if f is None:
                continue
            print(f"  [{label}] {name}: {json.dumps(f.get('value_expr'), ensure_ascii=False)[:400]}")

    print("\n==== totals ====")
    for label, doc in (("before", old), ("after", new)):
        free = sorted({v for f in doc.values() for v in f.get("free_vars") or []})
        print(f"  {label}: free_vars={len(free)} {free}")


if __name__ == "__main__":
    sys.exit(main())
