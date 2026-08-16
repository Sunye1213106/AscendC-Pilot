# -*- coding: utf-8 -*-
"""Process-local SourceIndex cache. Keyed by the resolved file set."""
from __future__ import annotations

from typing import Any

_INDEX: dict[str, Any] = {}


def cache_get(key: str) -> Any | None:
    return _INDEX.get(key)


def cache_put(key: str, value: Any) -> None:
    _INDEX[key] = value


def cache_clear() -> None:
    _INDEX.clear()
