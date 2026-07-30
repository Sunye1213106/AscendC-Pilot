# -*- coding: utf-8 -*-
import json
import re
from collections import Counter
from pathlib import Path

p = Path(r"d:\PR-review\AscendC-Pilot\.probe_cache\fag_derive.json")
doc = json.loads(p.read_text(encoding="utf-8"))
PARTIAL = {"SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut", "IsTndSwizzle"}
known = set(
    "qValue kvValue actualSeqQlen actualSeqKvlen invalidS1Array parseInfo inputLayout fBaseParams".split()
)
subs = Counter()
for f in doc["fields"]:
    if f["name"] not in PARTIAL:
        continue
    exp = f.get("expanded") or ""
    for m in re.finditer(r"(\w+)\s*\[[^\]]+\]", exp):
        name = m.group(1)
        if name not in known and not name.startswith("VAR_"):
            subs[name] += 1
print("unknown subscript bases:", dict(subs))
for f in doc["fields"]:
    if f["name"] not in PARTIAL:
        continue
    exp = f.get("expanded") or ""
    print(f"\n=== {f['name']} ===")
    for pat in [
        "VAR_ELEM_ELEM_FBASEPARAMS_ACTUALSEQQLEN",
        "VAR_ELEM_ELEM_FBASEPARAMS_ACTUALSEQKVLEN",
        "VAR_ELEM_ELEM_PARSEINFO",
        "VAR_ELEM_ELEM_QVALUE",
        "VAR_ELEM_ELEM_KVVALUE",
        "actualSeqQlen[",
        "actualSeqKvlen[",
        "parseInfo[",
        "invalidS1Array[",
        "qValue[",
        "kvValue[",
        "inputLayout[",
    ]:
        c = len(re.findall(pat, exp))
        if c:
            print(f"  {pat}: {c}")
