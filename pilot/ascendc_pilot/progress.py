"""Stderr progress lines for deterministic engine work (keep JSON stdout clean)."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Iterator


def emit(msg: str, *, prefix: str = "acp") -> None:
    """Always-on progress (unlike UO_TIMING which can be disabled)."""
    sys.stderr.write(f"[{prefix}] {msg}\n")
    sys.stderr.flush()


@contextmanager
def engine_span(workflow_id: str, action_id: str) -> Iterator[None]:
    """Mark entry/exit of a deterministic engine Action."""
    label = f"{workflow_id}/{action_id}" if workflow_id else action_id
    emit(f"engine start {label}", prefix="acp-engine")
    t0 = time.perf_counter()
    try:
        yield
    except Exception as exc:  # noqa: BLE001
        dt = time.perf_counter() - t0
        emit(f"engine FAIL {label} ({dt:.1f}s): {exc}"[:240], prefix="acp-engine")
        raise
    else:
        dt = time.perf_counter() - t0
        emit(f"engine done {label} ({dt:.1f}s)", prefix="acp-engine")
