#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drive lemma phase after Host saturation: leads → evidence → mine stage → apply.

Producer/referee agents fill parts/ and review.yaml; this script prepares the
deterministic gates and applies accepted certificates.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"
OP_NAME = "flash_attention_score_grad"
OUT = PILOT / "artifacts" / "fa-pr13"
RUN_ID = os.environ.get("TG_RUN_ID", "lemma_closure_composer")


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
            "TG_CLOSURE_CI": "0",
        }
    )


def main() -> int:
    setup()
    from ascendc_pilot.actions import engines as E
    from testcase_agent.closure import ledger
    from testcase_agent.closure import residual
    from testcase_agent.closure import search_round
    from testcase_agent.closure import workspace as W

    ws = W.default_workspace().ensure()
    ctx = {"run_id": RUN_ID, "architecture": ARCH, "project_root": str(OP)}

    print("== residual / round_analysis ==")
    res = E._run_closure_residual(OP, {**ctx, "round_budget": 64})
    print(json.dumps({k: res.get(k) for k in ("ok", "reason_code", "needs_rework", "escalate")}, ensure_ascii=False))

    print("== lemma_leads (guard families) ==")
    leads = E._run_lemma_leads(OP, ctx)
    print(json.dumps({k: leads.get(k) for k in ("ok", "lead_count", "artifact")}, ensure_ascii=False))

    print("== lemma_evidence ==")
    evid = E._run_lemma_evidence(OP, ctx)
    print(json.dumps({k: evid.get(k) for k in ("ok", "lead_count", "written_count", "error")}, ensure_ascii=False))

    print("== lemma_mine staging ==")
    mine = E._run_lemma_mine(OP, ctx)
    print(json.dumps(mine, ensure_ascii=False, default=str)[:800])

    st = ledger.state(ws)
    analysis = residual.analyse(ws)
    routed = search_round.route(ws)
    summary = {
        "timestamp": time.time(),
        "run_id": RUN_ID,
        "state": st,
        "residual": {
            "open": analysis.get("open"),
            "distance": analysis.get("distance"),
            "mostly_distance_1": analysis.get("mostly_distance_1"),
            "blame_top": (analysis.get("blame") or [])[:10],
        },
        "route": {
            "reason": routed.get("reason"),
            "target_hit_rate": routed.get("target_hit_rate"),
            "rewrite_share": routed.get("rewrite_share"),
        },
        "leads": {"lead_count": leads.get("lead_count")},
        "mine_staging": mine.get("staging"),
        "hint_families": [
            "SetSplitAxis: IsTndSwizzle=1 only on TND SplitAxis=5 non-FLOAT DTemplate 64/128",
            "ProcessSparseModeInfo: DeterType 3/4 requires atten_mask",
            "SetSplitAxis: SplitAxis=1 requires non-FLOAT, no drop/deter/NEqual, S1/S2=(128,128)",
            "SetSplitAxis: SplitAxis=5 requires non-FLOAT, no rope/deter/NEqual/BN2MultiBlk, DTemplate 64/128",
            "SetSplitAxis: IsBn2MultiBlk=1 only on non-TND SplitAxis=1 clean BN2 shape",
            "IsNzOut: requires SplitAxis=0, non-TND, non-FLOAT, DTemplate=128, DeterType 0/2",
            "SetSplitAxis: TND SplitAxis=1 requires DTemplate 64/128 and no rope",
            "GetDTemplateType: IsRope=1 forces DTemplateNum=192",
            "GetS1S2TemplateType: FLOAT expects S1/S2=(64,128) only for DTemplate=768 else (128,128)",
            "GetTilingKey: IsRope=1 forces IsDNoEqual=1",
        ],
        "note": "Historical families are HYPOTHESES only — must re-prove from current source+CodeMap.",
    }
    out = OUT / "lemma_closure_prep.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)
    print("STATE", json.dumps(st, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
