#!/usr/bin/env python3
import sqlite3
import json
from pathlib import Path
from collections import Counter

p = Path(r"d:\PR-review\AscendC-Pilot\artifacts\fa-pr13\flash_attention_score_grad.arch35.uo")
c = sqlite3.connect(p)

print("=== TILING_KEY entities ===")
rows = c.execute(
    "select name, status, file, line_start, data from entity where kind='TILING_KEY' order by name"
).fetchall()
for name, status, file, line, data in rows:
    d = json.loads(data) if data else {}
    keys = sorted(d.keys())
    print(f"\n{name} status={status} {file}:{line}")
    print(f"  data_keys={keys}")
    for k in (
        "bit_offset",
        "decl_order",
        "domain",
        "legal_values",
        "values",
        "packing",
        "producer",
        "bit_width",
        "width",
        "enum_values",
        "template_arg",
    ):
        if k in d:
            print(f"  {k}: {json.dumps(d[k], ensure_ascii=False)[:300]}")

print("\n=== relation kinds ===")
for k, n in c.execute(
    "select kind, count(*) from relation group by 1 order by 2 desc"
).fetchall():
    print(f"  {k}: {n}")

print("\n=== packing / key-related relations sample ===")
for kind in [
    "PACKS_INTO",
    "PACKED_BY",
    "BINDS",
    "CONTROLS",
    "WRITES",
    "READS",
    "PRODUCES",
    "DERIVES",
    "KEY_PACKING",
    "HOST_PACKS",
    "TEMPLATE_BINDS",
]:
    n = c.execute("select count(*) from relation where kind=?", (kind,)).fetchone()[0]
    if n:
        print(f"{kind}: {n}")
        samples = c.execute(
            "select src, dst, substr(data,1,200) from relation where kind=? limit 3",
            (kind,),
        ).fetchall()
        for s in samples:
            print(" ", s)

# meta packing
print("\n=== cm_host_tiling_key_packing ===")
row = c.execute("select value from meta where key='cm_host_tiling_key_packing'").fetchone()
if row:
    print(row[0][:2000] if isinstance(row[0], str) else row[0].decode()[:2000])

print("\n=== cm_source_declared_tiling_keys ===")
row = c.execute(
    "select value from meta where key='cm_source_declared_tiling_keys'"
).fetchone()
if row:
    print(row[0] if isinstance(row[0], str) else row[0].decode())

print("\n=== TEMPLATE_ARG entities ===")
rows = c.execute(
    "select name, data from entity where kind='TEMPLATE_ARG' order by name"
).fetchall()
for name, data in rows:
    d = json.loads(data) if data else {}
    print(f"{name}: {json.dumps(d, ensure_ascii=False)[:250]}")

print("\n=== summary view_blob ===")
row = c.execute("select data from view_blob where name='summary'").fetchone()
if row:
    print(row[0] if isinstance(row[0], str) else row[0].decode())
