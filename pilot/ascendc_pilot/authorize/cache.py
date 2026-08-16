"""In-process authorize verdict cache (effective under acp serve-authorize).

Skips exploration-budget paths (mutating). Invalidates on workflow/lease/active_action
mtime+size changes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

_TTL_SEC = 2.0
_MAX_ENTRIES = 256

# generation bumped by lease issue/revoke when available
_generation = 0
_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}


def bump_generation() -> None:
    global _generation
    _generation += 1
    _cache.clear()


def _stat_key(path: Path) -> tuple[int, int]:
    try:
        st = path.stat()
        return (int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        return (0, 0)


def _state_paths(project_root: Path) -> list[Path]:
    from ascendc_pilot.authorize.lease import active_action_path, lease_path
    from ascendc_pilot.paths import state_root

    try:
        root = state_root(project_root)
    except Exception:  # noqa: BLE001
        root = None
    paths = []
    if root is not None:
        paths.extend(
            [
                root / "workflow.yaml",
                root / "action_lease.yaml",
                root / "active_action.yaml",
            ]
        )
    try:
        paths.append(lease_path(project_root))
        paths.append(active_action_path(project_root))
    except Exception:  # noqa: BLE001
        pass
    return paths


def build_cache_key(
    project_root: Path | None,
    *,
    tool: str,
    command: str,
    path: str,
    agent: str,
    action: str,
    lease_id: str,
) -> tuple[Any, ...] | None:
    if project_root is None:
        return None
    root = Path(project_root)
    stats = tuple(_stat_key(p) for p in _state_paths(root))
    return (
        str(root.resolve()),
        (tool or "").strip().lower(),
        (command or "").strip()[:400],
        (path or "").strip().replace("\\", "/"),
        (agent or "").strip().lower(),
        (action or "").strip(),
        (lease_id or "").strip(),
        _generation,
        stats,
    )


def get(key: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if key is None:
        return None
    row = _cache.get(key)
    if not row:
        return None
    ts, verdict = row
    if time.monotonic() - ts > _TTL_SEC:
        _cache.pop(key, None)
        return None
    return dict(verdict)


def put(key: tuple[Any, ...] | None, verdict: dict[str, Any]) -> None:
    if key is None or not isinstance(verdict, dict):
        return
    # Never cache mutating exploration-budget paths (caller should skip).
    if verdict.get("_uncacheable"):
        return
    if len(_cache) >= _MAX_ENTRIES:
        # Drop oldest half
        items = sorted(_cache.items(), key=lambda kv: kv[1][0])
        for k, _ in items[: max(1, _MAX_ENTRIES // 2)]:
            _cache.pop(k, None)
    _cache[key] = (time.monotonic(), dict(verdict))


def clear() -> None:
    _cache.clear()


__all__ = ["bump_generation", "build_cache_key", "get", "put", "clear"]
