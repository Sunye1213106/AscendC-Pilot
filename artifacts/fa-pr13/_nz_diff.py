#!/usr/bin/env python3
import os
from testcase_agent.closure import ledger, workspace as W

os.environ.update({
    "ASCENDC_PROJECT_ROOT": "/work/ops-transformer/attention/flash_attention_score_grad",
    "UO_OP_DIR": "/work/ops-transformer/attention/flash_attention_score_grad",
    "UO_OPERATOR": "flash_attention_score_grad",
    "UO_ARCH": "arch35",
})
ws = W.default_workspace().ensure()
R = ledger.load_R(ws)
open_keys = sorted(ledger.declared() - R - ledger.load_E(ws))
o_nz = [(int(k), dict(W.decode(int(k)))) for k in open_keys if dict(W.decode(int(k))).get("IsNzOut") == "1"]
print("open_nz", len(o_nz))
for k, inst in o_nz[:15]:
    best = None
    bestd = 99
    best_inst = None
    dims = list(inst.keys())
    for rk in R:
        ri = dict(W.decode(int(rk)))
        if ri.get("IsNzOut") != "1":
            continue
        d = sum(1 for dim in dims if str(ri.get(dim)) != str(inst.get(dim)))
        if d < bestd:
            bestd, best, best_inst = d, rk, ri
    diff = [dim for dim in dims if str(best_inst.get(dim)) != str(inst.get(dim))] if best_inst else []
    print("d", bestd, "diff", diff, "Deter", inst.get("DeterType"), "Tnd", inst.get("IsTnd"), "Drop", inst.get("IsDrop"), "Mask", inst.get("IsAttenMask"), "Dtype", inst.get("InputDType"))
