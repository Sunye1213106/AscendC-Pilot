# -*- coding: utf-8 -*-
"""Candidate generation for directed search.

Uniform sampling of the knob space is mostly refused -- shape, mask, sparse
and sequence have to agree, and independent draws rarely do. Starting from a
witness the host already accepted and turning one to three knobs keeps most
of that agreement. Both sources are kept: mutation for yield, fresh sampling
for exploration.

The model arm of a directed search asks this module for a pool, then keeps
only candidates whose predicted key is still open. The random arm draws from
the same pool. That is how the 11x yield of model-over-random was measured.
"""

from __future__ import annotations

import random
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from testcase_agent.closure import workspace as W

#: Default sampling grid. Operator search_hints can narrow ladders later; this
#: is the exploration envelope that produced the first closure.
DEFAULT_GRID: dict[str, list[Any]] = {
    "layout": ["SBH", "BSH", "BNSD", "BSND", "TND"],
    "dtype": ["FLOAT16", "BF16", "FLOAT"],
    "b": [1, 2, 3, 4, 8, 16, 32, 48, 64],
    "s1": [1, 64, 128, 192, 256, 512, 768, 1024, 2048, 4096],
    "s2": [1, 64, 128, 192, 256, 512, 768, 1024, 2048, 4096],
    "n2": [1, 2, 4, 5, 8, 12, 16, 40],
    "g": [1, 2, 4, 8],
    "d": [16, 32, 64, 72, 96, 128, 144, 192, 256, 512, 768],
    "pse_type": [0, 1, 2, 3],
    "keep_prob": [1.0, 0.9, 0.5],
    "sparse_mode": [0, 1, 2, 3, 4, 5, 6],
    "tokens": [0, 1, 64, 128, 256, 512, 1024, 2048, 65536],
    "out_dtype": [0, 1, 2, 3],
}


def _grid() -> dict[str, list[Any]]:
    """Sampling grid, with enums filled from the operator's input semantics."""
    I = W.replay_inputs()
    g = dict(DEFAULT_GRID)
    g["atten_mask"] = list(I.ATTEN_MASKS)
    g["pse_shape"] = list(I.PSE_SHAPES)
    return g


def sample_case(rng: random.Random, grid: dict[str, list[Any]] | None = None):
    """One fresh Case drawn from the grid."""
    I = W.replay_inputs()
    g = grid or _grid()
    layout = rng.choice(g["layout"])
    b = rng.choice(g["b"])
    s1 = rng.choice(g["s1"])
    s2 = rng.choice(g["s2"]) if rng.random() < 0.5 else s1
    d = rng.choice(g["d"])
    d1 = d if rng.random() < 0.7 else rng.choice(g["d"])
    rope = rng.random() < 0.15
    pse = rng.random() < 0.45
    seq_q = seq_kv = None
    if layout == "TND":
        n = max(1, min(b, 16))
        if rng.random() < 0.6:
            seq_q = [s1 * (i + 1) for i in range(n)]
            seq_kv = [s2 * (i + 1) for i in range(n)]
        else:
            lens_q = [rng.choice([0, 64, 128, 256, 512, 1024]) for _ in range(n)]
            lens_kv = [rng.choice([0, 64, 128, 256, 512, 1024]) for _ in range(n)]
            seq_q = list(np.cumsum(lens_q))
            seq_kv = list(np.cumsum(lens_kv))
    return I.Case(
        layout=layout, dtype=rng.choice(g["dtype"]), b=b, s1=s1, s2=s2,
        n2=rng.choice(g["n2"]), g=rng.choice(g["g"]), d=d, d1=d1,
        atten_mask=rng.choice(g["atten_mask"]),
        pse=pse, pse_shape=rng.choice(g["pse_shape"]),
        pse_type=rng.choice(g["pse_type"]), rope=rope,
        keep_prob=rng.choice(g["keep_prob"]),
        sparse_mode=rng.choice(g["sparse_mode"]),
        pre_tokens=rng.choice(g["tokens"]),
        next_tokens=rng.choice(g["tokens"]),
        out_dtype=rng.choice(g["out_dtype"]),
        deterministic=rng.randint(0, 1),
        seq_q=seq_q, seq_kv=seq_kv,
    )


def _seq(text) -> list[int] | None:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None
    s = str(text).strip()
    if not s:
        return None
    try:
        return [int(v) for v in s.split("/") if v != ""]
    except ValueError:
        return None


def case_from_row(row) -> Any | None:
    """Rebuild the Case a corpus row describes."""
    I = W.replay_inputs()
    try:
        return I.Case(
            layout=str(row["layout"]), dtype=str(row["dtype"]),
            b=int(row["b"]), s1=int(row["s1"]), s2=int(row["s2"]),
            n2=int(row["n2"]), g=int(row["g"]), d=int(row["d"]),
            d1=int(row["d1"]),
            atten_mask=str(row["atten_mask"]) or "none",
            pse=bool(int(row["pse"])),
            pse_shape=str(row["pse_shape"]) or "bnss",
            pse_type=int(row["pse_type"]), rope=bool(int(row["rope"])),
            keep_prob=float(row["keep_prob"]),
            sparse_mode=int(row["sparse_mode"]),
            pre_tokens=int(row["pre_tokens"]),
            next_tokens=int(row["next_tokens"]),
            out_dtype=int(row["out_dtype"]),
            deterministic=int(row["deterministic"]),
            seq_q=_seq(row.get("seq_q")), seq_kv=_seq(row.get("seq_kv")),
        )
    except (ValueError, TypeError, KeyError):
        return None


def _mutable(grid: dict[str, list[Any]]) -> list[tuple[str, list[Any]]]:
    return [
        ("dtype", grid["dtype"]), ("layout", grid["layout"]),
        ("b", grid["b"]), ("s1", grid["s1"]), ("s2", grid["s2"]),
        ("n2", grid["n2"]), ("g", grid["g"]), ("d", grid["d"]),
        ("atten_mask", grid["atten_mask"]), ("pse_shape", grid["pse_shape"]),
        ("pse_type", grid["pse_type"]), ("keep_prob", grid["keep_prob"]),
        ("sparse_mode", grid["sparse_mode"]),
        ("pre_tokens", grid["tokens"]), ("next_tokens", grid["tokens"]),
        ("out_dtype", grid["out_dtype"]), ("deterministic", [0, 1]),
        ("pse", [True, False]), ("rope", [True, False]),
    ]


def mutate(case, rng: random.Random, k: int = 2, grid: dict | None = None):
    """Turn `k` knobs on a witness Case."""
    g = grid or _grid()
    options = _mutable(g)
    out = case
    for name, values in rng.sample(options, min(k, len(options))):
        v = rng.choice(values)
        if name == "d":
            out = replace(out, d=v, d1=v if rng.random() < 0.7 else out.d1)
        elif name == "layout" and v == "TND":
            n = max(1, min(out.b, 16))
            out = replace(
                out, layout="TND",
                seq_q=[out.s1 * (i + 1) for i in range(n)],
                seq_kv=[out.s2 * (i + 1) for i in range(n)])
        elif name == "layout":
            out = replace(out, layout=v, seq_q=None, seq_kv=None)
        else:
            out = replace(out, **{name: v})
    return out


def witnesses_from(corpus: pd.DataFrame, limit: int = 12000,
                   seed: int = 5) -> list:
    """Accepted inputs, rebuilt as Cases, to grow new candidates from."""
    if corpus.empty:
        return []
    acc = corpus[corpus.ok == 1]
    if len(acc) > limit:
        acc = acc.sample(limit, random_state=seed)
    out = []
    for _, row in acc.iterrows():
        c = case_from_row(row)
        if c is not None:
            out.append(c)
    return out


def pool(n: int, seed: int = 0, witnesses: list | None = None,
         mutate_share: float = 0.65) -> tuple[list, pd.DataFrame]:
    """Candidates: mostly mutated witnesses, some fresh draws."""
    I = W.replay_inputs()
    rng = random.Random(seed)
    grid = _grid()
    cases, recs = [], []
    seen: set[tuple] = set()
    stall = 0
    while len(cases) < n and stall < n * 20:
        if witnesses and rng.random() < mutate_share:
            c = mutate(rng.choice(witnesses), rng,
                       k=rng.choice([1, 2, 2, 3]), grid=grid)
        else:
            c = sample_case(rng, grid)
        try:
            desc = I.describe(c)
        except Exception:
            stall += 1
            continue
        sig = tuple(desc.values())
        if sig in seen:
            stall += 1
            continue
        seen.add(sig)
        stall = 0
        cases.append(c.normalised())
        recs.append(desc)
    return cases, pd.DataFrame(recs)


#: Knobs to sweep when a residual key is one dimension away from a witness.
NEAREST_KNOBS: dict[str, list[tuple[str, list]]] = {
    "DTemplateNum": [("d", [64, 128, 192, 256, 512])],
    "IsDrop": [("keep_prob", [1.0, 0.5])],
    "IsAttenMask": [("atten_mask", ["none", "ss", "bnss", "b1ss", "11ss"])],
    "DeterType": [
        ("deterministic", [0, 1]),
        ("sparse_mode", [0, 1, 2, 3, 4, 5, 6]),
    ],
    "IsPse": [("pse", [True, False])],
    "IsRope": [("rope", [True, False])],
    "InputDType": [("dtype", ["FLOAT16", "BF16", "FLOAT"])],
    "IsNEqual": [("g", [1, 2, 4])],
}


def sweep_nearest(case, differing_dims: list[str]) -> list:
    """Variants of a witness that only touch the dimensions that still differ."""
    out = [case]
    for dim in differing_dims:
        for name, values in NEAREST_KNOBS.get(dim, []):
            next_round = []
            for base in out:
                for v in values:
                    next_round.append(replace(base, **{name: v}))
            out = next_round
    normalised = []
    for c in out:
        try:
            normalised.append(c.normalised())
        except Exception:
            continue
    return normalised


#: Root categories that map onto Case knobs. Used by the influence cone.
_ROOT_TO_KNOBS: dict[str, list[str]] = {
    "ATTRIBUTE": ["layout", "sparse_mode", "pre_tokens", "next_tokens",
                  "keep_prob", "deterministic", "pse_type", "out_dtype"],
    "INPUT_DTYPE": ["dtype"],
    "INPUT_SHAPE": ["b", "s1", "s2", "n2", "g", "d", "d1"],
    "OPTIONAL_INPUT_PRESENCE": ["pse", "rope", "atten_mask"],
    "SESSION_OPTION": ["deterministic"],
    "INPUT_VALUE": ["seq_q", "seq_kv"],
}


def knobs_for_field(field: str, uo_root: str | None = None) -> list[str]:
    """Knobs in the influence cone of a key / host-state field.

    Reads come from the durable codemap. When the field has no reads recorded,
    every mutable knob is allowed (safe over-approximation for generation).
    """
    from pathlib import Path

    root = Path(uo_root) if uo_root else (
        Path(__file__).resolve().parents[4] / ".ascendc-pilot" / "uo")
    knobs: set[str] = set()
    try:
        from uo_init.host_codemap import CodemapQuery
        for r in CodemapQuery(root).reads_of(field):
            for k in _ROOT_TO_KNOBS.get(str(r.get("root") or ""), ()):
                knobs.add(k)
    except Exception:
        pass
    return sorted(knobs)


def mutate_in_cone(case, field: str, rng: random.Random, k: int = 2,
                   uo_root: str | None = None):
    """Mutate only knobs that feed ``field``, when the cone is known."""
    allowed = set(knobs_for_field(field, uo_root=uo_root))
    if not allowed:
        return mutate(case, rng, k=k)
    grid = _grid()
    options = [(n, v) for n, v in _mutable(grid) if n in allowed]
    if not options:
        return mutate(case, rng, k=k)
    out = case
    for name, values in rng.sample(options, min(k, len(options))):
        out = replace(out, **{name: rng.choice(values)})
    return out
