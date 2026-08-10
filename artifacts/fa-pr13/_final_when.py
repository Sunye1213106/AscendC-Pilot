#!/usr/bin/env python3
import os
from testcase_agent.closure import ledger, workspace as W, lemma

os.environ.update({
    "ASCENDC_PROJECT_ROOT": "/work/ops-transformer/attention/flash_attention_score_grad",
    "UO_OP_DIR": "/work/ops-transformer/attention/flash_attention_score_grad",
    "UO_OPERATOR": "flash_attention_score_grad",
    "UO_ARCH": "arch35",
})
ws = W.default_workspace().ensure()
R = ledger.load_R(ws)
wit = list(W.decode_many(sorted(R)))
open_keys = sorted(ledger.declared() - R - ledger.load_E(ws))
opn = list(zip(open_keys, W.decode_many(open_keys)))
checks = [
    {"IsBn2MultiBlk": "1", "IsDNoEqual": "1"},
    {"IsNzOut": "1", "IsNEqual": "1"},
    {"IsNzOut": "1", "DeterType": "3", "IsNEqual": "1"},
    {"IsNzOut": "1", "DeterType": "4", "IsNEqual": "1"},
    {"IsNzOut": "1", "DeterType": "3", "IsTnd": "0"},
    {"IsNzOut": "1", "DeterType": "4", "IsTnd": "1"},
]
for when in checks:
    v = lemma.verify(when, wit)
    n = sum(1 for _, o in opn if all(str(o.get(d)) == str(val) for d, val in when.items()))
    print(("ok" if v["ok"] else "refuted"), "hits", v["hit_count"], "open", n, when)
