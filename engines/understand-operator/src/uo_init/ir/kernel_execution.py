# -*- coding: utf-8 -*-
"""Kernel Execution IR — runtime execution semantics (not compile-time KernelIR).

Host answers "why this Kernel / where Tiling params come from".
Kernel Execution IR answers "once selected, how does it execute".

Track only execution-relevant values: buffer address/offset/size/stride,
loop bounds, operation args, sync identity, template/runtime guards,
core/pipe selection. Do not chase every scalar assignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecOperation:
    """One operation occurrence (site), never a collapsed callee symbol."""

    id: str
    callee: str
    category: str = "UNKNOWN"
    engine: str = "UNKNOWN"
    function: str = ""
    file: str = ""
    line: int = 0
    column: int = 0
    ordinal: int = 0
    args: list[str] = field(default_factory=list)
    receiver: str = ""
    guards: list[str] = field(default_factory=list)
    loop_stack: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    execution_domain: str = "UNKNOWN"
    provenance: str = "clang"
    confidence: str = "confirmed"
    registry_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "callee": self.callee,
            "category": self.category,
            "engine": self.engine,
            "function": self.function,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "ordinal": self.ordinal,
            "args": list(self.args),
            "receiver": self.receiver,
            "guards": list(self.guards),
            "loop_stack": list(self.loop_stack),
            "reads": list(self.reads),
            "writes": list(self.writes),
            "execution_domain": self.execution_domain,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "registry_version": self.registry_version,
        }


@dataclass
class Buffer:
    """Buffer storage identity (not a bare name)."""

    id: str
    name: str
    kind: str = ""
    memory_space: str = "UNKNOWN"
    backing: str = ""
    size_expr: str = ""
    scope: str = ""
    file: str = ""
    line: int = 0
    queue_depth: int | None = None
    provenance: str = "clang"
    confidence: str = "confirmed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "memory_space": self.memory_space,
            "backing": self.backing,
            "size_expr": self.size_expr,
            "scope": self.scope,
            "file": self.file,
            "line": self.line,
            "queue_depth": self.queue_depth,
            "provenance": self.provenance,
            "confidence": self.confidence,
        }


@dataclass
class BufferView:
    """View / alias / slice / reinterpret of a Buffer."""

    id: str
    name: str
    of_buffer: str
    offset_expr: str = ""
    reinterpret: str = ""
    file: str = ""
    line: int = 0
    provenance: str = "clang"
    confidence: str = "confirmed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "of_buffer": self.of_buffer,
            "offset_expr": self.offset_expr,
            "reinterpret": self.reinterpret,
            "file": self.file,
            "line": self.line,
            "provenance": self.provenance,
            "confidence": self.confidence,
        }


@dataclass
class SyncEvent:
    """SetFlag / WaitFlag / Barrier / cross-core sync site."""

    id: str
    kind: str
    file: str = ""
    line: int = 0
    column: int = 0
    function: str = ""
    flag: str = ""
    pipe: str = ""
    event: str = ""
    buffer_identity: str = ""
    cross_core: bool = False
    src_engine: str = ""
    dst_engine: str = ""
    guards: list[str] = field(default_factory=list)
    loop_stack: list[str] = field(default_factory=list)
    operation_id: str = ""
    provenance: str = "clang"
    confidence: str = "confirmed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "function": self.function,
            "flag": self.flag,
            "pipe": self.pipe,
            "event": self.event,
            "buffer_identity": self.buffer_identity,
            "cross_core": self.cross_core,
            "src_engine": self.src_engine,
            "dst_engine": self.dst_engine,
            "guards": list(self.guards),
            "loop_stack": list(self.loop_stack),
            "operation_id": self.operation_id,
            "provenance": self.provenance,
            "confidence": self.confidence,
        }


@dataclass
class ExecRegion:
    """Function / Loop / Branch / CompileGuard region (not derived pipeline stage)."""

    id: str
    kind: str
    name: str = ""
    function: str = ""
    file: str = ""
    line: int = 0
    execution_domain: str = "UNKNOWN"
    guards: list[str] = field(default_factory=list)
    provenance: str = "clang"
    confidence: str = "confirmed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "function": self.function,
            "file": self.file,
            "line": self.line,
            "execution_domain": self.execution_domain,
            "guards": list(self.guards),
            "provenance": self.provenance,
            "confidence": self.confidence,
        }


@dataclass
class KernelExecutionIR:
    """Runtime execution model for selected Kernel code."""

    operations: list[ExecOperation] = field(default_factory=list)
    buffers: list[Buffer] = field(default_factory=list)
    buffer_views: list[BufferView] = field(default_factory=list)
    sync_events: list[SyncEvent] = field(default_factory=list)
    regions: list[ExecRegion] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    registry_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "uo-kernel-execution-ir/v1",
            "registry_version": self.registry_version,
            "operations": len(self.operations),
            "buffers": len(self.buffers),
            "buffer_views": len(self.buffer_views),
            "sync_events": len(self.sync_events),
            "regions": len(self.regions),
            "notes": list(self.notes),
            "detail": {
                "operations": [o.to_dict() for o in self.operations],
                "buffers": [b.to_dict() for b in self.buffers],
                "buffer_views": [v.to_dict() for v in self.buffer_views],
                "sync_events": [s.to_dict() for s in self.sync_events],
                "regions": [r.to_dict() for r in self.regions],
            },
        }
