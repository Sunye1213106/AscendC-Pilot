# -*- coding: utf-8 -*-
"""Surrogate models for the key dimensions the derivation could not close.

These exist to *choose candidates*, not to decide anything. A tree here may
say "this input probably lands on that key, try it"; it may never say a key is
unreachable. Exclusion is the rule book's job, and only with a source citation.

`assess` is the honest report on how usable a node's model is. It prints three
numbers per node and the relation between them is the instruction:

  majority ~ static ~ all-knob    the node is not a function of the inputs at
                                  this granularity; stop fitting, go read source
  static << all-knob              the derivation dropped a parent it needed;
                                  the `note` field usually says why
  static ~ all-knob >> majority   the skeleton is right and can be inverted

The split is by input, not by row: the host is deterministic, so scoring on an
input the model trained on measures nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, train_test_split
from sklearn.tree import DecisionTreeClassifier

from testcase_agent.closure import features as F
from testcase_agent.closure.key_utils import int_exact
from testcase_agent.closure import workspace as W

#: Below this many labelled rows a tree is not fitted; the majority value is
#: used instead, which is honest about knowing nothing.
MIN_ROWS = 50

#: Marker for the model that predicts whether the host accepts an input at all.
#: Without it a directed search spends most of its budget on refusals.
ACCEPT = "__accept__"


@dataclass
class Surrogate:
    """One model per key dimension, plus one for host acceptance."""

    features: list[str]
    models: dict[str, object] = field(default_factory=dict)

    def predict_dim(self, X: np.ndarray, dim: str) -> np.ndarray:
        m = self.models.get(dim)
        if m is None:
            return np.zeros(len(X), dtype=int)
        if isinstance(m, (int, np.integer)):
            return np.full(len(X), int(m), dtype=int)
        return m.predict(X)

    def predict(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Predicted acceptance and predicted packed key, per candidate row."""
        X = F.build(frame)[self.features].values
        accept = self.predict_dim(X, ACCEPT)
        dims = W.dim_names()
        cols = {d: self.predict_dim(X, d) for d in dims}
        keys = np.zeros(len(frame), dtype=np.int64)
        for i in range(len(frame)):
            inst = {d: str(int(cols[d][i])) for d in dims}
            try:
                keys[i] = W.encode(inst)
            except (ValueError, KeyError):
                # A predicted combination the schema cannot pack is not a
                # target; leaving it 0 drops it from the model arm.
                keys[i] = 0
        return accept, keys


def fit(df: pd.DataFrame) -> Surrogate:
    """Fit acceptance over all rows and each dimension over accepted rows."""
    X = F.build(df)
    feats = list(X.columns)
    models: dict[str, object] = {}

    y_ok = df["ok"].astype(int).values
    if len(np.unique(y_ok)) < 2:
        models[ACCEPT] = int(y_ok[0]) if len(y_ok) else 1
    else:
        clf = DecisionTreeClassifier(random_state=0, min_samples_leaf=2)
        clf.fit(X[feats].values, y_ok)
        models[ACCEPT] = clf

    acc = df[df.ok == 1]
    Xa = F.build(acc)
    for dim in W.dim_names():
        col = "dim_" + dim
        if col not in acc:
            models[dim] = 0
            continue
        y = acc[col].fillna(-1).astype(int).values
        keep = y >= 0
        if keep.sum() < MIN_ROWS or len(np.unique(y[keep])) < 2:
            models[dim] = (int(np.bincount(np.maximum(y, 0)).argmax())
                           if len(y) else 0)
            continue
        clf = DecisionTreeClassifier(random_state=0, min_samples_leaf=2)
        clf.fit(Xa[feats].values[keep], y[keep])
        models[dim] = clf
    return Surrogate(features=feats, models=models)


def _score(X: pd.DataFrame, y: np.ndarray, feats: list[str], seed: int = 0
           ) -> tuple[float, int]:
    if len(np.unique(y)) < 2:
        return 1.0, 0
    Xtr, Xte, ytr, yte = train_test_split(
        X[feats].values, y, test_size=0.3, random_state=seed, stratify=y)
    clf = DecisionTreeClassifier(random_state=seed, min_samples_leaf=3)
    clf.fit(Xtr, ytr)
    return float(clf.score(Xte, yte)), int(clf.get_n_leaves())


def assess(df: pd.DataFrame, dims: list[str] | None = None,
           group_by: str = "layout") -> list[dict]:
    """Per-node: the majority floor, static parents, all knobs, extrapolation.

    `group_by` holds out one value of a knob at a time (train on four layouts,
    predict the fifth). A model that only interpolates scores well on a random
    split and poorly here; one that learned the rule scores well on both.
    """
    acc = df[df.ok == 1].reset_index(drop=True)
    if acc.empty:
        return []
    X = F.build(acc)
    allf = list(X.columns)
    out = []
    groups = acc[group_by].values if group_by in acc else None

    for dim in (dims or W.dim_names()):
        col = "dim_" + dim
        if col not in acc:
            continue
        y = acc[col].fillna(-1).astype(int).values
        if len(y) == 0:
            continue
        shifted = y - y.min()
        majority = float(np.bincount(shifted).max()) / len(y)
        parent_status = F.static_parent_status(dim)
        static_acc, _ = _score(X, y, F.static_parents(dim, allf))
        all_acc, leaves = _score(X, y, allf)

        extrapolated = None
        if groups is not None and len(np.unique(y)) >= 2:
            uniq = np.unique(groups)
            if len(uniq) >= 2:
                scores = []
                gkf = GroupKFold(n_splits=len(uniq))
                for tr, te in gkf.split(X, y, groups):
                    if len(np.unique(y[tr])) < 2:
                        continue
                    clf = DecisionTreeClassifier(random_state=0,
                                                 min_samples_leaf=3)
                    clf.fit(X.iloc[tr][allf].values, y[tr])
                    scores.append(clf.score(X.iloc[te][allf].values, y[te]))
                if scores:
                    extrapolated = float(np.mean(scores))

        out.append({
            "dim": dim,
            "values": int(len(np.unique(y))),
            "majority": round(majority, 3),
            "static": round(static_acc, 3),
            "all_knob": round(all_acc, 3),
            "extrapolated": (round(extrapolated, 3)
                             if extrapolated is not None else None),
            "leaves": leaves,
            "static_parent_status": parent_status,
            "verdict": _verdict(
                majority, static_acc, all_acc, parent_status=parent_status
            ),
        })
    return out


def _verdict(
    majority: float,
    static: float,
    all_knob: float,
    *,
    parent_status: str = "present",
) -> str:
    """What the three numbers say to do next."""
    if all_knob - majority < 0.02:
        return "not_a_function_of_inputs"
    if parent_status == "missing" and all_knob - majority > 0.05:
        return "kb_parent_spec_missing"
    if parent_status != "missing" and all_knob - static > 0.05:
        return "static_parents_incomplete"
    return "skeleton_usable"


def importances(df: pd.DataFrame, dim: str, top: int = 8) -> list[dict]:
    """Which features the tree actually split on, against the static parents.

    A feature the tree leans on that the derivation never named is a missed
    dependency; a static parent the tree never touches is over-approximation.
    Both are leads for the static side, never conclusions on their own.
    """
    acc = df[df.ok == 1].reset_index(drop=True)
    col = "dim_" + dim
    if acc.empty or col not in acc:
        return []
    X = F.build(acc)
    allf = list(X.columns)
    y = acc[col].fillna(-1).astype(int).values
    if len(np.unique(y)) < 2:
        return []
    clf = DecisionTreeClassifier(random_state=0, min_samples_leaf=3)
    clf.fit(X[allf].values, y)
    named = set(F.static_parents(dim, allf)) if F.has_static_parents(dim) else set()
    ranked = sorted(zip(allf, clf.feature_importances_),
                    key=lambda kv: kv[1], reverse=True)
    return [
        {"feature": name, "importance": round(float(w), 3),
         "static_parent": name in named}
        for name, w in ranked[:top] if w > 0
    ]


def write_parent_gap(df, ws=None, *, top: int = 8) -> dict:
    """Emit observation-only UO parent-gap candidates from MISSED features.

    TG must not mutate the KB; uo-update consumes this file and verifies
    against source before any derivation change.
    """
    from pathlib import Path

    import yaml

    from testcase_agent.closure import workspace as W

    ws = (ws or W.default_workspace()).ensure()
    # Prefer tg/feedback under artifact root when available.
    feedback = Path(ws.root) / "feedback" if hasattr(ws, "root") else ws.state / "feedback"
    # Workspace.state is tg/closure/...; climb to tg/ when possible.
    try:
        tg_root = Path(ws.state).parents[0]  # .../tg/closure → .../tg  OR state parent
        # Prefer dedicated tg/feedback; fall back beside state.
        if (Path(ws.state).name == "closure") or "closure" in str(ws.state):
            candidate = Path(ws.state)
            for _ in range(3):
                if candidate.name == "tg" or (candidate / "closure").is_dir():
                    break
                candidate = candidate.parent
            feedback = candidate / "feedback"
    except Exception:
        feedback = ws.state / "feedback"
    feedback.mkdir(parents=True, exist_ok=True)

    missed: list[dict] = []
    try:
        assessment = assess(df) if df is not None and not getattr(df, "empty", True) else []
    except Exception:
        assessment = []
    for row in assessment:
        dim = str(row.get("dim") or "")
        verdict = str(row.get("verdict") or "")
        if verdict not in ("static_parents_incomplete", "kb_parent_spec_missing") or not dim:
            continue
        try:
            ranks = importances(df, dim, top=top)
        except Exception:
            ranks = []
        for item in ranks:
            if item.get("static_parent"):
                continue
            if float(item.get("importance") or 0) <= 0:
                continue
            missed.append({
                "dim": dim,
                "feature": item["feature"],
                "importance": item["importance"],
                "status": "observation_only",
                "note": "sklearn MISSED vs STATIC_PARENTS — verify in source via uo-update",
            })
    path = feedback / "uo_parent_gap_candidates.yaml"
    doc = {
        "schema": "tg-uo-parent-gap/v1",
        "status": "observation_only",
        "candidates": missed,
    }
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return {"ok": True, "path": str(path), "count": len(missed)}


def _feedback_dir(ws=None) -> Path:
    ws = (ws or W.default_workspace()).ensure()
    try:
        candidate = Path(ws.state)
        for _ in range(4):
            if candidate.name == "tg":
                return candidate / "feedback"
            candidate = candidate.parent
    except Exception:
        pass
    return Path(ws.state) / "feedback"


def _uo_root(ws=None) -> Path:
    ws = (ws or W.default_workspace()).ensure()
    try:
        return Path(ws.state).parent.parent / "uo"
    except Exception:
        import os

        arch = None
        for _name in ("UO_ARCH", "ASCENDC_ARCH"):
            _raw = (os.environ.get(_name) or "").strip()
            if _raw:
                arch = _raw
                break
        if not arch:
            raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE: architecture required")
        return Path(ws.root) / ".ascendc-pilot" / arch / "uo"


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_static_blockers(ws=None) -> list[dict]:
    doc = _load_yaml(_uo_root(ws) / "ir" / "unresolved.yaml")
    rows = doc.get("blockers") or []
    return [r for r in rows if isinstance(r, dict)]


_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tokens(obj: object) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN.finditer(str(obj or ""))}


def _dim_aliases(features: list[str]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for dim in W.dim_names():
        items = {dim.lower(), ("dim_" + dim).lower()}
        try:
            items |= {
                str(x).lower()
                for x in F.static_parents(dim, features)
                if len(str(x)) >= 3
            }
        except Exception:
            pass
        aliases[dim] = items
    return aliases


def _target_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "_target_key" not in df:
        return pd.DataFrame()
    out = df.copy()
    out["_target_key_num"] = out["_target_key"].map(int_exact).astype(object)
    out = out[out["_target_key_num"] > 0].reset_index(drop=True)
    return out


def _intish(value: object, default: int = 0) -> int:
    return int_exact(value, default=default)


def _mismatch_report(rows: pd.DataFrame) -> dict[str, dict]:
    dims = W.dim_names()
    report = {
        d: {"targeted": 0, "hits": 0, "misses": 0, "refused": 0}
        for d in dims
    }
    for _, row in rows.iterrows():
        tkey = _intish(row.get("_target_key_num"))
        if not tkey:
            continue
        try:
            want = W.decode(tkey)
        except Exception:
            continue
        ok = _intish(row.get("ok")) == 1
        actual_key = _intish(row.get("tiling_key"))
        got = {}
        if ok and actual_key:
            try:
                got = W.decode(actual_key)
            except Exception:
                got = {}
        hinted = {
            x for x in str(row.get("_target_differing_dims") or "").split("|") if x
        }
        for dim in dims:
            if hinted and dim not in hinted:
                continue
            report[dim]["targeted"] += 1
            if not ok or not got:
                report[dim]["refused"] += 1
                report[dim]["misses"] += 1
            elif str(want.get(dim)) == str(got.get(dim)):
                report[dim]["hits"] += 1
            else:
                report[dim]["misses"] += 1
    for row in report.values():
        denom = max(1, int(row["targeted"]))
        row["hit_rate"] = round(float(row["hits"]) / denom, 3)
    return report


def _dim_tree_leads(rows: pd.DataFrame, dim: str, *, top: int = 6) -> dict:
    if rows.empty:
        return {}
    y_vals = []
    keep_index = []
    for i, row in rows.iterrows():
        tkey = _intish(row.get("_target_key_num"))
        actual = _intish(row.get("tiling_key"))
        if not tkey or not actual or _intish(row.get("ok")) != 1:
            continue
        try:
            want = W.decode(tkey)
            got = W.decode(actual)
        except Exception:
            continue
        y_vals.append(int(str(want.get(dim)) == str(got.get(dim))))
        keep_index.append(i)
    if len(y_vals) < MIN_ROWS or len(set(y_vals)) < 2:
        return {"status": "insufficient_labels", "rows": len(y_vals)}
    sub = rows.loc[keep_index].reset_index(drop=True)
    try:
        X = F.build(sub)
    except Exception as exc:  # noqa: BLE001
        return {"status": "feature_build_failed", "error": str(exc)[:120]}
    feats = list(X.columns)
    y = np.array(y_vals, dtype=int)
    try:
        score, leaves = _score(X, y, feats)
        clf = DecisionTreeClassifier(random_state=0, min_samples_leaf=3)
        clf.fit(X[feats].values, y)
        ranked = sorted(
            zip(feats, clf.feature_importances_),
            key=lambda kv: kv[1],
            reverse=True,
        )
        return {
            "status": "fit",
            "score": round(score, 3),
            "leaves": leaves,
            "top_features": [
                {"feature": name, "importance": round(float(weight), 3)}
                for name, weight in ranked[:top]
                if weight > 0
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "fit_failed", "error": str(exc)[:120]}


def write_blocker_model(df: pd.DataFrame, ws=None, *, top: int = 20) -> dict:
    """Rank static blockers from Host replay successes/failures.

    This is an observation-only sklearn report. It does not exclude keys and
    does not update the UO KB; source proof still owns those actions.
    """
    ws = (ws or W.default_workspace()).ensure()
    feedback = _feedback_dir(ws)
    feedback.mkdir(parents=True, exist_ok=True)
    path = feedback / "blocker_model_report.yaml"
    rows = _target_rows(df)
    blockers = _load_static_blockers(ws)
    try:
        features = list(F.build(rows if not rows.empty else df).columns)
    except Exception:
        features = []
    dim_report = _mismatch_report(rows) if not rows.empty else {}
    tree_report = {
        dim: _dim_tree_leads(rows, dim)
        for dim, stats in dim_report.items()
        if int(stats.get("targeted") or 0) > 0
    }
    aliases = _dim_aliases(features)
    ranked_blockers: list[dict] = []
    for blocker in blockers:
        text = " ".join(str(blocker.get(k) or "") for k in (
            "id", "reason", "reason_code", "text", "snippet", "readable_vars",
            "affected_nodes", "evidence",
        ))
        toks = _tokens(text)
        linked = [
            dim for dim, names in aliases.items()
            if toks & {n.lower() for n in names}
        ]
        score = sum(int(dim_report.get(dim, {}).get("misses") or 0) for dim in linked)
        score += min(10, len(blocker.get("affected_nodes") or []))
        ranked_blockers.append({
            "blocker_id": str(blocker.get("id") or blocker.get("blocker_id") or ""),
            "reason_code": str(blocker.get("reason_code") or ""),
            "linked_dims": linked,
            "score": int(score),
            "affected_nodes": len(blocker.get("affected_nodes") or []),
            "status": "observation_only",
        })
    ranked_blockers.sort(key=lambda r: (r["score"], r["affected_nodes"]), reverse=True)
    doc = {
        "schema": "tg-blocker-sklearn-report/v1",
        "status": "observation_only",
        "input": {
            "rows": int(len(df)) if df is not None else 0,
            "targeted_rows": int(len(rows)),
            "static_blockers": len(blockers),
        },
        "dim_report": dim_report,
        "tree_report": tree_report,
        "ranked_blockers": ranked_blockers[:top],
        "note": (
            "Models rank replay blockers only. They are not proof and must not "
            "write E or mutate UO derivations without source review."
        ),
    }
    try:
        import yaml

        path.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except Exception:
        path.write_text(str(doc), encoding="utf-8")
    return {
        "ok": True,
        "path": str(path),
        "targeted_rows": int(len(rows)),
        "ranked_blockers": len(ranked_blockers[:top]),
    }
