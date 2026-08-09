# -*- coding: utf-8 -*-
"""Unified AscendC CodeMap IR.

All Host / Kernel / Tiling / Macro / Template facts land in one graph.
Legacy IR modules adapt into :class:`CodeMap` rather than writing their own
persistent projections.
"""

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind

__all__ = [
    "CodeMap",
    "Entity",
    "EntityKind",
    "Relation",
    "RelationKind",
]
