# -*- coding: utf-8 -*-
"""Are two container producers mutually exclusive at their call sites?

Deciding a joint cardinality bound needs to know whether two loops that append
to the same-named container can both run in one execution. The appends' own path
conditions stop at the function boundary, so the answer has to come from the
guards on the calls that reach those functions.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

FNS = sys.argv[1:] or [
    "CalcleTNDDenseDeterSplitDkOffset",
    "CalcleTNDBandDeterSplitDkOffset",
]

with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
    ir = pickle.load(fh)["host_ir"]


def guards_reaching(fn: str, depth: int = 0, seen=()) -> None:
    pad = "  " * (depth + 1)
    if fn in seen or depth > 4:
        print(f"{pad}... {fn} (cycle or too deep)")
        return
    sites = ir.calls_to(fn)
    if not sites:
        print(f"{pad}{fn}: no recorded call site")
        return
    for s in sites:
        conds = [(pc.kind, pc.pretty()) for pc in s.path_conditions]
        print(f"{pad}{fn} <- {s.caller} @{s.line}:{getattr(s, 'column', 0)}")
        for k, t in conds:
            print(f"{pad}    [{k}] {t}")
        guards_reaching(s.caller, depth + 1, tuple(seen) + (fn,))


for fn in FNS:
    print(f"== guards on every path reaching {fn}")
    guards_reaching(fn)
    print()
