# -*- coding: utf-8 -*-
"""The compile-time guard chain above each steerable runtime branch.

A runtime branch only exists for the TilingKeys whose `if constexpr` guards all
hold, so the guard chain is what turns "42 branches in the source" into "these
branches under this key". Printed here to see what an evaluator has to handle.
"""

from __future__ import annotations

import json
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
from uo_init.store.reader import read_codemap  # noqa: E402

ARCH, REL = "arch35", "attention/flash_attention_score_grad"
ENTRY = "op_kernel/flash_attention_score_grad_apt.cpp"

op_dir = paths.op_dir(relative=REL)
ctx = BuildContext.load(op_dir=str(op_dir), arch_dir=ARCH)
cm = read_codemap(Path(sys.argv[1]))
known = {e.name for e in cm.entities.values() if e.kind == "TILING_FIELD"}

variant = os.environ.get("UO_DTYPE_VARIANT", "DT_FLOAT16")
res = walk_file(Path(op_dir) / ENTRY, ctx, side="kernel", dtype_variant=variant,
                op_needle="flash_attention_score_grad", collect_writes=False)

TD_ACCESS = re.compile(r"\b\w*[Tt]iling\w*\s*(?:->|\.)\s*(\w+)(?:\s*\.\s*(\w+))?")

steerable = []
for c in res.controls:
    if c.kind != "if" or not (c.condition or "").strip():
        continue
    hits = [(m.group(2) or m.group(1)) for m in TD_ACCESS.finditer(c.condition)]
    hits = [h for h in hits if h in known]
    if hits:
        steerable.append((c, sorted(set(hits))))

print(f"steerable runtime branches: {len(steerable)}")

guard_kinds, guard_texts = Counter(), Counter()
rows = []
for c, fields in steerable:
    pcs = list(getattr(c, "path_conditions", ()) or ())
    guard_kinds.update(p.kind for p in pcs)
    ce = [p for p in pcs if p.kind == "if_constexpr"]
    for p in ce:
        guard_texts[str(p.text)[:80]] += 1
    rows.append({
        "file": Path(c.file).name, "line": c.line, "function": c.function,
        "condition": c.condition, "fields": fields,
        "constexpr_guards": [{"text": p.text, "taken": p.taken} for p in ce],
        "all_guards": len(pcs),
    })

print("\n== guard kinds across steerable branches ==")
for k, n in guard_kinds.most_common():
    print(f"   {k}: {n}")

print(f"\n== distinct constexpr guard texts: {len(guard_texts)} ==")
for t, n in guard_texts.most_common(40):
    print(f"   [{n:2d}] {t}")

out = Path(__file__).parent / "steerable_branches.json"
out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"\nwrote {out}")

print("\n== per-branch guard depth ==")
for r in rows:
    print(f"  {r['file']}:{r['line']:5d} guards={len(r['constexpr_guards'])} "
          f"fields={r['fields']}")
    for g in r["constexpr_guards"]:
        print(f"        {'' if g['taken'] else 'NOT '}{str(g['text'])[:96]}")
