#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-round TG analysis (skill-required): residual → explain → leads → CodeMap.

Does NOT construct. Writes round_analysis_<n>.json for the iterate loop / human.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"
OP_NAME = "flash_attention_score_grad"
OUT = PILOT / "artifacts" / "fa-pr13"


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
            "TG_CLOSURE_CI": "0",
        }
    )


def codemap_for_dims(dims: list[str], *, limit: int = 6) -> list[dict]:
    """Query UO packing/producer/guards for blamed dims (structure, not proof)."""
    out: list[dict] = []
    try:
        from uo_query.api import CodeMapQuery
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"CodeMapQuery import failed: {exc}"}]
    try:
        q = CodeMapQuery(OP, arch=ARCH, operator=OP_NAME)
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"CodeMapQuery open failed: {exc}"}]
    for dim in dims[:limit]:
        entry: dict = {"dim": dim}
        for method, key in (
            ("packing", "packing"),
            ("producer", "producer"),
            ("guards", "guards"),
            ("all_writes", "all_writes"),
        ):
            try:
                fn = getattr(q, method, None)
                if fn is None:
                    continue
                # Common signatures: packing(dim) / query helpers
                try:
                    entry[key] = fn(dim)
                except TypeError:
                    entry[key] = fn(dim_name=dim)
            except Exception as exc:  # noqa: BLE001
                entry[key] = {"error": str(exc)[:200]}
        out.append(entry)
    return out


def main() -> int:
    setup()
    from ascendc_pilot.actions import engines as E
    from ascendc_pilot.paths import ensure_agent_layout, ensure_closure_layout
    from testcase_agent.closure import ledger
    from testcase_agent.closure import residual
    from testcase_agent.closure import search_round
    from testcase_agent.closure import observations as OBS

    ensure_agent_layout(OP, arch=ARCH)
    ensure_closure_layout(OP, arch=ARCH)
    ctx = {
        "op_name": OP_NAME,
        "architecture": ARCH,
        "mode": "tilingkey_full_coverage",
        "level": "L0",
        "live_replay": True,
        "live_explain": True,
        "open_limit": 40,
        "per_target": 16,
        "round_budget": 32,
    }
    ws = E._closure_ws(OP)
    st = ledger.state(ws)
    analysis = residual.analyse(ws)
    routed = search_round.route(ws)
    # residual.analyse returns blame as Counter.most_common → list[(dims, count)]
    blame = analysis.get("blame") or []
    if isinstance(blame, dict):
        top_blame = sorted(blame.items(), key=lambda x: -int(x[1] or 0))[:15]
    elif isinstance(blame, list):
        top_blame = [(str(a), int(b)) for a, b in blame[:15]]
    else:
        top_blame = []

    # Mismatch dims from residual rows (distance-1 open)
    dim_hit: Counter[str] = Counter()
    for row in analysis.get("rows") or []:
        diff = str(row.get("differing_dims") or "")
        if not diff:
            continue
        for d in diff.split("|"):
            if d:
                dim_hit[d] += 1
    top_dims = [d for d, _ in dim_hit.most_common(8)]

    # Explain (Host rewrite why) — may be heavy; keep bounded via ctx
    explain = E._run_closure_explain(OP, ctx)

    # Observation leads (REWRITE/REFUSE clusters) — required before lemma
    leads_doc = OBS.build_leads(ws, top=40)
    leads_path = (
        OP / ".ascendc-pilot" / "tg" / ARCH / "closure" / "lemmas" / "leads.yaml"
    )
    # Persist via engine for consistent path
    leads_eng = E._run_lemma_leads(OP, ctx)
    evid = E._run_lemma_evidence(OP, ctx)

    # CodeMap structure for top blamed dims
    cm = codemap_for_dims(top_dims, limit=6)

    # Decision per skill (not auto-construct)
    reason = str(routed.get("reason") or "")
    d1 = int((analysis.get("distance") or {}).get(1) or 0)
    open_n = int(analysis.get("open") or st.get("gap") or 0)
    mostly_d1 = bool(analysis.get("mostly_distance_1"))
    lead_n = int(leads_eng.get("lead_count") or leads_doc.get("lead_count") or 0)

    if open_n == 0:
        next_action = "CERTIFY"
    elif reason in {"NEED_LEMMA", "PROOF_BLOCKED"} or (not mostly_d1 and lead_n > 0 and d1 == 0):
        next_action = "LEMMA_MINE"
    elif lead_n > 0 and reason == "SEARCH_STALLED":
        next_action = "LEMMA_MINE"  # saturate → prove, not more blind construct
    elif d1 > 0 and mostly_d1:
        next_action = "CONSTRUCT_D1"
    elif d1 > 0:
        next_action = "CONSTRUCT_THEN_REANALYSE"  # construct limited, then re-analyse
    else:
        next_action = "LEMMA_MINE"

    top_leads = []
    for lead in (leads_doc.get("leads") or [])[:8]:
        if not isinstance(lead, dict):
            continue
        top_leads.append(
            {
                "id": lead.get("id"),
                "kind": lead.get("kind"),
                "when": lead.get("when"),
                "rewrite_to": lead.get("rewrite_to"),
                "mismatch_dims": lead.get("mismatch_dims"),
                "support": lead.get("support"),
                "affected_open_keys": lead.get("affected_open_keys"),
                "priority": lead.get("priority"),
                "evidence_path": lead.get("evidence_path"),
            }
        )

    report = {
        "schema": "tg-round-analysis/v1",
        "skill": "tg-closure + source-lemma-proof",
        "state": {
            "D": st.get("declared"),
            "R": st.get("R_declared") or st.get("R"),
            "E": st.get("E"),
            "gap": st.get("gap"),
            "violation": st.get("violation"),
        },
        "route_reason": reason,
        "residual": {
            "open": analysis.get("open"),
            "distance": analysis.get("distance"),
            "mostly_distance_1": mostly_d1,
            "top_blame": [{"dims": k, "count": v} for k, v in top_blame],
            "top_mismatch_dims": [{"dim": d, "count": c} for d, c in dim_hit.most_common(10)],
        },
        "explain": {
            "ran": explain.get("ran"),
            "accepted": explain.get("accepted"),
            "path": explain.get("path"),
            "error": explain.get("error"),
        },
        "leads": {
            "lead_count": lead_n,
            "observation_count": leads_eng.get("observation_count"),
            "evidence_written": evid.get("written_count"),
            "top": top_leads,
        },
        "codemap": cm,
        "next_action": next_action,
        "discipline": (
            "HIT→R; REWRITE/REFUSE→this analysis; stable residual→lemma mine "
            "(PROVED|REFUTED|INSUFFICIENT). No construct-only loops. "
            "E only via source_lemma after referee."
        ),
    }
    n = int(os.environ.get("TG_ANALYSE_ROUND", "0"))
    path = OUT / f"round_analysis_{n}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "state", "route_reason", "residual", "explain", "next_action"
    )}, ensure_ascii=False, indent=2, default=str))
    print(f"leads.top={json.dumps(top_leads[:3], ensure_ascii=False, default=str)[:2000]}")
    print(f"WROTE {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
