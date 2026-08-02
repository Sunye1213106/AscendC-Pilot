# -*- coding: utf-8 -*-
"""Which host-state variables each dimension still reads, and why.

    python scripts/_probe_tdf.py

`VAR_TDF_*` in a dimension's `variables` is the shape of the problem the
auxiliaries were meant to remove: a tiling field with no writer the analysis
could place, standing free in the expression. This lists what is left.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import drivable_root  # noqa: E402


def main() -> int:
    doc = json.loads((ROOT / ".probe_cache" / "fag_derive.json").read_text(encoding="utf-8"))
    aux = (doc.get("host_derivation") or {}).get("auxiliaries") or {}
    print(f"{len(aux)} auxiliaries derived\n")
    for var_id, row in sorted(aux.items()):
        undrivable = sorted(
            v for v in row.get("variables") or []
            if not drivable_root(v, row.get("var_roots"))
        )
        print(f"{var_id}  <- {row.get('host_expr')!r}")
        print(f"  {row.get('status')} / {row.get('exactness')} / "
              f"{row.get('input_closure')}  {row.get('expanded_chars')} chars")
        print(f"  reads {len(row.get('variables') or [])} variables, "
              f"{len(undrivable)} not settable: {undrivable}")

    print("\nper dimension: variables no test case can set")
    for f in doc["fields"]:
        roots = f.get("var_roots") or {}
        undrivable = sorted(
            v for v in f.get("variables") or [] if not drivable_root(v, roots)
        )
        tdf = [v for v in undrivable if v.startswith("VAR_TDF_")]
        mark = "  " if not tdf else "!!"
        print(f"{mark} {f['name']:<15} {f['exactness']:<17} "
              f"{len(f.get('variables') or []):>3} vars  {len(undrivable)} not settable")
        if undrivable:
            print(f"       {undrivable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
