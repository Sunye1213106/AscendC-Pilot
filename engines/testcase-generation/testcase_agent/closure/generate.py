# -*- coding: utf-8 -*-
"""Candidate generation for directed search.

Uniform sampling of the knob space is mostly refused -- shape, mask, sparse
and sequence have to agree, and independent draws rarely do. Starting from a
witness the host already accepted and turning one to three knobs keeps most
of that agreement. Both sources are kept: mutation for yield, fresh sampling
for exploration.

All Case field knowledge comes from the active operator's ``knob_schema()``
and ``search_hints.yaml``. Missing hints fail closed — there is no FAG
fallback table in the engine.
"""

from __future__ import annotations

import random
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from testcase_agent.closure import workspace as W


def _hints() -> dict[str, Any]:
    from replay.package_data import load_yaml

    doc = load_yaml("search_hints.yaml")
    if not doc:
        raise FileNotFoundError(
            "operators/<op>/<arch>/search_hints.yaml is required "
            "(no engine-side FAG fallback)"
        )
    return doc


def _grid() -> dict[str, list[Any]]:
    """Sampling grid from search_hints; enums may fill categorical knobs."""
    I = W.replay_inputs()
    raw = _hints().get("sampling_grid")
    if not raw:
        raise ValueError("search_hints.yaml missing sampling_grid")
    g = {str(k): list(v) for k, v in dict(raw).items()}
    sem = I.SEMANTICS
    enums = sem.enums() if hasattr(sem, "enums") else {}
    schema = sem.knob_schema() if hasattr(sem, "knob_schema") else {}
    for name, meta in schema.items():
        if name in g:
            continue
        if meta.get("kind") == "categorical" and name in enums:
            g[name] = list(enums[name])
        elif meta.get("kind") == "categorical" and meta.get("domain"):
            g[name] = list(meta["domain"])
    return g


def sample_case(rng: random.Random, grid: dict[str, list[Any]] | None = None):
    """One fresh Case drawn from the grid via knob_schema / from_knobs."""
    I = W.replay_inputs()
    sem = I.SEMANTICS
    if not hasattr(sem, "knob_schema") or not hasattr(sem, "from_knobs"):
        raise TypeError(
            "active InputSemantics must implement knob_schema() and from_knobs()"
        )
    g = grid or _grid()
    schema = sem.knob_schema()
    knobs: dict[str, Any] = {}
    for name, meta in schema.items():
        if not meta.get("mutable", True) and name not in g:
            if "default" in meta:
                knobs[name] = meta["default"]
            continue
        if name in g and g[name]:
            knobs[name] = rng.choice(g[name])
        elif meta.get("domain"):
            knobs[name] = rng.choice(list(meta["domain"]))
        elif "default" in meta:
            knobs[name] = meta["default"]
    case = sem.from_knobs(knobs)
    if hasattr(sem, "repair"):
        case = sem.repair(case)
    # Optional layout-specific sequence fill when the schema names seq_* knobs.
    if (
        knobs.get("layout") == "TND"
        and "seq_q" in schema
        and getattr(case, "seq_q", None) is None
        and "s1" in knobs
        and "b" in knobs
    ):
        n = max(1, min(int(knobs["b"]), 16))
        s1 = int(knobs["s1"])
        s2 = int(knobs.get("s2", s1))
        case = replace(
            case,
            seq_q=[s1 * (i + 1) for i in range(n)],
            seq_kv=[s2 * (i + 1) for i in range(n)],
        )
        if hasattr(sem, "repair"):
            case = sem.repair(case)
    return case


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
    """Rebuild the Case a corpus row describes via from_knobs."""
    I = W.replay_inputs()
    sem = I.SEMANTICS
    if not hasattr(sem, "from_knobs") or not hasattr(sem, "knob_schema"):
        return None
    schema = sem.knob_schema()
    knobs: dict[str, Any] = {}
    try:
        for name, meta in schema.items():
            if name not in row.index if hasattr(row, "index") else name not in row:
                continue
            raw = row[name]
            kind = meta.get("kind")
            if kind == "sequence":
                knobs[name] = _seq(raw)
            elif kind == "bool":
                knobs[name] = bool(int(raw)) if str(raw) not in ("", "nan") else False
            elif kind == "numeric":
                if isinstance(raw, float) and pd.isna(raw):
                    continue
                text = str(raw)
                knobs[name] = float(raw) if "." in text else int(float(raw))
            else:
                knobs[name] = str(raw) if raw is not None else meta.get("default", "")
        return sem.from_knobs(knobs)
    except (ValueError, TypeError, KeyError):
        return None


def _mutable(grid: dict[str, list[Any]]) -> list[tuple[str, list[Any]]]:
    I = W.replay_inputs()
    sem = I.SEMANTICS
    schema = sem.knob_schema() if hasattr(sem, "knob_schema") else {}
    out: list[tuple[str, list[Any]]] = []
    for name, meta in schema.items():
        if not meta.get("mutable", True):
            continue
        values = grid.get(name) or list(meta.get("domain") or [])
        if not values and meta.get("kind") == "bool":
            values = [True, False]
        if values:
            out.append((name, list(values)))
    return out


def mutate(case, rng: random.Random, k: int = 2, grid: dict | None = None):
    """Turn `k` knobs on a witness Case."""
    I = W.replay_inputs()
    sem = I.SEMANTICS
    g = grid or _grid()
    options = _mutable(g)
    out = case
    for name, values in rng.sample(options, min(k, len(options))):
        v = rng.choice(values)
        if name == "layout" and v == "TND" and hasattr(out, "s1") and hasattr(out, "b"):
            n = max(1, min(int(out.b), 16))
            out = replace(
                out, layout="TND",
                seq_q=[out.s1 * (i + 1) for i in range(n)],
                seq_kv=[getattr(out, "s2", out.s1) * (i + 1) for i in range(n)],
            )
        elif name == "layout":
            kwargs = {"layout": v}
            if hasattr(out, "seq_q"):
                kwargs["seq_q"] = None
                kwargs["seq_kv"] = None
            out = replace(out, **kwargs)
        elif name == "d" and hasattr(out, "d1"):
            out = replace(out, d=v, d1=v if rng.random() < 0.7 else out.d1)
        else:
            out = replace(out, **{name: v})
    if hasattr(sem, "repair"):
        out = sem.repair(out)
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
            desc = I.describe(c) if hasattr(I, "describe") else I.SEMANTICS.describe(c)
        except Exception:
            stall += 1
            continue
        sig = tuple(desc.values())
        if sig in seen:
            stall += 1
            continue
        seen.add(sig)
        stall = 0
        norm = c.normalised() if hasattr(c, "normalised") else c
        cases.append(norm)
        recs.append(desc)
    return cases, pd.DataFrame(recs)


def _nearest_knobs() -> dict[str, list[tuple[str, list]]]:
    raw = _hints().get("nearest_knobs") or {}
    if not raw:
        raise ValueError("search_hints.yaml missing nearest_knobs")
    out: dict[str, list[tuple[str, list]]] = {}
    for dim, rows in raw.items():
        entries: list[tuple[str, list]] = []
        for row in rows or []:
            if isinstance(row, dict):
                entries.append((str(row["knob"]), list(row.get("values") or [])))
            elif isinstance(row, (list, tuple)) and len(row) == 2:
                entries.append((str(row[0]), list(row[1])))
        out[str(dim)] = entries
    return out


def sweep_nearest(case, differing_dims: list[str]) -> list:
    """Variants of a witness that only touch the dimensions that still differ."""
    table = _nearest_knobs()
    out = [case]
    for dim in differing_dims:
        for name, values in table.get(dim, []):
            next_round = []
            for base in out:
                for v in values:
                    next_round.append(replace(base, **{name: v}))
            out = next_round
    normalised = []
    for c in out:
        try:
            normalised.append(c.normalised() if hasattr(c, "normalised") else c)
        except Exception:
            continue
    return normalised


def _root_to_knobs() -> dict[str, list[str]]:
    try:
        from replay.package_data import load_yaml

        raw = (load_yaml("feature_bindings.yaml") or {}).get("root_to_knobs") or {}
        return {str(k): [str(x) for x in (v or [])] for k, v in raw.items()}
    except Exception:
        return {}


def knobs_for_field(field: str, uo_root: str | None = None) -> list[str]:
    """Knobs in the influence cone of a key / host-state field."""
    from pathlib import Path

    if uo_root is None:
        raise ValueError("uo_root is required (pass the operator's .ascendc-pilot/<arch>/uo)")
    root = Path(uo_root)
    table = _root_to_knobs()
    knobs: set[str] = set()
    try:
        from uo_init.host_codemap import CodemapQuery
        for r in CodemapQuery(root).reads_of(field):
            for k in table.get(str(r.get("root") or ""), ()):
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
