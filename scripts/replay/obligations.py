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

    Named knobs below mirror the special generators so a hints file that
    omits them still drives search, and so the write side is testable on its
    own. Generic presence/attr/context inversion covers anything else whose
    `variables` intersect the bridge_spec bindings.
    """
    named = _binding_named(case, dim, want)
    if named is not None:
        return named
    try:
        from . import bridge as B
        field = B.fields().get(dim)
    except Exception:
        return []
    if not field:
        return []
    spec = default_spec()
    by_var = {b.var: b for b in spec.bindings}
    vars_ = list(field.get("variables") or [])
    if vars_ and all(v not in by_var for v in vars_):
        return []
    return _binding_generic(case, want, vars_, by_var)


def _binding_named(case: I.Case, dim: str, want: str) -> list[I.Case] | None:
    """Dims whose Case knobs are declared in ``search_hints.named_bindings``.

    Returns None when this dim has no named knob (caller tries generic).
    Returns [] when the named knob exists but cannot produce a Case for want.
    """
    hints = load_hints()
    table = hints.get("named_bindings") or {}
    spec = table.get(dim)
    if not isinstance(spec, dict):
        return None
    return _apply_named_binding(case, want, spec, hints)


def _apply_named_binding(
    case: I.Case,
    want: str,
    spec: Mapping[str, Any],
    hints: Mapping[str, Any],
) -> list[I.Case]:
    from .knobs import write_binding
    from .bridge_spec import Binding

    kind = str(spec.get("kind") or "").strip()
    if kind == "presence":
        var = str(spec.get("var") or "")
        tensor = str(spec.get("tensor") or "")
        if not var or not tensor:
            return []
        got = write_binding(
            case,
            Binding(var=var, root="OPTIONAL_INPUT_PRESENCE",
                    kind="optional_presence", operand=tensor),
            want == "1",
        )
        if got is None:
            return []
        if want == "1" and spec.get("on_field"):
            field = str(spec["on_field"])
            values = list(spec.get("on_values") or [])
            if not values and str(spec.get("on_values_attr") or "") == "PSE_SHAPES":
                values = list(I.PSE_SHAPES)
            if not values and str(spec.get("on_values_attr") or "") == "ATTEN_MASKS":
                values = [m for m in I.ATTEN_MASKS if m != "none"]
            if values:
                return [replace(got, **{field: v}) for v in values]
        return [got]

    if kind == "dtype":
        codes = hints.get(str(spec.get("codes_key") or "input_dtype_codes")) or {}
        name = codes.get(want)
        if not name:
            return []
        got = write_binding(
            case,
            Binding(
                var=str(spec.get("var") or "VAR_DTYPE_QUERY"),
                root=str(spec.get("root") or "INPUT_DTYPE"),
                kind="tensor_dtype",
                operand=str(spec.get("operand") or "query"),
            ),
            name,
        )
        return [got] if got is not None else []

    if kind == "case_field":
        field = str(spec.get("field") or "")
        if not field:
            return []
        cast = str(spec.get("cast") or "str")
        value: Any = want
        if cast == "int":
            value = int(want)
        elif cast == "bool":
            value = want in ("1", "true", "True")
        return [replace(case, **{field: value})]

    if kind == "ladder":
        field = str(spec.get("field") or "")
        if not field:
            return []
        want_i = int(want)
        mode = str(spec.get("mode") or "template")
        values: list[int]
        if mode == "template":
            values = [want_i, want_i - 1, want_i + 1, want_i * 2]
        elif mode == "s2":
            values = [want_i, want_i - 1, want_i * 2]
        elif mode == "d":
            values = list({want_i, max(1, want_i - 1)})
        else:
            values = [want_i]
        out = []
        for v in values:
            if v <= 0:
                continue
            kwargs: dict[str, Any] = {field: v}
            if field == "d" and getattr(case, "d1", None) is not None:
                kwargs["d1"] = None if (case.d1 or case.d) >= v else case.d1
            out.append(replace(case, **kwargs))
        return out

    if kind == "d1_pair":
        if want == "1":
            steps = list((hints.get("ladders") or {}).get("d1_on") or (64,))
            return [replace(case, d1=v) for v in steps if v < (case.d or 128)]
        return [replace(case, d1=None)]

    if kind == "group_equal":
        # e.g. IsNEqual: want 1 → g=1; want 0 → g>1
        on = dict(spec.get("on") or {"g": 1})
        off = dict(spec.get("off") or {"g": 2})
        if want == "1":
            return [replace(case, **on)]
        kwargs = dict(off)
        if "n2" in kwargs and kwargs["n2"] == "max1":
            kwargs["n2"] = max(1, case.n2)
        return [replace(case, **kwargs)]

    return []


def _binding_generic(
    case: I.Case,
    want: str,
    vars_: list[str],
    by_var: dict[str, Any],
) -> list[I.Case]:
    """Invert boolean-ish wants against presence / attr / context bindings.

    Non-boolean wants (e.g. SplitAxis=5) must stay empty: a dim whose
    variables merely *mention* presence knobs must not invent Cases by
    flipping those knobs when the target value is numeric host state.
    """
    from .knobs import write_binding

    if want not in ("0", "1", "true", "false", "True", "False"):
        return []
    out: list[I.Case] = []
    truthy = want not in ("0", "false", "False")
    for var in vars_:
        binding = by_var.get(var)
        if binding is None:
            continue
        if binding.kind == "optional_presence":
            got = write_binding(case, binding, truthy)
            if got is not None:
                out.append(got)
        elif binding.kind == "attr" and binding.operand == "keep_prob":
            got = write_binding(case, binding, 0.5 if truthy else 1.0)
            if got is not None:
                out.append(got)
        elif binding.kind == "context" and binding.var == "VAR_SESSION_DETERMINISTIC":
            got = write_binding(case, binding, truthy)
            if got is not None:
                out.append(got)
    # Deduplicate by Case field snapshot.
    seen: set[tuple] = set()
    uniq: list[I.Case] = []
    for c in out:
        key = (c.pse, c.atten_mask, c.keep_prob, c.rope, c.deterministic,
               c.dtype, c.layout, c.sparse_mode, c.s1, c.s2, c.d, c.d1, c.g)
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq
