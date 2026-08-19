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


# Hardware-generation directory / path token:
#   arch35, arch22     — published DAV_NNNN → first two digits
#   arch-920r1         — unpublished DAV_9201 (hyphenated product name)
#   arch920r1          — same identity, unhyphenated spelling on disk / in intent
# More-specific ``rN`` spellings must precede bare ``archNN`` so ``arch920r1``
# is not consumed as ``arch920``.
ARCH_NAME = r"arch(?:-\d+r\d+|\d+r\d+|\d+)"
ARCH_DIR_RE = re.compile(rf"^{ARCH_NAME}$")
ARCH_IN_PATH_RE = re.compile(rf"(?:^|/)({ARCH_NAME})(?:/|$)")
# Path segment `/arch22/` or filename token `_arch22.h` / `foo_arch35_bar.h`.
_ARCH_TOKEN_RE = re.compile(rf"(?:^|[/_.-])({ARCH_NAME})(?:[/_.-]|$)")
_ARCH_ALIAS = {
    "arch-920r1": "arch-920r1",
    "arch920r1": "arch-920r1",
    "dav_9201": "arch-920r1",
    "dav-9201": "arch-920r1",
    "9201": "arch-920r1",
}
# One-way: unpublished 920r1 may read arch35 sources. arch35 never reads 920r1.
_SOURCE_COUSINS: dict[str, frozenset[str]] = {
    "arch-920r1": frozenset({"arch35"}),
}
_CPP_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_QUOTED_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
_ANY_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*["<]([^">]+)[">]', re.MULTILINE)

# template <...> __global__, extern "C" __global__, or a plain __global__.
# Qualifier order is not operator-specific: both `__global__ __aicore__` and
# `__aicore__ __global__` (and `__global__` alone) appear in ops-transformer.
# Do not use DOTALL ``.*?`` here: IFA kernel TUs are multi-MB and that form
# spends tens of seconds backtracking.
_KERNEL_QUALS = r"(?:__global__\s+(?:__aicore__\s+)?|__aicore__\s+__global__\s+)"
GLOBAL_KERNEL_RE = re.compile(
    r"(?:template\s*<(?P<tpl>[^>]{0,800})>\s*)?"
    r"(?:extern\s+\"C\"\s+)?"
    rf"{_KERNEL_QUALS}void\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^;{}]{0,16000})\)(?:\s|//[^\n]*)*\{",
)
KERNEL_ENTRY_NAME_RE = re.compile(rf"{_KERNEL_QUALS}void\s+([A-Za-z_]\w*)")

_TILING_HEADER_GLOBS = (
    "*tiling_data*.h",
    "*tiling_data*.hpp",
    "*_tiling.h",
    "*_tiling.hpp",
    "*tiling*.h",
)


def canonicalize_architecture(value: str | None) -> str:
    """Map aliases onto the product arch name. Unknown input is returned as-is.

    ``arch920r1`` / ``DAV_9201`` / ``9201`` → ``arch-920r1``. Published
    ``arch35`` stays ``arch35``. Empty stays empty.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    low = re.sub(r"\s+", "", raw).lower()
    if low in _ARCH_ALIAS:
        return _ARCH_ALIAS[low]
    compact = low.replace("-", "").replace("_", "")
    if compact in {"dav9201"}:
        return "arch-920r1"
    m = re.fullmatch(r"arch-?(\d+)r(\d+)", low)
    if m:
        return f"arch-{m.group(1)}r{m.group(2)}"
    m = re.fullmatch(r"arch(\d+)", low)
    if m:
        return f"arch{m.group(1)}"
    return raw


def architectures_match(left: str | None, right: str | None) -> bool:
    """True when both names are the same compile identity (hyphen optional)."""
    a = canonicalize_architecture(left)
    b = canonicalize_architecture(right)
    return bool(a) and a == b


def identity_arch_names(architecture: str | None) -> frozenset[str]:
    """On-disk spellings of this architecture, not ISA cousins."""
    raw = str(architecture or "").strip()
    if not raw:
        return frozenset()
    canon = canonicalize_architecture(raw)
    names = {raw, raw.lower(), canon}
    if canon == "arch-920r1":
        names.update({"arch-920r1", "arch920r1"})
    return frozenset(n for n in names if n)


def arch_scope_names(architecture: str | None) -> frozenset[str]:
    """Identity folders plus one-way source cousins (920r1 may read arch35)."""
    ident = identity_arch_names(architecture)
    canon = canonicalize_architecture(architecture)
    extra = _SOURCE_COUSINS.get(canon, frozenset())
    return ident | extra


def architecture_in_scope(name: str | None, architecture: str | None) -> bool:
    """True when ``name`` is this arch or a permitted cousin folder."""
    token = str(name or "").strip()
    if not token:
        return False
    scope = arch_scope_names(architecture)
    low = {s.lower() for s in scope}
    if token in scope or token.lower() in low:
        return True
    return canonicalize_architecture(token) in {canonicalize_architecture(s) for s in scope}


def match_on_disk_architecture(pin: str | None, known: Iterable[str]) -> str:
    """Resolve a user pin onto an existing ``arch*`` folder name.

    Exact disk spelling wins; ``arch920r1`` matches ``arch-920r1``.
    """
    raw = str(pin or "").strip()
    names = [str(n).strip() for n in known if str(n).strip()]
    if not raw or not names:
        return raw
    if raw in names:
        return raw
    by_l = {n.lower(): n for n in names}
    hit = by_l.get(raw.lower())
    if hit:
        return hit
    canon = canonicalize_architecture(raw)
    hits = [n for n in names if canonicalize_architecture(n) == canon]
    if len(hits) == 1:
        return hits[0]
    if "arch-920r1" in hits:
        return "arch-920r1"
    return hits[0] if hits else raw


def iter_identity_arch_dirs(parent: Path, architecture: str) -> list[Path]:
    """Existing identity ``arch*`` folders under ``parent`` (not cousins)."""
    out: list[Path] = []
    seen: set[str] = set()
    for name in sorted(identity_arch_names(architecture)):
        d = Path(parent) / name
        try:
            if not d.is_dir():
                continue
            key = str(d.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def iter_cousin_arch_dirs(parent: Path, architecture: str) -> list[Path]:
    """Existing one-way cousin folders (``arch35`` when analysing 920r1)."""
    canon = canonicalize_architecture(architecture)
    extra = _SOURCE_COUSINS.get(canon, frozenset())
    out: list[Path] = []
    seen: set[str] = set()
    for name in sorted(extra):
        d = Path(parent) / name
        try:
            if not d.is_dir():
                continue
            key = str(d.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def iter_arch_source_dirs(parent: Path, architecture: str) -> list[Path]:
    """Identity folders first, then cousins. Used for host tiling / headers."""
    return iter_identity_arch_dirs(parent, architecture) + iter_cousin_arch_dirs(
        parent, architecture
    )


def path_owned_architecture(path: Path) -> str:
    """``archNN`` folder the file sits in. Empty when the path is arch-neutral.

    A file under ``op_kernel/arch22/`` belongs to arch22 even if it includes a
    shared ``*_arch35.h`` (A2/A3 pipeline reuse). Include-derived architecture
    is only for entries that live *above* the arch folders.
    """
    found = [part.lower() for part in Path(path).parts if ARCH_DIR_RE.match(part)]
    if len(found) == 1:
        return found[0]
    return ""


def is_other_arch_path(path: Path | str, architecture: str) -> bool:
    """True when a path segment is an ``arch*`` folder outside this scope.

    Cousin folders (``arch35`` while analysing ``arch-920r1``) are in scope.
    """
    arch = str(architecture or "").strip()
    if not arch:
        return False
    for part in Path(path).parts:
        if ARCH_DIR_RE.match(part) and not architecture_in_scope(part, arch):
            return True
    return False


def keep_lexical_kernel_path(path: Path | str, architecture: str) -> bool:
    """True when METHOD/CALLS / SourceIndex may scan this kernel file.

    Clang may confirm a foreign-arch tiling header for types. That path stays
    in ``selected_kernel_files``. Lexical body scans must not mint a second
    architecture's kernel graph from ``op_kernel/archNN/**``.
    """
    return not is_other_arch_path(path, architecture)


def include_root_owned_architecture(path: Path | str) -> str:
    """Arch folder a ``-I`` root sits in. Empty when the directory is arch-neutral.

    ``op_kernel/arch35`` → ``arch35``; ``op_kernel`` → ``""``.
    """
    return path_owned_architecture(Path(path))


_ENTRY_TU_SUFFIXES = {".cpp", ".cc", ".cxx"}


def is_foreign_arch_entry_tu(path: Path | str, architecture: str) -> bool:
    """True for another architecture's compile unit, not an included header.

    Cousin ``arch35/*.cpp`` stays a foreign entry when analysing 920r1: the
    sources may be included, but they are not this arch's kernel TU.
    """
    p = Path(path)
    if p.suffix.lower() not in _ENTRY_TU_SUFFIXES:
        return False
    owned = path_owned_architecture(p)
    if not owned:
        return False
    return not architectures_match(owned, architecture)


def includes_architecture(text: str, architecture: str) -> bool:
    """True when the TU pulls the current arch, including ``./arch35/``."""
    names = arch_scope_names(architecture)
    if not names:
        return False
    blob = text.replace("\\", "/")
    return any(f"{name}/" in blob for name in names)


def arch_tokens_in_include(include: str) -> set[str]:
    """``archNN`` markers in an include path or filename (not ``architecture.h``)."""
    text = "/" + (include or "").replace("\\", "/")
    return {m.group(1).lower() for m in _ARCH_TOKEN_RE.finditer(text)}


def arch_number(architecture: str) -> int:
    """Numeric rank for apt-vs-plain entry picking. ``arch-920r1`` → 920."""
    raw = canonicalize_architecture(architecture) or str(architecture or "").strip().lower()
    m = re.fullmatch(r"arch(\d+)", raw)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"arch-(\d+)r\d+", raw)
    if m:
        return int(m.group(1))
    return 0


def pick_kernel_entry(targets: list[Path], architecture: str) -> Path | None:
    """Pick the kernel TU for this architecture.

    A file under ``op_kernel/archNN/`` is owned by that folder. Root-level
    entries (``foo.cpp`` vs ``foo_apt.cpp``) use include-derived architecture
    when it is unique; otherwise apt vs plain is a candidate ranking by
    arch generation, not a semantic identity for the TU.

    ``arch-920r1`` may keep a root ``*_apt.cpp`` that ``#include "arch35/..."``.
    A compile unit sitting in a cousin folder is last-resort only.
    """
    arch = str(architecture or "").strip()
    arch_n = arch_number(arch)
    matching: list[Path] = []
    unscoped: list[Path] = []
    cousin_hits: list[Path] = []
    for raw in targets:
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            owned = path_owned_architecture(path)
        except OSError:
            owned = ""
        include_owned = ""
        if not owned:
            try:
                include_owned = entry_include_architecture(_text(path))
            except OSError:
                include_owned = ""
            owned = include_owned
        if owned and arch and not architecture_in_scope(owned, arch):
            continue
        if owned and architectures_match(owned, arch):
            matching.append(path)
        elif include_owned and architecture_in_scope(include_owned, arch):
            unscoped.append(path)
        elif owned:
            cousin_hits.append(path)
        else:
            unscoped.append(path)
    pool = matching or unscoped or cousin_hits
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

    After prepare, this is the kernel-side Clang set (included headers from
    another ``arch*`` folder stay when Clang confirmed them). Before that,
    layout heuristics bootstrap entry TUs and the current arch folder.
    """
    confirmed = _confirmed_subset(
        root,
        architecture,
        predicate=lambda rel, _path: _is_kernel_scope_rel(rel),
    )
    if confirmed is not None:
        out = list(confirmed)
        if kernel_entry is not None and kernel_entry.is_file():
            if not is_foreign_arch_entry_tu(kernel_entry, architecture):
                key = kernel_entry.resolve()
                if key not in {p.resolve() for p in out}:
                    owns = entry_include_architecture(_text(kernel_entry))
                    if not owns or architecture_in_scope(owns, architecture):
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
    for folder in iter_identity_arch_dirs(kernel_root, architecture):
        for path in sorted(iter_cpp(folder)):
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
            if owns and arch and not architecture_in_scope(owns, architecture):
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
        if is_foreign_arch_entry_tu(path, architecture):
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
