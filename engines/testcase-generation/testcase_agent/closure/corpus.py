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

from testcase_agent.closure.key_utils import int_exact
from testcase_agent.closure import workspace as W

SEQ_COLUMNS = ("seq_q", "seq_kv", "prefix_n")
STATES = ("isExceedL2Cache", "enableSwizzle", "sparseType")
KEY_COLUMNS = ("tiling_key", "_target_key", "_predicted_key")
FLAG_COLUMNS = ("_target_hit", "_prediction_hit", "_predicted_accept")


def _numeric_knobs() -> tuple[str, ...]:
    try:
        I = W.replay_inputs()
        schema = I.SEMANTICS.knob_schema()
        return tuple(
            name for name, meta in schema.items()
            if meta.get("kind") in ("numeric", "bool")
        )
    except (Exception, SystemExit):
        return (
            "b", "s1", "s2", "n2", "g", "d", "d1", "pse", "pse_type", "rope",
            "sparse_mode", "pre_tokens", "next_tokens", "inner_precise", "out_dtype",
            "deterministic", "all_same", "s1s2_same", "seq_has_zero",
        )


NUMERIC_KNOBS = (
    "b", "s1", "s2", "n2", "g", "d", "d1", "pse", "pse_type", "rope",
    "sparse_mode", "pre_tokens", "next_tokens", "inner_precise", "out_dtype",
    "deterministic", "all_same", "s1s2_same", "seq_has_zero",
)


def knob_columns() -> list[str]:
    """The knobs a case is built from, taken from the operator's semantics."""
    I = W.replay_inputs()
    return list(I.describe(I.Case()).keys())


def _read_repaired(path: Path) -> pd.DataFrame:
    """Read a wide table, re-joining the `tag` column when it split."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return pd.DataFrame()
    head, body = rows[0], rows[1:]
    n = len(head)
    if "tag" not in head:
        return pd.DataFrame([r for r in body if len(r) == n], columns=head, dtype=str)
    i_tag = head.index("tag")
    fixed = []
    for row in body:
        extra = len(row) - n
        if extra > 0:
            row = (
                row[:i_tag]
                + [",".join(row[i_tag : i_tag + 1 + extra])]
                + row[i_tag + 1 + extra :]
            )
        elif extra < 0:
            continue
        fixed.append(row)
    return pd.DataFrame(fixed, columns=head, dtype=str)


def load(ws: W.Workspace | None = None, pattern: str = W.WIDE_GLOB) -> pd.DataFrame:
    """Concatenate every wide table under the workspace's artifacts directory."""
    ws = ws or W.default_workspace()
    root = Path(ws.artifacts)
    patterns = (pattern,) if pattern != W.WIDE_GLOB else getattr(W, "CORPUS_GLOBS", (pattern,))
    seen: set[Path] = set()
    files: list[Path] = []
    for pat in patterns:
        for path in sorted(root.glob(pat)):
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

    Generic/key-only corpus normalization must not require locating the real
    operator. Dimension schema discovery is therefore lazy and happens only
    when `dim_*` columns are actually present.
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

    dim_columns = [str(col) for col in df.columns if str(col).startswith("dim_")]
    if dim_columns:
        try:
            known_dims = {"dim_" + name for name in W.dim_names()}
        except (Exception, SystemExit):
            known_dims = set(dim_columns)
        for col in dim_columns:
            if col in known_dims:
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


def accepted(df: pd.DataFrame) -> pd.DataFrame:
    """Rows the host judged as accepted, excluding non-verdicts."""
    if df.empty:
        return df
    if "reject" in df.columns:
        bad = df["reject"].astype(str).str.startswith(("HOST_CRASHED", "NOT_RUN"))
        judged = df[~bad]
    else:
        judged = df
    return judged[judged.ok == 1].reset_index(drop=True)


def commit(
    rows: pd.DataFrame | list[dict],
    ws: W.Workspace | None = None,
    *,
    name: str = "closure_commit.csv",
    reverify: bool = True,
) -> Path:
    """Append judged rows to the workspace corpus (wide table)."""
    ws = (ws or W.default_workspace()).ensure()
    path = Path(ws.artifacts) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if frame.empty:
        return path
    if "reject" in frame.columns:
        bad = frame["reject"].astype(str).str.startswith(("HOST_CRASHED", "NOT_RUN"))
        frame = frame[~bad]
    if frame.empty:
        return path
    header = not path.is_file()
    frame.to_csv(path, mode="a", header=header, index=False)
    if reverify:
        try:
            from testcase_agent.closure import lemma

            lemma.reverify_active(ws)
        except (Exception, SystemExit):
            pass
    return path


def summary(ws: W.Workspace | None = None) -> dict:
    """Counts a caller can print or gate on without retaining the full frame."""
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
