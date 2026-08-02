# -*- coding: utf-8 -*-
"""What the derived expressions read, and where each variable claims to come from.

Feeding the unit tests' inputs into the derivation needs a map from what a test
case sets (shapes, dtypes, attrs) to the host variables the expressions name.
This prints the variables and their recorded roots so the map can be written.
"""

from __future__ import annotations

import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import (  # noqa: E402
    Auxiliaries,
    Premises,
    ValueTree,
    domains_of,
    drivable_root,
)


def main() -> int:
    if not (CACHE / "fag_derive.json").is_file():
        print(f"no cache at {CACHE / 'fag_derive.json'}; run scripts/_probe_derive.py")
        return 1

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    saved = doc.get("host_derivation") or {}
    aux = Auxiliaries.from_rows(saved.get("auxiliaries") or {})
    premises = Premises(saved.get("premises") or [])

    fields = [f for f in doc["fields"] if f.get("value_expr") is not None]
    trees = [(f["name"], ValueTree(f["value_expr"])) for f in fields]
    print(f"{len(trees)}/{len(doc['fields'])} dimensions have an expression")
    nofx = [f["name"] for f in doc["fields"] if f.get("value_expr") is None]
    if nofx:
        print(f"  no expression: {nofx}")

    roots: dict[str, str] = {}
    for f in doc["fields"]:
        roots.update(f.get("var_roots") or {})

    allvars: set[str] = set()
    per_dim: dict[str, set] = {}
    for name, t in trees:
        _c, v = t.cuts()
        per_dim[name] = set(v)
        allvars |= v
    for t in aux.trees.values():
        _c, v = t.cuts()
        allvars |= v
    allvars -= aux.names

    print(f"\n{len(allvars)} variables read across all dimensions")
    print(f"{len(aux.names)} auxiliaries the operator computes: {sorted(aux.names)}")

    settable, host = [], []
    for v in sorted(allvars):
        (settable if drivable_root(v, roots) else host).append(v)

    print(f"\n=== {len(settable)} variables a test case can set ===")
    for v in settable:
        print(f"  {v:<42} root={roots.get(v, '<none>')}")

    print(f"\n=== {len(host)} variables it cannot (host state) ===")
    for v in host:
        print(f"  {v:<42} root={roots.get(v, '<none>')}")

    print(f"\n=== 每维读到的变量数 ===")
    for name, vs in sorted(per_dim.items(), key=lambda kv: -len(kv[1])):
        print(f"  {name:<18} {len(vs):>3} vars")

    if premises.vars:
        print(f"\n{len(premises.vars)} variables constrained by premises")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
