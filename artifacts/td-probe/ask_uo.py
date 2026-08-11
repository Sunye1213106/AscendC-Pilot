# -*- coding: utf-8 -*-
"""Ask the CodeMap what it already knows about the tiling data.

Reads the `.uo` product only. What is missing here is what UO has to learn to
say, and hard-coding it on the TG side instead would put the operator's struct
layout somewhere no source change can refresh.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.store.reader import list_views, read_codemap  # noqa: E402

uo = Path(sys.argv[1])
cm = read_codemap(uo)

ents = list(cm.entities.values())
tds = [e for e in ents if e.kind == "TILING_DATA"]
tfs = [e for e in ents if e.kind == "TILING_FIELD"]

print(f"== TILING_DATA ({len(tds)}) ==")
for e in tds:
    print(f"  {e.name}  line={getattr(e, 'line_start', '?')} attrs={sorted((e.attrs or {}))}")

print("\n== TILING_FIELD: 3 raw ==")
for e in tfs[:3]:
    print(json.dumps({"id": e.id, "name": e.name, "attrs": e.attrs},
                     indent=2, ensure_ascii=False, default=str)[:1400])

keys: dict[str, int] = {}
for e in tfs:
    for k in (e.attrs or {}):
        keys[k] = keys.get(k, 0) + 1
print(f"\n== attr keys across {len(tfs)} TILING_FIELD ==")
for k, n in sorted(keys.items(), key=lambda kv: -kv[1]):
    print(f"  {k}: {n}")

print("\n== fields per owner ==")
by_owner: dict[str, list] = {}
for e in tfs:
    by_owner.setdefault(str((e.attrs or {}).get("owner", "?")), []).append(e)
for owner, group in sorted(by_owner.items()):
    print(f"  {owner}: {len(group)}")

print("\n== declared cpp_type values ==")
types: dict[str, int] = {}
for e in tfs:
    types[str((e.attrs or {}).get("cpp_type", "?"))] = types.get(
        str((e.attrs or {}).get("cpp_type", "?")), 0) + 1
for t, n in sorted(types.items(), key=lambda kv: -kv[1]):
    print(f"  {t}: {n}")

print("\n== view_blobs ==")
for name in list_views(uo):
    print(f"  {name}")
