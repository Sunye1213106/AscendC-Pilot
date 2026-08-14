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
_ARCH_IN_PATH_RE = re.compile(r"(?:^|/)(arch\d+)(?:/|$)")
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


def entry_include_architecture(text: str) -> str:
    """Which ``archNN`` a root-level kernel entry builds, from its includes.

    Entries sit above ``archNN/`` folders, so the path alone cannot tell.
    Matching ``scope_scan.entry_architecture``: one concrete arch wins; mixed
    or absent markers yield empty.
    """
    found: set[str] = set()
    for inc in _QUOTED_INCLUDE_RE.findall(text or ""):
        match = _ARCH_IN_PATH_RE.search(inc.replace("\\", "/"))
        if match:
            found.add(match.group(1).lower())
    if len(found) == 1:
        return next(iter(found))
    return ""


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


def load_confirmed_source_files(root: Path, architecture: str) -> list[Path] | None:
    """Clang-confirmed files from prepare, or None when that list is not ready.

    Analyze/stub scans must not invent a second file universe. Layout heuristics
    remain only as bootstrap before ``summary/scope_set.yaml`` exists.
    """
    arch = str(architecture or "").strip()
    if not arch:
        return None
    op = Path(root).expanduser().resolve()
    scope_path = op / ".ascendc-pilot" / arch / "uo" / "summary" / "scope_set.yaml"
    if not scope_path.is_file():
        return None
    try:
        from uo_init.yaml_io import read_yaml

        doc = read_yaml(scope_path)
    except Exception:  # noqa: BLE001
        return None
    raw = doc.get("confirmed_source_files") if isinstance(doc, dict) else None
    if not isinstance(raw, list) or not raw:
        return None
    out: list[Path] = []
    seen: set[Path] = set()
    for item in raw:
        rel = str(item or "").replace("\\", "/").strip()
        if not rel:
            continue
        cand = (op / rel).resolve()
        if not cand.is_file():
            continue
        if cand in seen:
            continue
        seen.add(cand)
        out.append(cand)
    return out or None


def _posix_rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def _is_kernel_scope_rel(rel: str) -> bool:
    posix = rel.replace("\\", "/")
    return (
        posix.startswith("op_kernel/")
        or "/op_kernel/" in posix
        or posix.startswith("common/op_kernel/")
        or "/common/op_kernel/" in posix
    )


def _is_host_scope_rel(rel: str) -> bool:
    posix = rel.replace("\\", "/")
    return posix.startswith("op_host/") or "/op_host/" in posix


def _is_generated_rel(rel: str) -> bool:
    posix = rel.replace("\\", "/")
    return posix.startswith(".ascendc-pilot/") or "/.ascendc-pilot/" in posix


def _confirmed_subset(
    root: Path,
    architecture: str,
    *,
    predicate,
) -> list[Path] | None:
    confirmed = load_confirmed_source_files(root, architecture)
    if confirmed is None:
        return None
    out: list[Path] = []
    seen: set[Path] = set()
    for path in confirmed:
        rel = _posix_rel(root, path)
        if _is_generated_rel(rel):
            continue
        if is_other_arch_path(path, architecture):
            continue
        if not predicate(rel, path):
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def selected_kernel_files(
    root: Path,
    architecture: str,
    *,
    kernel_entry: Path | None = None,
) -> list[Path]:
    """Kernel files for this architecture.

    After prepare, this is the kernel-side Clang set (other-arch paths dropped).
    Before that, layout heuristics bootstrap entry TUs and the arch folder.
    """
    confirmed = _confirmed_subset(
        root,
        architecture,
        predicate=lambda rel, _path: _is_kernel_scope_rel(rel),
    )
    if confirmed is not None:
        out = list(confirmed)
        if kernel_entry is not None and kernel_entry.is_file():
            if not is_other_arch_path(kernel_entry, architecture):
                key = kernel_entry.resolve()
                if key not in {p.resolve() for p in out}:
                    owns = entry_include_architecture(
                        kernel_entry.read_text(encoding="utf-8", errors="replace")
                    )
                    arch = str(architecture or "").strip().lower()
                    if not (owns and arch and owns != arch):
                        out.append(kernel_entry)
        return out

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
    arch = str(architecture or "").strip().lower()
    if kernel_root.is_dir():
        for path in sorted(iter_cpp(kernel_root, recursive=False)):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Arch-neutral entry names (foo.cpp vs foo_apt.cpp) are disambiguated
            # by what they include — never take a TU that builds another archNN.
            owns = entry_include_architecture(text)
            if owns and arch and owns != arch:
                continue
            if includes_architecture(text, architecture):
                add(path)
                continue
            if not owns and ("__aicore__" in text or "GET_TILING_DATA" in text):
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
    confirmed = _confirmed_subset(
        root,
        architecture,
        predicate=lambda rel, _path: _is_host_scope_rel(rel),
    )
    if confirmed is not None:
        return confirmed
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
    def _tiling_header(rel: str, path: Path) -> bool:
        if path.suffix.lower() not in {".h", ".hpp", ".hh"}:
            return False
        return "tiling" in path.name.lower() or "tiling" in rel.lower()

    confirmed = _confirmed_subset(root, architecture, predicate=_tiling_header)
    if confirmed is not None:
        return confirmed
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
