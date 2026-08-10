#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round-2 lemmas for remaining open after first apply."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"
OP_NAME = "flash_attention_score_grad"
OUT = PILOT / "artifacts" / "fa-pr13"
RUN_ID = "lemma_closure_composer_r2"

COMMON = "op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp"
NORMAL = "op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp"


def setup() -> None:
    sys.path[:0] = [
        str(OUT),
        str(PILOT / "pilot"),
        str(PILOT / "engines" / "testcase-generation"),
        str(PILOT / "engines" / "understand-operator" / "src"),
        str(PILOT / "scripts"),
    ]
    os.environ.update(
        {
            "ASCENDC_PROJECT_ROOT": str(OP),
            "UO_OP_DIR": str(OP),
            "UO_OPERATOR": OP_NAME,
            "UO_ARCH": ARCH,
            "UO_OPS_ROOT": "/work/ops-transformer",
            "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
            "UO_REPLAY_HOST": "native",
        }
    )


def analyse() -> None:
    from ascendc_pilot.actions import engines as E
    from testcase_agent.closure import residual
    from testcase_agent.closure import search_round
    from testcase_agent.closure import workspace as W
    from testcase_agent.closure import ledger
    from collections import Counter

    ws = W.default_workspace().ensure()
    ctx = {"run_id": RUN_ID, "architecture": ARCH}
    E._run_closure_residual(OP, {**ctx, "round_budget": 64})
    E._run_lemma_leads(OP, ctx)
    analysis = residual.analyse(ws)
    routed = search_round.route(ws)
    st = ledger.state(ws)
    dim_hit: Counter[str] = Counter()
    for row in analysis.get("rows") or []:
        for d in str(row.get("differing_dims") or "").split("|"):
            if d:
                dim_hit[d] += 1
    # Sample open when patterns for IsTndSwizzle / SplitAxis / IsNzOut
    open_keys = sorted(ledger.declared() - ledger.load_R(ws) - ledger.load_E(ws))
    samples = []
    for k in open_keys[:2000]:
        try:
            inst = dict(W.decode(int(k)))
        except Exception:
            continue
        samples.append(inst)
    # Count patterns
    patterns = Counter()
    for s in samples:
        if s.get("IsTndSwizzle") == "1":
            patterns[("IsTndSwizzle=1", f"SplitAxis={s.get('SplitAxis')}", f"IsTnd={s.get('IsTnd')}", f"Deter={s.get('DeterType')}")] += 1
        if s.get("IsNzOut") == "1":
            patterns[("IsNzOut=1", f"SplitAxis={s.get('SplitAxis')}", f"IsTnd={s.get('IsTnd')}", f"DTpl={s.get('DTemplateNum')}", f"Deter={s.get('DeterType')}")] += 1
        if s.get("SplitAxis") == "5":
            patterns[("SplitAxis=5", f"IsRope={s.get('IsRope')}", f"IsBn2={s.get('IsBn2MultiBlk')}", f"Dtype={s.get('InputDType')}", f"DTpl={s.get('DTemplateNum')}")] += 1
        if s.get("SplitAxis") == "1":
            patterns[("SplitAxis=1", f"Dtype={s.get('InputDType')}", f"Drop={s.get('IsDrop')}", f"Deter={s.get('DeterType')}", f"NEq={s.get('IsNEqual')}", f"S1={s.get('S1TemplateNum')}")] += 1
    out = {
        "state": st,
        "route": routed.get("reason"),
        "distance": analysis.get("distance"),
        "blame": (analysis.get("blame") or [])[:15],
        "dim_hit": dim_hit.most_common(15),
        "open_patterns": patterns.most_common(40),
        "open_sample": len(samples),
        "open_total": len(open_keys),
    }
    (OUT / "lemma_r2_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("state", "route", "distance", "blame", "dim_hit")}, indent=2, ensure_ascii=False, default=str))
    print("TOP_PATTERNS")
    for p, n in patterns.most_common(25):
        print(n, p)


if __name__ == "__main__":
    setup()
    analyse()
