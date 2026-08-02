# -*- coding: utf-8 -*-
"""Every write to a name, with the conditions it runs under.

`def_sites` on a field record only covers the key field itself; when a minted
initial value points at some member deep in the chain, this is how to see what
the derivation had to work with. Usage: `_probe_writes.py fBaseParams.pseOptional`
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    wanted = sys.argv[1]

    with open(ROOT / ".probe_cache" / "fag_bundle.pkl", "rb") as fh:
        bundle = pickle.load(fh)
    ir = bundle.host_ir if hasattr(bundle, "host_ir") else bundle["host_ir"]

    hits = [w for w in ir.writes if w.path == wanted or w.path.endswith("." + wanted)]
    print(f"{wanted}: {len(hits)} write(s)")
    for w in sorted(hits, key=lambda w: (w.file, w.line)):
        print(f"\n  {w.file.rsplit('/', 1)[-1]}:{w.line}  [{w.function}]")
        print(f"      = {w.rhs[:100]}")
        for c in w.path_conditions:
            kind = getattr(c, "kind", "")
            neg = "not " if c.negated else ""
            print(f"      under {neg}{c.text[:100]}" + (f"   <{kind}>" if kind else ""))
        # `guards()` is what the derivation actually chains on: it drops the
        # bail-out premises, which are conditions on the whole run rather than
        # on this write.
        kept = list(w.guards())
        if len(kept) != len(w.path_conditions):
            print(f"      -> guards() keeps {len(kept)} of {len(w.path_conditions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
