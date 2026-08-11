# -*- coding: utf-8 -*-
"""Conservative sync pairing with optional nearest-preceding resolution.

Base identity remains (flag, pipe, event, buffer_identity, cross_core).
When multiple producers share an identity, prefer the nearest preceding site
in the same function (program order). That outcome is PARTIAL, never claimed
as a unique source-level proof.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _identity(event: dict[str, Any]) -> tuple[Any, ...]:
    return (
        event.get("flag"),
        event.get("pipe"),
        event.get("event"),
        event.get("buffer_identity"),
        bool(event.get("cross_core")),
    )


def _site_key(event: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(event.get("function") or ""),
        int(event.get("line") or 0),
        int(event.get("column") or 0),
    )


def _exec_rank(event: dict[str, Any]) -> int:
    try:
        return int(event.get("exec_rank") if event.get("exec_rank") is not None else -1)
    except (TypeError, ValueError):
        return -1


def _precedes(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True iff ``a`` is strictly before ``b`` in execution / program order."""
    ra, rb = _exec_rank(a), _exec_rank(b)
    if ra >= 0 and rb >= 0:
        return ra < rb
    _afun, aline, acol = _site_key(a)
    bfun, bline, bcol = _site_key(b)
    if _afun != bfun:
        return False
    return aline < bline or (aline == bline and acol <= bcol)


def pair_events(
    events: Iterable[dict[str, Any]],
    *,
    prefer_nearest_preceding: bool = True,
) -> list[dict[str, Any]]:
    """Pair SetFlag/WaitFlag only when identity is unambiguous or nearest-preceding.

    Missing or still-ambiguous candidates stay explicit unresolved outcomes.
    Nearest preceding prefers ``exec_rank`` when present; otherwise same-function
    (line, column) order.
    """
    producers: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    waits: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind") or "")
        identity = _identity(event)
        if kind in {"SetFlag", "SET", "CrossCoreSetFlag", "MutexLock", "IBSet"}:
            producers[identity].append(event)
        elif kind in {"WaitFlag", "WAIT", "CrossCoreWaitFlag", "MutexUnlock", "IBWait"}:
            waits.append(event)
    result: list[dict[str, Any]] = []
    for wait in waits:
        identity = _identity(wait)
        candidates = list(producers.get(identity, []))
        status = "UNRESOLVED_SYNC_PAIRING"
        producer: dict[str, Any] | None = None
        confidence = "confirmed"
        if not candidates:
            status = "UNRESOLVED_SYNC_PAIRING"
        elif len(candidates) == 1:
            status = "PAIRED"
            producer = candidates[0]
            confidence = "confirmed"
        elif prefer_nearest_preceding:
            wfun = str(wait.get("function") or "")
            preceding = [
                c
                for c in candidates
                if str(c.get("function") or "") == wfun and _precedes(c, wait)
            ]
            if not preceding:
                status = "MULTIPLE_PAIR_CANDIDATES"
            else:
                preceding.sort(
                    key=lambda c: (
                        _exec_rank(c) if _exec_rank(c) >= 0 else 10**9,
                        int(c.get("line") or 0),
                        int(c.get("column") or 0),
                    )
                )
                producer = preceding[-1]
                status = "PAIRED"
                confidence = "partial"
        else:
            status = "MULTIPLE_PAIR_CANDIDATES"
        result.append(
            {
                "status": status,
                "wait": wait,
                "producer": producer,
                "candidate_count": len(candidates),
                "confidence": confidence,
            }
        )
    return result
