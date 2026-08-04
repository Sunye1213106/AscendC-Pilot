# -*- coding: utf-8 -*-
"""Turn a wide replay table into features a tree can split on.

A decision tree splits on one axis at a time, so products the host compares
must be supplied. Which products come from ``feature_bindings.yaml`` (and
codemap ``feature_hint`` values), never from an engine-side FAG table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from testcase_agent.closure import workspace as W


@dataclass
class Ctx:
    feat: pd.DataFrame
    raw: pd.DataFrame

    def __getitem__(self, name: str) -> pd.Series:
        return self.feat[name]

    def text(self, column: str, default: str = "") -> pd.Series:
        if column not in self.raw:
            return pd.Series(default, index=self.feat.index)
        return self.raw[column].astype(str)


def _feature_bindings() -> dict:
    from replay.package_data import load_yaml

    doc = load_yaml("feature_bindings.yaml")
    if not doc:
        raise FileNotFoundError(
            "operators/<op>/<arch>/feature_bindings.yaml is required "
            "(no engine-side FAG fallback)"
        )
    return doc


def _categorical() -> tuple[str, ...]:
    return tuple(_feature_bindings().get("categorical") or ())


def _base_numeric() -> tuple[str, ...]:
    return tuple(_feature_bindings().get("base_numeric") or ())


def _builtin_specials() -> dict[str, Callable[[Ctx], pd.Series]]:
    return {
        "dtype_bytes": lambda c: pd.Series(
            np.where(c.text("dtype") == "FLOAT", 4, 2), index=c.feat.index),
        "dtype_is_fp32": lambda c: (c.text("dtype") == "FLOAT").astype(int),
        "is_tnd": lambda c: (c.text("layout") == "TND").astype(int),
        "has_mask": lambda c: (c.text("atten_mask", "none") != "none").astype(int),
        "has_drop": lambda c: (c["keep_prob"] < 1.0).astype(int),
        "band": lambda c: (
            (c["pre_tokens"] < c["s1"]).astype(int)
            + (c["next_tokens"] < c["s2"]).astype(int)
        ),
        "qkv_bytes": lambda c: (
            c["bn1s1"] * c["d"] + 2 * c["bn2s2"] * c["d"]
        ) * c["bytes"],
    }


_ALIAS = {"dtype_bytes": "bytes"}


def _levels() -> Mapping[str, tuple]:
    enums = W.replay_inputs().SEMANTICS.enums()
    return {name: tuple(enums[name]) for name in _categorical() if name in enums}


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric feature frame aligned to `df`'s index."""
    bindings = _feature_bindings()
    levels = _levels()
    f = pd.DataFrame(index=df.index)

    for name in _categorical():
        codes = {v: i for i, v in enumerate(levels.get(name, ()))}
        f[name] = df[name].map(codes).fillna(-1) if name in df else -1

    for col in _base_numeric():
        f[col] = (pd.to_numeric(df[col], errors="coerce").fillna(-1)
                  if col in df else -1)
    if "keep_prob" in df:
        f["keep_prob"] = pd.to_numeric(df["keep_prob"], errors="coerce").fillna(1.0)
    elif "keep_prob" not in f.columns:
        f["keep_prob"] = 1.0

    ctx = Ctx(feat=f, raw=df)
    specials = _builtin_specials()
    derived = dict(bindings.get("derived_terms") or {})

    # Order: evaluate null-specials and eval expressions; resolve dependencies
    # by repeating until fixed point (small set).
    pending = list(derived.keys()) + [
        k for k in ("dtype_bytes", "band", "qkv_bytes") if k not in derived
    ]
    guard = 0
    while pending and guard < 32:
        guard += 1
        name = pending.pop(0)
        col = _ALIAS.get(name, name)
        if col in f.columns:
            continue
        expr = derived.get(name, None)
        try:
            if name in specials and expr is None:
                f[col] = specials[name](ctx)
            elif expr is None and name in specials:
                f[col] = specials[name](ctx)
            elif isinstance(expr, str) and expr.strip():
                f[col] = f.eval(expr)
            elif name in specials:
                f[col] = specials[name](ctx)
            else:
                continue
            ctx.feat = f
        except Exception:
            pending.append(name)
    return f


def column_of(hint: str) -> str:
    return _ALIAS.get(hint, hint)


def coverage_of(hints) -> dict[str, list[str]]:
    want = {str(h) for h in hints if h}
    have = set((_feature_bindings().get("derived_terms") or {})) | set(_builtin_specials())
    return {
        "built": sorted(want & have),
        "missing": sorted(want - have),
        "unused": sorted(have - want),
    }


def hints_from_codemap(uo_root: str | None = None) -> list[str]:
    from pathlib import Path

    if uo_root is None:
        raise ValueError("uo_root is required (pass the operator's .ascendc-pilot/<arch>/uo)")
    root = Path(uo_root)
    try:
        from uo_init.host_codemap import CodemapQuery
        q = CodemapQuery(root)
        return sorted({
            p["feature_hint"] for p in q.predicates() if p.get("feature_hint")
        })
    except Exception:
        return []


def coverage_from_codemap(uo_root: str | None = None) -> dict[str, list[str]]:
    hints = hints_from_codemap(uo_root)
    floor = list(_feature_bindings().get("floor_terms") or [])
    return coverage_of(list(set(hints) | set(floor)))


def _static_parents_table() -> dict[str, list[str]]:
    raw = _feature_bindings().get("static_parents") or {}
    if not raw:
        raise ValueError("feature_bindings.yaml missing static_parents")
    return {str(k): [str(x) for x in (v or [])] for k, v in raw.items()}


def static_parents(dim: str, available: list[str]) -> list[str]:
    """Parent columns for `dim`, filtered to those the frame actually has."""
    named = _static_parents_table().get(dim)
    if not named:
        return list(available)
    return [c for c in named if c in available]


def has_static_parents(dim: str) -> bool:
    return dim in _static_parents_table()
