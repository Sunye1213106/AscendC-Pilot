# -*- coding: utf-8 -*-
"""Kernel members whose value is a function of tiling data, and that function.

A branch on `isDropBoolMode` is really a branch on the tiling data that member
was computed from, so the evaluator needs the definition. Only unguarded writes
are exported: a write under `if constexpr (IS_TND)` is not the definition for a
key where IS_TND is false, and treating it as one would decide branches wrongly
rather than leave them undecided.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init import paths  # noqa: E402
from uo_init.build_context import BuildContext  # noqa: E402
from uo_init.clang_walk import walk_file  # noqa: E402

ARCH, REL = "arch35", "attention/flash_attention_score_grad"
ENTRY = "op_kernel/flash_attention_score_grad_apt.cpp"
TD_ACCESS = re.compile(r"\b\w*[Tt]iling\w*\s*(?:->|\.)\s*(\w+)(?:\s*\.\s*(\w+))?")

op_dir = paths.op_dir(relative=REL)
ctx = BuildContext.load(op_dir=str(op_dir), arch_dir=ARCH)

out: dict[str, dict] = {}
skipped: dict[str, list[str]] = {}
for variant in ("DT_FLOAT16", "DT_BF16", "DT_FLOAT"):
    res = walk_file(Path(op_dir) / ENTRY, ctx, side="kernel",
                    dtype_variant=variant, op_needle="flash_attention_score_grad",
                    collect_writes=True)
    for w in getattr(res, "writes", []) or []:
        path = str(getattr(w, "path", ""))
        rhs = str(getattr(w, "rhs", "") or "")
        if not path or not rhs or not TD_ACCESS.search(rhs):
            continue
        member = path.split(".")[-1]
        guards = [p for p in (getattr(w, "path_conditions", ()) or ())]
        if guards:
            skipped.setdefault(member, []).append(
                f"{Path(str(w.file)).name}:{w.line} under {guards[0].pretty()[:60]}")
            continue
        # Self-referential writes define nothing on their own.
        if re.search(rf"\b{re.escape(member)}\b", rhs):
            continue
        prev = out.get(member)
        if prev and prev["expression"] != rhs:
            prev.setdefault("conflicts", []).append(rhs)
            continue
        out[member] = {
            "expression": rhs,
            "file": Path(str(w.file)).name,
            "line": w.line,
            "function": w.function,
            "variants": sorted(set((prev or {}).get("variants", []) + [variant])),
        }

path_out = Path(__file__).parent / "derived_members.json"
path_out.write_text(json.dumps(
    {"unguarded": out, "guarded_only": skipped}, indent=1, ensure_ascii=False),
    encoding="utf-8")
print(f"unguarded tiling-data-derived members: {len(out)}")
for k, v in out.items():
    flag = "  CONFLICT" if v.get("conflicts") else ""
    print(f"   {k:26s} = {v['expression'][:96]}{flag}")
print(f"\nmembers written only under a guard (not exported): {len(skipped)}")
for k, v in list(skipped.items())[:12]:
    print(f"   {k:26s} {v[0]}")
print(f"\nwrote {path_out}")
