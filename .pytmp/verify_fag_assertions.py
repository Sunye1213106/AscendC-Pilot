#!/usr/bin/env python3
"""Verify fag_derive.json assertions - read-only probe."""
import json
from pathlib import Path

DERIVE = Path(r"d:\PR-review\AscendC-Pilot\.probe_cache\fag_derive.json")

def main():
    with open(DERIVE, encoding="utf-8") as f:
        d = json.load(f)
    fields = d["fields"]
    print("=== SCHEMA ===")
    print("Total fields:", len(fields))
    if fields:
        print("First field keys:", sorted(fields[0].keys()))

    print("\n=== ALL FIELDS ===")
    for f in fields:
        roots = f.get("input_roots", [])
        print(f"{f.get('name')}\t{f.get('exactness')}\t{roots}")

    def show_field(name):
        for f in fields:
            if f.get("name") == name:
                print(f"\n=== FIELD: {name} ===")
                for k in sorted(f.keys()):
                    v = f[k]
                    if k == "value_expr":
                        if isinstance(v, str) and len(v) > 2000:
                            print(f"  {k}: <str len={len(v)}> first500={v[:500]!r}")
                        elif isinstance(v, dict):
                            print(f"  {k}: dict keys={list(v.keys())}")
                            print(f"    {json.dumps(v, ensure_ascii=False)[:3000]}")
                        else:
                            print(f"  {k}: {v}")
                    elif k == "variables" and isinstance(v, dict):
                        print(f"  {k}:")
                        for vn, vd in v.items():
                            if isinstance(vd, dict):
                                print(f"    {vn}: root={vd.get('root')} symbol={vd.get('symbol')} text={vd.get('text', '')[:80]}")
                            else:
                                print(f"    {vn}: {vd}")
                    else:
                        sv = json.dumps(v, ensure_ascii=False) if not isinstance(v, (str, int, float, bool, type(None))) else v
                        if isinstance(sv, str) and len(sv) > 500:
                            print(f"  {k}: <len={len(sv)}> {sv[:500]}...")
                        else:
                            print(f"  {k}: {sv}")
                return
        print(f"FIELD NOT FOUND: {name}")

    for nm in ["IsTnd", "IsPse", "IsAttenMask", "IsNEqual", "OutDType", "InputDType"]:
        show_field(nm)

if __name__ == "__main__":
    main()
