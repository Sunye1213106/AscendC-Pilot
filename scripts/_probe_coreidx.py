# -*- coding: utf-8 -*-
"""What `coreIdx` resolves to now that leaves carry their own scope.

Naming the variable after the symbol alone merged the counters of two
different packing functions into one, asserting the two counts equal, so the
id now takes the scope. Resolving in the right scope made the variable vanish
entirely rather than split in two, and the two ways that can happen point
opposite directions: the counter became a function of the input (good), or it
folded to its initial value (bad — `blockOuter` is then pinned to 1 and every
key needing more than one core disappears).
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

SCOPES = ["FillBlockInfoLoadBalanceForBn2", "CaclePerCoreBlockInfo", "GetTilingKey"]


def main() -> int:
    from uo_init.derive_key_fields import KeyFieldDeriver

    with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
        b = pickle.load(fh)
    deriver = KeyFieldDeriver(
        host_ir=b["host_ir"], resolver=b["resolver"], var_model=b["var_model"]
    )
    for fn in SCOPES:
        res = deriver._scope(fn).resolve("coreIdx")
        atoms = [(a.root, a.symbol) for a in res.atoms]
        print(f"{fn}")
        print(f"    atoms {atoms[:5]}")
        for attr in ("value", "expr", "text", "constant"):
            got = getattr(res, attr, None)
            if got is not None:
                print(f"    {attr} = {str(got)[:150]}")
    print("\nblockOuter, the value the counter reaches:")
    for fn in SCOPES[:2]:
        res = deriver._scope(fn).resolve("fBaseParams.blockOuter")
        print(f"    {fn}: atoms {[(a.root, a.symbol) for a in res.atoms][:4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
