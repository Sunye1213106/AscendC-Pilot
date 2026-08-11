# -*- coding: utf-8 -*-
"""What the CodeMap says about kernel branches: how many, keyed on what."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.store.reader import read_codemap  # noqa: E402

cm = read_codemap(Path(sys.argv[1]))
ents = list(cm.entities.values())
br = [e for e in ents if e.kind == "BRANCH"]

layers = Counter(str((e.attrs or {}).get("layer", "?")) for e in br)
print("== BRANCH by layer ==")
for k, n in layers.items():
    print(f"  {k}: {n}")

kern = [e for e in br if str((e.attrs or {}).get("layer")) == "kernel"]
print(f"\n== kernel BRANCH attr keys ({len(kern)}) ==")
keys = Counter()
for e in kern:
    keys.update((e.attrs or {}).keys())
for k, n in keys.most_common():
    print(f"  {k}: {n}")

print("\n== 8 kernel branches raw ==")
for e in kern[:8]:
    print(json.dumps({"id": e.id, "name": e.name, "attrs": e.attrs},
                     ensure_ascii=False, default=str)[:700])
    print()

with_dims = [e for e in kern if (e.attrs or {}).get("dimensions")]
with_tdf = [e for e in kern if (e.attrs or {}).get("tilingdata_fields")]
print(f"kernel branches with dimensions: {len(with_dims)}/{len(kern)}")
print(f"kernel branches with tilingdata_fields: {len(with_tdf)}/{len(kern)}")

stages = Counter(str((e.attrs or {}).get("stage", "?")) for e in kern)
print(f"\n== stage ==")
for k, n in stages.items():
    print(f"  {k}: {n}")

print("\n== conditions, 20 samples ==")
for e in kern[:20]:
    a = e.attrs or {}
    cond = a.get("condition") or a.get("text") or a.get("expression") or "?"
    print(f"  [{a.get('stage','?'):9s}] {str(cond)[:110]}")
