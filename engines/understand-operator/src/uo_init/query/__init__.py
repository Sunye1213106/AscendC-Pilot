# -*- coding: utf-8 -*-
"""CodeMap query API for agents (schema-agnostic)."""

from uo_init.query.engine import CodeMapQuery, open_codemap_query
from uo_init.query.slice import slice_backward, slice_forward

__all__ = [
    "CodeMapQuery",
    "open_codemap_query",
    "slice_backward",
    "slice_forward",
]
