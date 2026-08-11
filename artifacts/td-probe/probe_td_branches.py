# -*- coding: utf-8 -*-
"""Which kernel runtime branches a test could actually steer.

A branch is steerable when its condition is decided by tiling data: either it
names a field outright, or it names a member the kernel copied a field into.
Everything else -- buffer ping-pong flags, loop-local counters -- turns on
kernel state no input controls, and counting those as coverage targets would
set a goal no case can ever meet.
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

ARCH = "arch35"
REL = "attention/flash_attention_score_grad"
ENTRY = "op_kernel/flash_attention_score_grad_apt.cpp"

op_dir = paths.op_dir(relative=REL)
entry = Path(op_dir) / ENTRY
ctx = BuildContext.load(op_dir=str(op_dir), arch_dir=ARCH)

# The field names UO already knows, so this asks the CodeMap what a field is
# rather than guessing from the shape of the identifier.
uo = Path(sys.argv[1]) if len(sys.argv) > 1 else None
known: set[str] = set()
if uo:
    cm = read_codemap(uo)
    known = {e.name for e in cm.entities.values() if e.kind == "TILING_FIELD"}
print(f"known tiling fields from UO: {len(known)}")

variant = os.environ.get("UO_DTYPE_VARIANT", "DT_FLOAT16")
res = walk_file(entry, ctx, side="kernel", dtype_variant=variant,
                op_needle="flash_attention_score_grad", collect_writes=True)
controls = list(getattr(res, "controls", []) or [])
writes = list(getattr(res, "writes", []) or [])
runtime = [c for c in controls if c.kind == "if" and (c.condition or "").strip()]
print(f"runtime if with a readable condition: {len(runtime)}")

TD_ACCESS = re.compile(
    r"\b\w*[Tt]iling\w*\s*(?:->|\.)\s*(\w+)(?:\s*\.\s*(\w+))?")
IDENT = re.compile(r"\b[A-Za-z_]\w*\b")

# --- members the kernel copies a field into --------------------------------
cached: dict[str, str] = {}
for w in writes:
    rhs = str(getattr(w, "rhs", "") or getattr(w, "value", "") or "")
    name = str(getattr(w, "name", "") or "")
    if not name or not rhs:
        continue
    m = TD_ACCESS.search(rhs)
    if m:
        field = m.group(2) or m.group(1)
        if not known or field in known:
            cached.setdefault(name, field)
print(f"members cached from tiling data: {len(cached)}")
for k, v in list(cached.items())[:20]:
    print(f"   {k} <- {v}")

direct, indirect = [], []
for c in runtime:
    cond = c.condition or ""
    hits = [(m.group(2) or m.group(1)) for m in TD_ACCESS.finditer(cond)]
    hits = [h for h in hits if not known or h in known]
    if hits:
        direct.append((c, hits))
        continue
    named = [i for i in IDENT.findall(cond) if i in cached]
    if named:
        indirect.append((c, [cached[n] for n in named]))

print(f"\nsteerable runtime branches: direct={len(direct)} "
      f"via-cached-member={len(indirect)} total={len(direct) + len(indirect)}")

print("\n== direct (condition names a field) ==")
for c, f in direct:
    print(f"  {Path(c.file).name}:{c.line}  [{','.join(sorted(set(f)))}]")
    print(f"      {str(c.condition)[:120]}")

print("\n== via cached member ==")
for c, f in indirect[:40]:
    print(f"  {Path(c.file).name}:{c.line}  [{','.join(sorted(set(f)))}]")
    print(f"      {str(c.condition)[:120]}")

fields = Counter()
for _, f in direct + indirect:
    fields.update(set(f))
print(f"\n== distinct fields steering a branch: {len(fields)} ==")
for n, k in fields.most_common():
    print(f"   {n}: {k}")
