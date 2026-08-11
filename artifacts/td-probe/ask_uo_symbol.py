# -*- coding: utf-8 -*-
"""Ask the CodeMap where a kernel symbol comes from.

Used for the identifiers the branch evaluator could not resolve: if UO already
records the definition, the evaluator should read it from there rather than have
anyone re-derive it from source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.store.reader import read_codemap  # noqa: E402

cm = read_codemap(Path(sys.argv[1]))
wanted = [w.lower() for w in sys.argv[2:]] or ["isdropboolmode"]

hits = []
for e in cm.entities.values():
    name = (e.name or "").lower()
    if any(w in name for w in wanted):
        hits.append(e)

print(f"entities matching {wanted}: {len(hits)}")
for e in hits:
    print(f"\n  kind={e.kind} name={e.name}")
    print(f"  file={getattr(e, 'file', '')}:{getattr(e, 'line_start', '')}")
    a = dict(e.attrs or {})
    for k in ("cpp_type", "value", "initializer", "expression", "default_initializer",
              "domain", "provenance", "kind_detail", "is_constexpr", "condition"):
        if k in a:
            print(f"    {k} = {str(a[k])[:220]}")
    extra = {k: v for k, v in a.items() if k not in {
        "cpp_type", "value", "initializer", "expression", "default_initializer",
        "domain", "provenance", "kind_detail", "is_constexpr", "condition"}}
    if extra:
        print(f"    other attrs: {json.dumps(extra, ensure_ascii=False, default=str)[:400]}")

ids = {e.id for e in hits}
print("\n== relations touching them ==")
for r in cm.relations:
    if r.src in ids or r.dst in ids:
        s = cm.entities.get(r.src)
        d = cm.entities.get(r.dst)
        print(f"  {r.kind}: {(s.name if s else r.src)[:50]} -> "
              f"{(d.name if d else r.dst)[:50]}  {str(dict(r.attrs or {}))[:130]}")
