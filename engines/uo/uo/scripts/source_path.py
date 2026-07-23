"""Resolve operator source paths that may carry CBM / op-name prefixes."""
from __future__ import annotations

from pathlib import Path

_SOURCE_MARKERS = ("op_host/", "op_kernel/", "op_api/", "op_tiling/")


def resolve_repo_source_path(
    repo_root: Path,
    file_path: str,
    *,
    architecture: str = "arch35",
) -> Path | None:
    """Map a possibly-prefixed relative path to an existing file under ``repo_root``.

    Handles common CBM / staging shapes without operator-specific names:
    - ``{op_name}/op_host/...`` (extra leading folder)
    - ``.ascendc-agent/uo/.../cbm/index_stage/.../op_host/...``
    - bare ``op_host/...`` / ``op_kernel/...``
    - unique basename under ``op_host`` / ``op_kernel`` (prefer target architecture, then neutral)
    """
    raw = (file_path or "").replace("\\", "/").strip()
    if not raw:
        return None

    candidates: list[Path] = []
    p = Path(raw)
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(repo_root / raw)

    parts = [part for part in raw.split("/") if part and part != "."]
    for i in range(1, len(parts)):
        candidates.append(repo_root / "/".join(parts[i:]))

    for marker in _SOURCE_MARKERS:
        idx = raw.find(marker)
        if idx < 0:
            continue
        rest = raw[idx:]
        candidates.append(repo_root / rest)
        # Staging mirror under .ascendc-agent/uo/cbm/index_stage/<any>/<rest>
        for uo in (repo_root / ".ascendc-agent" / "uo",):
            stage = uo / "cbm" / "index_stage"
            if stage.is_dir():
                for staged_op in stage.iterdir():
                    if staged_op.is_dir():
                        candidates.append(staged_op / rest)

    name = Path(raw).name
    arch = (architecture or "").strip()
    if name and ("/" in raw or "\\" in file_path):
        for sub in ("op_host", "op_kernel", "op_api"):
            root = repo_root / sub
            if not root.is_dir():
                continue
            hits = [h for h in root.rglob(name) if h.is_file()]
            if not hits:
                continue
            if len(hits) == 1:
                candidates.append(hits[0])
            else:
                preferred = []
                if arch:
                    preferred = [h for h in hits if f"/{arch}/" in h.as_posix().replace("\\", "/")]
                if len(preferred) == 1:
                    candidates.append(preferred[0])
                elif preferred:
                    candidates.extend(preferred[:3])
                else:
                    # Prefer architecture-neutral paths over other arches.
                    neutral = [h for h in hits if "/arch" not in h.as_posix().replace("\\", "/")]
                    candidates.extend((neutral or hits)[:3])

    seen: set[Path] = set()
    for cand in candidates:
        try:
            key = cand.resolve()
        except OSError:
            key = cand
        if key in seen:
            continue
        seen.add(key)
        if cand.is_file():
            return cand
    return None


def to_repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")
