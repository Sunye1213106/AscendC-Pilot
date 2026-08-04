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
    random_cases: list = []
    try:
        model_cases, model_df = G.pool(n=half, seed=seed, witnesses=witnesses or None)
    except Exception:
        model_df = pd.DataFrame()
    try:
        random_cases, random_df = G.pool(
            n=half, seed=seed + 1, witnesses=witnesses or None, mutate_share=0.0
        )
    except Exception:
        random_df = pd.DataFrame()

    # Rank / filter model arm by predicted open keys when surrogate exists.
    if surrogate is not None and not model_df.empty and open_keys:
        try:
            accept, keys = surrogate.predict(model_df)
            keep = [i for i, k in enumerate(keys) if int(k) in open_keys and accept[i]]
            if keep:
                model_cases = [model_cases[i] for i in keep if i < len(model_cases)]
                model_df = model_df.iloc[keep].reset_index(drop=True)
        except Exception:
            pass

    model_arm = {"candidates": len(model_cases), "judged": 0, "new_declared_keys": 0}
    random_arm = {"candidates": len(random_cases), "judged": 0, "new_declared_keys": 0}
    new_r = 0
    oracle_suspect = False

    if oracle is None:
        try:
            from testcase_agent.closure.oracle import HostOracle

            oracle = HostOracle()
        except Exception:
            oracle = None

    r_before = set(ledger.load_R(ws)) if ws.r_path.is_file() else set()

    def _arm(name: str, cases: list, arm: dict) -> None:
        nonlocal new_r, oracle_suspect
        if not cases or oracle is None:
            return
        try:
            verdicts = oracle.judge(cases, tag=f"r{idx}_{name}")
        except Exception as exc:  # noqa: BLE001
            (rd / f"{name}_error.txt").write_text(str(exc)[:500], encoding="utf-8")
            return
        if hasattr(oracle, "batch_integrity"):
            flag = oracle.batch_integrity(len(cases), len(verdicts))
            if flag == "ORACLE_SUSPECT":
                oracle_suspect = True
                (ws.state / "oracle_suspect").write_text("1", encoding="utf-8")

        rows = []
        for i, v in enumerate(verdicts):
            if not v.verdict:
                continue
            arm["judged"] += 1
            desc = {}
            try:
                I = W.replay_inputs()
                desc = dict(I.SEMANTICS.describe(cases[i]))
            except Exception:
                pass
            desc.update({
                "ok": int(v.ok),
                "tiling_key": int(v.key),
                "reject": v.reject,
                "_arm": name,
            })
            rows.append(desc)
            if v.ok and v.key and v.key not in r_before:
                arm["new_declared_keys"] += 1
        if rows:
            C.commit(rows, ws, name=f"round_{idx:04d}_{name}.csv")
            try:
                ledger.rebuild(ws)
            except Exception:
                pass
            r_after = ledger.load_R(ws)
            new_r += len(r_after - r_before)

    _arm("model", model_cases, model_arm)
    _arm("random", random_cases, random_arm)

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
        "oracle_suspect": oracle_suspect,
        "distance_histogram": (R.analyse(ws) or {}).get("histogram"),
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
        "ok": not oracle_suspect,
        "round_dir": str(rd),
        "progress": progress,
        "assessment_dims": len(assessment),
        "route_hint": route(ws).get("reason"),
    }
