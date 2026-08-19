# -*- coding: utf-8 -*-
"""Per-file CPU maps. Merge results on the calling thread (CodeMap is not shared)."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def map_files(items: Sequence[T] | Iterable[T], fn: Callable[[T], R], *, workers: int | None = None) -> list[R]:
    """Apply ``fn`` per item. One item stays in-process; many files use a pool."""
    rows = list(items)
    if len(rows) <= 1:
        return [fn(row) for row in rows]
    n = workers if workers is not None else min(len(rows), os.cpu_count() or 4, 8)
    n = max(2, n)
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(fn, rows))
