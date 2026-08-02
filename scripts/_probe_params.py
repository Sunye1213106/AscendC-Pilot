# -*- coding: utf-8 -*-
"""Does the host IR carry enough to bind `m0Max` across the call chain?"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
    bundle = pickle.load(fh)
ir = bundle["host_ir"]

FNS = [
    "CalcleTNDCausalDeterParam",
    "CalcleTNDCausalDeterPrefix",
    "CalcleTNDCausalDeterParamNormal",
    "CalcleTNDCausalDeterParamGQA",
    "DoSplit",
    "FuzzyForBestSplit",
    "CalcleDeterParam",
]
for fn in FNS:
    s = ir.summaries.get(fn)
    print(f"\n=== {fn} ===")
    if s is None:
        print("  (no summary)")
        continue
    print(f"  params     : {list(s.params)}")
    print(f"  out_params : {list(s.out_params)}")
    print(f"  returns    : {list(s.returns)[:4]}")
    calls = [(c, a) for c, a in s.calls if "m0Max" in " ".join(a) or "s2Inner" in " ".join(a)]
    print(f"  calls with m0Max/s2Inner actuals: {calls}")

print("\n=== who calls the readers of m0Max ===")
for short in ("CalcleTNDCausalDeterParamNormal", "CalcleTNDCausalDeterParamGQA",
              "CalcleTNDCausalDeterPrefix", "FuzzyForBestSplit"):
    sites = ir.calls_to(short) if hasattr(ir, "calls_to") else []
    for st in sites:
        print(f"  {short} <- {st.caller} @ {Path(st.file).name}:{st.line} args={getattr(st,'args',None)}")

print("\n=== _out_param_defs reasoning for m0Max ===")
from uo_init.derive_key_fields import KeyFieldDeriver

d = KeyFieldDeriver(
    host_ir=ir, resolver=bundle["resolver"], var_model=bundle["var_model"]
)
for fn in ("CalcleTNDCausalDeterParamGQA", "CalcleTNDCausalDeterParamNormal",
           "CalcleTNDCausalDeterParam"):
    caller = ir.summaries.get(fn)
    found = []
    if caller is not None:
        for callee, args in caller.calls:
            target = ir.summaries.get(callee)
            if target is None or not target.out_params:
                continue
            for pname, actual in zip(target.params, args):
                if pname in set(target.out_params) and (actual or "").lstrip("&").strip() == "m0Max":
                    found.append((callee, pname))
    print(f"  {fn}: out_param candidates={found} "
          f"-> _out_param_defs={len(d._out_param_defs('m0Max', fn))}")
    owners = [o for o in ir.summaries if o != fn and ir.local_writes_in(o).get("m0Max")]
    print(f"      _unique_foreign_defs owners={owners} (needs exactly 1)")

print("\n=== s2Inner owners (for _active collision) ===")
print([o for o in ir.summaries if ir.local_writes_in(o).get("s2Inner")])

print("\n=== source files parsed (first 6 distinct) ===")
files = sorted({w.file for ws in (ir.local_writes_in(f) for f in list(ir.summaries)[:200])
                for wl in ws.values() for w in wl})
for f in files[:12]:
    print(f"  {f}")
