# -*- coding: utf-8 -*-
"""Operator-source discovery that is not FAG-directory-shaped.

FAG keeps Host under ``op_host/archXX/`` and kernel entries that
``#include "archXX/..."``. Other ops use ``op_host/op_tiling/``,
``./archXX/`` includes, and ``extern "C" __global__``. Walks that only
accept the FAG spelling drop KERNEL / packing / TilingData.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

ARCH_DIR_RE = re.compile(r"^arch\d+$")
_CPP_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_QUOTED_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)

# template <...> __global__, extern "C" __global__, or a plain __global__.
GLOBAL_KERNEL_RE = re.compile(
    r"(?:template\s*<(?P<tpl>.*?)>\s*)?"
    r"(?:extern\s+\"C\"\s+)?"
    r"__global__\s+__aicore__\s+void\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*?)\)\s*\{",
    re.S,
)

_TILING_HEADER_GLOBS = (
    "*tiling_data*.h",
    "*tiling_data*.hpp",
    "*_tiling.h",
    "*_tiling.hpp",
    "*tiling*.h",
)


def is_other_arch_path(path: Path, architecture: str) -> bool:
    arch = str(architecture or "").strip()
    for part in Path(path).parts:
        if ARCH_DIR_RE.match(part) and part != arch:
            return True
    return False


def includes_architecture(text: str, architecture: str) -> bool:
    """True when the TU pulls the current arch, including ``./arch35/``."""
    arch = str(architecture or "").strip()
    if not arch:
        return False
    return f"{arch}/" in text.replace("\\", "/")


def quoted_include_basenames(path: Path) -> set[str]:
    """Basenames from ``#include "..."`` in ``path`` (not angle includes)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {Path(inc.replace("\\", "/")).name.lower() for inc in _QUOTED_INCLUDE_RE.findall(text)}


def resolve_quoted_includes(path: Path) -> list[Path]:
    """Quoted includes resolved relative to the including file."""
    parent = Path(path).parent
    out: list[Path] = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for inc in _QUOTED_INCLUDE_RE.findall(text):
        cand = (parent / inc.replace("\\", "/")).resolve()
        if cand.is_file():
            out.append(cand)
    return out


def iter_cpp(root: Path, *, recursive: bool = True) -> Iterator[Path]:
    if not root.is_dir():
        return
    it = root.rglob("*") if recursive else root.glob("*")
    for path in it:
        if path.is_file() and path.suffix.lower() in _CPP_SUFFIXES:
            yield path


def selected_kernel_files(
    root: Path,
    architecture: str,
    *,
    kernel_entry: Path | None = None,
) -> list[Path]:
    """Kernel TUs for this architecture: arch folder, matching entries, apt."""
    out: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None or not path.is_file():
            return
        key = path.resolve()
        if key in seen:
            return
        seen.add(key)
        out.append(path)

    add(kernel_entry)
    kernel_root = Path(root) / "op_kernel"
    arch_dir = kernel_root / architecture
    if arch_dir.is_dir():
        for path in sorted(iter_cpp(arch_dir)):
            add(path)
    if kernel_root.is_dir():
        for path in sorted(iter_cpp(kernel_root, recursive=False)):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if (
                includes_architecture(text, architecture)
                or "__aicore__" in text
                or "GET_TILING_DATA" in text
            ):
                add(path)
    op_root = Path(root).resolve()
    pending = list(out)
    while pending:
        path = pending.pop()
        for included in resolve_quoted_includes(path):
            if is_other_arch_path(included, architecture):
                continue
            try:
                included.resolve().relative_to(op_root)
            except ValueError:
                continue
            before = len(seen)
            add(included)
            if len(seen) > before:
                pending.append(included)
    return out


def selected_host_files(root: Path, architecture: str) -> list[Path]:
    """Host sources for this arch, including ``op_host/op_tiling/``."""
    host_root = Path(root) / "op_host"
    out: list[Path] = []
    seen: set[Path] = set()
    for path in sorted(iter_cpp(host_root)):
        if is_other_arch_path(path, architecture):
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def selected_tiling_headers(root: Path, architecture: str) -> list[Path]:
    """TilingData headers under op_host / op_kernel, current arch only."""
    hits: list[Path] = []
    seen: set[Path] = set()
    for base in (Path(root) / "op_host", Path(root) / "op_kernel"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".h", ".hpp", ".hh"}:
                continue
            if is_other_arch_path(path, architecture):
                continue
            name = path.name.lower()
            if "tiling" not in name:
                continue
            key = path.resolve()
            if key in seen:
                continue
            seen.add(key)
            hits.append(path)
    return hits
