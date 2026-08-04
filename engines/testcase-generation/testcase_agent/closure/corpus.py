# -*- coding: utf-8 -*-
"""Every real host verdict, in one frame, one row per distinct input.

Nothing here fits or predicts. It answers only "what did the host say, for
which input", which is the raw material both halves of the closure rest on.

Two things are load-bearing and easy to get wrong:

  the tag repair    `write_wide` used to scrub commas from `reject` alone, and
                    tags like `BSND:d=64,d1=16` are common, so about a sixth of
                    the historical corpus carries one extra field. Dropping
                    those rows biases every count toward whichever search
                    happened to write comma-free tags.
  the dedup         the host is deterministic. Repeats of one input carry no
                    information and would inflate any score computed over rows.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from testcase_agent.closure import workspace as W

#: Columns that are sequence vectors rendered as text. They define the input,
#: so they take part in dedup, but no tree splits on them directly; the
#: summary properties the TND branch actually reads (`all_same`,
#: `seq_has_zero`, ...) are separate columns.
SEQ_COLUMNS = ("seq_q", "seq_kv", "prefix_n")

#: Host intermediates the tiling prints on its own.
STATES = ("isExceedL2Cache", "enableSwizzle", "sparseType")

#: Knob columns that are numeric once parsed. Everything else describe()
#: produces is either categorical text or a sequence.
NUMERIC_KNOBS = (
    "b", "s1", "s2", "n2", "g", "d", "d1", "pse", "pse_type", "rope",
    "sparse_mode", "pre_tokens", "next_tokens", "inner_precise", "out_dtype",
    "deterministic", "all_same", "s1s2_same", "seq_has_zero",
)


def knob_columns() -> list[str]:
    """The knobs a case is built from, taken from the operator's semantics.

    Asking `describe` rather than listing them keeps this working when the
    operator package grows a knob.
    """
    I = W.replay_inputs()
    return list(I.describe(I.Case()).keys())


def _read_repaired(path: Path) -> pd.DataFrame:
    """Read a wide table, re-joining the `tag` column when it split.

    `tag` is the last column before `ok`, and every column after `ok` is fixed
    width, so an overflow can only have come from `tag`.
    """
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return pd.DataFrame()
    head, body = rows[0], rows[1:]
    n = len(head)
    if "tag" not in head:
        return pd.DataFrame([r for r in body if len(r) == n],
                            columns=head, dtype=str)
    i_tag = head.index("tag")
    fixed = []
    for r in body:
        extra = len(r) - n
        if extra > 0:
            r = (r[:i_tag] + [",".join(r[i_tag:i_tag + 1 + extra])]
                 + r[i_tag + 1 + extra:])
        elif extra < 0:
            continue
        fixed.append(r)
    return pd.DataFrame(fixed, columns=head, dtype=str)


def load(ws: W.Workspace | None = None, pattern: str = W.WIDE_GLOB) -> pd.DataFrame:
    """Concatenate every wide table under the workspace's artifacts directory."""
    ws = ws or W.default_workspace()
    files = sorted(Path(ws.artifacts).glob(pattern))
    frames = []
    for f in files:
        df = _read_repaired(f)
        if df.empty:
            continue
        df["_src"] = f.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return coerce(df)


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    """Give the numeric columns numeric dtypes, leaving text alone."""
    if df.empty:
        return df
    df = df.copy()
    df["ok"] = pd.to_numeric(df.get("ok"), errors="coerce").fillna(0).astype(int)
    key = pd.to_numeric(df.get("tiling_key"), errors="coerce").fillna(0)
    df["tiling_key"] = key.astype("int64")
    for name in W.dim_names():
        col = "dim_" + name
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in STATES:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in NUMERIC_KNOBS:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "keep_prob" in df:
        df["keep_prob"] = pd.to_numeric(df["keep_prob"], errors="coerce")
    return df


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    """One row per distinct input."""
    if df.empty:
        return df
    keys = [c for c in knob_columns() if c in df.columns]
    if not keys:
        return df.reset_index(drop=True)
    return df.drop_duplicates(subset=keys, keep="first").reset_index(drop=True)


def accepted(df: pd.DataFrame) -> pd.DataFrame:
    return df[df.ok == 1].reset_index(drop=True) if not df.empty else df


def summary(ws: W.Workspace | None = None) -> dict:
    """Counts a caller can print or gate on, without holding the frame."""
    df = dedup(load(ws))
    if df.empty:
        return {"rows": 0, "inputs": 0, "accepted": 0, "refused": 0, "keys": 0}
    acc = accepted(df)
    return {
        "rows": int(len(df)),
        "inputs": int(len(df)),
        "accepted": int(len(acc)),
        "refused": int((df.ok == 0).sum()),
        "keys": int(acc.tiling_key.nunique()),
    }
