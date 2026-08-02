# -*- coding: utf-8 -*-
"""Decide which files an operator's analysis is allowed to look at.

Scope comes from the repository layout, never from the operator's name: a file
is in because of the directory it sits in, and a shared file is in because
something the operator compiles includes it. Name matching cannot express the
second half -- a domain keeps common headers beside its operators, and
`attention/common/op_kernel/arch35/pse.h` carries no operator name yet is
compiled into the kernel. Dropping it does not merely lose detail, it makes
whatever the operator reads from it look undefined.

    <op_dir>/op_api      user-facing contract: which inputs are refused
    <op_dir>/op_graph    prototype: inputs, outputs, attributes
    <op_dir>/op_host     tiling, definition, shape inference
    <op_dir>/op_kernel   the kernel itself
    <common>/**          only what the above actually include, transitively

One architecture per run: `archNN` folders other than the requested one are
dropped, since a run models one hardware generation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx"})
HEADER_SUFFIXES = frozenset({".h", ".hh", ".hpp", ".hxx"})
SCANNED_SUFFIXES = SOURCE_SUFFIXES | HEADER_SUFFIXES

# Path segments that never carry production behaviour. Matched per segment, so
# a directory named `st` is dropped while `fast_path.cpp` is not.
EXCLUDED_SEGMENTS = frozenset(
    {"test", "tests", "ut", "st", "example", "examples", "third_party", "build", "dist"}
)

# The four directories the Ascend C layout gives an operator. Their presence is
# what makes a file operator-owned; the file name plays no part.
OP_SEGMENTS = frozenset({"op_api", "op_graph", "op_host", "op_kernel"})

ARCH_SEGMENT_RE = re.compile(r"^arch\d+$")
ARCH_IN_PATH_RE = re.compile(r"(?:^|/)(arch\d+)/")
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*["<]([^">]+)[">]', re.MULTILINE)

# Only the head of a file is scanned for includes; no translation unit puts
# them past this point, and reading whole kernel headers would dominate.
INCLUDE_SCAN_BYTES = 200_000

ROLE_API = "api"
ROLE_GRAPH = "graph"
ROLE_HOST_DEF = "host_def"
ROLE_HOST_INFERSHAPE = "host_infershape"
ROLE_HOST_TILING = "host_tiling"
ROLE_HOST_OTHER = "host_other"
ROLE_KERNEL_ENTRY = "kernel_entry"
ROLE_KERNEL_OTHER = "kernel_other"
ROLE_HEADER = "header"

SIDE_HOST = "host"
SIDE_KERNEL = "kernel"


@dataclass(frozen=True)
class ScopeFile:
    """One file the analysis may read, and what it is."""

    path: Path
    role: str
    side: str
    is_tu: bool
    shared: bool = False

    @property
    def is_header(self) -> bool:
        return not self.is_tu


@dataclass
class ScopeSet:
    """Every file in scope for one operator on one architecture."""

    op_dir: Path
    workspace_root: Path
    arch_dir: str
    files: list[ScopeFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._index = {_key(f.path) for f in self.files}

    def contains(self, path: str | Path | None) -> bool:
        """Membership for a path clang reports, whose spelling we do not control."""
        if not path:
            return False
        return _key(path) in self._index

    def select(
        self, *, role: str | Iterable[str] | None = None, side: str | None = None,
        tu_only: bool = False,
    ) -> list[ScopeFile]:
        roles = {role} if isinstance(role, str) else (set(role) if role else None)
        out = []
        for f in self.files:
            if roles is not None and f.role not in roles:
                continue
            if side is not None and f.side != side:
                continue
            if tu_only and not f.is_tu:
                continue
            out.append(f)
        return out

    def paths(self, **kw) -> list[Path]:
        return [f.path for f in self.select(**kw)]

    def to_dict(self) -> dict:
        def rel(p: Path) -> str:
            try:
                return p.relative_to(self.workspace_root).as_posix()
            except ValueError:
                return p.as_posix()

        return {
            "op_dir": self.op_dir.as_posix(),
            "workspace_root": self.workspace_root.as_posix(),
            "arch_dir": self.arch_dir,
            "files": [
                {
                    "path": rel(f.path),
                    "role": f.role,
                    "side": f.side,
                    "is_tu": f.is_tu,
                    "shared": f.shared,
                }
                for f in self.files
            ],
            "notes": list(self.notes),
        }


def _key(path: str | Path) -> str:
    """Comparable form of a path: clang spells them with forward slashes and
    whatever case the include line used."""
    text = str(path).replace("\\", "/")
    return text.lower()


def _excluded(rel_parts: Iterable[str]) -> bool:
    return bool({p.lower() for p in rel_parts} & EXCLUDED_SEGMENTS)


def _walk_sources(root: Path) -> list[Path]:
    """Source and header files under one tree, skipping test-like folders."""
    if not root.is_dir():
        return []
    out: list[Path] = []
    stack = [root]
    while stack:
        here = stack.pop()
        try:
            entries = list(here.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                continue
            if entry.is_dir():
                if name.lower() in EXCLUDED_SEGMENTS:
                    continue
                stack.append(entry)
            elif entry.suffix.lower() in SCANNED_SUFFIXES:
                out.append(entry)
    return sorted(out)


def resolve_workspace(op_dir: Path) -> tuple[Path, str, list[str]]:
    """Where the operator sits and where its domain keeps shared code.

    Returns `(workspace_root, common_rel, notes)`; `common_rel` is empty when
    the domain has no shared tree. Three layouts are tried in the order they
    occur in Ascend C repositories: a `common` beside the operator package, one
    inside it, then one further up.
    """
    notes: list[str] = []
    op_like = (op_dir / "op_host").is_dir() or (op_dir / "op_kernel").is_dir()

    sibling = op_dir.parent / "common"
    if op_like and sibling.is_dir():
        notes.append(f"common_beside_operator: {sibling.as_posix()}")
        return op_dir.parent, "common", notes

    inner = op_dir / "common"
    if inner.is_dir():
        notes.append(f"common_inside_operator: {inner.as_posix()}")
        return op_dir, "common", notes

    cur = op_dir.parent
    for _ in range(3):
        cand = cur.parent / "common"
        if cand.is_dir() and op_like:
            notes.append(f"common_above_operator: {cand.as_posix()}")
            return cur.parent, "common", notes
        if cur.parent == cur:
            break
        cur = cur.parent

    notes.append("no_common_tree")
    return op_dir.parent if op_like else op_dir, "", notes


def _operator_files(op_dir: Path) -> list[Path]:
    """Everything under the operator's four layout directories."""
    out: list[Path] = []
    for segment in sorted(OP_SEGMENTS):
        out.extend(_walk_sources(op_dir / segment))
    return out


def filter_architecture(paths: Iterable[Path], arch_dir: str) -> list[Path]:
    """Drop `archNN` folders other than the requested one.

    A path with no `archNN` segment is architecture-neutral and stays.
    """
    arch = (arch_dir or "").strip().lower()
    if not arch:
        return list(paths)
    out: list[Path] = []
    for path in paths:
        segments = [p.lower() for p in path.parts]
        arch_segments = [p for p in segments if ARCH_SEGMENT_RE.match(p)]
        if not arch_segments or arch in arch_segments:
            out.append(path)
    return out


def _include_targets(text: str) -> list[str]:
    return [m.group(1).replace("\\", "/").strip() for m in INCLUDE_RE.finditer(text)]


def _read_head(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:INCLUDE_SCAN_BYTES]
    except OSError:
        return ""


def _shared_index(shared: Iterable[Path], workspace_root: Path) -> tuple[dict, dict]:
    by_rel: dict[str, Path] = {}
    by_name: dict[str, list[Path]] = {}
    for path in shared:
        try:
            rel = path.relative_to(workspace_root).as_posix()
        except ValueError:
            rel = path.as_posix()
        by_rel[_key(rel)] = path
        by_name.setdefault(path.name.lower(), []).append(path)
    return by_rel, by_name


def _resolve_include(
    include: str, *, source: Path, workspace_root: Path,
    by_rel: dict[str, Path], by_name: dict[str, list[Path]],
) -> Path | None:
    """Which shared file an include line names, if any.

    Three ways, narrowing: resolved against the including file, matched as a
    workspace-relative path, then matched on a trailing path fragment. Never on
    the bare file name -- `matmul.h` exists in three trees here, and picking one
    by name would attach a file the operator does not compile.
    """
    candidate = (source.parent / include).resolve()
    for known in by_name.get(candidate.name.lower(), ()):
        if _key(known) == _key(candidate):
            return known

    try:
        rel = candidate.relative_to(workspace_root).as_posix()
    except (ValueError, OSError):
        rel = ""
    if rel and _key(rel) in by_rel:
        return by_rel[_key(rel)]

    if "/" in include:
        tail = _key(include)
        for known in by_name.get(Path(include).name.lower(), ()):
            if _key(known).endswith("/" + tail):
                return known
    return None


def prune_shared_by_includes(
    operator_files: Iterable[Path], shared: Iterable[Path], workspace_root: Path
) -> list[Path]:
    """Shared files reachable from the operator through `#include`.

    Transitive: a common header that pulls another common header brings it in.
    Bounded by the shared set itself, so the walk cannot leave the domain.
    """
    shared = list(shared)
    if not shared:
        return []
    by_rel, by_name = _shared_index(shared, workspace_root)

    selected: dict[str, Path] = {}
    frontier = list(operator_files)
    seen: set[str] = set()
    while frontier:
        source = frontier.pop()
        marker = _key(source)
        if marker in seen:
            continue
        seen.add(marker)
        for include in _include_targets(_read_head(source)):
            hit = _resolve_include(
                include,
                source=source,
                workspace_root=workspace_root,
                by_rel=by_rel,
                by_name=by_name,
            )
            if hit is not None and _key(hit) not in selected:
                selected[_key(hit)] = hit
                frontier.append(hit)
    return sorted(selected.values())


def _role_of(path: Path) -> str:
    """What a file is, from where it sits and what kind of file it is."""
    suffix = path.suffix.lower()
    segments = {p.lower() for p in path.parts}
    stem = path.stem.lower()

    # These two directories hold one thing each, so what a file is there does
    # not depend on its suffix: the prototype is a header and is still the
    # prototype. Under `op_host` and `op_kernel` the suffix does matter, since
    # the finer roles below describe translation units.
    if "op_api" in segments:
        return ROLE_API
    if "op_graph" in segments:
        return ROLE_GRAPH
    if suffix in HEADER_SUFFIXES:
        return ROLE_HEADER
    if "op_kernel" in segments:
        return ROLE_KERNEL_ENTRY
    if "op_host" in segments:
        if stem.endswith("_def"):
            return ROLE_HOST_DEF
        if "infershape" in stem or stem.endswith("_proto"):
            return ROLE_HOST_INFERSHAPE
        if "_tiling" in stem:
            return ROLE_HOST_TILING
        return ROLE_HOST_OTHER
    return ROLE_HOST_OTHER


def _side_of(path: Path) -> str:
    """Which compiler configuration this file needs.

    Only `op_kernel` is built by the device compiler; the API layer, the
    prototype and tiling are all host code.
    """
    return SIDE_KERNEL if "op_kernel" in {p.lower() for p in path.parts} else SIDE_HOST


def entry_architecture(path: Path) -> str:
    """Which `archNN` a kernel entry compiles, read from what it includes.

    A repository can keep one entry per architecture beside each other. Their
    names carry no reliable marker -- one may end in `_apt`, the other not --
    but each includes only its own architecture's headers.
    """
    for include in _include_targets(_read_head(path)):
        found = ARCH_IN_PATH_RE.search("/" + include)
        if found:
            return found.group(1).lower()
    return ""


def scan(op_dir: str | Path, *, arch_dir: str = "") -> ScopeSet:
    """Everything the analysis may read for one operator on one architecture."""
    op_dir = Path(op_dir).expanduser().resolve()
    workspace_root, common_rel, notes = resolve_workspace(op_dir)

    owned = _operator_files(op_dir)
    owned = filter_architecture(owned, arch_dir)

    shared: list[Path] = []
    if common_rel:
        pool = _walk_sources(workspace_root / common_rel)
        pool = filter_architecture(pool, arch_dir)
        shared = prune_shared_by_includes(owned, pool, workspace_root)
        notes.append(f"shared_available={len(pool)} shared_included={len(shared)}")

    from_common = {_key(p) for p in shared}
    files: list[ScopeFile] = []
    for path in owned + shared:
        files.append(
            ScopeFile(
                path=path,
                role=_role_of(path),
                side=_side_of(path),
                is_tu=path.suffix.lower() in SOURCE_SUFFIXES,
                shared=_key(path) in from_common,
            )
        )

    files = _drop_foreign_arch_entries(files, arch_dir, notes)
    files.sort(key=lambda f: f.path.as_posix())
    return ScopeSet(
        op_dir=op_dir,
        workspace_root=workspace_root,
        arch_dir=arch_dir,
        files=files,
        notes=notes,
    )


def _drop_foreign_arch_entries(
    files: list[ScopeFile], arch_dir: str, notes: list[str]
) -> list[ScopeFile]:
    """Kernel entries sit above the `archNN` folders, so the path filter cannot
    see which architecture they build. Their includes can."""
    arch = (arch_dir or "").strip().lower()
    if not arch:
        return files
    out: list[ScopeFile] = []
    for f in files:
        if f.role != ROLE_KERNEL_ENTRY or not f.is_tu:
            out.append(f)
            continue
        owns = entry_architecture(f.path)
        if owns and owns != arch:
            notes.append(f"kernel_entry_other_arch: {f.path.name} builds {owns}")
            continue
        out.append(f)
    return out
