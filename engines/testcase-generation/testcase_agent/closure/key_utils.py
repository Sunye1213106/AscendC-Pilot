# -*- coding: utf-8 -*-
"""Exact integer helpers for tiling-key sized values.

Tiling keys are often 17-digit integers.  They fit in signed int64, but they do
not fit in IEEE-754's exact integer range.  Any ``int(float(value))`` hop can
silently change the key and corrupt mismatch analysis.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import numbers
from typing import Any


def int_exact(value: Any, default: int = 0) -> int:
    """Parse an integer-like value without routing decimal strings via float."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        try:
            f = float(value)
            if not math.isfinite(f):
                return default
            return int(f)
        except (TypeError, ValueError, OverflowError):
            return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "<na>"}:
        return default
    try:
        return int(text, 10)
    except ValueError:
        pass
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return default
    if not dec.is_finite():
        return default
    try:
        return int(dec.to_integral_exact())
    except (InvalidOperation, ValueError):
        return default
