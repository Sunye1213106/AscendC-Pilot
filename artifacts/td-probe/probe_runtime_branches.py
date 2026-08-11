# -*- coding: utf-8 -*-
"""How many kernel branches actually turn on tiling data?

`kernel_ir` keeps only `if_constexpr`, so the runtime `if`s clang already
collected are dropped. This counts what is being dropped, and how much of it
names a tiling data field, which is what decides whether a per-TilingKey branch
domain is worth building.
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init import paths  # noqa: E402
from uo_init.build_context import BuildContext  # noqa: E402
from uo_init.clang_walk import walk_file  # noqa: E402

ARCH = "arch35"
REL = "attention/flash_attention_score_grad"
ENTRY = "op_kernel/flash_attention_score_grad_apt.cpp"

op_dir = paths.op_dir(relative=REL)
if op_dir is None:
    raise SystemExit(f"cannot locate operator\n{paths.explain()}")
entry = Path(op_dir) / ENTRY
ctx = BuildContext.load(op_dir=str(op_dir), arch_dir=ARCH)

variant = os.environ.get("UO_DTYPE_VARIANT", "DT_FLOAT16")
print(f"walking {entry.name} variant={variant} ...", flush=True)
res = walk_file(entry, ctx, side="kernel", dtype_variant=variant,
                op_needle="flash_attention_score_grad", collect_writes=False)

controls = list(getattr(res, "controls", []) or [])
print(f"controls: {len(controls)}")
print("by kind:", dict(Counter(c.kind for c in controls)))

op_root = str(op_dir).replace("\\", "/").lower()


def in_operator(c) -> bool:
    return op_root in str(c.file).replace("\\", "/").lower()


own = [c for c in controls if in_operator(c)]
print(f"\nin operator sources: {len(own)}")
print("by kind:", dict(Counter(c.kind for c in own)))

runtime = [c for c in own if c.kind == "if"]
print(f"\nruntime if in operator: {len(runtime)}")

# A condition that reads tiling data goes through the tiling pointer or one of
# the cached member copies the kernel keeps.
TD_RE = re.compile(
    r"\b(?:tilingData|tiling|td)\s*(?:->|\.)\s*(\w+)\s*(?:\.\s*(\w+))?"
    r"|\b(this\s*->\s*)?(\w*[Tt]ilingData)\b")
touching, fields = [], Counter()
for c in runtime:
    cond = (c.condition or "")
    hits = re.findall(r"(?:tilingData|tilingData_|td)\s*(?:->|\.)\s*"
                      r"(\w+)(?:\s*\.\s*(\w+))?", cond)
    if hits:
        touching.append(c)
        for a, b in hits:
            fields[b or a] += 1

print(f"runtime if naming tiling data directly: {len(touching)}")
print("\ntop named members:")
for name, n in fields.most_common(25):
    print(f"   {name}: {n}")

print("\n-- 30 runtime conditions in operator sources --")
for c in runtime[:30]:
    print(f"  {Path(c.file).name}:{c.line}  {str(c.condition)[:100]}")

uniq = {(c.file, c.line, c.condition) for c in runtime}
print(f"\nunique runtime if sites: {len(uniq)}")
