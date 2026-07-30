# -*- coding: utf-8 -*-
import pickle
import sys
from pathlib import Path

ROOT = Path(r"d:\PR-review\AscendC-Pilot")
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

ir = pickle.loads((ROOT / ".probe_cache" / "fag_bundle.pkl").read_bytes())["host_ir"]

for fn in ["GetParseS1S2OuterInfo", "GetSparseBlockInfo", "DoBn2s2Sparse"]:
    lw = ir.local_writes_in(fn)
    print(f"\n=== {fn} local_writes ===")
    for name in sorted(lw.keys()):
        if any(x in name for x in ("invalid", "parseInfo", "isInvalid")):
            print(f"  {name}: {len(lw[name])} writes")
            for w in lw[name][:2]:
                print(f"    L{w.line}: guards={len(w.guards)} rhs={w.rhs[:60]}")

print("\n=== writes to isInvalidRow ===")
for w in ir.writes_to("isInvalidRow"):
    print(f"  {w.function} L{w.line}: {w.path} = {w.rhs[:80]}")
