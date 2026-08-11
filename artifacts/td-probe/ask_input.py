# -*- coding: utf-8 -*-
"""What the CodeMap knows about one operator input: dtype, rank, and the host
code that reads it. Needed before the case constructor can express it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.store.reader import read_codemap  # noqa: E402

cm = read_codemap(Path(sys.argv[1]))
wanted = {w.lower() for w in (sys.argv[2:] or ["sink"])}

ids = {}
for e in cm.entities.values():
    if e.kind.name in ("INPUT", "OUTPUT") and e.name.lower() in wanted:
        ids[e.id] = e
        print(f"=== {e.kind.name} {e.name} ===")
        print(f"  file={getattr(e,'file','')}:{getattr(e,'line_start','')}")
        print(f"  attrs={json.dumps(dict(e.attrs or {}), ensure_ascii=False, default=str)[:900]}")

print("\n== variables / fields whose name mentions it ==")
for e in cm.entities.values():
    n = (e.name or "").lower()
    if any(w in n for w in wanted) and e.kind.name in (
            "VARIABLE", "TILING_FIELD", "FIELD", "COMPILE_VAR"):
        a = dict(e.attrs or {})
        print(f"  {e.kind.name:14s} {e.name:30s} "
              f"{a.get('cpp_type','')}  {Path(str(getattr(e,'file',''))).name}:"
              f"{getattr(e,'line_start','')}")
        for s in (a.get("host_writer_sites") or [])[:3]:
            print(f"        <- {str(s.get('expression'))[:120]} "
                  f"({Path(str(s.get('file',''))).name}:{s.get('line')})")

print("\n== relations from these inputs ==")
n = 0
for r in cm.relations:
    if r.src in ids or r.dst in ids:
        s, d = cm.entities.get(r.src), cm.entities.get(r.dst)
        print(f"  {r.kind.name if hasattr(r.kind,'name') else r.kind}: "
              f"{(s.name if s else r.src)[:44]} -> {(d.name if d else r.dst)[:44]}")
        n += 1
        if n > 40:
            break
