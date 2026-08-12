# -*- coding: utf-8 -*-
"""Resolve operator-local data without a Pilot ``operators/`` tree.

Authority order:
1. ``ASCENDC_PROJECT_ROOT`` / ``UO_OP_DIR`` → ``.ascendc-pilot/<arch>/``
   (adapter pack, local extensions, optional ``_compat_package``)
2. Explicit ``UO_PACKAGE_DIR``
3. Test fixtures under ``tests/fixtures/`` (synthetic / archived adapters)

Production code must never import AscendC-Pilot ``operators.*``.
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


def _arch_name() -> str:
    for name in ("UO_ARCH", "ASCENDC_ARCH"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    raise ValueError("ARCHITECTURE_MISSING: set UO_ARCH or ASCENDC_ARCH")


def _operator_project_root() -> Path | None:
    for env in ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR"):
        raw = (os.environ.get(env) or "").strip()
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                return p
    return None


def active_operator_arch() -> tuple[str, str]:
    """(operator, arch) from env — no silent operator default."""
    op = (os.environ.get("UO_OPERATOR") or "").strip()
    arch = (os.environ.get("UO_ARCH") or "").strip()
    if op and arch:
        return op, arch
    if op and not arch:
        raise ValueError("UO_OPERATOR set but UO_ARCH missing")
    if arch and not op:
        raise ValueError("UO_ARCH set but UO_OPERATOR missing")
    raise ValueError(
        "UO_OPERATOR and UO_ARCH must be set (or ASCENDC_PROJECT_ROOT with "
        "local package); Pilot never auto-selects an operator identity"
    )


def _fixture_package_dir(root: Path, op: str, arch: str) -> Path | None:
    cand = root / "tests" / "fixtures" / op / arch
    if cand.is_dir():
        return cand
    return None


def _compat_package_dir(op_root: Path, arch: str) -> Path | None:
    """Optional migration shim: ``.ascendc-pilot/<arch>/local/_compat_package``."""
    try:
        from ascendc_pilot.paths import artifact_root, LOCAL_SUBDIR

        base = artifact_root(op_root, arch, allow_pilot_checkout=False)
    except Exception:
        base = op_root / ".ascendc-pilot" / arch
    cand = base / "local" / "_compat_package"
    if cand.is_dir():
        return cand
    # Also accept flat local package files next to extensions (legacy dump).
    flat = base / "local"
    if (flat / "operator.yaml").is_file() or (flat / "input_semantics.py").is_file():
        return flat
    return None


def active_package_dir(root: Path | None = None) -> Path:
    """Directory holding package-side YAML / Python for the active operator.

    Prefer operator-local ``.ascendc-pilot`` trees; fall back to test fixtures.
    Never requires AscendC-Pilot ``operators/``.
    """
    base = root or _ROOT
    override = (os.environ.get("UO_PACKAGE_DIR") or "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_dir():
            return path

    op_proj = _operator_project_root()
    if op_proj is not None:
        arch = _arch_name()
        if os.environ.get("UO_OPERATOR") or os.environ.get("UO_ARCH"):
            try:
                _, arch = active_operator_arch()
            except ValueError:
                pass
        compat = _compat_package_dir(op_proj, arch)
        if compat is not None:
            return compat
        # No compat package: still return local root so callers can look for
        # extension implementations via LocalExtensionRegistry.
        try:
            from ascendc_pilot.workspace import OperatorWorkspace

            ws = OperatorWorkspace.resolve(
                op_proj, arch=arch, allow_pilot_checkout=False
            )
            return ws.local_root
        except Exception:
            return op_proj / ".ascendc-pilot" / arch / "local"

    if os.environ.get("UO_OPERATOR") or os.environ.get("UO_ARCH"):
        op, arch = active_operator_arch()
        fixture = _fixture_package_dir(base, op, arch)
        if fixture is not None:
            return fixture

    try:
        from .runner import default

        pkg = default().manifest.package
        if pkg.is_dir():
            return Path(pkg)
    except Exception:
        pass

    raise ValueError(
        "UO_OPERATOR and UO_ARCH must be set (or ASCENDC_PROJECT_ROOT with "
        "local package); Pilot never auto-selects an operator identity"
    )


def package_file(name: str, *, root: Path | None = None) -> Path:
    """Resolve a package-side file, including Local Extension implementations."""
    base = active_package_dir(root)
    direct = base / name
    if direct.is_file():
        return direct

    # Map legacy filenames → Local Extension layout.
    ext_map = {
        "input_semantics.py": ("case_builder", "implementation.py"),
        "tilingdata_decoder.py": ("tilingdata_decoder", "implementation.py"),
        "log_protocol.yaml": ("replay_parser", "log_protocol.yaml"),
    }
    if name in ext_map:
        interface, filename = ext_map[name]
        # When base is already local/, look for interface subdir.
        kebab = {
            "case_builder": "case-builder",
            "tilingdata_decoder": "tilingdata-decoder",
            "replay_parser": "replay-parser",
        }[interface]
        cand = base / kebab / filename
        if cand.is_file():
            return cand
        # When ASCENDC_PROJECT_ROOT points at op root, registry path:
        op_proj = _operator_project_root()
        if op_proj is not None:
            try:
                from ascendc_pilot.local_extension import LocalExtensionRegistry

                reg = LocalExtensionRegistry.from_operator_root(
                    op_proj, arch=_arch_name()
                )
                ext = reg.discover(interface)
                if ext is not None:
                    if name.endswith(".py"):
                        return ext.implementation
                    alt = ext.root / filename
                    if alt.is_file():
                        return alt
            except Exception:
                pass
    return direct


def adapter_pack_dir(root: Path | None = None) -> Path | None:
    """Prefer ``<op>/.ascendc-pilot/<arch>/uo/adapter`` when present."""
    bases: list[Path] = []
    if root is not None:
        bases.append(Path(root))
    op_proj = _operator_project_root()
    if op_proj is not None:
        bases.insert(0, op_proj)
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
    """Locate an adapter YAML: ``uo/adapter/`` first, then package / fixture."""
    adapter = adapter_pack_dir(root)
    if adapter is not None:
        path = adapter / name
        if path.is_file():
            return path
    try:
        path = package_file(name, root=root)
    except ValueError:
        return None
    return path if path.is_file() else None


@lru_cache(maxsize=32)
def _load_yaml_cached(name: str) -> dict[str, Any]:
    path = resolve_adapter_file(name)
    if path is None:
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def load_yaml(name: str, *, refresh: bool = False) -> dict[str, Any]:
    """Read adapter YAML (uo/adapter first, then package / fixture)."""
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
