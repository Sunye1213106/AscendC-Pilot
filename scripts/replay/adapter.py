# -*- coding: utf-8 -*-
"""Expanding a FlashAttentionScoreGrad case into what the host is handed.

This is the operator's half of P2. Shapes, dtypes and report columns come
from the operator package's InputSemantics; this file only expands them into
the MaterializedCase the engine's four exits share.

Since P3 this file names no variables. It says what the case contains, under
the names the operator definition uses, and the bridge spec -- exported from
the derivation rather than written here -- decides which of that the host
actually reads.
"""

from __future__ import annotations

from typing import Any

from . import inputs as I
from .materialized import (
    ROLE_INPUT, ROLE_OUTPUT, ContextValue, MaterializedAttr, MaterializedCase,
    MaterializedTensor)

#: Inputs the host reads the contents of, and where the contents come from.
VALUE_SOURCE = {
    "actual_seq_qlen": "seq_q",
    "actual_seq_kvlen": "seq_kv",
    "prefix": "prefix_n",
}


class OperatorInputAdapter:
    """Expand a case the way the host will read it.

    New code should depend on
    ``scripts.replay.operator_adapter.OperatorAdapter``.
    """

    def materialize(self, case: I.Case, case_id: str = "") -> MaterializedCase:
        sem = I.SEMANTICS
        c = sem.normalize(case)
        ins, outs = sem.shapes(c)
        main = I.DT[c.dtype]

        return MaterializedCase(
            case_id=case_id,
            inputs=tuple(self._tensor(c, name, ins, main, ROLE_INPUT)
                         for name in sem.in_order),
            outputs=tuple(self._tensor(c, name, outs, main, ROLE_OUTPUT)
                          for name in sem.out_order),
            attrs=self._attrs(c),
            # What the host reads off the session rather than off an
            # argument. The platform's architecture is not here: it is the
            # same for every case the spec covers, so the spec carries it.
            context=(
                ContextValue("VAR_SESSION_DETERMINISTIC", bool(c.deterministic)),
            ),
            report=sem.describe(c),
            driver_flags=(str(c.deterministic),),
        )

    def _tensor(self, c: I.Case, name: str, shapes: dict, main: int,
                role: str) -> MaterializedTensor:
        dims = tuple(shapes.get(name) or ())
        source = VALUE_SOURCE.get(name) if role == ROLE_INPUT else None
        values = getattr(c, source, None) if source else None
        return MaterializedTensor(
            name=name,
            present=bool(dims),
            dims=dims,
            # Outputs are written in the case's own dtype; only inputs have a
            # type of their own to respect.
            dtype=I.SEMANTICS.dtype_of(c, name, main) if role == ROLE_INPUT
            else main,
            values=tuple(values) if values else None,
            read_by_value=source is not None,
            role=role,
        )

    def _attrs(self, c: I.Case) -> tuple[MaterializedAttr, ...]:
        scale = 1.0 / (c.d ** 0.5)
        raw: list[tuple[str, str, Any, str]] = [
            # The only attr whose two readings differ: the line takes eight
            # decimals, the solver takes the number.
            ("scale_value", "f", scale, f"{scale:.8f}"),
            ("keep_prob", "f", c.keep_prob, ""),
            ("pre_tockens", "i", c.pre_tokens, ""),
            ("next_tockens", "i", c.next_tokens, ""),
            ("head_num", "i", c.n1, ""),
            ("input_layout", "s", c.layout, ""),
            ("inner_precise", "i", c.inner_precise, ""),
            ("sparse_mode", "i", c.sparse_mode, ""),
            ("pse_type", "i", c.pse_type, ""),
            # The dropout generator's seed and offset, and a softmax layout
            # the host accepts and never reads. No tiling decision touches
            # them, which is why no variable holds them.
            ("seed", "i", 2, ""),
            ("offset", "i", 0, ""),
            ("out_dtype", "i", c.out_dtype, ""),
            ("softmax_in_layout", "s", "", ""),
        ]
        return tuple(
            MaterializedAttr(name=name, kind=kind, value=value, text=text)
            for name, kind, value, text in raw)


ADAPTER = OperatorInputAdapter()
