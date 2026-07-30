# -*- coding: utf-8 -*-
import pickle
import sys
from pathlib import Path

ROOT = Path(r"d:\PR-review\AscendC-Pilot")
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

bundle = pickle.loads((ROOT / ".probe_cache" / "fag_bundle.pkl").read_bytes())
resolver = bundle["resolver"]

for fn in ["GetShapeAttrsInfo", "GetParseS1S2OuterInfo", "CalcleActualToken", "DoBn2s2Sparse"]:
    r = resolver._in_function(fn)
    print(f"\n=== {fn} ===")
    for sym in ["qValue", "kvValue", "fBaseParams.actualSeqQlen", "parseInfo", "invalidS1Array"]:
        res = r.resolve(sym)
        atoms = [(a.root, a.symbol) for a in (res.atoms if res else []) if a.root and a.root != "CONSTANT"]
        print(f"  {sym:30} atoms={atoms}")
