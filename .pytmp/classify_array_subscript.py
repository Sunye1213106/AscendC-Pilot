# -*- coding: utf-8 -*-
"""Read-only: classify array_subscript undecided guards in fag_derive.json."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"d:\PR-review\AscendC-Pilot")
JSON = ROOT / ".probe_cache" / "fag_derive.json"


def primary_class(hits: list[str]) -> str:
    if "A_invalidS1Array" in hits:
        return "A"
    if "B_parseInfo" in hits:
        return "B"
    if "C_actualSeq" in hits:
        return "C"
    if any(h.startswith("D_") for h in hits):
        return "D"
    return "OTHER"


def main() -> int:
    doc = json.loads(JSON.read_text(encoding="utf-8"))
    items = []
    for f in doc.get("fields", []):
        fname = f.get("name", "")
        exp = f.get("expanded", "") or ""
        for g in f.get("undecided_guards") or []:
            if g.get("blocked_on") == "array_subscript":
                items.append({**g, "field": fname, "expanded": exp})

    print(f"array_subscript guards: {len(items)}")
    print(f"unique var_ids: {len({i.get('var_id') for i in items})}")

    patterns = {
        "A_invalidS1Array": r"invalidS1Array\s*\[",
        "B_parseInfo": r"parseInfo\s*\[",
        "C_actualSeq": r"actualSeq(?:Q|K)?len\s*\[",
        "D_qValue": r"qValue\s*\[",
        "D_kValue": r"kValue\s*\[",
        "D_vValue": r"vValue\s*\[",
        "D_dropValue": r"dropValue\s*\[",
        "D_pseValue": r"pseValue\s*\[",
    }

    for item in items:
        combined = item.get("text", "") + "\n" + item.get("expanded", "")
        item["hits"] = [k for k, pat in patterns.items() if re.search(pat, combined)]
        item["cls"] = primary_class(item["hits"])

    by_cls = Counter(i["cls"] for i in items)
    print("class counts (text+expanded):", dict(by_cls))

    # OTHER: what subscripts appear in expanded?
    other_subs = Counter()
    for item in items:
        if item["cls"] != "OTHER":
            continue
        for m in re.finditer(r"(\w+)\s*\[[^\]]+\]", item.get("expanded", "")):
            other_subs[m.group(1)] += 1
    print("OTHER subscript names in expanded:", other_subs.most_common(15))

    # per-field breakdown
    field_cls = defaultdict(Counter)
    for item in items:
        field_cls[item["field"]][item["cls"]] += 1
    print("\nper field:")
    for fname, ctr in sorted(field_cls.items()):
        print(f"  {fname}: {dict(ctr)}")

    # var_id samples
    print("\nvar_id groups:")
    vids = defaultdict(list)
    for item in items:
        vids[item.get("var_id", "")].append(item)
    for vid, group in sorted(vids.items(), key=lambda kv: -len(kv[1])):
        sample = group[0]
        fields = sorted({g["field"] for g in group})
        print(f"  {vid} x{len(group)} fields={fields} cls={sample['cls']} hits={sample['hits']}")
        print(f"    guard_head: {sample.get('text', '')[:100]}")

    # check resolved VAR_ELEM in value_expr vs still blocked
    elem_vars = set()
    for f in doc.get("fields", []):
        for v in f.get("variables") or []:
            if str(v).startswith("VAR_ELEM_"):
                elem_vars.add(str(v))
    print(f"\nVAR_ELEM_* in variables: {len(elem_vars)}")
    for v in sorted(elem_vars):
        print(f"  {v}")

    # search CEBE4AE2E0D5 / qValue undecided
    raw = JSON.read_text(encoding="utf-8")
    for needle in ("CEBE4AE2E0D5", "qValue[0]", "VAR_ELEM_ELEM_QVALUE", "VAR_UNDECIDED"):
        print(f"{needle} in json: {needle in raw}")

    # guards that mention parseInfo/actualSeq in undecided text only (short)
    short_hits = Counter()
    for item in items:
        t = item.get("text", "")
        for name in ("parseInfo", "actualSeqQlen", "actualSeqKvlen", "qValue", "invalidS1Array"):
            if name in t:
                short_hits[name] += 1
    print("short guard text mentions:", dict(short_hits))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
