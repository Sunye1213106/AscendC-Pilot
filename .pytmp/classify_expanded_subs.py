# -*- coding: utf-8 -*-
"""Classify remaining subscript patterns in expanded (incl call-style)."""
import json
import re
from collections import Counter
from pathlib import Path

JSON = Path(r"d:\PR-review\AscendC-Pilot\.probe_cache\fag_derive.json")
PARTIAL = {"SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut", "IsTndSwizzle"}

PATS = [
    ("D_qValue0", r"\bqValue\s*\[\s*0\s*\]"),
    ("D_kvValue0", r"\bkvValue\s*\[\s*0\s*\]"),
    ("C_member", r"\bfBaseParams\.actualSeq(?:Q|K)?len\s*\["),
    ("C_call", r"\bactualSeq(?:Q|K)?len\s*\(\s*fBaseParams\s*\)\s*\["),
    ("C_reduce", r"max_element\s*\(\s*begin\s*\(\s*actualSeq"),
    ("A_invalid", r"\binvalidS1Array\s*\["),
    ("B_parse_flat", r"\bparseInfo\s*\[\s*\w+\s*\]\s*\[\s*BEGIN_IDX\s*\]"),
    ("B_parse_any", r"\bparseInfo\s*\["),
    ("OTHER_inputLayout", r"\binputLayout\s*\["),
]


def main():
    doc = json.loads(JSON.read_text(encoding="utf-8"))
    total = Counter()
    per_field = {}
    for f in doc["fields"]:
        if f["name"] not in PARTIAL:
            continue
        exp = f.get("expanded") or ""
        ctr = Counter()
        for label, pat in PATS:
            ctr[label] = len(re.findall(pat, exp))
            total[label] += ctr[label]
        per_field[f["name"]] = dict(ctr)

    print("TOTAL literal occurrences in expanded:")
    for k, v in total.most_common():
        print(f"  {k}: {v}")
    print("\nPer field:")
    for fn, ctr in sorted(per_field.items()):
        nz = {k: v for k, v in ctr.items() if v}
        print(f"  {fn}: {nz}")

    # Unique guard-level: which patterns appear in each array_subscript guard's expanded
    guard_pat = Counter()
    for f in doc["fields"]:
        exp = f.get("expanded") or ""
        for g in f.get("undecided_guards") or []:
            if g.get("blocked_on") != "array_subscript":
                continue
            for label, pat in PATS:
                if re.search(pat, exp):
                    guard_pat[label] += 1
    print("\narray_subscript guards containing pattern (37 total guards):")
    for k, v in guard_pat.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
