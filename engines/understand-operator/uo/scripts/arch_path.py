"""Architecture path helpers shared by scope, entrypoints, and extractors."""

from __future__ import annotations

import re
from pathlib import Path

_ARCH_SEG_RE = re.compile(r"^arch\d+$", re.IGNORECASE)


def path_arch_segments(rel: str) -> list[str]:
    parts = [p.lower() for p in Path(str(rel or "").replace("\\", "/")).parts]
    return [p for p in parts if _ARCH_SEG_RE.fullmatch(p)]


def architecture_of_path(rel: str) -> str:
    """Return 'neutral' when no archNN segment, else the first arch segment."""
    segs = path_arch_segments(rel)
    return segs[0] if segs else "neutral"


def arch_compatible(rel: str, architecture: str) -> bool:
    """Keep paths with no arch* segment, or containing the target architecture.

    Other arch* directories are excluded. Neutral does NOT mean membership in every
    architecture — callers must still link via evidence.
    """
    arch = str(architecture or "").strip().lower()
    if not arch:
        return True
    segs = path_arch_segments(rel)
    if not segs:
        return True
    return arch in segs


def path_family_of(rel: str) -> str:
    low = str(rel or "").replace("\\", "/").lower()
    if "varlen" in low or "var_len" in low:
        return "varlen"
    if "empty" in low:
        return "empty"
    if "normal" in low:
        return "normal"
    if architecture_of_path(rel) == "neutral":
        return "shared"
    return "unknown"
