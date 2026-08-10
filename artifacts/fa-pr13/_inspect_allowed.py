#!/usr/bin/env python3
import sqlite3
import json
from pathlib import Path

p = Path(r"d:\PR-review\AscendC-Pilot\artifacts\fa-pr13\flash_attention_score_grad.arch35.uo")
c = sqlite3.connect(p)
rows = c.execute("select name, data from entity where kind='TILING_KEY'").fetchall()
items = []
for name, data in rows:
    d = json.loads(data)
    items.append((int(d.get("decl_order") or 0), name, d))
items.sort()
prod = 1
for order, name, d in items:
    av = d.get("allowed_values")
    pack = d.get("host_packing_expressions")
    print(f"{order:02d} {name}")
    print(f"  allowed_values={av!r}")
    print(f"  packing={pack!r}")
    print(f"  bit_offset={d.get('bit_offset')} width={d.get('bit_width')}")
    if isinstance(av, list) and av:
        prod *= len(av)
    elif isinstance(av, dict) and av:
        prod *= len(av)
print("product_if_all_allowed=", prod)

# Look for TPL / ARGS_SEL related entities
print("\nentities with 'tpl' or 'ARGS' in name/kind sample:")
for kind, n in c.execute(
    "select kind, count(*) from entity where name like '%ARGS%' or name like '%TPL%' or name like '%SEL%' group by 1"
).fetchall():
    print(kind, n)
