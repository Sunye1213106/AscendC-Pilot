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
from typing import Iterable, Iterator

def _text(path: Path | str) -> str:
    from uo_init.passes.source_text_cache import read_text

    return read_text(path)


ARCH_DIR_RE = re.compile(r"^arch\d+$")
_ARCH_IN_PATH_RE = re.compile(r"(?:^|/)(arch\d+)(?:/|$)")
# Path segment `/arch22/` or filename token `_arch22.h` / `foo_arch35_bar.h`.
_ARCH_TOKEN_RE = re.compile(r"(?:^|[/_.-])(arch\d+)(?:[/_.-]|$)")
_CPP_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_QUOTED_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
_ANY_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*["<]([^">]+)[">]', re.MULTILINE)

# template <...> __global__, extern "C" __global__, or a plain __global__.
# Qualifier order is not operator-specific: both `__global__ __aicore__` and
# `__aicore__ __global__` (and `__global__` alone) appear in ops-transformer.
_KERNEL_QUALS = r"(?:__global__\s+(?:__aicore__\s+)?|__aicore__\s+__global__\s+)"
GLOBAL_KERNEL_RE = re.compile(
    r"(?:template\s*<(?P<tpl>.*?)>\s*)?"
    r"(?:extern\s+\"C\"\s+)?"
    rf"{_KERNEL_QUALS}void\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*?)\)\s*\{",
    re.S,
)
KERNEL_ENTRY_NAME_RE = re.compile(rf"{_KERNEL_QUALS}void\s+([A-Za-z_]\w*)")

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


def arch_tokens_in_include(include: str) -> set[str]:
    """``archNN`` markers in an include path or filename (not ``architecture.h``)."""
    text = "/" + (include or "").replace("\\", "/")
    return {m.group(1).lower() for m in _ARCH_TOKEN_RE.finditer(text)}


def arch_number(architecture: str) -> int:
    m = re.fullmatch(r"arch(\d+)", str(architecture or "").strip().lower())
    return int(m.group(1)) if m else 0


def pick_kernel_entry(targets: list[Path], architecture: str) -> Path | None:
    """Pick the kernel TU for this architecture.

    ops-transformer keeps ``foo.cpp`` (typically arch22) beside ``foo_apt.cpp``
    (regbase / arch35+). Include-derived architecture wins when it is unique;
    otherwise apt vs plain follows the arch generation.
    """
    arch = str(architecture or "").strip().lower()
    arch_n = arch_number(arch)
    matching: list[Path] = []
    unscoped: list[Path] = []
    for raw in targets:
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            owns = entry_include_architecture(_text(path))
        except OSError:
            owns = ""
        if owns and arch and owns != arch:
            continue
        if owns == arch:
            matching.append(path)
        else:
            unscoped.append(path)
    pool = matching or unscoped
    if not pool:
        return None
    apt = [p for p in pool if p.name.endswith("_apt.cpp")]
    plain = [p for p in pool if not p.name.endswith("_apt.cpp")]
    chosen = (apt or plain) if arch_n >= 35 else (plain or apt)
    return sorted(chosen, key=lambda p: p.as_posix())[0]


def follow_repo_includes(
    seeds: Iterable[Path],
    *,
    repo_root: Path,
    architecture: str = "",
) -> list[Path]:
    """Quoted includes under the ops repo (sibling operators), not CANN."""
    root = Path(repo_root).resolve()
    out: list[Path] = []
    seen: set[Path] = set()
    pending = [Path(p) for p in seeds if Path(p).is_file()]
    while pending:
        path = pending.pop()
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        for included in resolve_quoted_includes(path):
            try:
                rel = included.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if "/tests/" in f"/{rel}/" or rel.startswith("tests/"):
                continue
            if is_other_arch_path(included, architecture):
                continue
            pending.append(included)
            if included.suffix.lower() in {".h", ".hpp", ".hh"}:
                out.append(included)
    return out


def entry_include_architecture(text: str) -> str:
    """Which ``archNN`` a root-level kernel entry builds, from its includes.

    Entries sit above ``archNN/`` folders, so the path alone cannot tell.
    Matching ``scope_scan.entry_architecture``: one concrete arch wins; mixed
    or absent markers yield empty so a preprocessor-gated entry (arch22 header
    plus an ``arch38/`` include behind ``#if``) is not rejected.
    """
    found: set[str] = set()
    for inc in _ANY_INCLUDE_RE.findall(text or ""):
        found |= arch_tokens_in_include(inc)
    if len(found) == 1:
        return next(iter(found))
    return ""


def quoted_include_basenames(path: Path) -> set[str]:
    """Basenames from ``#include "..."`` in ``path`` (not angle includes)."""
    try:
        text = _text(path)
    except OSError:
        return set()
    return {Path(inc.replace("\\", "/")).name.lower() for inc in _QUOTED_INCLUDE_RE.findall(text)}


def resolve_quoted_includes(path: Path) -> list[Path]:
    """Quoted includes resolved relative to the including file."""
    parent = Path(path).parent
    out: list[Path] = []
    try:
        text = _text(path)
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


def _resolve_confirmed_path(op: Path, rel: str) -> Path | None:
    """Resolve a prepare-confirmed path against the operator, family, or ops root.

    Clang records sibling-operator includes (``moe_distribute_dispatch_v2/...``)
    relative to the family folder, not ``op_dir``. ``op / rel`` then misses the
    file and TilingData structs living next door drop out of analyze.
    """
    rel_path = Path(str(rel or "").replace("\\", "/"))
    if not str(rel_path):
        return None
    candidates = [op / rel_path, op.parent / rel_path]
    try:
        from uo_init.paths import ops_root

        repo = ops_root()
        if repo is not None:
            candidates.append(Path(repo) / rel_path)
    except Exception:  # noqa: BLE001
        pass
    seen: set[Path] = set()
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


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
        cand = _resolve_confirmed_path(op, rel)
        if cand is None:
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
                    owns = entry_include_architecture(_text(kernel_entry))
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
    arch_n = arch_number(arch)
    if kernel_root.is_dir():
        root_tus: list[tuple[Path, str, str]] = []
        for path in sorted(iter_cpp(kernel_root, recursive=False)):
            try:
                text = _text(path)
            except OSError:
                continue
            owns = entry_include_architecture(text)
            if owns and arch and owns != arch:
                continue
            root_tus.append((path, text, owns))
        apt_here = any(p.name.endswith("_apt.cpp") for p, _t, _o in root_tus)
        for path, text, owns in root_tus:
            if includes_architecture(text, architecture):
                add(path)
                continue
            if path.name.endswith("_apt.cpp") and arch_n >= 35:
                add(path)
                continue
            if arch_n and arch_n < 35 and not path.name.endswith("_apt.cpp"):
                if "__aicore__" in text or "GET_TILING_DATA" in text:
                    add(path)
                continue
            if not apt_here and not owns and ("__aicore__" in text or "GET_TILING_DATA" in text):
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


def _kernel_include_closure(root: Path, architecture: str) -> list[Path]:
    """Quoted-include walk from current-arch kernel entries (no other-arch)."""
    kernel_files = list(selected_kernel_files(root, architecture))
    by_key = {p.resolve(): p for p in kernel_files}
    entries: list[Path] = []
    for path in kernel_files:
        if path.suffix.lower() not in {".cpp", ".cc", ".cxx"}:
            continue
        if is_other_arch_path(path, architecture):
            continue
        try:
            text = _text(path)
        except OSError:
            continue
        if GLOBAL_KERNEL_RE.search(text):
            entries.append(path)
    order: list[Path] = []
    seen: set[Path] = set()
    pending = list(entries)
    while pending:
        path = pending.pop(0)
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        order.append(path)
        for inc in resolve_quoted_includes(path):
            if is_other_arch_path(inc, architecture):
                continue
            resolved = inc.resolve()
            if resolved in seen:
                continue
            pending.append(by_key.get(resolved, inc))
    return order


def _path_is_under(path: Path, root: Path) -> bool:
    """True when ``path`` lives in this operator tree, not a sibling op include."""
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False


def _first_tpl_marker_file(
    root: Path, architecture: str, marker: str
) -> list[Path]:
    kernel_files = list(selected_kernel_files(root, architecture))
    for path in kernel_files:
        if path.suffix.lower() not in {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}:
            continue
        try:
            text = _text(path)
        except OSError:
            continue
        if marker not in text:
            continue
        for inc in resolve_quoted_includes(path):
            if is_other_arch_path(inc, architecture):
                continue
            if not _path_is_under(inc, root):
                continue
            try:
                inc_text = _text(inc)
            except OSError:
                continue
            if marker in inc_text:
                return [inc]
        if _path_is_under(path, root):
            return [path]
    return []


def tpl_decl_files(root: Path, architecture: str) -> list[Path]:
    """One TPL ARGS_DECL schema: the header the current-arch kernel entry includes.

    Layout globs and Clang scope often also list sibling ``*_tiling_key.h``
    files (apt vs non-apt, ifdef-gated variants). Merging those schemas
    inflates TILING_KEY counts so GET_TPL_TILING_KEY packing never matches.
    Fusion wrappers that ``#include "../../../other_op/...tiling_key.h"`` must
    not inherit that sibling's ARGS_DECL as this operator's source-declared keys.
    """
    for path in _kernel_include_closure(root, architecture):
        if not _path_is_under(path, root):
            continue
        try:
            text = _text(path)
        except OSError:
            continue
        if "ASCENDC_TPL_ARGS_DECL" in text:
            return [path]
    return _first_tpl_marker_file(root, architecture, "ASCENDC_TPL_ARGS_DECL")


def tpl_sel_files(root: Path, architecture: str) -> list[Path]:
    """ARGS_SEL headers reachable from the current-arch kernel entry.

    DECL and SEL are often split: the entry includes ``archNN/*_tiling_key.h``
    (SEL) which includes ``*_tiling_key_decl.h`` (DECL). Stopping at the first
    ARGS_DECL file drops the selections, so commit cannot rebuild TPL views.
    """
    hits: list[Path] = []
    seen: set[Path] = set()
    for path in _kernel_include_closure(root, architecture):
        if not _path_is_under(path, root):
            continue
        try:
            text = _text(path)
        except OSError:
            continue
        if "ASCENDC_TPL_ARGS_SEL" not in text:
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        hits.append(path)
    if hits:
        return hits
    return _first_tpl_marker_file(root, architecture, "ASCENDC_TPL_ARGS_SEL")


def select_tpl_decl_header(root: Path, architecture: str) -> Path | None:
    hits = tpl_decl_files(root, architecture)
    return hits[0] if hits else None
