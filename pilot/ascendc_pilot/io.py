"""Shared stdout helpers (UTF-8 JSON) for acp CLI surfaces."""

from __future__ import annotations

import json
import sys
from typing import Any


def configure_stdio() -> None:
    """Force UTF-8 on stdout/stderr so Chinese label_zh / todo_md stay readable on Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def print_json(payload: Any, *, default: Any = None) -> None:
    kwargs: dict[str, Any] = {"ensure_ascii": False, "indent": 2}
    if default is not None:
        kwargs["default"] = default
    text = json.dumps(payload, **kwargs)
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
