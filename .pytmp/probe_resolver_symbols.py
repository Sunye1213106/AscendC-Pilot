# -*- coding: utf-8 -*-
import pickle
import sys
from pathlib import Path

ROOT = Path(r"d:\PR-review\AscendC-Pilot")
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

bundle = pickle.loads((ROOT / ".probe_cache" / "fag_bundle.pkl").read_bytes())
resolver = bundle["resolver"]
ir = bundle["host_ir"]

fn = "GetShapeAttrsInfo"
r = resolver.scope_for(fn) if hasattr(resolver, "scope_for") else resolver

for sym in ["qValue", "kvValue", "actualSeqQlen", "fBaseParams.actualSeqQlen", "actualSeqQlen(fBaseParams)", "parseInfo", "invalidS1Array"]:
    res = r.resolve(sym)
    atoms = [(a.root, a.symbol) for a in (res.atoms if res else []) if a.root and a.root != "CONSTANT"]
    print(f"{sym:35} closed={getattr(res,'closed',None)} atoms={atoms}")

# local bindings in GetShapeAttrsInfo
summary = ir.summaries.get(fn)
if summary:
    print("\nGetShapeAttrsInfo locals sample:")
    for k in sorted(summary.locals.keys()):
        if any(x in k for x in ("qValue", "kvValue", "actualSeq", "Seq")):
            print(f"  {k} = {summary.locals[k][:80]}")

print("\nGetParseS1S2OuterInfo locals:")
summary2 = ir.summaries.get("GetParseS1S2OuterInfo")
if summary2:
    for k in sorted(summary2.locals.keys()):
        if any(x in k for x in ("parse", "invalid", "S1")):
            print(f"  {k} = {summary2.locals[k][:80]}")
