# -*- coding: utf-8 -*-
"""Simulate _container_element resolution with bundle resolvers."""
import pickle
import sys
from pathlib import Path

ROOT = Path(r"d:\PR-review\AscendC-Pilot")
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.derive_key_fields import _container_of
from uo_init.expr_ir import Call, Ref, Select, Const

bundle = pickle.loads((ROOT / ".probe_cache" / "fag_bundle.pkl").read_bytes())
resolver = bundle["resolver"]

# approximate scope_for
def scope_for(fn):
    if hasattr(resolver, "scope_for"):
        return resolver.scope_for(fn)
    return resolver

FB = Ref("fBaseParams", scope="GetShapeAttrsInfo")
cases = [
    ("C_member", "GetShapeAttrsInfo", Select(Call("field:actualSeqQlen", (FB,)), Ref("batchIdx"))),
    ("C_call", "CalcleActualToken", Select(Call("actualSeqQlen", (FB,)), Ref("batchIdx"))),
    ("D_qValue", "GetShapeAttrsInfo", Select(Ref("qValue", scope="GetShapeAttrsInfo"), Const(0))),
    ("B_parseInfo", "GetParseS1S2OuterInfo", Select(Ref("parseInfo", scope="GetParseS1S2OuterInfo"), Ref("i"))),
    ("A_invalid", "GetParseS1S2OuterInfo", Select(Ref("invalidS1Array", scope="GetParseS1S2OuterInfo"), Ref("j"))),
]

for label, fn, sel in cases:
    container = _container_of(sel.array)
    if not container:
        from uo_init.source_resolver import dotted_path
        container = dotted_path(sel.array) or ""
    res = scope_for(fn).resolve(container or "???")
    atoms = [a for a in (res.atoms if res else []) if a.root and a.root != "CONSTANT"]
    print(f"{label:12} container={container!r:40} atoms={[(a.root,a.symbol) for a in atoms]}")
