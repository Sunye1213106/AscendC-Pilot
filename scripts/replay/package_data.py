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


@lru_cache(maxsize=32)
def load_yaml(name: str, *, refresh: bool = False) -> dict[str, Any]:
    """Read a YAML file from the active package (cached per name+mtime)."""
    if refresh:
        load_yaml.cache_clear()
    path = package_file(name)
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def clear_caches() -> None:
    load_yaml.cache_clear()
