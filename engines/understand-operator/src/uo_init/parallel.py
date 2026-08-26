# -*- coding: utf-8 -*-
"""Per-file CPU maps. Merge results on the calling thread (CodeMap is not shared)."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def _requested_workers() -> int | None:
    """``UO_MAP_WORKERS`` override, or None to size the pool from the machine.

    ``1`` runs every item inline. The knob exists because the benefit here is
    not obvious and should not be assumed: Python's ``re`` holds the GIL, so a
    pool of eight threads scanning with regexes is one thread doing the work
    while seven pay for scheduling and lock handoffs. File reads *do* release
    it, and these callbacks mix reading with scanning in different proportions,
    so which way a given call site comes out is an empirical question. Being
    able to run the same build both ways is how it gets answered.
    """
    raw = str(os.environ.get("UO_MAP_WORKERS") or "").strip()
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def map_files(
    items: Sequence[T] | Iterable[T], fn: Callable[[T], R], *, workers: int | None = None
) -> list[R]:
    """Apply ``fn`` per item. One item stays in-process; many files use a pool."""
    rows = list(items)
    if len(rows) <= 1:
        return [fn(row) for row in rows]
    override = _requested_workers()
    if override is not None:
        n = min(override, len(rows))
    elif workers is not None:
        n = workers
    else:
        n = min(len(rows), os.cpu_count() or 4, 8)
    if n <= 1:
        return [fn(row) for row in rows]
    n = max(2, n)
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(fn, rows))
