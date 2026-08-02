# -*- coding: utf-8 -*-
"""Print ablation free-var detail from reached_amplify.json."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
d = json.loads((ROOT / ".probe_cache" / "reached_amplify.json").read_text(encoding="utf-8"))
for mode, stats in (d.get("ablation") or {}).items():
    print("==", mode, "==")
    if "error" in stats:
        print(stats["error"])
        continue
    print("free", stats["distinct_free"], stats["by_prefix"])
    print("implicit_vars", stats.get("implicit_default_vars"))
    print("free_list", stats.get("free_list"))
    ex = stats.get("exactness") or {}
    for name, frees in (stats.get("free_per_field") or {}).items():
        print(f"  {name}: {ex.get(name)} nfree={len(frees)}")
        for v in frees:
            print(f"    {v}")
