#!/usr/bin/env python3
import os
from collections import Counter
from testcase_agent.closure import ledger, workspace as W

os.environ.setdefault(
    "TG_CLOSURE_STATE",
    "/work/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/closure",
)
ws = W.default_workspace().ensure()
R = ledger.load_R(ws)
wit = list(W.decode_many(sorted(R)))

for dt in ["3", "4"]:
    hits = [w for w in wit if str(w.get("IsAttenMask")) == "0" and str(w.get("DeterType")) == dt]
    print(f"R hits IsAttenMask=0 DeterType={dt}: {len(hits)}")

when = {
    "IsEmptyTensor": "0",
    "SplitAxis": "0",
    "IsAttenMask": "0",
    "S2TemplateNum": "128",
    "IsBn2MultiBlk": "0",
    "IsTndSwizzle": "0",
    "IsRegbase": "1",
}
hits = [w for w in wit if all(str(w.get(k)) == str(v) for k, v in when.items())]
print("R hits lead combo:", len(hits))

c = Counter(str(w.get("DeterType")) for w in wit if str(w.get("IsAttenMask")) == "0")
print("DeterType for IsAttenMask=0 in R:", dict(c))

# IsTndSwizzle=1 in R
hits_tnd = [w for w in wit if str(w.get("IsTndSwizzle")) == "1"]
print("R hits IsTndSwizzle=1:", len(hits_tnd))
if hits_tnd:
    w = hits_tnd[0]
    print(" sample:", {k: w.get(k) for k in ["SplitAxis", "IsTnd", "InputDType", "DTemplateNum", "IsTndSwizzle"]})

# SplitAxis values in open vs R
c_sa = Counter(str(w.get("SplitAxis")) for w in wit)
print("SplitAxis in R:", dict(c_sa))
