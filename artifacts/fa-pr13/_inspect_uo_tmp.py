#!/usr/bin/env python3
import sqlite3
import json
from pathlib import Path

p = Path(r"d:\PR-review\AscendC-Pilot\artifacts\fa-pr13\flash_attention_score_grad.arch35.uo")
c = sqlite3.connect(p)
print("tables:", [r[0] for r in c.execute("select name from sqlite_master where type='table'")])
print()
try:
    rows = c.execute("select name, length(data), schema_id from view_blob order by name").fetchall()
    print("view_blob count", len(rows))
    for name, n, sid in rows:
        print(f"  {name}\t{n}\tschema={sid}")
except Exception as e:
    print("view_blob err", e)
print()
try:
    keys = c.execute("select key, value from meta").fetchall()
    print("meta count", len(keys))
    for k, v in keys:
        s = v.decode("utf-8", errors="replace") if isinstance(v, (bytes, bytearray)) else str(v)
        print(f"  {k}: {s[:200]!r}")
except Exception as e:
    print("meta err", e)
print()
for t in [
    "entity",
    "relation",
    "entities",
    "relations",
    "node",
    "edge",
    "symbol",
    "fact",
    "codemap_entity",
    "codemap_relation",
]:
    try:
        n = c.execute(f"select count(*) from {t}").fetchone()[0]
        print(f"{t}: {n}")
        cols = [r[1] for r in c.execute(f"pragma table_info({t})").fetchall()]
        print(f"  cols: {cols}")
        sample = c.execute(f"select * from {t} limit 2").fetchall()
        print(f"  sample0 kinds/types:", sample[0][:6] if sample else None)
    except Exception as e:
        pass

# entity kind histogram if possible
for t in ["entity", "entities", "codemap_entity"]:
    try:
        cols = [r[1] for r in c.execute(f"pragma table_info({t})").fetchall()]
        kind_col = next((x for x in cols if "kind" in x.lower() or x.lower() == "type"), None)
        if kind_col:
            rows = c.execute(
                f"select {kind_col}, count(*) from {t} group by 1 order by 2 desc limit 30"
            ).fetchall()
            print(f"\n{t} by {kind_col}:")
            for k, n in rows:
                print(f"  {k}: {n}")
    except Exception:
        pass
