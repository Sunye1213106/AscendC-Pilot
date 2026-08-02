# -*- coding: utf-8 -*-
"""What does the deriver now believe about who is guaranteed to run?

Builds the host IR fresh (so it sees the framework call edges) and asks for
the dominator set plus `_reached` / `_always_runs` on the tiling hooks.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))
CACHE = ROOT / ".probe_cache"

HOOKS = (
    "DoTiling",
    "GetTilingKey",
    "GetShapeAttrsInfo",
    "GetPlatformInfo",
    "DoOpTiling",
    "DetermineMode",
    "ProcessSparseModeInfo",
    "ProcessPseInfo",
    "DoBn2s2Sparse",
    "CalcleCausalDeterParam",
)


def main() -> int:
    from uo_init import paths
    from uo_init.build_context import BuildContext
    from uo_init.derive_key_fields import Const, KeyFieldDeriver
    from uo_init.expr_ir import Ref
    from uo_init.host_ir import build_host_ir
    from uo_init.op_spec import discover

    op = paths.op_dir(
        relative=os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")
    )
    spec = discover(op, arch_dir="arch35")
    ctx = BuildContext.load(
        cann_root=str(paths.cann_root()),
        ops_root=str(paths.ops_root()),
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
    )
    ir = build_host_ir(
        [p for p in spec.host_targets if p.exists()], ctx=ctx, op_needle=spec.op_needle
    )

    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        bundle = pickle.load(fh)
    blob = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    encode = blob.get("encode_function") or ""
    print(f"encode_function from the last run: {encode!r}")

    d = KeyFieldDeriver(
        host_ir=ir,
        resolver=bundle["resolver"],
        var_model=bundle["var_model"],
        max_helper_guards=4,
    )
    d._encode_fn = encode or "GetTilingKey"
    d._encode_path_cache = None
    d._reach_cache.clear()
    print(f"encode_path (dominators): {sorted(d._encode_path())}\n")

    print(f"{'function':28} {'always':7} {'reached':10} calls")
    for fn in HOOKS:
        d._reach_cache.clear()
        try:
            reached = d._reached(fn, 0)
            always = d._always_runs(fn, 0)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the probe
            print(f"{fn:28} raised {type(exc).__name__}: {exc}")
            continue
        if isinstance(reached, Const):
            kind = f"Const({reached.value!r})"
        elif isinstance(reached, Ref):
            kind = f"Ref {reached.symbol}"
        else:
            kind = type(reached).__name__
        print(f"{fn:28} {str(always):7} {kind:10} {len(list(ir.calls_to(fn)))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
