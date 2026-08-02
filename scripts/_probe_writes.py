# -*- coding: utf-8 -*-
"""Where a host name is written, as the expander sees it.

    python scripts/_probe_writes.py splitAxis fBaseParams.splitAxis

`VAR_TDF_X` in an expression means the expander handed back the surface name.
It does that for three reasons -- no write site, loop-scoped writes only, or a
cycle -- and which one it was decides whether anything can be done about it.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))


def main() -> int:
    names = sys.argv[1:] or ["splitAxis", "fBaseParams.splitAxis", "deterSparseType"]
    with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
        bundle = pickle.load(fh)
    from uo_init.derive_key_fields import KeyFieldDeriver

    d = KeyFieldDeriver(
        host_ir=bundle["host_ir"],
        resolver=bundle["resolver"],
        var_model=bundle["var_model"],
    )
    ir = bundle["host_ir"]
    print(f"class_fields: {len(getattr(ir, 'class_fields', ()) or ())}")
    for name in names:
        print(f"\n=== {name}")
        print(f"  in class_fields: {name in (getattr(ir, 'class_fields', ()) or ())}")
        for fn in ("", "DoBn2s2Sparse", "CalcleDeterParam", "DoSparse", "SetTilingKey"):
            canon = d._canonical_name(name, fn)
            pool = d._sites_for(name, canon, fn)
            print(f"  in {fn or '<top>':<18} canon={canon:<32} {len(pool)} writes")
            for s in pool[:4]:
                print(f"      {Path(str(s.file)).name}:{s.line} in {s.function}"
                      f"  = {str(getattr(s, 'value_text', ''))[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
