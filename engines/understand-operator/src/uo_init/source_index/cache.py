# -*- coding: utf-8 -*-
"""Process-local SourceIndex cache. Keyed by the resolved file set."""
from __future__ import annotations

import threading
from typing import Any

_INDEX: dict[str, Any] = {}
_LOCK = threading.Lock()


def cache_get(key: str) -> Any | None:
    with _LOCK:
        return _INDEX.get(key)


def cache_put(key: str, value: Any) -> None:
    with _LOCK:
        _INDEX[key] = value


def cache_clear() -> None:
    with _LOCK:
        _INDEX.clear()
