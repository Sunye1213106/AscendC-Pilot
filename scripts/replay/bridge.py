# -*- coding: utf-8 -*-
"""Speak the static derivation's language on behalf of a replay case.

The derivation talks about `VAR_SHAPE_QUERY_D2` and `VAR_OPT_PSE_SHIFT`; the
replay side talks about `Case.d` and `Case.pse`. Both describe the same tensor
set, and the translation has been missing, which is why 50 extracted premises
and 19 derived expressions have never once been consulted while generating an
input.

Everything here goes through `inputs._shapes()` rather than reconstructing
shapes, because the variables are syntactic: `VAR_SHAPE_QUERY_D2` is whatever
`queryShape->GetDim(2)` returns, and which quantity that is depends on the
layout. Guessing from the name would be right for TND and wrong for BSND.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import inputs as I
from .adapter import ADAPTER

ROOT = Path(__file__).resolve().parents[2]
DERIVE = ROOT / ".probe_cache" / "fag_derive.json"


def env_of(case: I.Case) -> dict[str, Any]:
    """The derivation's input variables, valued for this case.

    One of four exits from the same expansion, so the presence, shape and
    dtype seen here are by construction the ones the replayed line carries.
    They used to be worked out again from the case, which is how a dtype
    override reached the line and not the environment.

    Host tiling state is deliberately absent. `fBaseParams.layoutType` reads
    like it should be `attr input_layout`, and it is not: `SupportTrans2BS2N2GD`
    rewrites TND to BSND when every sequence is the same length, and a later
    `bn2S2RouteLimit` branch rewrites it back. A dimension reading that field
    is not predictable from the inputs, which is exactly what the derivation
    says by marking it `input_derivable: false`. Supplying a guess here would
    turn an honest "unknown" into a confident wrong answer -- and it is why
    nothing in `OBSERVED` is set here.
    """
    return ADAPTER.materialize(case, "").build_static_env()


#: The wide table prefixes the log's own field names. The protocol names the
#: field `isTnd`; the column recording it is `log_isTnd`.
LOG_COLUMN_PREFIX = "log_"


def observed(row: dict, case: I.Case) -> dict[str, tuple[Any, str]]:
    """Host state this run reported, each with the dimension it was read from.

    Only what the tiling actually printed. The array elements and loop
    reductions the hard dimensions also wait on are not logged, and are left
    unbound rather than guessed -- an unknown that stays unknown costs a
    prediction, an invented one costs the truth of every prediction near it.

    Which observations exist, and how each logged number becomes a variable's
    value, comes from the operator's spec. It used to be a table here with the
    layout codes transcribed from a header, which is a copy that goes stale
    silently: the constants are now resolved at export from the headers the
    analysis read.
    """
    from .materialized import default_spec

    out: dict[str, tuple[Any, str]] = {}
    for ob in default_spec().observations:
        raw = row.get(LOG_COLUMN_PREFIX + ob.column)
        if raw in (None, "", "None"):
            continue
        out[ob.var] = (ob.value(int(raw)), ob.withheld_from)
    return out


def grounded_env(base: dict[str, Any], obs: dict[str, tuple[Any, str]]) -> dict[str, Any]:
    """`base` plus every real host state this run printed.

    The values are observed facts, not predictions: `log_splitAxis` is what the
    tiling computed and reported. Filling `VAR_TDF_SPLITAXIS` from it is not the
    self-fulfilling move that filling it from a guessed expression would be, so
    there is no target to exclude for. A dimension that reads the field then
    gets its true value and the rest of the expression is checked against it.
    """
    env = dict(base)
    for var, (value, _whose) in obs.items():
        env[var] = value
    return env


_cache: dict[str, Any] = {}


def derivation() -> dict[str, Any]:
    """The static derivation, read once."""
    if "d" not in _cache:
        with DERIVE.open(encoding="utf-8") as f:
            _cache["d"] = json.load(f)["host_derivation"]
    return _cache["d"]


def fields() -> dict[str, dict]:
    return {f["name"]: f for f in derivation()["fields"]}


def exact_fields() -> dict[str, dict]:
    """Dimensions the derivation claims to know exactly."""
    return {n: f for n, f in fields().items()
            if f["exactness"] in ("exact", "constant") and f.get("value_expr")}


def premises():
    """Every extracted legality condition, graded or not."""
    if "p" not in _cache:
        from uo_init.concrete_eval import Premises

        _cache["p"] = Premises(derivation().get("premises") or [])
    return _cache["p"]


GRADES = ROOT / ".probe_cache" / "replay" / "premise_grades.yaml"


def _unsound() -> set[str] | None:
    """Premises known to refuse inputs the host accepts, by source location.

    None when nothing has been graded yet, which is not the same as nothing
    being unsound: the extraction drops the guard a check sits behind, so
    `CheckSoftmaxMaxShape` demands rank 4 of layouts that never call it. An
    ungraded premise has not been shown to be safe, and gating on it would
    throw away witnesses.
    """
    if not GRADES.is_file():
        return None
    bad, where = set(), ""
    for line in GRADES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- where:"):
            where = line.split(":", 1)[1].strip()
        elif line == "grade: unsound":
            bad.add(where)
    return bad


def gated_premises():
    """The subset a preflight may refuse an input on."""
    if "g" not in _cache:
        from uo_init.concrete_eval import Premises

        bad = _unsound()
        blobs = [] if bad is None else [
            p for p in (derivation().get("premises") or [])
            if f"{Path(str(p.get('file'))).name}:{p.get('line')}" not in bad
        ]
        _cache["g"] = Premises(blobs)
    return _cache["g"]


def refused_by(case: I.Case) -> list[dict]:
    """Premises this case breaks, or an empty list if the host would take it."""
    return gated_premises().violations(env_of(case))


#: Roots naming host tiling state rather than anything a case can set.
STATE_ROOTS = {"TILING_DATA"}


def reads_host_state(field: dict) -> list[str]:
    """Variables in `field` that no input can set, so no env can supply.

    Refuses a derivation written before `var_roots` existed rather than reading
    it as "this dimension reads no host state". The two are the same empty list,
    and while a cache from then was on disk every dimension looked input-driven,
    so the searcher was never told which ones have no knob behind them -- it
    fell back to hand-written ones instead, quietly.

    `var_roots` maps each variable to its root; `root_vars` is only the set of
    roots the field touches, which cannot say *which* variable is host state.
    """
    roots = field.get("var_roots")
    if roots is None:
        raise KeyError(
            f"dimension {field.get('name', '?')!r} carries no var_roots: this "
            "derivation predates the field. Re-run: acp run-action derive_key_fields"
        )
    return sorted(v for v, root in roots.items() if root in STATE_ROOTS)
