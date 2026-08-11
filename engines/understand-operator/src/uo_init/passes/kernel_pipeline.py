# -*- coding: utf-8 -*-
"""Derived Kernel pipeline view from Operation DAG (not a canonical source fact).

Order of work: classify → src/dst memory (CopyIn/Out) → stages → overlap.
Never invent CopyIn/Compute/CopyOut solely from function names.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind

_LOCAL = {"UB", "L1", "L0A", "L0B", "L0C"}
# Workspace is GM-backed staging; treat as GM-like for CopyIn/Out direction.
_GM_LIKE = {"GM", "WORKSPACE"}
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


def _exec_rank(ent) -> int:
    try:
        return int(ent.attrs.get("exec_rank") if ent.attrs.get("exec_rank") is not None else -1)
    except (TypeError, ValueError):
        return -1


def _base_stage(op_attrs: dict[str, Any]) -> str:
    cat = str(op_attrs.get("category") or "")
    eng = str(op_attrs.get("engine") or "").upper()
    base = _STAGE_BY_CATEGORY.get(cat, "Other")
    if base == "Compute":
        if eng == "CUBE":
            return "ComputeCube"
        if eng == "VECTOR":
            return "ComputeVector"
    return base


def _mem_spaces(codemap: CodeMap, op_id: str) -> tuple[set[str], set[str]]:
    src: set[str] = set()
    dst: set[str] = set()
    for _rel, buf in codemap.neighbors(op_id, kind=RelationKind.READS_BUFFER, direction="out"):
        src.add(str(buf.attrs.get("memory_space") or "UNKNOWN"))
    for _rel, buf in codemap.neighbors(op_id, kind=RelationKind.WRITES_BUFFER, direction="out"):
        dst.add(str(buf.attrs.get("memory_space") or "UNKNOWN"))
    return src, dst


def _refine_copy_stage(src: set[str], dst: set[str]) -> str:
    """GM/WORKSPACE→UB/L1 = CopyIn; UB/L1→GM/WORKSPACE = CopyOut; else InternalTransfer."""
    src_gm = bool(src & _GM_LIKE)
    dst_gm = bool(dst & _GM_LIKE)
    src_local = bool(src & _LOCAL)
    dst_local = bool(dst & _LOCAL)
    if src_gm and dst_local:
        return "CopyIn"
    if src_local and dst_gm:
        return "CopyOut"
    if src or dst:
        return "InternalTransfer"
    return "Copy"


def _reachable(adj: dict[str, set[str]], src: str, dst: str) -> bool:
    if src == dst:
        return True
    seen = {src}
    q: deque[str] = deque([src])
    while q:
        cur = q.popleft()
        for nxt in adj.get(cur) or ():
            if nxt == dst:
                return True
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return False


def _dep_order_graph(codemap: CodeMap) -> tuple[dict[str, set[str]], set[tuple[str, str]]]:
    """Forward must-precede edges from HB + DATA_DEPENDS (not PRECEDES)."""
    adj: dict[str, set[str]] = defaultdict(set)
    raw_pairs: set[tuple[str, str]] = set()
    for rel in codemap.relations.values():
        kind = rel.kind_name()
        if kind == RelationKind.HAPPENS_BEFORE.value:
            adj[rel.src].add(rel.dst)
        elif kind == RelationKind.DATA_DEPENDS_ON.value:
            # Consumer → producer in link; producer must precede consumer.
            adj[rel.dst].add(rel.src)
            if str(rel.attrs.get("hazard") or "") == "RAW":
                raw_pairs.add((rel.dst, rel.src))
                raw_pairs.add((rel.src, rel.dst))
    return adj, raw_pairs


def analyze_kernel_pipeline(codemap: CodeMap) -> dict[str, Any]:
    """Build a derived pipeline view and store it in ``codemap.meta``."""
    ops = sorted(
        codemap.by_kind(EntityKind.OPERATION),
        key=lambda e: (
            _exec_rank(e) if _exec_rank(e) >= 0 else 10**9,
            e.file,
            e.line_start,
            int(e.attrs.get("column") or 0),
            int(e.attrs.get("ordinal") or 0),
        ),
    )

    # 1) Classify + 2) refine Copy by src/dst memory BEFORE building stages.
    copy_in = copy_out = internal = 0
    for op in ops:
        stage = _base_stage(op.attrs)
        if stage == "Copy" and str(op.attrs.get("category") or "") == "memory_transfer":
            src, dst = _mem_spaces(codemap, op.id)
            stage = _refine_copy_stage(src, dst)
            op.attrs["src_memory"] = sorted(src)
            op.attrs["dst_memory"] = sorted(dst)
            if stage == "CopyIn":
                copy_in += 1
            elif stage == "CopyOut":
                copy_out += 1
            elif stage == "InternalTransfer":
                internal += 1
        op.attrs["pipeline_stage_hint"] = stage

    # 3) Stages after refine.
    stages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    lanes: dict[str, list[str]] = defaultdict(list)
    for op in ops:
        stage = str(op.attrs.get("pipeline_stage_hint") or _base_stage(op.attrs))
        row = {
            "id": op.id,
            "callee": op.name,
            "function": op.attrs.get("function"),
            "engine": op.attrs.get("engine"),
            "category": op.attrs.get("category"),
            "file": op.file,
            "line": op.line_start,
            "exec_rank": _exec_rank(op),
            "stage": stage,
            "entry_reachable": op.attrs.get("entry_reachable", True),
        }
        stages[stage].append(row)
        eng = str(op.attrs.get("engine") or "UNKNOWN")
        lanes[eng].append(op.id)

    # 4) Overlap: different engines, no dep-path (HB/DATA), no RAW.
    dep_adj, raw_pairs = _dep_order_graph(codemap)
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
        if (src, dst) in raw_pairs:
            continue
        if _reachable(dep_adj, src, dst) or _reachable(dep_adj, dst, src):
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

    view = {
        "schema": "kernel/execution_pipeline/v1",
        "authority": "derived",
        "stages": {k: v for k, v in sorted(stages.items())},
        "lanes": {k: v for k, v in sorted(lanes.items())},
        "overlap_capable_pairs": overlap[:500],
        "overlap_capable_count": len(overlap),
        "copy_in_hints": copy_in,
        "copy_out_hints": copy_out,
        "internal_transfer_hints": internal,
        "operation_count": len(ops),
        "note": (
            "PIPELINE_STAGE is a derived view from operation DAG / engines / "
            "buffer deps — not a canonical compiler fact. Overlap requires "
            "different engines, no HB/DATA path, and no RAW hazard."
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
