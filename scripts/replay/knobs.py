# -*- coding: utf-8 -*-
"""The write side of a Binding: Case quantity ← desired variable value.

`bridge_spec.bind` reads a Case into an environment. This module is the
inverse for the quantities a search can actually set. A Binding whose
operand has no Case field returns None — that emptiness is what keeps
host-state dimensions from inventing a knob.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import inputs as I
from .bridge_spec import (
    ATTR,
    CONTEXT,
    TENSOR_AXIS,
    TENSOR_AXIS_LAST,
    TENSOR_DTYPE,
    TENSOR_PRESENCE,
    Binding,
)

#: optional_presence operand → Case field writer (keys are squash()'d).
_PRESENCE: dict[str, str] = {
    "pseshift": "pse",
    "attenmask": "atten_mask",
    "dropmask": "drop",
    "queryrope": "rope",
    "keyrope": "rope",
    "queryropeidx": "rope",
    "keyropeidx": "rope",
}

#: attr operand → Case field.
_ATTR: dict[str, str] = {
    "keep_prob": "keep_prob",
    "input_layout": "layout",
    "sparse_mode": "sparse_mode",
    "pre_tockens": "pre_tokens",
    "next_tockens": "next_tokens",
    "head_num": "head_num",
}


def _squash(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", text.lower())


def write_binding(case: I.Case, binding: Binding, value: Any) -> I.Case | None:
    """Apply one Binding's desired value to a Case, or None if unwritable."""
    kind = binding.kind
    if kind == TENSOR_PRESENCE:
        return _write_presence(case, binding.operand, bool(value))
    if kind == ATTR:
        return _write_attr(case, binding.operand, value)
    if kind == TENSOR_DTYPE:
        return _write_dtype(case, binding.operand, value)
    if kind == CONTEXT:
        return _write_context(case, binding.var, value)
    if kind in (TENSOR_AXIS, TENSOR_AXIS_LAST):
        return _write_axis(case, binding, value)
    return None


def _write_presence(case: I.Case, operand: str, present: bool) -> I.Case | None:
    field = _PRESENCE.get(_squash(operand))
    if field is None:
        return None
    if field == "pse":
        if present:
            return replace(case, pse=True, pse_shape=case.pse_shape or "bnss")
        return replace(case, pse=False)
    if field == "atten_mask":
        if present:
            mask = case.atten_mask if case.atten_mask != "none" else "ss"
            return replace(case, atten_mask=mask)
        return replace(case, atten_mask="none")
    if field == "drop":
        if present:
            return replace(case, keep_prob=0.5 if case.keep_prob >= 1.0 else case.keep_prob)
        return replace(case, keep_prob=1.0)
    if field == "rope":
        if present:
            return replace(case, rope=True, d=I.ROPE_TOTAL_D, d1=None)
        return replace(case, rope=False)
    return None


def _write_attr(case: I.Case, operand: str, value: Any) -> I.Case | None:
    field = {
        "keep_prob": "keep_prob",
        "input_layout": "layout",
        "sparse_mode": "sparse_mode",
        "pre_tockens": "pre_tokens",
        "next_tockens": "next_tokens",
        "head_num": "head_num",
    }.get(operand) or {
        "keepprob": "keep_prob",
        "inputlayout": "layout",
        "sparsemode": "sparse_mode",
        "pretockens": "pre_tokens",
        "nexttockens": "next_tokens",
        "headnum": "head_num",
    }.get(_squash(operand))
    if field is None:
        return None
    if field == "keep_prob":
        return replace(case, keep_prob=float(value))
    if field == "layout":
        layout = str(value)
        if layout == "TND":
            n = max(1, case.b)
            return replace(
                case, layout="TND",
                seq_q=case.seq_q or [case.s1] * n,
                seq_kv=case.seq_kv or [case.s2] * n,
            )
        return replace(case, layout=layout, seq_q=None, seq_kv=None)
    if field == "sparse_mode":
        return replace(case, sparse_mode=int(value))
    if field == "pre_tokens":
        return replace(case, pre_tokens=int(value))
    if field == "next_tokens":
        return replace(case, next_tokens=int(value))
    if field == "head_num":
        g = max(1, case.g)
        return replace(case, n2=max(1, int(value) // g))
    return None


def _write_dtype(case: I.Case, operand: str, value: Any) -> I.Case | None:
    if _squash(operand) not in ("query", "key", "value", "dy"):
        return None
    # Accept either a DT code (int) or a name the Case.dtype field uses.
    if isinstance(value, str) and value in I.DT:
        return replace(case, dtype=value)
    code = int(value)
    for name, dt in I.DT.items():
        if dt == code:
            return replace(case, dtype=name)
    return None


def _write_context(case: I.Case, var: str, value: Any) -> I.Case | None:
    if var == "VAR_SESSION_DETERMINISTIC":
        return replace(case, deterministic=1 if value else 0)
    # Platform arch is a run property, not a Case knob.
    return None


def _write_axis(case: I.Case, binding: Binding, value: Any) -> I.Case | None:
    """Best-effort axis write for the common FAG shape knobs.

    Layout-aware mapping is incomplete by design: only the axes the search
    already ladders (S1/S2/D) are inverted here. Unknown (tensor, axis) pairs
    return None so cone keeps its size grid.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    tensor = _squash(binding.operand)
    axis = binding.axis
    if binding.kind == TENSOR_AXIS_LAST:
        # Last axis of query is D under BNSD/BSND.
        if tensor == "query":
            return replace(case, d=n, d1=None if (case.d1 or case.d) >= n else case.d1)
        return None
    if axis is None:
        return None
    # BSND/BNSD-ish: treat axis 1 as an S-like extent when the tensor is query.
    if tensor == "query":
        if axis in (1, 2) and n in (64, 128, 256, 512, 1024, 2048):
            # Ambiguous between S1 and S2; prefer s1 for odd wants of template.
            return replace(case, s1=n)
        if axis >= 2 and n in (64, 128, 192, 256, 512, 768):
            return replace(case, d=n, d1=None if (case.d1 or case.d) >= n else case.d1)
    if tensor == "value" and axis >= 2:
        return replace(case, d1=n)
    return None


def apply_writes(
    case: I.Case, writes: list[tuple[Binding, Any]]
) -> I.Case | None:
    """Compose several Binding writes; None if any step is unwritable."""
    out = case
    for binding, value in writes:
        nxt = write_binding(out, binding, value)
        if nxt is None:
            return None
        out = nxt
    return out
