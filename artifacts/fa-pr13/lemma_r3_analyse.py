#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys
from pathlib import Path
from collections import Counter

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
OUT = PILOT / "artifacts" / "fa-pr13"

sys.path[:0] = [str(OUT), str(PILOT/"pilot"), str(PILOT/"engines/testcase-generation"),
                str(PILOT/"engines/understand-operator/src"), str(PILOT/"scripts")]
os.environ.update({
    "ASCENDC_PROJECT_ROOT": str(OP), "UO_OP_DIR": str(OP),
    "UO_OPERATOR": "flash_attention_score_grad", "UO_ARCH": "arch35",
    "UO_OPS_ROOT": "/work/ops-transformer", "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
})

from testcase_agent.closure import ledger, workspace as W, residual
from operators.flash_attention_score_grad.arch35 import input_semantics as IS

ws = W.default_workspace().ensure()
open_keys = sorted(ledger.declared() - ledger.load_R(ws) - ledger.load_E(ws))
print("open", len(open_keys))
analysis = residual.analyse(ws)
print("blame", analysis.get("blame")[:12])
print("distance", analysis.get("distance"))

patterns = Counter()
reason_hits = Counter()
for k in open_keys:
    inst = dict(W.decode(int(k)))
    key = (
        f"SA={inst.get('SplitAxis')}",
        f"Tnd={inst.get('IsTnd')}",
        f"Swz={inst.get('IsTndSwizzle')}",
        f"Bn2={inst.get('IsBn2MultiBlk')}",
        f"Nz={inst.get('IsNzOut')}",
        f"Rope={inst.get('IsRope')}",
        f"Deter={inst.get('DeterType')}",
        f"Drop={inst.get('IsDrop')}",
        f"Dtype={inst.get('InputDType')}",
        f"DTpl={inst.get('DTemplateNum')}",
        f"S1={inst.get('S1TemplateNum')}",
    )
    patterns[key] += 1
    try:
        for r in IS.construct_reasons(inst) or []:
            reason_hits[r] += 1
    except Exception as e:
        reason_hits[f"err:{e}"] += 1

print("TOP_PATTERNS")
for p, n in patterns.most_common(30):
    print(n, p)
print("TOP_REASONS")
for r, n in reason_hits.most_common(20):
    print(n, r)
