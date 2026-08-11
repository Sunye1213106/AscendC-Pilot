# -*- coding: utf-8 -*-
"""Observed value set of chosen fields, over every case that hit one key.

A field that held one value across every case is either pinned by the key or
merely under-explored, and knowing which value it held is the first thing a
lemma or a search needs.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_pilot import HERE as PH, decode, replay  # noqa: E402
from replay import inputs as I  # noqa: E402
from run_multicase import variants  # noqa: E402

trait = sys.argv[1] if len(sys.argv) > 1 else "bn2gs1s2_plain"
want = sys.argv[2:] or ["dropoutIsDivisibleBy8", "sinkOptional", "sparseType",
                        "isSplitByBlockIdx", "keepProb", "dropMaskOuter",
                        "sValueZeroUnderTND", "hasInvalidCol", "coreNum",
                        "layout", "enablePreSfmg", "attenMaskShapeType",
                        "sparseMode", "s2Outer", "blockOuter"]

picked = json.loads((PH / "picked_keys.json").read_text(encoding="utf-8"))
layouts = json.loads((PH / "layout.json").read_text(encoding="utf-8"))
by_size = {lay["size"]: (n, lay) for n, lay in layouts.items()}
row = picked[trait]
target = row["tiling_key"]

cases = variants(I.construct_case(row["dims"])[0])
results = replay(cases)
on_key = [r for r in results.values()
          if r.get("ok") and r.get("key") == target and r.get("td")]
print(f"trait={trait} key={target}  on-key observations: {len(on_key)}")

seen: dict[str, Counter] = {w: Counter() for w in want}
for r in on_key:
    if len(r["td"]) not in by_size:
        continue
    _, layout = by_size[len(r["td"])]
    fields = decode(r["td"], layout)
    for w in want:
        if w in fields:
            v = fields[w]
            seen[w][str(v if not isinstance(v, list) else v[:4])] += 1

print(f"\n{'field':26s} {'distinct':>8s}  values (count)")
for w in want:
    c = seen[w]
    if not c:
        print(f"{w:26s} {'-':>8s}  not in this variant")
        continue
    vals = ", ".join(f"{k}({n})" for k, n in c.most_common(6))
    print(f"{w:26s} {len(c):8d}  {vals}")
