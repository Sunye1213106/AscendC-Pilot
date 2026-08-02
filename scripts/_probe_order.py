# -*- coding: utf-8 -*-
"""Can a write's position be lifted into a common function, the way a read's is?

`_field_defs` sorts writes by `(file, line)`, which is a textual order with no
relation to the order the program runs them in. `_read_lines` already solves
the same problem for reads: it climbs single call sites out of loops into
callers that run once, and reports where the read happens *as seen from* each
of those callers. This checks the climb terminates somewhere useful for the
writes that are currently folded in the wrong order.

    python scripts/_probe_order.py fBaseParams.deterSparseType fBaseParams.blockOuter
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"


def short(path: str) -> str:
    return Path(path).name.replace("flash_attention_score_grad_tiling_", "")


def main() -> int:
    sys.setrecursionlimit(20000)
    wanted = sys.argv[1:] or ["fBaseParams.deterSparseType"]

    with BUNDLE.open("rb") as fh:
        bundle = pickle.load(fh)
    ir = bundle["host_ir"]

    from uo_init.derive_key_fields import DefSite, KeyFieldDeriver

    deriver = KeyFieldDeriver(
        host_ir=ir,
        resolver=bundle["resolver"],
        var_model=bundle["var_model"],
        max_helper_guards=4,
    )

    for path in wanted:
        print(f"\n=== {path}")
        for w in sorted(
            [w for w in ir.writes if w.path == path or w.path.endswith("." + path)],
            key=lambda w: (w.file, w.line),
        ):
            site = DefSite(rhs=w.rhs, file=w.file, line=w.line, function=w.function)
            # `_read_lines` is written for reads but asks a question about
            # position only: where does this point sit, expressed in each
            # function it happens inside?
            seen = deriver._read_lines(site)
            print(f"  {short(w.file)}:{w.line} [{w.function}]  runs_once={deriver._runs_once(w.function)}")
            for (f, fn), line in seen.items():
                if fn != w.function:
                    print(f"      seen from {fn} as {short(f)}:{line}")
            calls = deriver._calls_to(w.function)
            if len(seen) == 1:
                print(f"      climb stopped immediately: {len(calls)} call site(s)")
                for c in calls:
                    print(
                        f"          called at {short(getattr(c, 'file', ''))}:"
                        f"{getattr(c, 'line', 0)} in {getattr(c, 'caller', '')}"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
