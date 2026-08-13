# -*- coding: utf-8 -*-
"""Process-local source text cache shared across CodeMap enrichment passes.

``resolve_source_gaps`` and ``finalize_kernel_tiling_closure`` both walk the
same operator tree. Reading each file once keeps both passes complete while
avoiding duplicate I/O on large kernels.
"""

from __future__ import annotations

from pathlib import Path

_TEXT: dict[str, str] = {}


def read_text(path: str | Path) -> str:
    key = str(Path(path).expanduser().resolve())
    hit = _TEXT.get(key)
    if hit is not None:
        return hit
    text = Path(key).read_text(encoding="utf-8", errors="replace")
    _TEXT[key] = text
    return text


def cached_snippet(path: str | Path, line: int) -> str:
    """Return one cached source line, or empty if the file was never read."""
    if int(line or 0) <= 0:
        return ""
    raw = str(path or "").replace("\\", "/")
    if not raw:
        return ""
    text = None
    needle = raw.lstrip("./")
    for key, val in _TEXT.items():
        norm = key.replace("\\", "/")
        if norm == raw or norm.endswith("/" + needle) or needle.endswith(norm.split("/")[-1]) and needle in norm:
            text = val
            break
    if text is None:
        return ""
    lines = text.splitlines()
    if int(line) > len(lines):
        return ""
    return lines[int(line) - 1].strip()[:400]


def clear() -> None:
    _TEXT.clear()

