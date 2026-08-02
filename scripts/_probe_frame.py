# -*- coding: utf-8 -*-
"""Did following the override edges recover the framework's call order?

Reports which base-class headers were let in, and whether the tiling hooks
still look like functions nobody calls.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))


def main() -> int:
    from uo_init import paths
    from uo_init.build_context import BuildContext
    from uo_init.clang_walk import walk_file
    from uo_init.op_spec import discover

    import os

    op = paths.op_dir(
        relative=os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")
    )
    if op is None:
        print(f"no operator directory\n{paths.explain()}")
        return 1
    spec = discover(op, arch_dir="arch35")
    ctx = BuildContext.load(
        cann_root=str(paths.cann_root()),
        ops_root=str(paths.ops_root()),
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
    )
    targets = [p for p in spec.host_targets if p.exists()]
    print(f"needle={spec.op_needle!r}  {len(targets)} host translation units")

    called: Counter[str] = Counter()
    callers: dict[str, set[str]] = {}
    outside: set[str] = set()
    for path in targets:
        res = walk_file(path, ctx, side="host", op_needle=spec.op_needle)
        for site in res.call_sites:
            called[site.callee] += 1
            callers.setdefault(site.callee, set()).add(site.caller)
            if spec.op_needle and spec.op_needle not in site.file:
                outside.add(site.file)

    print(f"\ncall sites recorded from outside the operator: {len(outside)}")
    for name in sorted(outside):
        print(f"  {name}")

    print("\nwho calls the tiling hooks now:")
    for hook in (
        "GetShapeAttrsInfo",
        "GetPlatformInfo",
        "IsCapable",
        "DoOpTiling",
        "DoLibApiTiling",
        "GetWorkspaceSize",
        "PostTiling",
        "GetTilingKey",
        "DoTiling",
    ):
        who = sorted(callers.get(hook, ()))
        print(f"  {called[hook]:4d}  {hook:20s} {who if who else '(nobody)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
