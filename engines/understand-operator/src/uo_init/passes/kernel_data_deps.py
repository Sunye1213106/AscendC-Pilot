# -*- coding: utf-8 -*-
"""Derive RAW/WAR/WAW data dependencies from buffer accesses + exec_rank."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def _exec_rank(ent) -> int:
    try:
        return int(ent.attrs.get("exec_rank") if ent.attrs.get("exec_rank") is not None else -1)
    except (TypeError, ValueError):
        return -1


def finalize_kernel_data_deps(codemap: CodeMap, *_args: Any, **_kwargs: Any) -> CodeMap:
    """Emit DATA_DEPENDS_ON edges; strengthen HAPPENS_BEFORE for confirmed RAW."""
    drop_ids: list[str] = []
    for rid, rel in codemap.relations.items():
        kind = rel.kind_name()
        if kind == RelationKind.DATA_DEPENDS_ON.value:
            drop_ids.append(rid)
        elif (
            kind == RelationKind.HAPPENS_BEFORE.value
            and str(rel.attrs.get("provenance") or "") == "kernel_data_dep_raw"
        ):
            drop_ids.append(rid)
    for rid in drop_ids:
        codemap.relations.pop(rid, None)

    # Single pass over relations — avoid per-op neighbors() scans.
    writes: dict[str, list[str]] = defaultdict(list)
    reads: dict[str, list[str]] = defaultdict(list)
    for rel in codemap.relations.values():
        kind = rel.kind_name()
        if kind == RelationKind.WRITES_BUFFER.value:
            writes[rel.src].append(rel.dst)
        elif kind == RelationKind.READS_BUFFER.value:
            reads[rel.src].append(rel.dst)

    ops = sorted(
        codemap.by_kind(EntityKind.OPERATION),
        key=lambda e: (_exec_rank(e), e.file, e.line_start, int(e.attrs.get("column") or 0)),
    )
    accesses: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for op in ops:
        rank = _exec_rank(op)
        for buf_id in writes.get(op.id, ()):
            accesses[buf_id].append((op.id, "write", rank))
        for buf_id in reads.get(op.id, ()):
            accesses[buf_id].append((op.id, "read", rank))

    raw = war = waw = 0
    for buf_id, rows in accesses.items():
        rows.sort(key=lambda t: (t[2], 0 if t[1] == "write" else 1))
        last_write: str | None = None
        last_reads: list[str] = []
        for op_id, role, _rank in rows:
            if role == "read":
                if last_write and last_write != op_id:
                    codemap.link(
                        RelationKind.DATA_DEPENDS_ON,
                        op_id,
                        last_write,
                        attrs={
                            "hazard": "RAW",
                            "buffer_id": buf_id,
                            "provenance": "kernel_data_deps",
                        },
                        status="confirmed",
                    )
                    codemap.link(
                        RelationKind.HAPPENS_BEFORE,
                        last_write,
                        op_id,
                        attrs={
                            "provenance": "kernel_data_dep_raw",
                            "via": "RAW",
                            "buffer_id": buf_id,
                        },
                        status="confirmed",
                    )
                    raw += 1
                last_reads.append(op_id)
            else:
                if last_write and last_write != op_id:
                    codemap.link(
                        RelationKind.DATA_DEPENDS_ON,
                        op_id,
                        last_write,
                        attrs={
                            "hazard": "WAW",
                            "buffer_id": buf_id,
                            "provenance": "kernel_data_deps",
                        },
                        status="confirmed",
                    )
                    waw += 1
                for reader in last_reads:
                    if reader == op_id:
                        continue
                    codemap.link(
                        RelationKind.DATA_DEPENDS_ON,
                        op_id,
                        reader,
                        attrs={
                            "hazard": "WAR",
                            "buffer_id": buf_id,
                            "provenance": "kernel_data_deps",
                        },
                        status="confirmed",
                    )
                    war += 1
                last_write = op_id
                last_reads = []

    prev = dict(codemap.meta.get("kernel_execution") or {})
    prev.update(
        {
            "data_deps_raw": raw,
            "data_deps_war": war,
            "data_deps_waw": waw,
            "data_deps_total": raw + war + waw,
        }
    )
    quality = dict(prev.get("quality") or {})
    quality.update(
        {
            "data_deps_raw": raw,
            "data_deps_war": war,
            "data_deps_waw": waw,
            "data_deps_total": raw + war + waw,
        }
    )
    prev["quality"] = quality
    codemap.meta["kernel_execution"] = prev
    return codemap
