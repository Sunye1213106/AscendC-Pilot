# -*- coding: utf-8 -*-
"""Candidate generation for directed search.

Uniform sampling of the knob space is mostly refused -- shape, mask, sparse
and sequence have to agree, and independent draws rarely do. Starting from a
witness the host already accepted and turning one to three knobs keeps most
of that agreement. Both sources are kept: mutation for yield, fresh sampling
for exploration.

All Case field knowledge comes from the active operator's ``knob_schema()``
and ``search_hints.yaml``. Missing hints are empty (cold-start / before
``export_adapter_pack``); there is no engine-side FAG fallback table.
"""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from testcase_agent.closure.key_utils import int_exact
from testcase_agent.closure import workspace as W


def _hints() -> dict[str, Any]:
    from replay.package_data import load_yaml

    return load_yaml("search_hints.yaml") or {}


def _grid() -> dict[str, list[Any]]:
    """Sampling grid from search_hints; enums may fill categorical knobs."""
    I = W.replay_inputs()
    raw = _hints().get("sampling_grid") or {}
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


def _describe_case(case) -> dict[str, Any] | None:
    I = W.replay_inputs()
    try:
        desc = I.describe(case) if hasattr(I, "describe") else I.SEMANTICS.describe(case)
    except Exception:
        return None
    return dict(desc)


def _add_case(
    cases: list,
    recs: list[dict[str, Any]],
    seen: set[tuple],
    case,
    *,
    meta: Mapping[str, Any] | None = None,
) -> bool:
    desc = _describe_case(case)
    if desc is None:
        return False
    sig = tuple(desc.values())
    if sig in seen:
        return False
    seen.add(sig)
    norm = case.normalised() if hasattr(case, "normalised") else case
    cases.append(norm)
    row = dict(desc)
    if meta:
        row.update(dict(meta))
    recs.append(row)
    return True


def _open_target_rows(
    ws: W.Workspace,
    open_keys: Iterable[int] | None,
    *,
    seed: int = 0,
    control: bool = False,
) -> list[dict[str, Any]]:
    keys = {int(k) for k in (open_keys or []) if str(k).strip()}
    rows: list[dict[str, Any]] = []
    if keys:
        try:
            from testcase_agent.closure import residual

            res = residual.analyse(ws)
            rows = [r for r in (res.get("rows") or []) if int(r.get("key")) in keys]
        except Exception:
            rows = [{"key": k, "distance": 99, "differing_dims": ""} for k in sorted(keys)]
    else:
        try:
            from testcase_agent.closure import ledger

            rset, eset, dset = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
            rows = [{"key": k, "distance": 99, "differing_dims": ""} for k in sorted(dset - rset - eset)]
        except Exception:
            rows = []

    rng = random.Random(seed)
    if control:
        rng.shuffle(rows)
        return rows
    return sorted(rows, key=lambda r: (int(r.get("distance") or 99), rng.random(), int(r.get("key") or 0)))


def _target_meta(row: Mapping[str, Any], source: str) -> dict[str, Any]:
    return {
        "_generation": source,
        "_target_key": int(row.get("key") or 0),
        "_target_distance": int(row.get("distance") or 99),
        "_target_differing_dims": str(row.get("differing_dims") or ""),
    }


def _explore_meta(row: Mapping[str, Any], source: str) -> dict[str, Any]:
    """Metadata for exploratory candidates that are not meant to hit a key.

    A witness mutation can be useful for learning which host checks still
    reject nearby regions, but it is not an inverse construction for the row's
    key.  Keeping ``_target_key`` at zero prevents the later accounting from
    treating a drifted mutation as a failed attempt at one specific open key.
    """
    return {
        "_generation": source,
        "_target_key": 0,
        "_target_distance": int(row.get("distance") or 99) if row else 99,
        "_target_differing_dims": str(row.get("differing_dims") or ""),
    }


def _intish(value: Any, default: int = 0) -> int:
    return int_exact(value, default=default)


def _floatish(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _rank_by_surrogate(
    cases: list,
    frame: pd.DataFrame,
    *,
    surrogate: Any | None,
    open_keys: set[int],
) -> tuple[list, pd.DataFrame]:
    """Put likely useful rows first; never discard solely on a model opinion."""
    if surrogate is None or frame.empty:
        return cases, frame
    try:
        accept, keys = surrogate.predict(frame)
    except Exception:
        return cases, frame
    scores = []
    for i, pred in enumerate(keys):
        pkey = _intish(pred)
        target = _intish(frame.iloc[i].get("_target_key"))
        generation = str(frame.iloc[i].get("_generation") or "")
        score = 0.0
        # Direct KB inverse construction is the only arm that claims to hit a
        # specific open key.  Surrogate ranking can choose among those rows, but
        # must not bury them under exploratory mutations whose actual key is
        # intentionally free to drift.
        score += 100.0 if generation == "kb_construct" else 0.0
        score += 4.0 if _intish(accept[i]) else 0.0
        score += 3.0 if pkey in open_keys else 0.0
        score += 2.0 if target and pkey == target else 0.0
        score -= _floatish(frame.iloc[i].get("_target_distance"), 99.0) * 0.01
        scores.append((score, i, pkey, _intish(accept[i])))
    by_index = {i: (pkey, acc) for _score, i, pkey, acc in scores}
    order = [i for _score, i, _pkey, _acc in sorted(scores, reverse=True)]
    ranked = frame.iloc[order].reset_index(drop=True).copy()
    ranked["_predicted_key"] = [by_index[i][0] for i in order]
    ranked["_predicted_accept"] = [by_index[i][1] for i in order]
    return [cases[i] for i in order], ranked


def kb_guided_pool(
    n: int,
    seed: int = 0,
    witnesses: list | None = None,
    *,
    open_keys: Iterable[int] | None = None,
    surrogate: Any | None = None,
    control: bool = False,
    ws: W.Workspace | None = None,
    oversample: int = 4,
    explore_fill: bool = False,
) -> tuple[list, pd.DataFrame]:
    """Build candidates from the KB/open set first, then mutate witnesses.

    The random control arm still uses the KB envelope: it randomises target
    order and knob choices, but it does not go back to unconstrained draws.
    """
    if n <= 0:
        return [], pd.DataFrame()
    ws = (ws or W.default_workspace()).ensure()
    rng = random.Random(seed)
    target_n = n if control else max(n, n * max(1, oversample))
    cases: list = []
    recs: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    uo_root = ""
    try:
        # .../.ascendc-pilot/<arch>/tg/closure -> .../<arch>/uo
        uo_root = str(Path(ws.state).parent.parent / "uo")
    except Exception:
        uo_root = ""

    try:
        from testcase_agent.closure import construct

        for row in _open_target_rows(ws, open_keys, seed=seed, control=control):
            if len(cases) >= target_n:
                break
            try:
                inst = W.decode(int(row["key"]))
                built = construct.build(inst, seed=seed)
            except Exception:
                built = []
            if control:
                rng.shuffle(built)
            for c in built:
                if _add_case(cases, recs, seen, c, meta=_target_meta(row, "kb_construct")):
                    if len(cases) >= target_n:
                        break
    except Exception:
        pass

    # If the KB inverse constructor can already spell enough open keys, stop
    # here.  Sklearn may rank these direct candidates, but witness mutation is
    # only an exploration fallback and must not displace target-preserving
    # construction.
    if len(cases) >= n:
        frame = pd.DataFrame(recs)
        open_set = {int(k) for k in (open_keys or []) if str(k).strip()}
        cases, frame = _rank_by_surrogate(cases, frame, surrogate=surrogate, open_keys=open_set)
        if len(cases) > n:
            cases = cases[:n]
            frame = frame.iloc[:n].reset_index(drop=True)
        return cases, frame

    if not explore_fill:
        frame = pd.DataFrame(recs)
        open_set = {int(k) for k in (open_keys or []) if str(k).strip()}
        cases, frame = _rank_by_surrogate(cases, frame, surrogate=surrogate, open_keys=open_set)
        if len(cases) > n:
            cases = cases[:n]
            frame = frame.iloc[:n].reset_index(drop=True)
        return cases, frame

    # If construction cannot spell enough targets, mutate accepted witnesses in
    # the UO influence cone of near-open dimensions. This is still KB-guided.
    if len(cases) < target_n and witnesses:
        rows = _open_target_rows(ws, open_keys, seed=seed + 17, control=True)
        stall = 0
        while len(cases) < target_n and stall < target_n * 20:
            row = rows[stall % len(rows)] if rows else {}
            fields = [
                x for x in str(row.get("differing_dims") or "").split("|") if x
            ]
            base = rng.choice(witnesses)
            if fields:
                try:
                    c = mutate_in_cone(
                        base,
                        rng.choice(fields),
                        rng,
                        k=rng.choice([1, 2, 2, 3]),
                        uo_root=uo_root or None,
                    )
                except Exception:
                    c = mutate(base, rng, k=rng.choice([1, 2, 2, 3]))
            else:
                c = mutate(base, rng, k=rng.choice([1, 2, 2, 3]))
            if _add_case(cases, recs, seen, c, meta=_explore_meta(row, "kb_mutate_explore")):
                stall = 0
            else:
                stall += 1

    # Last resort: schema/hints sampling. This is bounded fallback, not the
    # main arm; the caller can see it through _generation.
    if len(cases) < target_n:
        extra, frame = pool(
            target_n - len(cases),
            seed=seed + 101,
            witnesses=witnesses,
            mutate_share=0.5 if witnesses else 0.0,
        )
        for i, c in enumerate(extra):
            meta = {"_generation": "schema_fallback"}
            if frame is not None and not frame.empty and i < len(frame):
                row_meta = {k: v for k, v in frame.iloc[i].to_dict().items() if k.startswith("_")}
                meta.update(row_meta)
            _add_case(cases, recs, seen, c, meta=meta)

    frame = pd.DataFrame(recs)
    open_set = {int(k) for k in (open_keys or []) if str(k).strip()}
    cases, frame = _rank_by_surrogate(cases, frame, surrogate=surrogate, open_keys=open_set)
    if len(cases) > n:
        cases = cases[:n]
        frame = frame.iloc[:n].reset_index(drop=True)
    return cases, frame


def _nearest_knobs() -> dict[str, list[tuple[str, list]]]:
    raw = _hints().get("nearest_knobs") or {}
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


def _feature_bindings_tables() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return ``(dim_to_roots, root_to_knobs)`` with legacy inversion repair.

    Older adapter packs mistakenly stored ``root_to_knobs`` as dim→roots.
    Detect that shape (values look like INPUT_/ATTR_ roots) and recover.
    """
    try:
        from replay.package_data import load_yaml

        doc = load_yaml("feature_bindings.yaml") or {}
    except Exception:
        return {}, {}

    dim_to_roots = {
        str(k): [str(x) for x in (v or [])]
        for k, v in (doc.get("dim_to_roots") or {}).items()
    }
    root_to_knobs = {
        str(k): [str(x) for x in (v or [])]
        for k, v in (doc.get("root_to_knobs") or {}).items()
    }

    def _looks_like_roots(values: list[str]) -> bool:
        if not values:
            return False
        return any(
            v.startswith("INPUT_") or v.startswith("ATTR_") or v.startswith("VAR_")
            for v in values
        )

    # Legacy: root_to_knobs was actually dim→roots.
    if not dim_to_roots and root_to_knobs and any(
        _looks_like_roots(v) for v in root_to_knobs.values()
    ):
        dim_to_roots = dict(root_to_knobs)
        root_to_knobs = {}
        schema_keys: list[str] = []
        try:
            I = W.replay_inputs()
            schema_keys = list((I.SEMANTICS.knob_schema() or {}).keys())
        except Exception:
            schema_keys = []
        for roots in dim_to_roots.values():
            for r in roots:
                named = [k for k in schema_keys if k.lower() in r.lower()]
                if not named:
                    continue
                bucket = root_to_knobs.setdefault(r, [])
                for k in named:
                    if k not in bucket:
                        bucket.append(k)
    return dim_to_roots, root_to_knobs


def knobs_for_field(field: str, uo_root: str | None = None) -> list[str]:
    """Knobs in the influence cone of a key / host-state field.

    Path: ``field → dim_to_roots / Codemap roots → root_to_knobs``.
    Falls back to ``static_parents[field]`` when the cone is empty.
    """
    from pathlib import Path

    if uo_root is None:
        raise ValueError("uo_root is required (pass the operator's .ascendc-pilot/<arch>/uo)")
    root = Path(uo_root)
    dim_to_roots, table = _feature_bindings_tables()
    knobs: set[str] = set()
    roots: list[str] = []
    roots.extend(dim_to_roots.get(str(field), ()))
    try:
        from uo_init.host_codemap import CodemapQuery
        for r in CodemapQuery(root).reads_of(field):
            roots.append(str(r.get("root") or ""))
    except Exception:
        pass
    for r in roots:
        if not r:
            continue
        for k in table.get(r, ()):
            knobs.add(k)
    if not knobs:
        try:
            from replay.package_data import load_yaml

            parents = (load_yaml("feature_bindings.yaml") or {}).get("static_parents") or {}
            for k in parents.get(str(field), ()) or []:
                knobs.add(str(k))
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
