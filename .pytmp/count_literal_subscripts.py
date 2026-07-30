# -*- coding: utf-8 -*-
"""Count literal subscripts still in expanded (not VAR_ELEM) for partial fields."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

JSON = Path(r"d:\PR-review\AscendC-Pilot\.probe_cache\fag_derive.json")
PARTIAL = {"SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut", "IsTndSwizzle"}

# patterns for semantic buckets
BUCKETS = [
    ("D_qValue", r"\bqValue\s*\[\s*0\s*\]"),
    ("D_kvValue", r"\bkvValue\s*\[\s*0\s*\]"),
    ("C_actualSeqQlen", r"\bactualSeqQlen\s*\["),
    ("C_actualSeqKvlen", r"\bactualSeqKvlen\s*\["),
    ("C_fBaseParams_actualSeq", r"\bfBaseParams\.actualSeq(?:Q|K)?len\s*\["),
    ("A_invalidS1Array", r"\binvalidS1Array\s*\["),
    ("B_parseInfo", r"\bparseInfo\s*\["),
    ("B_parseInfo_nested", r"\bparseInfo\s*\[\s*\w+\s*\]\s*\["),
    ("other_inputLayout", r"\binputLayout\s*\["),
    ("other_generic", r"\b\w+\s*\[[^\]]+\]"),
]


def main():
    doc = json.loads(JSON.read_text(encoding="utf-8"))
    total = Counter()
    per_field = defaultdict(Counter)
    guards_with = Counter()

    for f in doc.get("fields", []):
        name = f.get("name", "")
        if name not in PARTIAL:
            continue
        exp = f.get("expanded") or ""
        # skip if already VAR_ELEM slug present for container
        for label, pat in BUCKETS:
            hits = re.findall(pat, exp)
            if hits:
                total[label] += len(hits)
                per_field[name][label] += len(hits)

        for g in f.get("undecided_guards") or []:
            if g.get("blocked_on") != "array_subscript":
                continue
            t = (g.get("text") or "") + "\n" + exp
            for label, pat in BUCKETS:
                if re.search(pat, t):
                    guards_with[label] += 1

    print("=== literal subscripts in expanded (5 partial fields) ===")
    for k, v in total.most_common():
        print(f"  {k}: {v}")
    print("\n=== per field ===")
    for fname in sorted(per_field):
        print(f"  {fname}: {dict(per_field[fname])}")
    print("\n=== array_subscript guards touching bucket (may double-count) ===")
    for k, v in guards_with.most_common():
        print(f"  {k}: {v}")

    # array_subscript-only guards: what's in SHORT text (first 500 of undecided)
    print("\n=== short guard texts (unique) for array_subscript ===")
    seen = set()
    for f in doc.get("fields", []):
        for g in f.get("undecided_guards") or []:
            if g.get("blocked_on") != "array_subscript":
                continue
            t = g.get("text", "")
            key = t[:80]
            if key in seen:
                continue
            seen.add(key)
            subs = []
            for label, pat in BUCKETS:
                if re.search(pat, t):
                    subs.append(label)
            print(f"  subs_in_short={subs or ['none']}")
            print(f"    {t[:160]}")
            print()


if __name__ == "__main__":
    main()
