# -*- coding: utf-8 -*-
"""Lexical SourceIndex — one scan per file, many queries afterwards."""

from uo_init.source_index.builder import SourceIndexBuilder, get_or_build, reset_index_cache
from uo_init.source_index.model import SourceFacts, SourceIndex

__all__ = [
    "SourceFacts",
    "SourceIndex",
    "SourceIndexBuilder",
    "get_or_build",
    "reset_index_cache",
]
