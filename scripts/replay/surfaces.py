# -*- coding: utf-8 -*-
"""Which functions the contract gate should audit, for this operator.

Everything here is FlashAttentionScoreGrad-specific and none of it is
interesting: it is the list of doors, written down so the gate does not have
to import the operator to find them. After P1 the same object is built from
`operator.yaml` and this module goes away.
"""

from __future__ import annotations

from typing import Any, Mapping

from . import bridge as B
from . import corpus as C
from . import inputs as I
from .adapter import ADAPTER
from .contract_audit import Surfaces
from .materialized import default_spec

#: Inputs whose contents the host reads, so the line carries values rather
#: than an extent.
VALUE_TENSORS = frozenset({"actual_seq_qlen", "actual_seq_kvlen", "prefix"})


def _rebuild(row: Mapping[str, Any]) -> I.Case:
    """Rebuild a case the way a later run reads it back.

    The row is stringified first. That is not a formality: the report is
    written to a wide CSV and read back as text, so a round trip that skips
    the text is a round trip the pipeline never performs.
    """
    return C.case_of({k: "" if v is None else str(v) for k, v in row.items()})


def fag() -> Surfaces:
    """The generator surfaces for FlashAttentionScoreGrad."""
    return Surfaces(
        in_order=tuple(I.IN_ORDER),
        out_order=tuple(I.OUT_ORDER),
        spec=default_spec(),
        serialize=I.to_csv_line,
        static_env=B.env_of,
        report=I.describe,
        rebuild=_rebuild,
        value_tensors=VALUE_TENSORS,
        enums=I.SEMANTICS.enums(),
        # A pse shape only has to name something real when there is a pse.
        enum_guards={"pse_shape": lambda c: bool(c.pse)},
        # scale_value is written with eight decimals, so an exact comparison
        # against 1/sqrt(d) fails on d values whose root is not representable.
        float_tol=1e-7,
        materialize=ADAPTER.materialize,
    )
