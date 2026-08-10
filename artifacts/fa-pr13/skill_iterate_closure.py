#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skill-aligned TG closure loop: ANALYSE every round, then act.

Per tg-closure / tg-solve:
  Host verdict → residual/explain/leads → (construct|search|lemma*) → re-analyse
  Stop only when gap=0, or honest NEED_LEMMA/SEARCH_STALLED after real mine attempt.

Construct is NOT the default; analysis decides. Lemma mine is subagent work —
this driver stages evidence and stops with NEED_LEMMA when proofs are required.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"
OP_NAME = "flash_attention_score_grad"
OUT = PILOT / "artifacts" / "fa-pr13"
LOG = OUT / "skill_iterate_closure.log"

MAX_ROUNDS = int(os.environ.get("TG_ITER_ROUNDS", "12"))
BUDGET = int(os.environ.get("TG_ITER_BUDGET", "48"))
CONSTRUCT_LIMIT = int(os.environ.get("TG_ITER_CONSTRUCT", "48"))
DIRECTED_LIMIT = int(os.environ.get("TG_ITER_DIRECTED", "64"))
STALL_ROUNDS = int(os.environ.get("TG_ITER_STALL", "2"))
# After this many zero-gain construct rounds, force lemma path (no more blind construct).
FORCE_LEMMA_AFTER = int(os.environ.get("TG_FORCE_LEMMA_AFTER", "2"))


def log(msg: str) -> None:
    text = msg if msg.endswith("\n") else msg + "\n"
    sys.stdout.write(text)
    sys.stdout.flush()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text)


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


def analyse_round(E, ws, ctx, *, round_i: int) -> dict:
    """Mandatory per-round analysis (residual + explain + leads + evidence)."""
    from testcase_agent.closure import ledger
    from testcase_agent.closure import residual
    from testcase_agent.closure import search_round
    from testcase_agent.closure import observations as OBS
    from collections import Counter

    st = ledger.state(ws)
    analysis = residual.analyse(ws)
    routed = search_round.route(ws)
    reason = str(routed.get("reason") or "")

    blame = analysis.get("blame") or []
    if isinstance(blame, dict):
        top_blame = sorted(blame.items(), key=lambda x: -int(x[1] or 0))[:12]
    elif isinstance(blame, list):
        top_blame = [(str(a), int(b)) for a, b in blame[:12]]
    else:
        top_blame = []

    dim_hit: Counter[str] = Counter()
    for row in analysis.get("rows") or []:
        for d in str(row.get("differing_dims") or "").split("|"):
            if d:
                dim_hit[d] += 1

    explain = E._run_closure_explain(OP, {**ctx, "open_limit": 40, "per_target": 12})
    leads_doc = OBS.build_leads(ws, top=40)
    leads_eng = E._run_lemma_leads(OP, ctx)
    evid = E._run_lemma_evidence(OP, ctx)

    d1 = int((analysis.get("distance") or {}).get(1) or 0)
    open_n = int(analysis.get("open") or st.get("gap") or 0)
    mostly_d1 = bool(analysis.get("mostly_distance_1"))
    lead_n = int(leads_eng.get("lead_count") or 0)

    if open_n == 0:
        next_action = "CERTIFY"
    elif reason in {"NEED_LEMMA", "PROOF_BLOCKED"}:
        next_action = "LEMMA_MINE"
    elif reason == "SEARCH_STALLED" and lead_n > 0:
        next_action = "LEMMA_MINE"
    elif mostly_d1 and d1 > 0:
        next_action = "CONSTRUCT_D1"
    elif d1 > 0:
        next_action = "CONSTRUCT_THEN_REANALYSE"
    elif lead_n > 0:
        next_action = "LEMMA_MINE"
    else:
        next_action = "SEARCH"

    top_leads = []
    for lead in (leads_doc.get("leads") or [])[:6]:
        if isinstance(lead, dict):
            top_leads.append(
                {
                    "id": lead.get("id"),
                    "kind": lead.get("kind"),
                    "when": lead.get("when"),
                    "rewrite_to": lead.get("rewrite_to"),
                    "mismatch_dims": lead.get("mismatch_dims"),
                    "support": lead.get("support"),
                    "affected_open_keys": lead.get("affected_open_keys"),
                }
            )

    doc = {
        "round": round_i,
        "state": {
            "D": st.get("declared"),
            "R": st.get("R_declared") or st.get("R"),
            "E": st.get("E"),
            "gap": st.get("gap"),
        },
        "route_reason": reason,
        "residual": {
            "open": analysis.get("open"),
            "distance": analysis.get("distance"),
            "mostly_distance_1": mostly_d1,
            "top_blame": [{"dims": k, "count": v} for k, v in top_blame],
            "top_mismatch_dims": [
                {"dim": d, "count": c} for d, c in dim_hit.most_common(8)
            ],
        },
        "explain": {
            "ran": explain.get("ran"),
            "accepted": explain.get("accepted"),
            "error": explain.get("error"),
        },
        "leads": {
            "lead_count": lead_n,
            "observation_count": leads_eng.get("observation_count"),
            "evidence_written": evid.get("written_count"),
            "top": top_leads,
        },
        "next_action": next_action,
    }
    path = OUT / f"round_analysis_{round_i}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return doc


def directed_distance1(ws, oracle, *, limit: int, seed: int) -> dict:
    """Nearest-witness → flip differing dims → construct → Host (after analysis)."""
    from testcase_agent.closure import corpus as C
    from testcase_agent.closure import ledger
    from testcase_agent.closure import residual
    from replay import inputs as I

    analysis = residual.analyse(ws)
    rows = [r for r in (analysis.get("rows") or []) if int(r.get("distance") or 99) == 1]
    if len(rows) < limit // 2:
        rows += [r for r in (analysis.get("rows") or []) if int(r.get("distance") or 99) == 2]
    rows = rows[:limit]
    r_before = set(ledger.load_R(ws))
    cases = []
    meta = []
    for i, row in enumerate(rows):
        key = int(row["key"])
        try:
            from testcase_agent.closure import workspace as W

            target = W.decode(key)
        except Exception:
            continue
        built = list(I.construct_case(target) or [])
        if not built:
            continue
        case = built[0]
        if hasattr(case, "tag"):
            case.tag = f"d1_{seed}_{i}_{key}"
        cases.append(case)
        meta.append(key)

    hits = rewrites = 0
    new_keys: set[int] = set()
    if cases:
        verdicts = oracle.judge(cases, tag=f"dir{seed}")
        rows_out = []
        for i, v in enumerate(verdicts):
            if not v.verdict:
                continue
            actual = int(v.key or 0)
            target = meta[i] if i < len(meta) else 0
            if v.ok and actual == target:
                hits += 1
            elif v.ok and actual:
                rewrites += 1
            if v.ok and actual:
                new_keys.add(actual)
                rows_out.append(
                    {
                        "ok": 1,
                        "tiling_key": actual,
                        "reject": v.reject,
                        "_arm": "directed_d1",
                        "_target_key": meta[i] if i < len(meta) else 0,
                        "_target_hit": int(actual == (meta[i] if i < len(meta) else -1)),
                    }
                )
        if rows_out:
            C.commit(rows_out, ws, name=f"directed_{seed}_key_cases.csv")
            ledger.rebuild(ws)
    r_after = set(ledger.load_R(ws))
    return {
        "targets": len(rows),
        "cases": len(cases),
        "hits": hits,
        "rewrites": rewrites,
        "new_R": len(r_after - r_before),
        "R": len(r_after),
        "gap": ledger.state(ws).get("gap"),
    }


def lemma_path(E, ctx, *, run_id: str) -> dict:
    """leads→evidence→mine scaffold→review scaffold→apply.

    Real PROVED certificates require subagent filling part_0.yaml / review.yaml.
    Apply only grows E when referee accepted source_lemma rules exist.
    """
    leads = E._run_lemma_leads(OP, ctx)
    evid = E._run_lemma_evidence(OP, ctx)
    mine = E._run_lemma_mine(OP, {**ctx, "run_id": run_id})
    review = E._run_lemma_review(OP, {**ctx, "run_id": run_id})
    apply = E._run_lemma_apply(OP, {**ctx, "run_id": run_id})
    E._run_closure_ledger(OP, ctx)
    from testcase_agent.closure import ledger

    st = ledger.state(E._closure_ws(OP))
    return {
        "lead_count": leads.get("lead_count"),
        "evidence_written": evid.get("written_count"),
        "mine_need_subagent": mine.get("need_subagent"),
        "mine_staging": mine.get("staging"),
        "review_status": review.get("status"),
        "apply_ok": apply.get("ok"),
        "E": st.get("E"),
        "gap": st.get("gap"),
        "R": st.get("R_declared") or st.get("R"),
        "note": (
            "lemma_mine/review are subagent gates; without PROVED certificates E stays 0. "
            "Do not mark unreachable."
        ),
    }


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    setup()

    from ascendc_pilot.actions import engines as E
    from ascendc_pilot.paths import ensure_agent_layout, ensure_closure_layout, tg_root
    from testcase_agent.closure import ledger
    from testcase_agent.closure import oracle as oracle_mod
    from native_oracle import NativeHostOracle

    oracle_mod.HostOracle = NativeHostOracle  # type: ignore[misc,assignment]

    ensure_agent_layout(OP, arch=ARCH)
    ensure_closure_layout(OP, arch=ARCH)
    closure = tg_root(OP, arch=ARCH) / "closure"
    rounds = closure / "rounds"
    if rounds.is_dir():
        bak = closure / f"rounds_bak_{int(time.time())}"
        shutil.move(str(rounds), str(bak))
        log(f"archived rounds -> {bak}")
    rounds.mkdir(parents=True, exist_ok=True)
    suspect = closure / "oracle_suspect"
    if suspect.is_file():
        suspect.unlink()

    ctx = {
        "op_name": OP_NAME,
        "architecture": ARCH,
        "mode": "tilingkey_full_coverage",
        "level": "L0",
        "live_replay": True,
        "live_explain": True,
        "budget": BUDGET,
        "limit": CONSTRUCT_LIMIT,
        "round_budget": MAX_ROUNDS,
    }

    led0 = E._run_closure_ledger(OP, ctx)
    log(
        "ledger0 "
        + json.dumps(
            {k: led0.get(k) for k in ("ok", "declared", "R", "E", "gap", "error")},
            default=str,
        )
    )

    history: list[dict] = []
    stop_reason = ""
    zero_gain = 0
    t0 = time.time()
    oracle = NativeHostOracle()
    run_id = f"iter_{int(t0)}"

    for i in range(MAX_ROUNDS):
        ws = E._closure_ws(OP)

        # ---- 1) ANALYSE (mandatory) ----
        adoc = analyse_round(E, ws, ctx, round_i=i)
        next_action = str(adoc["next_action"])
        log(
            f"-- round {i} ANALYSE route={adoc['route_reason']} "
            f"gap={adoc['state']['gap']} R={adoc['state']['R']} E={adoc['state']['E']} "
            f"dist={adoc['residual']['distance']} mostly_d1={adoc['residual']['mostly_distance_1']} "
            f"leads={adoc['leads']['lead_count']} next={next_action}"
        )
        if adoc["residual"].get("top_blame"):
            log(f"  top_blame={adoc['residual']['top_blame'][:5]}")
        if adoc["leads"].get("top"):
            t0l = adoc["leads"]["top"][0]
            log(
                f"  top_lead id={t0l.get('id')} when={t0l.get('when')} "
                f"rewrite_to={t0l.get('rewrite_to')} open={t0l.get('affected_open_keys')}"
            )

        entry: dict = {"round": i, "analysis": adoc, "next_action": next_action}

        if next_action == "CERTIFY" or int(adoc["state"]["gap"] or 0) == 0:
            stop_reason = "GAP_ZERO"
            history.append(entry)
            break

        # Force lemma after repeated zero-gain — skill forbids construct-only loops
        if zero_gain >= FORCE_LEMMA_AFTER and adoc["leads"]["lead_count"]:
            next_action = "LEMMA_MINE"
            entry["forced_lemma"] = True
            log(f"  force LEMMA_MINE after {zero_gain} zero-gain rounds")

        r_before = set(ledger.load_R(ws))
        gained = 0

        # ---- 2) ACT based on analysis ----
        if next_action == "LEMMA_MINE":
            lem = lemma_path(E, ctx, run_id=f"{run_id}_r{i}")
            log(
                f"  lemma leads={lem.get('lead_count')} evid={lem.get('evidence_written')} "
                f"need_subagent={lem.get('mine_need_subagent')} "
                f"review={lem.get('review_status')} E={lem.get('E')} gap={lem.get('gap')}"
            )
            entry["lemma"] = lem
            history.append(entry)
            if int(lem.get("gap") or 0) == 0:
                stop_reason = "GAP_ZERO"
                break
            # Honest stop: proofs require subagent; do not fake E
            stop_reason = "NEED_LEMMA"
            log(
                "  STOP NEED_LEMMA — staging ready; fill lemma_mine parts with "
                "source-lemma-proof (PROVED|REFUTED|INSUFFICIENT), then review/apply"
            )
            break

        if next_action in {"CONSTRUCT_D1", "CONSTRUCT_THEN_REANALYSE", "SEARCH"}:
            if next_action.startswith("CONSTRUCT"):
                d_out = directed_distance1(ws, oracle, limit=DIRECTED_LIMIT, seed=i)
                log(
                    f"  directed targets={d_out.get('targets')} cases={d_out.get('cases')} "
                    f"hits={d_out.get('hits')} rewrites={d_out.get('rewrites')} "
                    f"new_R={d_out.get('new_R')}"
                )
                entry["directed"] = d_out
                gained += int(d_out.get("new_R") or 0)

            c_out = E._run_closure_construct(OP, {**ctx, "seed": i})
            log(
                f"  construct targets={c_out.get('targets')} built={c_out.get('built_cases')} "
                f"replayed={c_out.get('replayed')}"
            )
            entry["construct"] = {
                "targets": c_out.get("targets"),
                "built": c_out.get("built_cases"),
                "replayed": c_out.get("replayed"),
            }
            if suspect.is_file():
                suspect.unlink()
            s_out = E._run_closure_search(
                OP,
                {
                    **ctx,
                    "seed": 1000 + i,
                    "budget": BUDGET,
                    "oracle": NativeHostOracle(),
                },
            )
            prog = s_out.get("progress") or {}
            log(
                f"  search ok={s_out.get('ok')} new_R={prog.get('new_R')} "
                f"new_declared={prog.get('new_declared_R')}"
            )
            entry["search_new_R"] = prog.get("new_R")
            E._run_closure_ledger(OP, ctx)
            gained = len(set(ledger.load_R(E._closure_ws(OP))) - r_before)
            entry["gained_R"] = gained

            # ---- 3) RE-ANALYSE after Host (skill: every verdict batch) ----
            post = analyse_round(E, E._closure_ws(OP), ctx, round_i=i)
            # overwrite round file with post-action view; keep pre in entry
            entry["post_analysis"] = {
                "gap": post["state"]["gap"],
                "R": post["state"]["R"],
                "distance": post["residual"]["distance"],
                "lead_count": post["leads"]["lead_count"],
                "next_action": post["next_action"],
                "top_blame": post["residual"].get("top_blame", [])[:5],
            }
            log(
                f"  post-ANALYSE gap={post['state']['gap']} R={post['state']['R']} "
                f"dist={post['residual']['distance']} next={post['next_action']}"
            )

        if gained == 0:
            zero_gain += 1
        else:
            zero_gain = 0
        entry["zero_gain_streak"] = zero_gain
        history.append(entry)

        if int(ledger.state(E._closure_ws(OP)).get("gap") or 0) == 0:
            stop_reason = "GAP_ZERO"
            break

        if zero_gain >= STALL_ROUNDS:
            # One more analyse → lemma, then stop
            ad2 = analyse_round(E, E._closure_ws(OP), ctx, round_i=i)
            lem = lemma_path(E, ctx, run_id=f"{run_id}_stall")
            log(
                f"  stall→lemma leads={lem.get('lead_count')} E={lem.get('E')} "
                f"gap={lem.get('gap')} need_subagent={lem.get('mine_need_subagent')}"
            )
            history.append({"round": i, "phase": "stall_lemma", "analysis": ad2, "lemma": lem})
            stop_reason = "NEED_LEMMA" if lem.get("mine_need_subagent") else "SEARCH_STALLED"
            break
    else:
        stop_reason = "MAX_ROUNDS"

    fin_res = E._run_closure_residual(OP, ctx)
    cert = E._run_closure_certify(OP, ctx)
    stf = ledger.state(E._closure_ws(OP))
    report = {
        "stop_reason": stop_reason,
        "elapsed_sec": round(time.time() - t0, 2),
        "final_state": stf,
        "residual_reason": fin_res.get("reason_code"),
        "certify": {
            "ok": cert.get("ok"),
            "error": cert.get("error"),
            "message": cert.get("message") or cert.get("status"),
        },
        "history": history,
        "closed": bool(stf.get("gap") == 0 and stf.get("violation", 1) == 0),
        "skill_stop": (
            "GAP_ZERO complete"
            if stf.get("gap") == 0
            else (
                f"honest stop: {stop_reason} — per-round analysis done; "
                "E requires source-lemma-proof subagent (PROVED), not more construct"
            )
        ),
        "analysis_artifacts": [
            str(OUT / f"round_analysis_{h['round']}.json")
            for h in history
            if isinstance(h.get("round"), int)
        ],
    }
    path = OUT / "skill_iterate_report.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    log(json.dumps({k: report[k] for k in (
        "stop_reason", "final_state", "skill_stop", "elapsed_sec"
    )}, ensure_ascii=False, indent=2, default=str))
    log(f"WROTE {path}")
    return 0 if report["closed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
