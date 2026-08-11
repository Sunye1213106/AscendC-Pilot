# -*- coding: utf-8 -*-
"""Assign global exec_rank from Kernel entry call graph + local op order.

Cross-function order must not use source-file dictionary order. Within one
function, (line, column, ordinal) is still the local program order.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.kernel_execution import ExecOperation, FunctionExecSummary, SyncEvent
from uo_init.ir.relation import RelationKind

_BOUND_CALL = {
    "source_kernel_call_bound",
    "source_kernel_macro_call_bound",
    "source_kernel_call_refined",
}


def _local_key(op: ExecOperation) -> tuple[int, int, int]:
    return (int(op.line), int(op.column), int(op.ordinal))


def _func_names(ent_name: str, attrs: dict[str, Any] | None = None) -> set[str]:
    names = {ent_name}
    short = str((attrs or {}).get("short_name") or "").strip()
    if short:
        names.add(short)
    if "::" in ent_name:
        names.add(ent_name.rsplit("::", 1)[-1])
    return {n for n in names if n}


def _call_adj(codemap: CodeMap) -> dict[str, list[tuple[str, int, int]]]:
    """caller_name -> list of (callee_name, line, column) from CALLS sites."""
    adj: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for rel in codemap.relations.values():
        if rel.kind_name() != RelationKind.CALLS.value:
            continue
        prov = str(rel.attrs.get("provenance") or "")
        if prov not in _BOUND_CALL and not prov.startswith("source_kernel"):
            continue
        src = codemap.entities.get(rel.src)
        dst = codemap.entities.get(rel.dst)
        if src is None or dst is None:
            continue
        caller_names = _func_names(src.name, src.attrs)
        callee_names = _func_names(dst.name, dst.attrs)
        sites = rel.attrs.get("sites") or []
        if sites:
            for site in sites:
                if not isinstance(site, dict):
                    continue
                line = int(site.get("line") or rel.attrs.get("line") or 0)
                col = int(site.get("column") or 0)
                for caller in caller_names:
                    for callee in callee_names:
                        adj[caller].append((callee, line, col))
        else:
            line = int(rel.attrs.get("line") or 0)
            for caller in caller_names:
                for callee in callee_names:
                    adj[caller].append((callee, line, 0))
    # Stable order per caller.
    for caller, rows in adj.items():
        rows.sort(key=lambda t: (t[1], t[2], t[0]))
    return adj


def assign_exec_ranks(
    codemap: CodeMap,
    operations: list[ExecOperation],
    sync_events: list[SyncEvent] | None = None,
) -> tuple[list[FunctionExecSummary], dict[str, Any]]:
    """Mutate ``exec_rank`` on operations (and sync events when linked).

    Returns function summaries and a small meta report.
    """
    by_func: dict[str, list[ExecOperation]] = defaultdict(list)
    for op in operations:
        by_func[str(op.function or "")].append(op)
    for rows in by_func.values():
        rows.sort(key=_local_key)

    adj = _call_adj(codemap)
    starts: list[str] = []
    for e in codemap.by_kind(EntityKind.KERNEL):
        if e.attrs.get("source_definition") or e.attrs.get("source_signature"):
            starts.extend(sorted(_func_names(e.name, e.attrs)))
    if not starts:
        # Fall back: functions that contain ops, in local discovery order.
        starts = sorted(n for n in by_func if n)

    rank = 0
    visiting: set[str] = set()
    summaries: dict[str, FunctionExecSummary] = {}
    ranked_ops = 0

    def expand(func: str) -> None:
        nonlocal rank, ranked_ops
        if not func or func in visiting:
            return
        visiting.add(func)
        ops = by_func.get(func) or []
        calls = adj.get(func) or []
        # Merge local ops and outbound calls into one timeline.
        timeline: list[tuple[tuple[int, int, int], str, Any]] = []
        for op in ops:
            timeline.append((_local_key(op), "op", op))
        for callee, line, col in calls:
            timeline.append(((int(line), int(col), -1), "call", callee))
        timeline.sort(key=lambda t: t[0])

        summary = summaries.get(func) or FunctionExecSummary(function=func)
        if summary.entry_rank < 0:
            summary.entry_rank = rank
        summary.call_count = len(calls)
        summary.op_count = len(ops)

        for _key, kind, payload in timeline:
            if kind == "op":
                op = payload
                if int(op.exec_rank) < 0:
                    op.exec_rank = rank
                    rank += 1
                    ranked_ops += 1
            else:
                expand(str(payload))

        summary.exit_rank = rank - 1 if rank else -1
        summaries[func] = summary
        visiting.discard(func)

    for seed in starts:
        expand(seed)

    # Ops never reached from entries: append in local order (partial).
    unreached = [op for op in operations if int(op.exec_rank) < 0]
    unreached.sort(key=lambda o: (o.function, *_local_key(o)))
    for op in unreached:
        op.exec_rank = rank
        rank += 1
        ranked_ops += 1
        summary = summaries.get(op.function) or FunctionExecSummary(function=op.function)
        if summary.entry_rank < 0:
            summary.entry_rank = op.exec_rank
        summary.exit_rank = op.exec_rank
        summary.op_count = max(summary.op_count, len(by_func.get(op.function) or []))
        summaries[op.function] = summary

    # Sync events inherit linked operation ranks.
    op_rank = {op.id: int(op.exec_rank) for op in operations}
    for sev in sync_events or ():
        if sev.operation_id and sev.operation_id in op_rank:
            sev.exec_rank = op_rank[sev.operation_id]

    meta = {
        "ranked_operations": ranked_ops,
        "unreached_appended": len(unreached),
        "entry_seeds": len(starts),
        "functions": len(summaries),
        "call_edges": sum(len(v) for v in adj.values()),
        "authority": "kernel_entry_call_expand",
    }
    return list(summaries.values()), meta
