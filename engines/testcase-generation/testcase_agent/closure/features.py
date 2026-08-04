# -*- coding: utf-8 -*-
"""Turn a wide replay table into features a tree can split on.

A decision tree splits on one axis at a time, so it cannot synthesise
`b * n1 * s1 * s2 * dtype_bytes` however much data it is given. The host
branches on exactly such products, so they have to be supplied.

Which products? The ones the source compares against. Guessing wastes columns
and invites the tree to fit noise, so `DERIVED_TERMS` is keyed by the name a
comparison carries in the codemap (`predicates[].feature_hint`). That lets the
set be checked against what the source actually tests rather than against
someone's memory of it -- see `coverage_of`.

Two feature sets are built from the same rows. `static_parents` restricts a
node to the inputs the derivation says it reads; the full set gives every knob.
The gap between the two scores answers "did the static skeleton keep the right
parents" as a number instead of by reading an expression.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from testcase_agent.closure import workspace as W

#: Categorical knobs, encoded as one integer per level. A tree splits on that
#: as well as on a one-hot and keeps an exported tree readable.
CATEGORICAL = ("layout", "dtype", "atten_mask", "pse_shape")

BASE_NUMERIC = (
    "b", "s1", "s2", "n2", "g", "d", "d1", "pse", "pse_type", "rope",
    "sparse_mode", "pre_tokens", "next_tokens", "out_dtype", "deterministic",
    "all_same", "s1s2_same", "seq_has_zero",
)


@dataclass
class Ctx:
    """What a derived term may read.

    `raw` is kept alongside `feat` because two of the terms are cleaner as
    tests on the original text: an unrecognised mask name is not "no mask", and
    encoding it to -1 first would say it was.
    """

    feat: pd.DataFrame
    raw: pd.DataFrame

    def __getitem__(self, name: str) -> pd.Series:
        return self.feat[name]

    def text(self, column: str, default: str = "") -> pd.Series:
        if column not in self.raw:
            return pd.Series(default, index=self.feat.index)
        return self.raw[column].astype(str)


#: Quantities the host computes before it branches. Every one is a function of
#: the knobs, so none is new information -- they exist because the comparison
#: is not axis-aligned in the raw knobs.
DERIVED_TERMS: dict[str, Callable[[Ctx], pd.Series]] = {
    "n1": lambda c: c["n2"] * c["g"],
    "dtype_bytes": lambda c: pd.Series(
        np.where(c.text("dtype") == "FLOAT", 4, 2), index=c.feat.index),
    "dtype_is_fp32": lambda c: (c.text("dtype") == "FLOAT").astype(int),
    "is_tnd": lambda c: (c.text("layout") == "TND").astype(int),
    "has_mask": lambda c: (c.text("atten_mask", "none") != "none").astype(int),
    "has_drop": lambda c: (c["keep_prob"] < 1.0).astype(int),
    "d_ne_d1": lambda c: (c["d"] != c["d1"]).astype(int),
    "bn1s1": lambda c: c["b"] * c["n1"] * c["s1"],
    "bn2s2": lambda c: c["b"] * c["n2"] * c["s2"],
    "bn1s1s2": lambda c: c["bn1s1"] * c["s2"],
    "qkv_bytes": lambda c: (
        c["bn1s1"] * c["d"] + 2 * c["bn2s2"] * c["d"]) * c["bytes"],
    "s1_mod128": lambda c: c["s1"] % 128,
    "s2_mod128": lambda c: c["s2"] % 128,
    "s1_div64": lambda c: c["s1"] // 64,
    "d_le64": lambda c: (c["d"] <= 64).astype(int),
    "s1_eq_s2": lambda c: (c["s1"] == c["s2"]).astype(int),
    "band": lambda c: ((c["pre_tokens"] < c["s1"]).astype(int)
                       + (c["next_tokens"] < c["s2"]).astype(int)),
}

#: Evaluation order: `bn1s1s2` reads `bn1s1`, `qkv_bytes` reads `bytes`.
_TERM_ORDER = (
    "n1", "dtype_bytes", "dtype_is_fp32", "is_tnd", "has_mask", "has_drop",
    "d_ne_d1", "bn1s1", "bn2s2", "bn1s1s2", "qkv_bytes", "s1_mod128",
    "s2_mod128", "s1_div64", "d_le64", "s1_eq_s2", "band",
)

#: Column name for a term whose hint reads differently. `bytes` predates the
#: hint vocabulary and the static parent table below already speaks it.
_ALIAS = {"dtype_bytes": "bytes"}


def _levels() -> Mapping[str, tuple]:
    """Level order for each categorical knob, from the operator's semantics."""
    enums = W.replay_inputs().SEMANTICS.enums()
    return {name: tuple(enums[name]) for name in CATEGORICAL if name in enums}


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric feature frame aligned to `df`'s index."""
    levels = _levels()
    f = pd.DataFrame(index=df.index)

    for name in CATEGORICAL:
        codes = {v: i for i, v in enumerate(levels.get(name, ()))}
        f[name] = df[name].map(codes).fillna(-1) if name in df else -1

    for col in BASE_NUMERIC:
        f[col] = (pd.to_numeric(df[col], errors="coerce").fillna(-1)
                  if col in df else -1)
    f["keep_prob"] = (pd.to_numeric(df["keep_prob"], errors="coerce").fillna(1.0)
                      if "keep_prob" in df else 1.0)

    ctx = Ctx(feat=f, raw=df)
    for hint in _TERM_ORDER:
        f[_ALIAS.get(hint, hint)] = DERIVED_TERMS[hint](ctx)
    return f


def column_of(hint: str) -> str:
    """The frame column a codemap `feature_hint` lands in."""
    return _ALIAS.get(hint, hint)


def coverage_of(hints) -> dict[str, list[str]]:
    """Which comparison terms the source names are, and are not, built here.

    P3 feeds this the `feature_hint` values the codemap exported. A term the
    source compares but nothing builds is a blind spot: the tree has to
    approximate it with thresholds on the raw knobs.
    """
    want = {str(h) for h in hints if h}
    have = set(DERIVED_TERMS)
    return {
        "built": sorted(want & have),
        "missing": sorted(want - have),
        "unused": sorted(have - want),
    }


def hints_from_codemap(uo_root: str | None = None) -> list[str]:
    """Collect `feature_hint` values from the durable codemap predicates."""
    from pathlib import Path

    root = Path(uo_root) if uo_root else (
        Path(__file__).resolve().parents[4] / ".ascendc-pilot" / "uo")
    try:
        from uo_init.host_codemap import CodemapQuery
        q = CodemapQuery(root)
        return sorted({
            p["feature_hint"] for p in q.predicates() if p.get("feature_hint")
        })
    except Exception:
        return []


def coverage_from_codemap(uo_root: str | None = None) -> dict[str, list[str]]:
    """Run `coverage_of` against whatever the live codemap exported."""
    hints = hints_from_codemap(uo_root)
    # Always include the four known-critical terms as a floor: the regex
    # projection may miss a hint the source still needs.
    floor = ["bn1s1s2", "qkv_bytes", "s1_mod128", "band"]
    return coverage_of(list(set(hints) | set(floor)))


#: Which knob features each node's derivation actually reads, translated from
#: the codemap's per-field `reads` into the columns above. A node absent here
#: is scored on the full set only.
STATIC_PARENTS: dict[str, list[str]] = {
    "SplitAxis": [
        "layout", "dtype", "n1", "n2", "g", "b", "s1", "s2", "d", "d1",
        "sparse_mode", "pre_tokens", "next_tokens", "deterministic",
        "has_mask", "has_drop", "rope", "all_same", "s1s2_same",
        "seq_has_zero", "is_tnd",
    ],
    # The derivation collapsed this one to a single root. That is the claim
    # under test, so the feature set is exactly what it says -- and the gap to
    # the full set is how the missing parents were found.
    "DeterType": ["deterministic"],
    "IsBn2MultiBlk": [
        "layout", "dtype", "n1", "n2", "g", "b", "s1", "s2", "d", "d1",
        "sparse_mode", "pre_tokens", "next_tokens",
        "has_mask", "has_drop", "rope", "all_same", "s1s2_same",
        "seq_has_zero", "is_tnd",
    ],
    "IsNzOut": [
        "layout", "dtype", "n1", "n2", "b", "s1", "s2", "d", "d1",
        "sparse_mode", "deterministic", "rope", "is_tnd",
    ],
    "IsTndSwizzle": [
        "layout", "dtype", "n1", "n2", "g", "b", "s1", "s2", "d", "d1",
        "sparse_mode", "pre_tokens", "next_tokens", "deterministic",
        "has_mask", "has_drop", "rope", "all_same", "s1s2_same",
        "seq_has_zero", "is_tnd",
    ],
    "IsTnd": ["layout", "is_tnd", "all_same", "s1s2_same", "seq_has_zero", "b"],
}


def static_parents(dim: str, available: list[str]) -> list[str]:
    """Parent columns for `dim`, filtered to those the frame actually has."""
    named = STATIC_PARENTS.get(dim)
    if not named:
        return list(available)
    return [c for c in named if c in available]
