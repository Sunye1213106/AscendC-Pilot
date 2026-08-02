# -*- coding: utf-8 -*-
"""Probe real FAG host_ir bindings + GetDimNum resolution."""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

b = pickle.load(open(ROOT / ".probe_cache" / "fag_bundle.pkl", "rb"))
ir = b["host_ir"]
resolver = b["resolver"]
model = b["var_model"]

print("operands:", model.operand_names())
print("VAR_SHAPE_GETDIMNUM:", model.get("VAR_SHAPE_GETDIMNUM"))
print("sample shape vars:", [k for k in model.variables if k.startswith("VAR_SHAPE_")][:40])

locals_map = ir.locals_by_function()
for fn in [
    "ProcessPseInfo",
    "ProcessSparseModeInfo",
    "GetShapeAttrsInfo",
    "GetDTemplateType",
    "IsSameShape",
]:
    locs = locals_map.get(fn, {})
    interesting = {
        k: v
        for k, v in locs.items()
        if any(
            x in k.lower() or x in (v or "").lower()
            for x in ("pse", "atten", "rope", "shape", "dim", "query", "mask", "storage")
        )
    }
    print(f"\n=== locals {fn} ({len(locs)} total, {len(interesting)} interesting) ===")
    for k, v in sorted(interesting.items()):
        print(f"  {k} = {v}")

# Resolve the exact guards from derive
guards = [
    ("ProcessPseInfo", "pseShape == nullptr || pseShape->GetStorageShape().GetDimNum()== 0"),
    ("ProcessPseInfo", "pseShape->GetStorageShape().GetDimNum() == 0"),
    ("ProcessSparseModeInfo", "attenMaskShape == nullptr || attenMaskShape->GetStorageShape().GetDimNum()== 0"),
    ("GetShapeAttrsInfo", "queryRopeShape->GetDimNum() != 0"),
    ("GetShapeAttrsInfo", "keyRopeShape->GetDimNum() != 0"),
    ("GetShapeAttrsInfo", "queryShape->GetStorageShape().GetDimNum()"),
    ("IsSameShape", "aShape->GetStorageShape().GetDimNum()"),
    ("IsSameShape", "bShape->GetStorageShape().GetDimNum()"),
]

print("\n\n======== RESOLVE WITH FUNCTION SCOPE ========")
for fn, expr in guards:
    r = resolver._in_function(fn)
    res = r.resolve(expr)
    for a in res.atoms:
        vid = model.var_id_for(a.root or "", a.symbol, a.index) if a.root else None
        print(f"[{fn}] {expr[:70]}")
        print(f"  atom root={a.root} symbol={a.symbol!r} index={a.index} -> {vid}")

# Also check GetDim path with same locals for contrast
print("\n\n======== GetDim CONTRAST ========")
for fn, expr in [
    ("GetShapeAttrsInfo", "queryShape->GetStorageShape().GetDim(INPUT_DIM_2)"),
    ("ProcessSparseModeInfo", "storageShape.GetDim(dimNum - LAST_AXIS_IDX)"),
]:
    r = resolver._in_function(fn)
    res = r.resolve(expr)
    for a in res.atoms:
        vid = model.var_id_for(a.root or "", a.symbol, a.index) if a.root else None
        print(f"[{fn}] {expr}")
        print(f"  atom root={a.root} symbol={a.symbol!r} index={a.index} -> {vid}")

# Trace _operand_of failure for pseShape chain
from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Call, Ref
from uo_init.source_resolver import _match, CALL_ROOTS

print("\n\n======== TRACE ProcessPseInfo pseShape.GetDimNum ========")
r = resolver._in_function("ProcessPseInfo")
print("pseShape binding:", r.bindings.get("pseShape"))
expr = "pseShape->GetStorageShape().GetDimNum()"
tree = parse_expr(expr)
assert isinstance(tree, Call)
print("call", tree.func, "nargs", len(tree.args))
# manually step
inner = tree.args[0]
print("receiver type", type(inner).__name__, getattr(inner, "func", None), getattr(inner, "symbol", None))
got = r._operand_of(inner, 0)
print("_operand_of(receiver)=", got)
if isinstance(inner, Call):
    atom = r.resolve_call(inner, 0)
    print("resolve_call receiver:", atom)
    print("  CALL_ROOTS match on symbol?", _match(CALL_ROOTS, atom.symbol or ""))

# value_leaves for the 9 dims
d = json.loads((ROOT / ".probe_cache" / "fag_derive.json").read_text(encoding="utf-8"))
print("\n\n======== value_leaves mentioning GETDIMNUM ========")
for f in d["host_derivation"]["fields"]:
    if "VAR_SHAPE_GETDIMNUM" not in (f.get("variables") or []):
        continue
    leaves = f.get("value_leaves") or []
    hit = [x for x in leaves if "GETDIMNUM" in json.dumps(x, ensure_ascii=False)]
    print(f"\n{f['name']}: {len(hit)} leaves")
    for x in hit[:8]:
        print(" ", json.dumps(x, ensure_ascii=False)[:300])
    # also free_vars / root_vars
    print(" root_vars:", f.get("root_vars"))
    # implicit defaults guards
    for rec in f.get("implicit_defaults") or []:
        if "GetDimNum" in str(rec):
            print(" implicit:", rec.get("function"), rec.get("guard"))
    for site in f.get("def_sites") or []:
        g = " | ".join(site.get("guards") or [])
        if "GetDimNum" in g or "DimNum" in g:
            print(" def_site guards:", site.get("file"), site.get("line"), g[:200])
