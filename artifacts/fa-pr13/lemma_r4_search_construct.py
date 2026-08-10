#!/usr/bin/env python3
"""Round-4: directed search + targeted Host construct for remaining open."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
OUT = PILOT / "artifacts" / "fa-pr13"
RUN_ID = "lemma_closure_composer_r4"


def setup():
    sys.path[:0] = [
        str(OUT),
        str(PILOT / "pilot"),
        str(PILOT / "engines/testcase-generation"),
        str(PILOT / "engines/understand-operator/src"),
        str(PILOT / "scripts"),
        str(PILOT / "operators"),
    ]
    os.environ.update(
        {
            "ASCENDC_PROJECT_ROOT": str(OP),
            "UO_OP_DIR": str(OP),
            "UO_OPERATOR": "flash_attention_score_grad",
            "UO_ARCH": "arch35",
            "UO_OPS_ROOT": "/work/ops-transformer",
            "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
            "UO_REPLAY_HOST": "native",
            "TG_SKIP_ANALYSIS_GATE": "1",
        }
    )


def main():
    setup()
    from ascendc_pilot.actions import engines as E
    from testcase_agent.closure import ledger, workspace as W, construct, residual
    from testcase_agent.closure.oracle import HostOracle
    from testcase_agent.closure import corpus as C

    ws = W.default_workspace().ensure()
    ctx = {"run_id": RUN_ID, "architecture": "arch35", "skip_analysis_gate": True}

    # Search round with larger budget
    print("== search ==")
    search = E._run_closure_search(OP, {**ctx, "budget": 128, "seed": 7})
    print({k: search.get(k) for k in ("ok", "new_R", "error", "engine") if k in search or True})
    print("keys", [k for k in search.keys()])

    st = ledger.state(ws)
    print("after search", st)

    # Targeted construct for ALL remaining open (decode + construct_case + host)
    open_keys = sorted(ledger.declared() - ledger.load_R(ws) - ledger.load_E(ws))
    print("open", len(open_keys))
    cases = []
    traces = []
    for k in open_keys:
        try:
            inst = W.decode(int(k))
            spelled = construct.build(inst)
            for c in spelled[:2]:
                cases.append(c)
            traces.append({"key": int(k), "spelled": len(spelled), "path": construct.last_build_path()})
        except Exception as exc:
            traces.append({"key": int(k), "error": str(exc)[:160]})
    print("built_cases", len(cases), "targets", len(traces))

    gained = 0
    if cases:
        oracle = HostOracle()
        # batch to avoid huge host runs
        batch = cases[:256]
        verdicts = oracle.judge(batch, tag="r4_open")
        rows = []
        for v in verdicts:
            if not v.verdict:
                continue
            rows.append(
                {
                    "ok": int(v.ok),
                    "tiling_key": int(v.key),
                    "reject": v.reject,
                    "_arm": "r4_open",
                }
            )
            if v.ok and int(v.key) in set(open_keys):
                gained += 1
        if rows:
            C.commit(rows, ws, name="r4_open_cases.csv")
            ledger.rebuild(ws)
        print("replayed", len(verdicts), "rows", len(rows), "gained_open_hits", gained)

    st = ledger.state(ws)
    print("FINAL", st)
    E._run_closure_residual(OP, {**ctx, "round_budget": 64})
    (OUT / "lemma_r4_result.json").write_text(
        json.dumps(
            {"state": st, "search": {k: search.get(k) for k in ("ok", "new_R")}, "open_traces": traces[:40]},
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
