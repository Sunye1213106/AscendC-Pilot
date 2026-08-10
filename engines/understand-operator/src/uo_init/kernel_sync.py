"""Conservative pairing for extracted kernel synchronization events."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def pair_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair SetFlag/WaitFlag only when identity is unambiguous.

    Missing or multiple candidates are explicit unresolved outcomes, never a
    claimed synchronization defect.
    """
    producers: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    waits: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind") or "")
        identity = (
            event.get("flag"), event.get("pipe"), event.get("event"),
            event.get("buffer_identity"), event.get("cross_core"),
        )
        if kind == "SetFlag":
            producers[identity].append(event)
        elif kind == "WaitFlag":
            waits.append(event)
    result: list[dict[str, Any]] = []
    for wait in waits:
        identity = (
            wait.get("flag"), wait.get("pipe"), wait.get("event"),
            wait.get("buffer_identity"), wait.get("cross_core"),
        )
        candidates = producers.get(identity, [])
        if not candidates:
            status = "UNRESOLVED_SYNC_PAIRING"
        elif len(candidates) > 1:
            status = "MULTIPLE_PAIR_CANDIDATES"
        else:
            status = "PAIRED"
        result.append(
            {
                "status": status,
                "wait": wait,
                "producer": candidates[0] if len(candidates) == 1 else None,
                "candidate_count": len(candidates),
            }
        )
    return result
