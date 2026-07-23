"""Load Agent declarations (scopes/role/mode) from agents-src or installed bundles."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any


def _repo_root_candidates(project_root: Path | None) -> list[Path]:
    roots: list[Path] = []
    here = Path(__file__).resolve()
    # harness/ascendc_harness → repo root
    roots.append(here.parents[2])
    if project_root is not None:
        pr = Path(project_root).expanduser().resolve()
        roots.append(pr)
        for parent in pr.parents:
            roots.append(parent)
            if len(roots) > 12:
                break
    home = Path.home()
    roots.extend(
        [
            home / ".config" / "opencode" / "ascendc-agent-plugin",
            home / ".cursor" / "ascendc-agent-plugin",
            home / ".agents" / "ascendc-agent-plugin",
        ]
    )
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@lru_cache(maxsize=64)
def load_agent_meta(agent_id: str, project_root: str | None = None) -> dict[str, Any]:
    """Return agent YAML meta for ``agent_id`` or {} if missing."""
    aid = (agent_id or "").strip()
    if not aid:
        return {}
    pr = Path(project_root).resolve() if project_root else None
    for root in _repo_root_candidates(pr):
        path = root / "agents-src" / f"{aid}.yaml"
        meta = _load_yaml(path)
        if meta.get("id"):
            return meta
        # Installed plugin may copy agents-src under bundle root
        path2 = root / "agents" / f"{aid}.yaml"
        meta2 = _load_yaml(path2)
        if meta2.get("id"):
            return meta2
    return {}


def agent_write_scopes(agent_id: str, project_root: Path | None = None) -> list[str]:
    meta = load_agent_meta(agent_id, str(project_root) if project_root else None)
    return [str(x) for x in (meta.get("write_scopes") or [])]


def agent_read_scopes(agent_id: str, project_root: Path | None = None) -> list[str]:
    meta = load_agent_meta(agent_id, str(project_root) if project_root else None)
    return [str(x) for x in (meta.get("read_scopes") or [])]


def path_matches_scope(rel_under_agent: str, scopes: list[str]) -> bool:
    """Match a path relative to ``.ascendc-agent/`` against glob-like scopes.

    Supports ``**``, ``*``, and exact prefixes. Empty scopes → deny (caller decides).
    """
    from fnmatch import fnmatch

    norm = rel_under_agent.replace("\\", "/").lstrip("/")
    if not scopes:
        return False
    for scope in scopes:
        s = str(scope).replace("\\", "/").lstrip("/")
        if not s:
            continue
        if s.endswith("/**"):
            prefix = s[:-3]
            if norm == prefix or norm.startswith(prefix + "/"):
                return True
            # also allow exact file under prefix via fnmatch
        if fnmatch(norm, s):
            return True
        # Directory scope without glob: treat as prefix
        if "*" not in s and "?" not in s and "[" not in s:
            if norm == s or norm.startswith(s.rstrip("/") + "/"):
                return True
    return False


def rel_under_agent_dir(path: str | Path, project_root: Path | None) -> str | None:
    """Return path relative to ``.ascendc-agent`` if contained; else None."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return None
    norm = str(resolved).replace("\\", "/")
    marker = "/.ascendc-agent/"
    if marker not in norm:
        if norm.rstrip("/").endswith("/.ascendc-agent"):
            return ""
        return None
    return norm.split(marker, 1)[1]
