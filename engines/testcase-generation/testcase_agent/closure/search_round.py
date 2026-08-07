# -*- coding: utf-8 -*-
"""One bounded directed-search round (fit → generate → replay → progress).

The workflow state machine drives the outer loop via SEARCH_PROGRESS; this
module never loops forever inside a single action.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from testcase_agent.closure import corpus as C
from testcase_agent.closure import generate as G
from testcase_agent.closure.key_utils import int_exact
from testcase_agent.closure import ledger
from testcase_agent.closure import models as M
from testcase_agent.closure import residual as R
from testcase_agent.closure import workspace as W


def _fp(rows: Any, *extra: str) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(rows, sort_keys=True, default=str).encode("utf-8"))
    for e in extra:
        h.update(e.encode("utf-8"))
    return h.hexdigest()[:16]


def route(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Deterministic residual router reason codes for the tg-solve state machine."""
    ws = (ws or W.default_workspace()).ensure()
    st = ledger.state(ws)
    if st.get("gap", 1) == 0 and st.get("violation", 1) == 0:
        return {"reason": "GAP_ZERO", **st}

    # Oracle suspect flag left by a prior round.
    flag = ws.state / "oracle_suspect"
    if flag.is_file():
        return {"reason": "ORACLE_SUSPECT", **st}

    res = R.analyse(ws)
    open_n = int(st.get("gap") or 0)
    mostly_near = bool(res.get("mostly_distance_1"))

    progress_path = ws.state / "rounds"
    zero_gain = 0
    hist_unchanged = 0
    prev_hist = None
    if progress_path.is_dir():
        rounds = sorted(progress_path.glob("round_*"))
        for rd in rounds[-2:]:
            prog = rd / "progress.yaml"
            if not prog.is_file():
                continue
            try:
                import yaml

                doc = yaml.safe_load(prog.read_text(encoding="utf-8")) or {}
                if int(doc.get("new_R") or 0) == 0:
                    zero_gain += 1
                hist = doc.get("distance_histogram")
                if prev_hist is not None and hist == prev_hist:
                    hist_unchanged += 1
                prev_hist = hist
            except Exception:
                pass

    if zero_gain >= 2 and hist_unchanged >= 1 and not mostly_near:
        return {"reason": "SEARCH_STALLED", "mostly_distance_1": mostly_near, **st}
    if zero_gain >= 2 and mostly_near:
        return {"reason": "CONSTRUCT_TARGETS", "mostly_distance_1": True, **st}
    if zero_gain >= 2:
        return {"reason": "NEED_LEMMA", "mostly_distance_1": mostly_near, **st}
    if open_n > 0:
        return {"reason": "SEARCH_PROGRESS", "mostly_distance_1": mostly_near, **st}
    return {"reason": "PROOF_BLOCKED", **st}


def run_round(
    ws: W.Workspace | None = None,
    *,
    budget: int = 64,
    seed: int = 0,
    oracle: Any | None = None,
    feature_schema_hash: str = "",
    uo_graph_fingerprint: str = "",
    oracle_protocol_version: str = "v1",
) -> dict[str, Any]:
    """Execute one search round including optional live host replay.

    Pass ``oracle=StubOracle(...)`` in CI. When ``oracle`` is None, attempt
    ``HostOracle``; failures are recorded without crashing the round.
    """
    ws = (ws or W.default_workspace()).ensure()
    rounds_dir = ws.state / "rounds"
    rounds_dir.mkdir(parents=True, exist_ok=True)
    idx = len(list(rounds_dir.glob("round_*"))) + 1
    rd = rounds_dir / ("round_%04d" % idx)
    rd.mkdir(parents=True, exist_ok=True)

    try:
        df = C.load(ws)
        df = C.dedup(C.coerce(df)) if df is not None and not df.empty else df
    except Exception:
        df = None

    if df is not None and not df.empty and "reject" in df.columns:
        bad = df["reject"].astype(str).str.startswith(("HOST_CRASHED", "NOT_RUN"))
        judged = df[~bad].reset_index(drop=True)
    else:
        judged = df if df is not None else None

    records = (
        judged.to_dict(orient="records")
        if judged is not None and not judged.empty
        else []
    )
    corpus_fp = _fp(
        records,
        feature_schema_hash or "feat",
        uo_graph_fingerprint or "uo",
        oracle_protocol_version,
    )
    models_dir = ws.state / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = models_dir / "manifest.yaml"
    prev_fp = ""
    if manifest_path.is_file():
        try:
            import yaml

            prev_fp = str(
                (yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}).get(
                    "corpus_fingerprint"
                )
                or ""
            )
        except Exception:
            prev_fp = ""

    refit = corpus_fp != prev_fp or not (models_dir / "assessment.yaml").is_file()
    assessment: list[dict] = []
    surrogate = None
    if judged is not None and not judged.empty:
        try:
            if refit:
                assessment = M.assess(judged)
                import yaml

                (models_dir / "assessment.yaml").write_text(
                    yaml.safe_dump(assessment, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
                try:
                    M.write_parent_gap(judged, ws)
                except Exception:
                    pass
            surrogate = M.fit(judged)
            # Persist a lightweight marker (sklearn models are process-local).
            import yaml

            manifest_path.write_text(
                yaml.safe_dump(
                    {
                        "schema": "tg-surrogate-model/v1",
                        "corpus_fingerprint": corpus_fp,
                        "feature_schema_hash": feature_schema_hash,
                        "uo_graph_fingerprint": uo_graph_fingerprint,
                        "oracle_protocol_version": oracle_protocol_version,
                        "seed": seed,
                        "metrics": {
                            row["dim"]: row for row in assessment if "dim" in row
                        },
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            assessment = [{"error": str(exc)[:200]}]

    open_keys: set[int] = set()
    if ws.open_path.is_file():
        open_keys = {
            int(x)
            for x in ws.open_path.read_text(encoding="utf-8").splitlines()
            if x.strip().isdigit()
        }

    half = max(1, budget // 2)
    witnesses = []
    if judged is not None and not judged.empty:
        try:
            witnesses = G.witnesses_from(judged)
        except Exception:
            witnesses = []

    model_cases: list = []
    try:
        model_cases, model_df = G.kb_guided_pool(
            n=half,
            seed=seed,
            witnesses=witnesses or None,
            open_keys=open_keys,
            surrogate=surrogate,
            control=False,
            ws=ws,
        )
    except Exception:
        model_df = pd.DataFrame()

    model_arm = {
        "candidates": len(model_cases),
        "judged": 0,
        "new_declared_keys": 0,
        "new_undeclared_keys": 0,
    }
    random_arm = {
        "candidates": 0,
        "judged": 0,
        "new_declared_keys": 0,
        "new_undeclared_keys": 0,
    }
    new_r = 0
    oracle_suspect = False

    if oracle is None:
        try:
            from testcase_agent.closure.oracle import HostOracle

            oracle = HostOracle()
        except Exception:
            oracle = None

    r_initial = set(ledger.load_R(ws)) if ws.r_path.is_file() else set()
    try:
        D = set(ledger.declared())
    except Exception:
        D = set()

    def _intish(value: Any, default: int = 0) -> int:
        return int_exact(value, default=default)

    def _arm(name: str, cases: list, arm: dict, r_before: set, frame: pd.DataFrame) -> set:
        nonlocal oracle_suspect
        if not cases or oracle is None:
            return r_before
        try:
            verdicts = oracle.judge(cases, tag=f"r{idx}_{name}")
        except Exception as exc:  # noqa: BLE001
            (rd / f"{name}_error.txt").write_text(str(exc)[:500], encoding="utf-8")
            return r_before
        acct = dict(getattr(oracle, "last_accounting", {}) or {})
        if acct:
            arm["accounting"] = acct
            arm["not_run"] = int(acct.get("not_run") or 0)
            arm["crashed"] = int(acct.get("crashed") or 0)
            arm["parse_failed"] = int(acct.get("parse_failed") or 0)
            if arm["not_run"] or arm["crashed"] or arm["parse_failed"]:
                oracle_suspect = True
                (ws.state / "oracle_suspect").write_text("1", encoding="utf-8")
        if hasattr(oracle, "batch_integrity"):
            flag = oracle.batch_integrity(len(cases), len(verdicts))
            if flag == "ORACLE_SUSPECT":
                oracle_suspect = True
                (ws.state / "oracle_suspect").write_text("1", encoding="utf-8")

        arm_keys: set[int] = set()
        arm_undeclared: set[int] = set()
        rows = []
        for i, v in enumerate(verdicts):
            if not v.verdict:
                continue
            arm["judged"] += 1
            meta = {}
            if frame is not None and not frame.empty and i < len(frame):
                meta = {
                    str(k): frame.iloc[i][k]
                    for k in frame.columns
                    if str(k).startswith("_")
                }
            desc = {}
            try:
                I = W.replay_inputs()
                desc = dict(I.SEMANTICS.describe(cases[i]))
            except Exception:
                pass
            actual_key = _intish(v.key)
            target_key = _intish(meta.get("_target_key"))
            predicted_key = _intish(meta.get("_predicted_key"))
            mismatch = ""
            if v.ok and target_key and actual_key:
                try:
                    want = W.decode(target_key)
                    got = W.decode(actual_key)
                    dims = W.dim_names()
                    mismatch = "|".join(d for d in dims if str(want.get(d)) != str(got.get(d)))
                except Exception:
                    mismatch = ""
            desc.update({
                "ok": int(v.ok),
                "tiling_key": actual_key if v.key is not None else -1,
                "reject": v.reject,
                "_arm": name,
                **meta,
                "_actual_declared": int(bool(v.ok and actual_key and (not D or actual_key in D))),
                "_target_hit": int(bool(v.ok and target_key and actual_key == target_key)),
                "_prediction_hit": int(bool(v.ok and predicted_key and actual_key == predicted_key)),
                "_mismatch_dims": mismatch,
            })
            rows.append(desc)
            if v.ok and v.key is not None:
                try:
                    k = int(v.key)
                except (TypeError, ValueError):
                    continue
                if D and k not in D:
                    arm_undeclared.add(k)
                else:
                    arm_keys.add(k)
        arm["new_declared_keys"] = len(arm_keys - r_before)
        arm["new_undeclared_keys"] = len(arm_undeclared - r_before)
        if arm_undeclared:
            arm["undeclared_keys"] = len(arm_undeclared)
            arm["undeclared_sample"] = sorted(arm_undeclared)[:10]
        if rows:
            C.commit(rows, ws, name=f"round_{idx:04d}_{name}_key_cases.csv")
            try:
                ledger.rebuild(ws)
            except Exception:
                pass
            return set(ledger.load_R(ws)) if ws.r_path.is_file() else r_before
        return r_before

    r_after_model = _arm("model", model_cases, model_arm, r_initial, model_df)
    if D:
        open_after_model = D - (r_after_model & D) - set(ledger.load_E(ws))
    else:
        open_after_model = open_keys
    random_cases: list = []
    try:
        random_cases, random_df = G.kb_guided_pool(
            n=half,
            seed=seed + 1,
            witnesses=witnesses or None,
            open_keys=open_after_model,
            control=True,
            ws=ws,
        )
    except Exception:
        random_df = pd.DataFrame()
    random_arm["candidates"] = len(random_cases)
    r_final = _arm("random", random_cases, random_arm, r_after_model, random_df)
    new_r = len(r_final - r_initial)
    if D:
        new_declared_r = len((r_final & D) - (r_initial & D))
        new_undeclared_r = len((r_final - D) - (r_initial - D))
        undeclared_r = r_final - D
    else:
        new_declared_r = new_r
        new_undeclared_r = 0
        undeclared_r = set()
    domain_suspect = bool(undeclared_r)
    undeclared_path = ""
    if undeclared_r:
        try:
            from testcase_agent.closure import report as closure_report

            undeclared_path = closure_report.write_undeclared(ws, undeclared_r)
        except Exception:
            undeclared_path = ""
    blocker_model = {}
    try:
        df_after = C.dedup(C.coerce(C.load(ws)))
        if hasattr(M, "write_blocker_model"):
            blocker_model = M.write_blocker_model(df_after, ws)
    except Exception as exc:  # noqa: BLE001
        blocker_model = {"ok": False, "error": str(exc)[:200]}

    lift = None
    if random_arm["judged"] and model_arm["judged"]:
        ry = random_arm["new_declared_keys"] / max(1, random_arm["judged"])
        my = model_arm["new_declared_keys"] / max(1, model_arm["judged"])
        lift = round(my / ry, 3) if ry > 0 else None

    progress = {
        "round": idx,
        "corpus_fingerprint": corpus_fp,
        "refit": refit,
        "judged_rows": int(len(records)),
        "open": len(open_keys),
        "model_arm": model_arm,
        "random_arm": random_arm,
        "model_lift": lift,
        "new_R": new_r,
        "new_declared_R": new_declared_r,
        "new_undeclared_R": new_undeclared_r,
        "undeclared_R": len(undeclared_r),
        "undeclared_path": undeclared_path,
        "oracle_suspect": oracle_suspect,
        "domain_suspect": domain_suspect,
        "blocker_model": blocker_model,
        "distance_histogram": (R.analyse(ws) or {}).get("distance"),
    }
    try:
        import yaml

        (rd / "progress.yaml").write_text(
            yaml.safe_dump(progress, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (rd / "targets.yaml").write_text(
            yaml.safe_dump({"open_count": len(open_keys)}, allow_unicode=True),
            encoding="utf-8",
        )
    except Exception:
        (rd / "progress.yaml").write_text(json.dumps(progress), encoding="utf-8")

    return {
        "ok": not oracle_suspect and not domain_suspect,
        "round_dir": str(rd),
        "progress": progress,
        "assessment_dims": len(assessment),
        "route_hint": route(ws).get("reason"),
    }
