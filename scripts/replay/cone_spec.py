# -*- coding: utf-8 -*-
"""Derive the influence cone of a dimension from the static derivation.

`replay_cone` today knows the answer for one operator: which knob moves the
differing dimension, and that s1/s2 cancel the coupling. Both were written
down by hand. The derivation already says which input variables each
dimension reads (`fag_derive.json` per field `variables` / `input_roots`),
and `bridge_spec.yaml` already says which Case field each input variable is.
Composed, they give the cone for free:

  DirectCone     the Case fields this dimension reads -- what a nudge may move
  SideEffects    other dimensions that read the same inputs, so they move too
  Compensation   inputs read by the side effects but NOT by the target, which
                 is where a counter-move can live without touching the target

A dimension whose every input is also read by nothing else has an empty
SideEffects and needs no compensation. A dimension reading only host tiling
state has an empty DirectCone and no knob at all -- the size grid is the only
move, exactly what `replay_cone._candidates` already does for those names.

Nothing here names an operator. The only operator-specific inputs are the two
already-exported artifacts; a second operator produces its own and this module
reads them the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import bridge as B

#: Variable prefixes that name something derived from a replay Case's
#: tensors or attributes. Everything else (`VAR_TDF_`, `VAR_INIT_`,
#: `VAR_LOOPELEM_`, `VAR_SESSION_`, ...) is host state or a derivation
#: invention. Not every such variable is *settable* -- `VAR_ELEM_BACK_...`
#: reads a value the host computed, not an input -- so the cone intersects
#: these with the bridge's bound set, which is the authority on what maps
#: onto a Case field.
_INPUT_PREFIXES = ("VAR_ATTR_", "VAR_SHAPE_", "VAR_DTYPE_", "VAR_OPT_",
                   "VAR_VALUE_", "VAR_RANK_", "VAR_ELEM_", "VAR_REDUCE_")

#: Variable prefixes that name host tiling state specifically: the dimension
#: has no input knob at all when these are its only reads.
_STATE_PREFIXES = ("VAR_TDF_",)


def _bound_vars() -> set[str]:
    """Variables the bridge binds to a Case field -- the settable inputs."""
    from .materialized import default_spec

    return {b.var for b in default_spec().bindings}


@dataclass
class Cone:
    """How to reach one dimension, derived from what it reads."""

    dim: str
    #: Case-settable variable names this dimension reads (its knobs).
    direct_inputs: list[str] = field(default_factory=list)
    #: Host-state variables it reads -- present means no full knob exists.
    host_state: list[str] = field(default_factory=list)
    #: Other dimensions sharing at least one direct input (they move too).
    side_effects: list[str] = field(default_factory=list)
    #: Inputs the side effects read but the target does not (the counter-move).
    compensation: list[str] = field(default_factory=list)
    #: True when no Case field can move this dimension (host-state only).
    knobless: bool = False


def _input_vars(fld: dict, bound: set[str]) -> list[str]:
    return sorted(v for v in (fld.get("variables") or [])
                  if v.startswith(_INPUT_PREFIXES) and v in bound)


def _state_vars(fld: dict) -> list[str]:
    return sorted(v for v in (fld.get("variables") or [])
                  if v.startswith(_STATE_PREFIXES))


def cones() -> dict[str, Cone]:
    """The influence cone of every derived dimension, computed once."""
    fields = B.fields()
    bound = _bound_vars()
    direct = {n: _input_vars(f, bound) for n, f in fields.items()}
    state = {n: _state_vars(f) for n, f in fields.items()}

    # Which other dimensions read each input variable.
    readers: dict[str, set[str]] = {}
    for n, vs in direct.items():
        for v in vs:
            readers.setdefault(v, set()).add(n)

    out: dict[str, Cone] = {}
    for n, f in fields.items():
        mine = set(direct[n])
        sides = sorted({o for v in mine for o in readers.get(v, ()) if o != n})
        comp = sorted({v for o in sides for v in direct[o]} - mine)
        out[n] = Cone(
            dim=n,
            direct_inputs=direct[n],
            host_state=state[n],
            side_effects=sides,
            compensation=comp,
            knobless=(not mine and bool(state[n] or f.get("variables"))),
        )
    return out


def report(dims: list[str] | None = None) -> str:
    """A compact per-dimension cone table, for the search planner to print."""
    cs = cones()
    names = dims or sorted(cs)
    lines = []
    for n in names:
        c = cs.get(n)
        if c is None:
            continue
        tag = "KNOBLESS" if c.knobless else (
            "direct" if not c.side_effects else "direct+comp")
        lines.append(
            f"{n:<16} {tag:<12} inputs={len(c.direct_inputs)} "
            f"sides={len(c.side_effects)} comp={len(c.compensation)}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    print(report(sys.argv[1:] or None))
