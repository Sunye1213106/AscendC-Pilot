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


def clear() -> None:
    _TEXT.clear()
