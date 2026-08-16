# -*- coding: utf-8 -*-
"""Process-local source text cache shared across CodeMap enrichment passes.

Every disk read is counted so ``performance.yaml`` can show files scanned more
than once. Callers should go through this module instead of ``Path.read_text``.
"""

from __future__ import annotations

from pathlib import Path

_TEXT: dict[str, str] = {}


def _key(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def read_text(path: str | Path) -> str:
    key = _key(path)
    hit = _TEXT.get(key)
    if hit is not None:
        try:
            from uo_init.perf import record_read

            record_read(key, 0, cache_hit=True)
        except Exception:  # noqa: BLE001
            pass
        return hit
    text = Path(key).read_text(encoding="utf-8", errors="replace")
    _TEXT[key] = text
    try:
        from uo_init.perf import record_read

        record_read(key, len(text.encode("utf-8", errors="replace")), cache_hit=False)
    except Exception:  # noqa: BLE001
        pass
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


def stats() -> dict[str, int]:
    return {"cached_files": len(_TEXT)}


def clear() -> None:
    _TEXT.clear()
