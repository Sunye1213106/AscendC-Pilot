# -*- coding: utf-8 -*-
"""How a steerable branch's reachability is decided.

Two candidate sources, both checked here rather than assumed:
  1. the guard chain clang recorded above the branch (`path_conditions`), and
  2. the CodeMap's own ACTIVE_UNDER / CONTROLS edges, which is where the entry's
     `if constexpr` dispatch onto whole kernel classes should live.
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
from uo_init.store.reader import read_codemap  # noqa: E402

ARCH, REL = "arch35", "attention/flash_attention_score_grad"
ENTRY = "op_kernel/flash_attention_score_grad_apt.cpp"

cm = read_codemap(Path(sys.argv[1]))
ents = cm.entities
known = {e.name for e in ents.values() if e.kind == "TILING_FIELD"}
dim_names = [e.name for e in ents.values() if e.kind == "TILING_KEY"]
print(f"tiling key dims: {len(dim_names)} -> {dim_names}")

# --- 1. guard chains from the walk ----------------------------------------
op_dir = paths.op_dir(relative=REL)
ctx = BuildContext.load(op_dir=str(op_dir), arch_dir=ARCH)
res = walk_file(Path(op_dir) / ENTRY, ctx, side="kernel",
                dtype_variant=os.environ.get("UO_DTYPE_VARIANT", "DT_FLOAT16"),
                op_needle="flash_attention_score_grad", collect_writes=False)

TD_ACCESS = re.compile(r"\b\w*[Tt]iling\w*\s*(?:->|\.)\s*(\w+)(?:\s*\.\s*(\w+))?")
steerable = []
for c in res.controls:
    if c.kind != "if" or not (c.condition or "").strip():
        continue
    hits = [h for h in ((m.group(2) or m.group(1))
                        for m in TD_ACCESS.finditer(c.condition)) if h in known]
    if hits:
        steerable.append(c)

from uo_init.kernel_ir import _Dimensions  # noqa: E402

dims = _Dimensions(dim_names)


def names_a_dim(text: str) -> list[str]:
    out = []
    for ident in re.findall(r"\b[A-Za-z_]\w*\b", str(text)):
        hit, near = dims.classify(ident)
        if hit and hit not in out:
            out.append(hit)
        elif near and near not in out:
            out.append(near)
    return out


print("\n== all guards above each steerable branch, dim-bearing marked ==")
dim_bearing = Counter()
for c in steerable:
    pcs = list(getattr(c, "path_conditions", ()) or ())
    tagged = [(p, names_a_dim(p.text)) for p in pcs]
    hot = [t for t in tagged if t[1]]
    dim_bearing[len(hot)] += 1
    print(f"\n  {Path(c.file).name}:{c.line}  guards={len(pcs)} dim_bearing={len(hot)}")
    for p, ds in tagged:
        mark = f"<{','.join(ds)}>" if ds else "        "
        print(f"      {mark} [{p.kind}] {p.pretty()[:88]}")

print(f"\nbranches by dim-bearing guard count: {dict(dim_bearing)}")

# --- 2. what the CodeMap says --------------------------------------------
print("\n== ACTIVE_UNDER / CONTROLS shape in the CodeMap ==")
by_kind = Counter()
samples: dict[str, list] = {}
for r in cm.relations:
    if r.kind in ("ACTIVE_UNDER", "CONTROLS", "GUARDED_BY", "SELECTS"):
        s, d = ents.get(r.src), ents.get(r.dst)
        tag = f"{r.kind}: {s.kind if s else '?'} -> {d.kind if d else '?'}"
        by_kind[tag] += 1
        samples.setdefault(tag, []).append(
            (r.src, r.dst, dict(r.attrs or {})))
for tag, n in by_kind.most_common():
    print(f"  [{n:4d}] {tag}")
    for src, dst, attrs in samples[tag][:2]:
        print(f"           {src[:64]} -> {dst[:64]}")
        if attrs:
            print(f"           attrs={str(attrs)[:150]}")
