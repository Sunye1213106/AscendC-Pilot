# -*- coding: utf-8 -*-
"""Evaluate _reached / _always_runs for every VAR_INIT minting function.

    python scripts/_probe_always_runs.py
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CACHE = ROOT / ".probe_cache"


def main() -> int:
    blob = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        bundle = pickle.load(fh)
    ir = bundle["host_ir"]

    from uo_init.derive_key_fields import Const, KeyFieldDeriver
    from uo_init.expr_ir import Ref

    d = KeyFieldDeriver(
        host_ir=ir,
        resolver=bundle["resolver"],
        var_model=bundle["var_model"],
        max_helper_guards=4,
    )
    d._encode_fn = blob.get("encode_function") or "GetTilingKey"
    d._encode_path_cache = None
    d._reach_cache.clear()

    free = {v for f in blob["fields"] for v in (f.get("free_vars") or [])}
    fns = []
    seen: set[str] = set()
    for f in blob["fields"]:
        for drec in f.get("implicit_defaults") or []:
            vid = drec.get("variable")
            fn = drec.get("function") or ""
            if vid in free and fn and fn not in seen:
                seen.add(fn)
                fns.append((vid, fn, drec.get("field"), drec.get("line")))

    for e in (
        "GetTilingKey",
        "DoOpTiling",
        "GetShapeAttrsInfo",
        "DoSparse",
        "SetSplitAxis",
        "ProcessSparseModeInfo",
        "DetermineMode",
        "GetPlatformInfo",
        "ProcessPseInfo",
        "CalcleCausalDeterParam",
        "GetDeterSparseTilingKey",
        "DoBn2s2Sparse",
    ):
        if e not in seen:
            fns.append(("-", e, "-", 0))
            seen.add(e)

    print(f"encode_fn={d._encode_fn}  encode_path={sorted(d._encode_path())}")
    print()
    print(f"{'function':32} {'always':8} {'kind':16} calls  detail")
    rows = []
    for vid, fn, field, line in fns:
        # Fresh reach cache per ask so encode_path / note_root state is stable
        d._reach_cache.clear()
        d._encode_path_cache = None
        reached = d._reached(fn, 0)
        always = d._always_runs(fn, 0)
        if isinstance(reached, Const):
            kind = f"Const({reached.value!r})"
            detail = ""
        elif isinstance(reached, Ref):
            kind = "Ref"
            detail = reached.symbol
        else:
            kind = type(reached).__name__
            try:
                from uo_init.derive_key_fields import _pretty_dag

                detail = _pretty_dag(reached)[:140]
            except Exception:
                detail = repr(reached)[:140]
        calls = list(ir.calls_to(fn.split("::")[-1]))
        print(f"{fn:32} {str(always):8} {kind:16} {len(calls):5}  {detail}")
        rows.append(
            {
                "var": vid,
                "function": fn,
                "field": field,
                "line": line,
                "always_runs": always,
                "reached_kind": kind,
                "detail": detail,
                "n_calls": len(calls),
            }
        )

    n_init = [r for r in rows if r["var"] != "-"]
    n_false = sum(1 for r in n_init if not r["always_runs"])
    print()
    print(f"VAR_INIT minting fns: {len(n_init)}  always_runs=False: {n_false}")

    # Also: for HAS_CALLS cases, does the reach expression mention __reached_?
    print("\n=== call-site chains for HAS_CALLS init fns ===")
    for r in n_init:
        if r["n_calls"] == 0:
            continue
        short = r["function"].split("::")[-1]
        calls = list(ir.calls_to(short))
        for c in calls[:4]:
            caller = getattr(c, "caller", "")
            d._reach_cache.clear()
            up = d._reached(caller, 0)
            up_s = (
                f"Const({up.value!r})"
                if isinstance(up, Const)
                else (up.symbol if isinstance(up, Ref) else type(up).__name__)
            )
            print(
                f"  {short} <- {caller}@{getattr(c, 'line', 0)}  "
                f"caller_reached={up_s}  caller_calls={len(ir.calls_to(caller.split('::')[-1]))}"
            )

    (CACHE / "always_runs.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nwrote {CACHE / 'always_runs.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
