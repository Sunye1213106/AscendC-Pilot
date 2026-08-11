# -*- coding: utf-8 -*-
"""What the host does to a tiling data field, as evidence for a lemma.

An outcome that no case reached is either unreachable under this key or merely
unconstructed, and the difference has to come from the host's own code. This
prints the writes UO recorded for a field, with the conditions they sit under,
which is the material a reachability lemma is argued from.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.store.reader import read_codemap  # noqa: E402

cm = read_codemap(Path(sys.argv[1]))
wanted = set(sys.argv[2:]) or {"isSplitByBlockIdx"}

for e in cm.entities.values():
    if e.kind != "TILING_FIELD" or e.name not in wanted:
        continue
    a = dict(e.attrs or {})
    print(f"\n=== {a.get('qualified_name', e.name)}  ({a.get('cpp_type')}) ===")
    sites = a.get("host_writer_sites") or []
    print(f"host writer sites: {len(sites)}")
    for s in sites:
        print(f"  {Path(str(s.get('file',''))).name}:{s.get('line')}  "
              f"mode={s.get('mode')}  recv={s.get('receiver')}")
        print(f"      = {str(s.get('expression'))[:200]}")
        for g in (s.get("guards") or s.get("path_conditions") or []):
            print(f"        guard: {str(g)[:150]}")
    extra = {k: v for k, v in a.items()
             if k not in {"host_writer_sites", "qualified_name", "cpp_type",
                          "owner", "provenance", "host_writer_site_count"}}
    if extra:
        print(f"  other: {json.dumps(extra, ensure_ascii=False, default=str)[:300]}")
