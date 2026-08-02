# -*- coding: utf-8 -*-
"""Small read-only dumps over the cached derivation JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"

doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
what = sys.argv[1] if len(sys.argv) > 1 else "table"

if what == "table":
    for f in doc["fields"]:
        print(
            f"{f['index']:3} {f['name']:16} {f['status']:11} "
            f"{str(f.get('exactness')):16} {f.get('seconds')}s  note={f.get('note')}"
        )
    print()
    r = json.loads((CACHE / "fag_reach.json").read_text(encoding="utf-8"))
    print(json.dumps(r, indent=2, ensure_ascii=False))
elif what == "detail":
    names = sys.argv[2:]
    for f in doc["fields"]:
        if names and f["name"] not in names:
            continue
        print(f"\n===== {f['name']} =====")
        print(f"  unresolved   : {f.get('unresolved')}")
        print(f"  var_scope    : {(f.get('host_derivation') or {})}")
        for g in f.get("undecided_guards") or []:
            print(
                f"  guard {g['var_id']} [{g['presort']}] {g['reason']} "
                f"scope={g.get('scope')} blocked_on={g.get('blocked_on')} "
                f":: {g['text'][:150]}"
            )
elif what == "raw":
    name = sys.argv[2]
    hd = doc["host_derivation"]
    for row in hd["fields"]:
        if row["name"] == name:
            for k, v in row.items():
                if k in ("value_expr", "expanded"):
                    continue
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:2000]}")
