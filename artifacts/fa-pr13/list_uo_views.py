# -*- coding: utf-8 -*-
"""List view_blob names inside the product .uo archive."""
import sqlite3
from pathlib import Path

p = Path("/work/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/uo/flash_attention_score_grad.arch35.uo")
c = sqlite3.connect(str(p))
rows = c.execute("select name, length(data) from view_blob order by name").fetchall()
print("view_blob count:", len(rows))
for name, n in rows:
    print(f"  {name}: {n} bytes")
