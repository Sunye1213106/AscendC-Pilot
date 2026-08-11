# -*- coding: utf-8 -*-
"""Unified AscendC CodeMap IR.

All Host / Kernel / Tiling / Macro / Template facts land in one graph.
Legacy IR modules adapt into :class:`CodeMap` rather than writing their own
persistent projections.

``KernelExecutionIR`` (``ir/kernel_execution.py``) is the runtime execution
model (operations / buffers / sync), distinct from compile-time ``KernelIR``.
"""

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.kernel_execution import (
    Buffer,
    BufferView,
    ExecOperation,
    ExecRegion,
    KernelExecutionIR,
    SyncEvent,
)
from uo_init.ir.relation import Relation, RelationKind

__all__ = [
    "Buffer",
    "BufferView",
    "CodeMap",
    "Entity",
    "EntityKind",
    "ExecOperation",
    "ExecRegion",
    "KernelExecutionIR",
    "Relation",
    "RelationKind",
    "SyncEvent",
]
