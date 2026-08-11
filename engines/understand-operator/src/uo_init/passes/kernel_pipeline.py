# -*- coding: utf-8 -*-
"""Derived Kernel pipeline view from Operation DAG (not a canonical source fact).

Pipeline stages are inferred from operation categories + engines + buffer deps.
Never invent CopyIn/Compute/CopyOut solely from function names.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind

_STAGE_BY_CATEGORY = {
    "memory_transfer": "Copy",
    "memory_init": "Copy",
    "buffer_acquire": "BufferMgmt",
    "buffer_release": "BufferMgmt",
    "buffer_init": "BufferMgmt",
    "queue_enqueue": "BufferMgmt",
    "queue_dequeue": "BufferMgmt",
    "buffer_view": "BufferMgmt",
    "vector_compute": "Compute",
    "cube_compute": "Compute",
    "cube_load": "Copy",
    "cube_store": "Copy",
    "sync_signal": "Sync",
    "sync_wait": "Sync",
    "sync_barrier": "Sync",
}


def _stage_for(op_attrs: dict[str, Any]) -> str:
    cat = str(op_attrs.get("category") or "")
    eng = str(op_attrs.get("engine") or "").upper()
    base = _STAGE_BY_CATEGORY.get(cat, "Other")
    if base == "Copy":
        if eng in {"MTE", "MTE2", "MTE3"}:
            # Direction hint from reads/writes memory spaces is done later.
            return "Copy"
        return "Copy"
    if base == "Compute":
        if eng == "CUBE":
            return "ComputeCube"
        if eng == "VECTOR":
            return "ComputeVector"
        return "Compute"
    return base


def analyze_kernel_pipeline(codemap: CodeMap) -> dict[str, Any]:
    """Build a derived pipeline view and store it in ``codemap.meta``."""
    ops = sorted(
        codemap.by_kind(EntityKind.OPERATION),
        key=lambda e: (e.file, e.line_start, int(e.attrs.get("column") or 0), int(e.attrs.get("ordinal") or 0)),
    )
    stages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    lanes: dict[str, list[str]] = defaultdict(list)
    for op in ops:
        stage = _stage_for(op.attrs)
        row = {
            "id": op.id,
            "callee": op.name,
            "function": op.attrs.get("function"),
            "engine": op.attrs.get("engine"),
            "category": op.attrs.get("category"),
            "file": op.file,
            "line": op.line_start,
            "stage": stage,
            "entry_reachable": op.attrs.get("entry_reachable", True),
        }
        stages[stage].append(row)
        eng = str(op.attrs.get("engine") or "UNKNOWN")
        lanes[eng].append(op.id)

    # Overlap-capable pairs: consecutive program-order ops on different engines
    # with no HAPPENS_BEFORE edge between them.
    hb: set[tuple[str, str]] = set()
    for rel in codemap.relations.values():
        if rel.kind_name() == RelationKind.HAPPENS_BEFORE.value:
            hb.add((rel.src, rel.dst))

    precedes: list[tuple[str, str]] = []
    for rel in codemap.relations.values():
        if rel.kind_name() == RelationKind.PRECEDES.value:
            precedes.append((rel.src, rel.dst))

    overlap: list[dict[str, Any]] = []
    for src, dst in precedes:
        a = codemap.entities.get(src)
        b = codemap.entities.get(dst)
        if not a or not b:
            continue
        ea = str(a.attrs.get("engine") or "")
        eb = str(b.attrs.get("engine") or "")
        if not ea or not eb or ea == eb or ea == "UNKNOWN" or eb == "UNKNOWN":
            continue
        if (src, dst) in hb:
            continue
        overlap.append(
            {
                "a": src,
                "b": dst,
                "a_engine": ea,
                "b_engine": eb,
                "status": "overlap-capable",
                "confidence": "partial",
            }
        )

    # Refine Copy → CopyIn/CopyOut using GM involvement when available.
    buffers = {e.id: e for e in codemap.by_kind(EntityKind.BUFFER)}
    copy_in = 0
    copy_out = 0
    for rel in codemap.relations.values():
        if rel.kind_name() == RelationKind.WRITES_BUFFER.value:
            op = codemap.entities.get(rel.src)
            buf = buffers.get(rel.dst)
            if not op or not buf:
                continue
            if str(op.attrs.get("category")) != "memory_transfer":
                continue
            mem = str(buf.attrs.get("memory_space") or "")
            if mem in {"UB", "L1", "L0A", "L0B", "L0C"}:
                op.attrs["pipeline_stage_hint"] = "CopyIn"
                copy_in += 1
        if rel.kind_name() == RelationKind.READS_BUFFER.value:
            op = codemap.entities.get(rel.src)
            buf = buffers.get(rel.dst)
            if not op or not buf:
                continue
            if str(op.attrs.get("category")) != "memory_transfer":
                continue
            mem = str(buf.attrs.get("memory_space") or "")
            if mem in {"UB", "L1"} and str(op.attrs.get("pipeline_stage_hint") or "") != "CopyIn":
                # reading UB often means compute source; GM write is CopyOut
                pass
        if rel.kind_name() == RelationKind.WRITES_BUFFER.value:
            op = codemap.entities.get(rel.src)
            buf = buffers.get(rel.dst)
            if op and buf and str(buf.attrs.get("memory_space") or "") == "GM":
                if str(op.attrs.get("category")) == "memory_transfer":
                    op.attrs["pipeline_stage_hint"] = "CopyOut"
                    copy_out += 1

    view = {
        "schema": "kernel/execution_pipeline/v1",
        "authority": "derived",
        "stages": {k: v for k, v in sorted(stages.items())},
        "lanes": {k: v for k, v in sorted(lanes.items())},
        "overlap_capable_pairs": overlap[:500],
        "overlap_capable_count": len(overlap),
        "copy_in_hints": copy_in,
        "copy_out_hints": copy_out,
        "operation_count": len(ops),
        "note": (
            "PIPELINE_STAGE is a derived view from operation DAG / engines / "
            "buffer deps — not a canonical compiler fact."
        ),
    }
    codemap.meta["kernel_execution_pipeline"] = view
    return view


def finalize_kernel_pipeline(codemap: CodeMap, *_args: Any, **_kwargs: Any) -> CodeMap:
    if not codemap.by_kind(EntityKind.OPERATION):
        codemap.meta["kernel_execution_pipeline"] = {
            "schema": "kernel/execution_pipeline/v1",
            "authority": "derived",
            "operation_count": 0,
        }
        return codemap
    analyze_kernel_pipeline(codemap)
    return codemap
