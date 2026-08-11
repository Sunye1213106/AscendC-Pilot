# -*- coding: utf-8 -*-
"""Where a kernel member gets its value.

The branch evaluator needs this for members a condition turns on that are not
tiling data themselves -- they are computed from it, and the computation is what
has to be resolved before the branch can be decided.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init import paths  # noqa: E402
from uo_init.build_context import BuildContext  # noqa: E402
from uo_init.clang_walk import walk_file  # noqa: E402

ARCH, REL = "arch35", "attention/flash_attention_score_grad"
ENTRY = "op_kernel/flash_attention_score_grad_apt.cpp"
wanted = {w.lower() for w in (sys.argv[1:] or ["isdropboolmode"])}

op_dir = paths.op_dir(relative=REL)
ctx = BuildContext.load(op_dir=str(op_dir), arch_dir=ARCH)
res = walk_file(Path(op_dir) / ENTRY, ctx, side="kernel",
                dtype_variant=os.environ.get("UO_DTYPE_VARIANT", "DT_FLOAT16"),
                op_needle="flash_attention_score_grad", collect_writes=True)

writes = list(getattr(res, "writes", []) or [])
print(f"writes collected: {len(writes)}")
for w in writes:
    path = str(getattr(w, "path", ""))
    if not any(x in path.lower() for x in wanted):
        continue
    print(f"\n  {Path(str(w.file)).name}:{w.line}  in {w.function}")
    print(f"    path = {path}")
    print(f"    kind = {getattr(w, 'kind', '')}")
    print(f"    rhs  = {str(getattr(w, 'rhs', ''))[:400]}")
    for p in getattr(w, "path_conditions", ()) or ():
        print(f"      guard [{p.kind}] {p.pretty()[:110]}")

print("\n== declarations mentioning it ==")
for v in getattr(res, "variables", []) or []:
    name = str(getattr(v, "name", ""))
    if any(x in name.lower() for x in wanted):
        print(f"  {name}: {vars(v) if hasattr(v, '__dict__') else v}")
