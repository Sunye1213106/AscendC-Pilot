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
E = ledger.load_E(ws)
D = ledger.declared()
wit = list(W.decode_many(sorted(R)))
open_keys = D - R - E
open_wit = list(W.decode_many(sorted(open_keys)))

def hits(when, pool):
    return [w for w in pool if all(str(w.get(k)) == str(v) for k, v in when.items())]

def count(when):
    return len(hits(when, wit)), len(hits(when, open_wit))

candidates = [
    ("IsAttenMask=0 DeterType=3", {"IsAttenMask": "0", "DeterType": "3"}),
    ("IsAttenMask=0 DeterType=4", {"IsAttenMask": "0", "DeterType": "4"}),
    ("IsAttenMask=0 DeterType in 3,4", {"IsAttenMask": "0", "DeterType": "3"}),
    ("IsTndSwizzle=1 SplitAxis=0", {"IsTndSwizzle": "1", "SplitAxis": "0"}),
    ("IsTndSwizzle=1 IsTnd=0", {"IsTndSwizzle": "1", "IsTnd": "0"}),
    ("IsTnd=1 IsTndSwizzle=1 SplitAxis=0", {"IsTnd": "1", "IsTndSwizzle": "1", "SplitAxis": "0"}),
    ("SplitAxis=1 InputDType=2(FLOAT)", {"SplitAxis": "1", "InputDType": "2"}),
    ("SplitAxis=5 IsRope=1", {"SplitAxis": "5", "IsRope": "1"}),
    ("SplitAxis=5 InputDType=2", {"SplitAxis": "5", "InputDType": "2"}),
    ("IsBn2MultiBlk=1 IsTnd=1", {"IsBn2MultiBlk": "1", "IsTnd": "1"}),
    ("IsBn2MultiBlk=1 SplitAxis=0", {"IsBn2MultiBlk": "1", "SplitAxis": "0"}),
    ("IsRope=1 DTemplateNum!=192", {"IsRope": "1", "DTemplateNum": "64"}),
    ("IsRope=0 IsDNoEqual=0 has rope mismatch", {"IsRope": "1", "IsDNoEqual": "0"}),
    ("FLOAT S1=64 S2=128 D!=768", {"InputDType": "2", "S1TemplateNum": "64", "S2TemplateNum": "128", "DTemplateNum": "64"}),
    ("IsNzOut=1 SplitAxis=1", {"IsNzOut": "1", "SplitAxis": "1"}),
    ("IsNzOut=1 DeterType=1", {"IsNzOut": "1", "DeterType": "1"}),
    ("IsTnd=1 IsTndSwizzle=1", {"IsTnd": "1", "IsTndSwizzle": "1"}),
    ("IsTnd=0 IsTndSwizzle=1", {"IsTnd": "0", "IsTndSwizzle": "1"}),
]
for name, when in candidates:
    rh, oh = count(when)
    print(f"{name}: R={rh} open={oh}")

# broader stats
print("\nOpen IsAttenMask=0 DeterType distribution:")
c = Counter(str(w.get("DeterType")) for w in open_wit if str(w.get("IsAttenMask")) == "0")
print(dict(c))

print("\nOpen IsTndSwizzle=1 distribution:")
c2 = Counter((str(w.get("IsTnd")), str(w.get("SplitAxis")), str(w.get("InputDType"))) for w in open_wit if str(w.get("IsTndSwizzle")) == "1")
for k,v in c2.most_common(10):
    print(k, v)

print("\nOpen SplitAxis distribution:")
c3 = Counter(str(w.get("SplitAxis")) for w in open_wit)
print(dict(c3))

print("\nOpen IsTndSwizzle distribution:")
c4 = Counter(str(w.get("IsTndSwizzle")) for w in open_wit)
print(dict(c4))
