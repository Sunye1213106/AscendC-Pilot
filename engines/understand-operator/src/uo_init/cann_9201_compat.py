# -*- coding: utf-8 -*-
"""Compile arch-920r1 as __NPU_ARCH__=9201; overlay CANN headers that still gate 3510.

CANN 9.1/9.2 ship DAV_9201 in some compiler headers but not in
``kernel_tpipe.h`` / ``kernel_reg_compute_utils.h`` or ``platform_config``.
Do not remap the compile macro to 3510. When a header still tests
``__NPU_ARCH__ == 3510`` and does not mention 9201, write a wrapper under
``.ascendc-pilot/<arch>/uo/cache/cann_9201_overlay/`` and put that ``-I``
ahead of the CANN include roots.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from uo_init.source_layout import canonicalize_architecture

_HAS_9201 = re.compile(r"__NPU_ARCH__\s*==\s*9201")
_HAS_3510 = re.compile(r"__NPU_ARCH__\s*==\s*3510")
_ALREADY = re.compile(
    r"\(__NPU_ARCH__\s*==\s*3510\)\s*\|\|\s*\(__NPU_ARCH__\s*==\s*9201\)"
)
_PROBE_BASENAMES = (
    "kernel_tpipe.h",
    "kernel_reg_compute_intf.h",
    "kernel_reg_compute_utils.h",
    "kernel_tensor.h",
    "kernel_operator.h",
    "sys_macros.h",
)
_KNOWN_RELS = (
    "cann-asc-devkit/x86_64-linux/asc/include/basic_api",
    "cann-asc-devkit/x86_64-linux/asc/include/basic_api/interface",
    "cann-asc-devkit/x86_64-linux/asc/include/basic_api/reg_compute",
    "cann-asc-devkit/x86_64-linux/tikcpp/tikcfw",
    "cann-asc-devkit/x86_64-linux/tikcpp/tikcfw/interface",
    "cann-asc-devkit/x86_64-linux/tikcpp/tikcfw/interface/reg_compute",
    "cann-asc-devkit/x86_64-linux/ascendc/include/basic_api",
    "cann-asc-devkit/x86_64-linux/ascendc/include/basic_api/interface",
)
_SUBDIRS = ("", "interface", "reg_compute", "interface/reg_compute")


def overlay_dir(op_dir: str | Path, arch_dir: str) -> Path:
    arch = str(arch_dir or "").strip()
    return (
        Path(op_dir).expanduser().resolve()
        / ".ascendc-pilot"
        / arch
        / "uo"
        / "cache"
        / "cann_9201_overlay"
    )


def expand_3510_gates(text: str) -> str:
    """Widen ``__NPU_ARCH__ == 3510`` so 9201 takes the same branch. Idempotent."""
    placeholders: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"\x00PILOT{len(placeholders) - 1}\x00"

    held = _ALREADY.sub(_hold, text)
    held = _HAS_3510.sub("((__NPU_ARCH__ == 3510) || (__NPU_ARCH__ == 9201))", held)
    for i, orig in enumerate(placeholders):
        held = held.replace(f"\x00PILOT{i}\x00", orig)
    return held


def _iter_search_dirs(ctx: Any) -> list[Path]:
    from uo_init.paths import resolve_cann_relative

    out: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            if not path.is_dir():
                return
            key = str(path.resolve())
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        out.append(path)

    cann = Path(getattr(ctx, "cann_root", "") or "")
    raw_includes = ((getattr(ctx, "raw", None) or {}).get("kernel") or {}).get("includes") or []
    resolve = getattr(ctx, "resolve_path", None)
    if callable(resolve):
        for item in raw_includes:
            add(Path(resolve(str(item))))
    if cann.is_dir():
        for rel in _KNOWN_RELS:
            add(resolve_cann_relative(cann, rel))
    return out


def _rel_from_roots(header: Path, roots: list[Path]) -> str:
    """Relative include spelling against the deepest matching ``-I`` root."""
    resolved = header.resolve()
    best = header.name
    best_root_len = -1
    for root in roots:
        try:
            key = root.resolve()
            rel = resolved.relative_to(key).as_posix()
        except (OSError, ValueError):
            continue
        n = len(str(key))
        if n > best_root_len:
            best = rel
            best_root_len = n
    return best


def _find_header(roots: list[Path], name: str) -> Path | None:
    for root in roots:
        for sub in _SUBDIRS:
            cand = root / sub / name if sub else root / name
            try:
                if cand.is_file():
                    return cand
            except OSError:
                continue
    return None


def probe_cann_9201(ctx: Any) -> dict[str, Any]:
    """Inspect CANN headers and platform_config for native 9201 support."""
    from uo_init.platform_ini import list_profiles

    cann = Path(getattr(ctx, "cann_root", "") or "")
    report: dict[str, Any] = {
        "npu_arch": 9201,
        "headers": "missing",
        "ini": "missing",
        "overlay_files": [],
        "native_files": [],
        "sku_fallback": "",
    }
    if cann.is_dir():
        try:
            native_ini = list_profiles(cann, npu_arch=9201)
        except OSError:
            native_ini = []
        if native_ini:
            report["ini"] = "native"
        else:
            report["ini"] = "sku_fallback"
            report["sku_fallback"] = "Ascend950PR_9589"
    roots = _iter_search_dirs(ctx)
    overlay_names: list[str] = []
    native_names: list[str] = []
    sources: list[tuple[str, Path]] = []
    for name in _PROBE_BASENAMES:
        found = _find_header(roots, name)
        if found is None:
            continue
        try:
            text = found.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _rel_from_roots(found, roots)
        if _HAS_9201.search(text):
            native_names.append(rel)
            continue
        if _HAS_3510.search(text):
            overlay_names.append(rel)
            sources.append((rel, found))
    report["overlay_files"] = overlay_names
    report["native_files"] = native_names
    if overlay_names:
        report["headers"] = "overlay"
    elif native_names:
        report["headers"] = "native"
    report["_sources"] = sources
    report["_roots"] = roots
    return report


def materialize_9201_overlay(ctx: Any, report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write overlay headers and return the public probe record."""
    info = dict(report or probe_cann_9201(ctx))
    sources = list(info.pop("_sources", []) or [])
    info.pop("_roots", None)
    op_dir = str(getattr(ctx, "op_dir", "") or "")
    arch = str(getattr(ctx, "arch_dir", "") or "")
    if not op_dir or not arch:
        return info
    dest_root = overlay_dir(op_dir, arch)
    dest_root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for rel, src in sources:
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            dest.write_text(expand_3510_gates(text), encoding="utf-8")
            written.append(rel.replace("\\", "/"))
        except OSError:
            continue
    info["overlay_files"] = written
    info["overlay_dir"] = str(dest_root).replace("\\", "/") if written else ""
    if written:
        info["headers"] = "overlay"
    probe_path = dest_root / "probe.yaml"
    public = {k: v for k, v in info.items() if not str(k).startswith("_")}
    probe_path.write_text(
        yaml.safe_dump(public, allow_unicode=True, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    info["probe_path"] = str(probe_path).replace("\\", "/")
    return info


def attach_9201_overlay(ctx: Any) -> dict[str, Any]:
    """If this BuildContext is 920r1, probe CANN and prepend overlay ``-I``."""
    arch = str(getattr(ctx, "arch_dir", "") or "")
    if canonicalize_architecture(arch) != "arch-920r1":
        return {}
    cann = Path(getattr(ctx, "cann_root", "") or "")
    if not cann.is_dir():
        report = {"npu_arch": 9201, "headers": "no_cann", "ini": "no_cann"}
        ctx.cann_9201 = report
        return report
    try:
        report = materialize_9201_overlay(ctx)
    except OSError as exc:
        report = {"npu_arch": 9201, "headers": "probe_failed", "error": str(exc)[:200]}
        ctx.cann_9201 = report
        return report
    ctx.cann_9201 = report
    overlay = str(report.get("overlay_dir") or "").strip()
    if overlay:
        current = [str(p).replace("\\", "/").rstrip("/") for p in (ctx.overlay_includes or [])]
        posix = overlay.rstrip("/")
        if posix.lower() not in {p.lower() for p in current}:
            ctx.overlay_includes = [posix, *current]
    return report
