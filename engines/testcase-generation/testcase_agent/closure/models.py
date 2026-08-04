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

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, train_test_split
from sklearn.tree import DecisionTreeClassifier

from testcase_agent.closure import features as F
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
            "verdict": _verdict(majority, static_acc, all_acc),
        })
    return out


def _verdict(majority: float, static: float, all_knob: float) -> str:
    """What the three numbers say to do next."""
    if all_knob - majority < 0.02:
        return "not_a_function_of_inputs"
    if all_knob - static > 0.05:
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
    named = set(F.static_parents(dim, allf)) if dim in F.STATIC_PARENTS else set()
    ranked = sorted(zip(allf, clf.feature_importances_),
                    key=lambda kv: kv[1], reverse=True)
    return [
        {"feature": name, "importance": round(float(w), 3),
         "static_parent": name in named}
        for name, w in ranked[:top] if w > 0
    ]
