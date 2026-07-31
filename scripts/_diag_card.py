# -*- coding: utf-8 -*-
"""Can the append count of two containers be bounded from the IR alone?"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

NAMES = sys.argv[1:] or ["syncRounds", "syncRoundRanges"]

with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
    bundle = pickle.load(fh)
ir = bundle["host_ir"]
model = bundle["var_model"]

for name in NAMES:
    print(f"== {name}")
    for w in list(ir.writes) + list(ir.local_writes):
        if w.path != name:
            continue
        print(f"  {w.kind} @{w.line}:{w.column} in {w.function}")
        for pc in w.path_conditions:
            print(f"      [{pc.kind}] {pc.pretty()}   @{Path(pc.file).name}:{pc.line}")
            if pc.kind in ("for", "while", "do", "cxx_for_range"):
                node = ir.loop_at(pc.file, pc.line)
                print(
                    f"         loop_at -> cond={node and node.condition!r} "
                    f"induction={node and node.induction_vars}"
                )

print("\n== constant lookup")
for sym in ("CORE_LIST_NUM", "ARRAY_LENGTH"):
    fn = getattr(model, "lookup_constant", None)
    print(f"  {sym} -> {fn(sym) if fn else 'no lookup_constant'}")

print("\n== declarations / construction of these containers")
for name in NAMES:
    hits = [
        w
        for w in list(ir.writes) + list(ir.local_writes)
        if w.path == name and w.kind != "append"
    ]
    print(f"  {name}: non-append events = {len(hits)}")
    for w in hits:
        print(f"      {w.kind} @{w.line} rhs={w.rhs!r}")
