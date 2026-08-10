#!/usr/bin/env python3
import os
from collections import Counter
from testcase_agent.closure import ledger, workspace as W

os.environ.update({
    "ASCENDC_PROJECT_ROOT": "/work/ops-transformer/attention/flash_attention_score_grad",
    "UO_OP_DIR": "/work/ops-transformer/attention/flash_attention_score_grad",
    "UO_OPERATOR": "flash_attention_score_grad",
    "UO_ARCH": "arch35",
})
ws = W.default_workspace().ensure()
R = ledger.load_R(ws)
E = ledger.load_E(ws)
D = ledger.declared()
open_keys = sorted(D - R - E)

def sig(inst):
    return tuple(sorted((k, str(v)) for k, v in inst.items()))

r_bn2 = {sig(dict(W.decode(int(k)))) for k in R if dict(W.decode(int(k))).get("IsBn2MultiBlk") == "1"}
o_bn2 = []
for k in open_keys:
    inst = dict(W.decode(int(k)))
    if inst.get("IsBn2MultiBlk") == "1":
        o_bn2.append((int(k), inst))

print("r_bn2", len(r_bn2), "o_bn2", len(o_bn2))
# dims differing vs nearest R bn2 by hamming
dims = list(o_bn2[0][1].keys())
for k, inst in o_bn2[:12]:
    best = None
    bestd = 99
    best_inst = None
    for rk in R:
        ri = dict(W.decode(int(rk)))
        if ri.get("IsBn2MultiBlk") != "1":
            continue
        d = sum(1 for dim in dims if str(ri.get(dim)) != str(inst.get(dim)))
        if d < bestd:
            bestd = d
            best = rk
            best_inst = ri
    diff = [dim for dim in dims if str(best_inst.get(dim)) != str(inst.get(dim))] if best_inst else []
    print("open", k, "d", bestd, "diff", diff, "DTpl", inst.get("DTemplateNum"), "Drop", inst.get("IsDrop"), "Pse", inst.get("IsPse"), "Mask", inst.get("IsAttenMask"), "Out", inst.get("OutDType"))

# Count open bn2 by DTpl
c = Counter(inst.get("DTemplateNum") for _, inst in o_bn2)
print("open_bn2_dtpl", c)
c2 = Counter(
    (inst.get("DTemplateNum"), inst.get("IsDrop"), inst.get("IsPse"), inst.get("IsAttenMask"), inst.get("OutDType"), inst.get("InputDType"))
    for _, inst in o_bn2
)
print("open_bn2_combos", len(c2))
for combo, n in c2.most_common(20):
    print(n, combo)
