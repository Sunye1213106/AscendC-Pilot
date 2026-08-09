# -*- coding: utf-8 -*-
"""Corpus loading, normalization and deduplication for closure search."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from testcase_agent.closure import workspace as W
from testcase_agent.closure.key_utils import int_exact

KEY_COLUMNS = ("tiling_key", "_target_key", "_predicted_key")
FLAG_COLUMNS = ("ok", "is_tnd", "is_sparse", "is_deterministic")
STATES = ("status", "selected", "covered")


def _numeric_knobs() -> list[str]:
    return [
        "b", "n1", "n2", "s1", "s2", "d", "d1", "d2", "g",
        "pre_tokens", "next_tokens", "sparse_mode", "seed", "offset",
    ]


def knob_columns() -> list[str]:
    cols = ["layout", "dtype", "pse_type", "atten_mask_type"]
    cols.extend(_numeric_knobs())
    try:
        cols.extend("dim_" + name for name in W.dim_names())
    except (SystemExit, FileNotFoundError):
        # Generic dataframe operations must remain usable without a local CANN
        # checkout. Dimension-aware closure search resolves the schema later.
        pass
    return cols


def _read_repaired(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype={name: "string" for name in KEY_COLUMNS})
    except Exception:
        return pd.read_csv(path)


def load(files: Iterable[Path]) -> pd.DataFrame:
    frames = []
    for path in files:
        frame = _read_repaired(Path(path))
        if frame.empty:
            continue
        frame["_src"] = Path(path).name
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return coerce(pd.concat(frames, ignore_index=True))


def discover(root: Path) -> pd.DataFrame:
    root = Path(root)
    patterns = ("*.csv", "**/cases*.csv", "**/corpus*.csv", "**/closure*.csv")
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    frames = []
    for path in files:
        frame = _read_repaired(path)
        if frame.empty:
            continue
        frame["_src"] = path.name
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return coerce(pd.concat(frames, ignore_index=True))


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    """Give known numeric columns numeric dtypes while preserving exact keys.

    Schema discovery is lazy: a key-only or generic corpus must not require a
    local CANN/operator checkout merely to normalize scalar columns.
    """
    if df.empty:
        return df
    df = df.copy()
    df["ok"] = pd.to_numeric(df.get("ok"), errors="coerce").fillna(0).astype(int)
    for col in KEY_COLUMNS:
        if col in df:
            df[col] = df[col].map(int_exact).astype(object)
    for col in FLAG_COLUMNS:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    dim_columns = [col for col in df.columns if str(col).startswith("dim_")]
    if dim_columns:
        try:
            declared = {"dim_" + name for name in W.dim_names()}
        except (SystemExit, FileNotFoundError):
            declared = set(dim_columns)
        for col in dim_columns:
            if col in declared:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in STATES:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in _numeric_knobs():
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "keep_prob" in df:
        df["keep_prob"] = pd.to_numeric(df["keep_prob"], errors="coerce")
    return df


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    """One row per distinct input."""
    if df.empty:
        return df
    keys = [col for col in knob_columns() if col in df.columns]
    if not keys:
        return df.reset_index(drop=True)
    return df.drop_duplicates(subset=keys, keep="first").reset_index(drop=True)
