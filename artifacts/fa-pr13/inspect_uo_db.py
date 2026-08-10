# -*- coding: utf-8 -*-
import sqlite3
from pathlib import Path

p = Path("/work/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/uo/flash_attention_score_grad.arch35.uo")
c = sqlite3.connect(str(p))
tables = c.execute("select name from sqlite_master where type='table'").fetchall()
print("tables:", [t[0] for t in tables])
for t in tables:
    name = t[0]
    try:
        n = c.execute(f"select count(*) from [{name}]").fetchone()[0]
        cols = [r[1] for r in c.execute(f"pragma table_info([{name}])").fetchall()]
        print(f"  {name}: {n} rows cols={cols[:8]}")
    except Exception as e:
        print(f"  {name}: ERR {e}")

# look for view blobs
for t in tables:
    name = t[0]
    if "view" in name.lower() or "blob" in name.lower() or "file" in name.lower():
        rows = c.execute(f"select * from [{name}] limit 5").fetchall()
        print(f"sample {name}:", rows[:2])
