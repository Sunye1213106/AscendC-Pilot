#!/usr/bin/env python3
import sqlite3
from pathlib import Path

p = Path(
    "/work/ops-transformer/attention/flash_attention_score_grad/"
    ".ascendc-pilot/uo/flash_attention_score_grad.arch35.uo"
)
c = sqlite3.connect(p)
print("tables", [r[0] for r in c.execute("select name from sqlite_master where type='table'")])
try:
    rows = c.execute("select name, length(data) from view_blob order by name").fetchall()
    print("view_blob count", len(rows))
    for name, n in rows:
        print(f"  {name}\t{n}")
except Exception as e:
    print("view_blob err", e)
try:
    keys = [r[0] for r in c.execute("select key from meta").fetchall()]
    print("meta keys", keys[:50])
except Exception as e:
    print("meta err", e)
