# -*- coding: utf-8 -*-
"""Turn a dimension target into Case mutations, without naming the dimension
in an if-ladder.

The search used to ask `if dim == "IsPse"`. That table duplicated what the
derivation already says (which variables the dimension reads) and what the
operator package already knows (how to build a pse / TND / rope case). Here
the dimension picks a named generator from search_hints.yaml, and the
generator builds the Cases. A second operator adds generators and hints; it
does not add another if-ladder to the engine.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from . import inputs as I
from .materialized import default_spec

Generator = Callable[[I.Case, str, Mapping[str, Any]], list[I.Case]]


_HINTS: dict[str, dict[str, Any]] = {}


def load_hints(
    path: str | Path | None = None, *, refresh: bool = False
) -> dict[str, Any]:
    """The operator's search hints, read once per file.

    Callers ask this per dimension and per candidate -- several thousand times
    in one search -- and parsing the file again for each of them costs far
    more than the lookups it answers. Treat the result as read-only; `variants`
    copies before it changes anything.
    """
    if path is None:
        from .runner import default
        path = default().manifest.package / "search_hints.yaml"
    path = Path(path)
    key = str(path)
    if not refresh and key in _HINTS:
        return _HINTS[key]
    doc: dict[str, Any] = {}
    if path.is_file():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _HINTS[key] = doc
    return doc


def variants(case: I.Case, dim: str, want: str,
             hints: Mapping[str, Any] | None = None) -> list[I.Case]:
    """Cases that try to push `dim` to `want`, starting from `case`."""
    hints = dict(hints if hints is not None else load_hints())
    special = (hints.get("special_generators") or {}).get(dim)
    if special is None:
        # No named generator: try a Binding-driven knob. Host-state dims and
        # anything the hints leave unnamed return empty here; cone supplies
        # the compensation grid for those.
        return _from_bindings(case, dim, want)
    name = special.get("generator") if isinstance(special, dict) else special
    gen = GENERATORS.get(str(name))
    if gen is None:
        raise KeyError(
            f"search_hints names generator {name!r} for {dim}, which is not "
            f"registered; known: {sorted(GENERATORS)}")
    return gen(case, want, hints)


def is_host_state(dim: str, hints: Mapping[str, Any] | None = None) -> bool:
    hints = hints if hints is not None else load_hints()
    return dim in set(hints.get("host_state_dims") or ())


def needs_compensation(dim: str, hints: Mapping[str, Any] | None = None) -> bool:
    hints = hints if hints is not None else load_hints()
    return dim not in set(hints.get("no_compensation") or ())


# --- generators ----------------------------------------------------------


def _pse(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    if want == "1":
        return [replace(c, pse=True, pse_shape=s) for s in I.PSE_SHAPES]
    return [replace(c, pse=False)]


def _keep_prob(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    return [replace(c, keep_prob=0.5 if want == "1" else 1.0)]


def _rope(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    if want == "1":
        return [replace(c, rope=True, d=I.ROPE_TOTAL_D, d1=None)]
    return [replace(c, rope=False)]


def _atten_mask(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    if want == "1":
        return [replace(c, atten_mask=m) for m in I.ATTEN_MASKS if m != "none"]
    return [replace(c, atten_mask="none")]


def _tnd_layout(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    if want == "1":
        n = max(1, c.b)
        return [
            replace(c, layout="TND", seq_q=[c.s1] * n, seq_kv=[c.s2] * n),
            replace(c, layout="TND", seq_q=[c.s1] * n,
                    seq_kv=[max(1, c.s2 // 2)] * n),
        ]
    return [replace(c, layout=lay, seq_q=None, seq_kv=None)
            for lay in ("BSND", "BNSD", "BSH", "SBH")]


def _d_ladder(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    want_i = int(want)
    ladder = list((hints.get("ladders") or {}).get("d") or [want_i])
    lo = max([x for x in ladder if x < want_i], default=0)
    return [replace(c, d=v, d1=None if (c.d1 or c.d) >= v else c.d1)
            for v in {want_i, max(1, want_i - 1), lo + 1} if v > 0]


def _d1_pair(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    if want == "1":
        steps = list((hints.get("ladders") or {}).get("d1_on") or ())
        return [replace(c, d1=v) for v in steps if v < (c.d or 128)]
    return [replace(c, d1=None)]


def _s1_ladder(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    want_i = int(want)
    return [replace(c, s1=v) for v in
            (want_i, want_i - 1, want_i + 1, want_i * 2, want_i * 4) if v > 0]


def _s2_ladder(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    want_i = int(want)
    return [replace(c, s2=v) for v in
            (want_i, want_i - 1, want_i * 2, want_i * 4) if v > 0]


def _input_dtype(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    codes = hints.get("input_dtype_codes") or {}
    code = codes.get(want)
    return [replace(c, dtype=code)] if code else []


def _out_dtype(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    return [replace(c, out_dtype=int(want))]


def _deter_sparse(c: I.Case, want: str, hints: Mapping[str, Any]) -> list[I.Case]:
    modes = list(hints.get("deter_sparse_modes") or (0, 2, 3, 5))
    return [replace(c, deterministic=1, sparse_mode=m) for m in modes]


GENERATORS: dict[str, Generator] = {
    "pse": _pse,
    "keep_prob": _keep_prob,
    "rope": _rope,
    "atten_mask": _atten_mask,
    "tnd_layout": _tnd_layout,
    "d_ladder": _d_ladder,
    "d1_pair": _d1_pair,
    "s1_ladder": _s1_ladder,
    "s2_ladder": _s2_ladder,
    "input_dtype": _input_dtype,
    "out_dtype": _out_dtype,
    "deter_sparse": _deter_sparse,
}


def _from_bindings(case: I.Case, dim: str, want: str) -> list[I.Case]:
    """Best-effort Binding reverse map for dims without a special generator.

    Returns empty when the dimension only reads tiling state or when no
    Binding maps onto a Case field we know how to write. That emptiness is
    the signal cone uses to fall back to a size grid.
    """
    try:
        from . import bridge as B
        field = B.fields().get(dim)
    except Exception:
        return []
    if not field:
        return []
    spec = default_spec()
    by_var = {b.var: b for b in spec.bindings}
    # If every variable is unbound tiling state, there is no CaseKnob.
    vars_ = list(field.get("variables") or [])
    if vars_ and all(v not in by_var for v in vars_):
        return []
    return []
