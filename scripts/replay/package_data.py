# -*- coding: utf-8 -*-
"""Load operator-package YAML data without hardcoding one operator's path.

Closure / obligations / inputs all ask "what does the active package say?"
through this module so a second operator only adds files under operators/.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return _ROOT


def active_operator_arch() -> tuple[str, str]:
    """(operator, arch) from env — no silent FAG default."""
    op = (os.environ.get("UO_OPERATOR") or "").strip()
    arch = (os.environ.get("UO_ARCH") or "").strip()
    if op and arch:
        return op, arch
    if op and not arch:
        raise ValueError("UO_OPERATOR set but UO_ARCH missing")
    if arch and not op:
        raise ValueError("UO_ARCH set but UO_OPERATOR missing")
    # Fall through: try runner.default() single-package discovery.
    try:
        from .runner import default, available

        pkgs = available()
        if len(pkgs) == 1:
            man = default().manifest
            return man.name, man.arch
        if len(pkgs) == 0:
            raise ValueError("no operator packages under operators/")
        raise ValueError(
            "multiple operator packages found; set UO_OPERATOR and UO_ARCH "
            f"(have: {[p.name for p in pkgs]})"
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "UO_OPERATOR/UO_ARCH unset and operator package discovery failed"
        ) from exc


def active_package_dir(root: Path | None = None) -> Path:
    """Directory containing operator.yaml for the active operator."""
    base = root or _ROOT
    if os.environ.get("UO_OPERATOR") or os.environ.get("UO_ARCH"):
        op, arch = active_operator_arch()
        return base / "operators" / op / arch
    try:
        from .runner import default

        pkg = default().manifest.package
        if pkg.is_dir():
            return Path(pkg)
    except Exception:
        pass
    op, arch = active_operator_arch()
    return base / "operators" / op / arch


def package_file(name: str, *, root: Path | None = None) -> Path:
    return active_package_dir(root) / name


def _arch_name() -> str:
    return (os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or "arch35").strip()


def adapter_pack_dir(root: Path | None = None) -> Path | None:
    """Prefer ``<op>/.ascendc-pilot/<arch>/uo/adapter`` when present.

    ``export_adapter_pack`` writes adapter YAML here so ``operators/`` stays
    limited to identity + log_protocol + input_semantics. Legacy
    ``tg/adapter`` is still accepted if present.
    """
    bases: list[Path] = []
    if root is not None:
        bases.append(Path(root))
    for env in ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR"):
        raw = (os.environ.get(env) or "").strip()
        if raw:
            bases.append(Path(raw).expanduser().resolve())
    seen: set[Path] = set()
    arch = _arch_name()
    for base in bases:
        if base in seen:
            continue
        seen.add(base)
        candidates: list[Path] = []
        try:
            from ascendc_pilot.paths import uo_root, tg_root

            candidates.append(uo_root(base, arch=arch) / "adapter")
            candidates.append(tg_root(base, arch=arch) / "adapter")
        except Exception:
            candidates.append(base / ".ascendc-pilot" / arch / "uo" / "adapter")
            candidates.append(base / ".ascendc-pilot" / arch / "tg" / "adapter")
        for cand in candidates:
            if cand.is_dir():
                return cand
    return None


def resolve_adapter_file(name: str, *, root: Path | None = None) -> Path | None:
    """Locate an adapter YAML: ``uo/adapter/`` first, then operator package."""
    adapter = adapter_pack_dir(root)
    if adapter is not None:
        path = adapter / name
        if path.is_file():
            return path
    path = package_file(name, root=root)
    return path if path.is_file() else None


@lru_cache(maxsize=32)
def _load_yaml_cached(name: str) -> dict[str, Any]:
    path = resolve_adapter_file(name)
    if path is None:
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def load_yaml(name: str, *, refresh: bool = False) -> dict[str, Any]:
    """Read adapter YAML (uo/adapter first, then operators package).

    ``refresh`` must not participate in the cache key: the resolved path
    depends on ambient env (``ASCENDC_PROJECT_ROOT`` / ``UO_OPERATOR``), so a
    cached ``refresh=True`` entry would keep serving another operator's pack.
    """
    if refresh:
        _load_yaml_cached.cache_clear()
    return _load_yaml_cached(name)


def clear_caches() -> None:
    _load_yaml_cached.cache_clear()
    try:
        from .runner import reset

        reset()
    except Exception:
        pass
