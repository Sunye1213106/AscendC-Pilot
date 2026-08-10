#!/usr/bin/env python3
import sqlite3
import json
from pathlib import Path

p = Path(r"d:\PR-review\AscendC-Pilot\artifacts\fa-pr13\flash_attention_score_grad.arch35.uo")
c = sqlite3.connect(p)

# meta keys mentioning tpl/key/tiling
print("=== meta keys ===")
for k, v in c.execute("select key, value from meta order by key"):
    vs = v if isinstance(v, str) else v.decode()
    if any(x in k.lower() for x in ("tpl", "key", "tiling", "sel", "legal", "block")):
        print(f"{k}: {vs[:400]}")

print("\n=== TEMPLATE entity ===")
for name, data in c.execute("select name, data from entity where kind='TEMPLATE'"):
    d = json.loads(data)
    print(name, json.dumps(d, ensure_ascii=False)[:800])

print("\n=== entities with sel_group / ARGS_SEL / template_block attrs ===")
count = 0
for name, kind, data in c.execute("select name, kind, data from entity"):
    if not data:
        continue
    if any(x in data for x in ("sel_group", "ARGS_SEL", "template_block", "ASCENDC_TPL", "legal_key")):
        count += 1
        if count <= 15:
            d = json.loads(data)
            keys = [k for k in d if any(x in k.lower() for x in ("sel", "tpl", "block", "legal", "args"))]
            print(f"{kind} {name}: {keys} sample={ {k:d.get(k) for k in keys} }")
print("total matching entities", count)

print("\n=== relation data with sel/tpl ===")
count = 0
for kind, data in c.execute("select kind, data from relation"):
    if data and any(x in data for x in ("sel_group", "ARGS_SEL", "template_block", "legal_key")):
        count += 1
        if count <= 10:
            print(kind, data[:250])
print("total matching relations", count)

# Check tiling key header file entity
print("\n=== FILE entities with tiling_key ===")
for name, data in c.execute(
    "select name, data from entity where kind='FILE' and name like '%tiling_key%'"
):
    print(name)
