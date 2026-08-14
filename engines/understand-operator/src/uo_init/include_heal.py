# -*- coding: utf-8 -*-
"""Heal missing-header clang probes by adding -I roots to BuildContext.

``build_context.yaml`` is a generic ``-I/-D`` baseline. Operators still include
CANN / family headers from directories that yaml never listed. Prepare used to
fail as ``clang_probe_unclean`` / ``SCOPE_VALIDATE_BLOCKED``; this module finds
the header in the extracted CANN tree or ops repo, adds the matching include
directory, and retries. Per-operator extras are persisted so extract uses the
same flags. The shared yaml is not rewritten.

Disable with ``UO_INCLUDE_HEAL=0``. Round cap: ``UO_INCLUDE_HEAL_ROUNDS`` (8).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from uo_init.paths import require_architecture

MISSING_RE = re.compile(
    r"""['"<]([^'"><\s]+?\.(?:h|hpp|hh|inc|cuh))['">]\s+file not found""",
    re.IGNORECASE,
)
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.MULTILINE)
HEADER_SUFFIXES = (".h", ".hpp", ".hh", ".inc", ".cuh")
# CANN layout moved highlevel_api matmul headers. Operators still include the
# old path; forward to the file that exists in the current unpack.
INCLUDE_PREFIX_ALIASES = (
    ("lib/matrix/matmul/", "lib/matmul/"),
)
SKIP_DIR_NAMES = {
    ".git",
    ".svn",
    ".ascendc-pilot",
    "__pycache__",
    "bin",
    "lib",
    "lib64",
    "python",
    "python3",
    "share",
    "tools",
    "tests",
    "test",
    "build",
    "output",
    "cmake-build-debug",
    "cmake-build-release",
    "node_modules",
}
# Kernel trap: this -I makes ../../../../include/... resolve under impl/include.
FORBIDDEN_INCLUDE_SUBSTR = (
    "ascendc/include/basic_api",
)
# Relative to each cann-* package. Seeded even when yaml omitted them.
CANN_PACKAGE_RELS = (
    "x86_64-linux/include",
    "x86_64-linux/include/base",
    "x86_64-linux/pkg_inc",
    "x86_64-linux/pkg_inc/base",
    "x86_64-linux/include/op_common",
    "x86_64-linux/include/op_common/op_host",
    "x86_64-linux/include/aclnn",
    "x86_64-linux/asc/include",
    "x86_64-linux/asc/include/adv_api",
    "x86_64-linux/asc/include/adv_api/hccl/internal/hcomm",
    "x86_64-linux/asc/include/adv_api/hccl/internal/hcomm/pkg_inc",
    "x86_64-linux/asc/impl",
    "x86_64-linux/ascendc/include",
    "x86_64-linux/ascendc/include/highlevel_api",
    "x86_64-linux/tikcpp/tikcfw",
    "x86_64-linux/third_party/include",
    "x86_64-linux/include/nlohmann",
)
STD_HEADERS = frozenset(
    {
        "algorithm",
        "array",
        "atomic",
        "cassert",
        "cctype",
        "cerrno",
        "chrono",
        "cmath",
        "csignal",
        "cstdarg",
        "cstddef",
        "cstdint",
        "cstdio",
        "cstdlib",
        "cstring",
        "ctime",
        "cwchar",
        "deque",
        "exception",
        "filesystem",
        "functional",
        "initializer_list",
        "iomanip",
        "ios",
        "iosfwd",
        "iostream",
        "istream",
        "iterator",
        "limits",
        "list",
        "map",
        "memory",
        "mutex",
        "new",
        "numeric",
        "optional",
        "ostream",
        "queue",
        "set",
        "sstream",
        "stack",
        "stdexcept",
        "string",
        "string_view",
        "system_error",
        "thread",
        "tuple",
        "type_traits",
        "typeinfo",
        "unordered_map",
        "unordered_set",
        "utility",
        "variant",
        "vector",
        "climits",
        "cfloat",
        "complex",
        "condition_variable",
        "future",
        "random",
        "regex",
        "shared_mutex",
        "span",
        "stdalign.h",
        "stdbool.h",
        "stddef.h",
        "stdint.h",
        "stdio.h",
        "stdlib.h",
        "string.h",
        "math.h",
        "assert.h",
        "errno.h",
        "limits.h",
        "float.h",
        "time.h",
        "ctype.h",
        "wchar.h",
    }
)
_ENV_ENABLE = "UO_INCLUDE_HEAL"
_ENV_ROUNDS = "UO_INCLUDE_HEAL_ROUNDS"
_INDEX_CACHE: dict[tuple[str, ...], dict[str, list[str]]] = {}


def reset_index_cache() -> None:
    _INDEX_CACHE.clear()


@dataclass
class MissingInclude:
    name: str
    side: str  # host | kernel


@dataclass
class HealHit:
    include: str
    include_dir: str
    found: str
    side: str
    round: int = 0
    source: str = "probe"  # probe | bootstrap


@dataclass
class HealReport:
    rounds: int = 0
    healed: list[HealHit] = field(default_factory=list)
    unresolved: list[MissingInclude] = field(default_factory=list)
    added_host: list[str] = field(default_factory=list)
    added_kernel: list[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rounds": self.rounds,
            "added_host": list(self.added_host),
            "added_kernel": list(self.added_kernel),
            "healed": [
                {
                    "include": h.include,
                    "include_dir": h.include_dir,
                    "found": h.found,
                    "side": h.side,
                    "round": h.round,
                    "source": h.source,
                }
                for h in self.healed
            ],
            "unresolved": [{"include": u.name, "side": u.side} for u in self.unresolved],
        }


def heal_enabled() -> bool:
    raw = os.environ.get(_ENV_ENABLE, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def max_rounds() -> int:
    raw = os.environ.get(_ENV_ROUNDS, "8").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 8
    return max(1, min(n, 16))


def extras_summary_path(op_dir: str | Path, arch_dir: str | None) -> Path:
    arch = require_architecture(arch_dir)
    return Path(op_dir) / ".ascendc-pilot" / arch / "uo" / "summary" / "build_context_extras.yaml"


def extras_run_path(op_dir: str | Path, arch_dir: str | None, run_id: str) -> Path:
    arch = require_architecture(arch_dir)
    rid = str(run_id or "default").strip() or "default"
    return (
        Path(op_dir)
        / ".ascendc-pilot"
        / arch
        / "uo"
        / "runs"
        / rid
        / "scope"
        / "build_context_extras.yaml"
    )


def _posix(path: str | Path) -> str:
    return str(path).replace("\\", "/").rstrip("/")


def _norm_key(path: str | Path) -> str:
    return _posix(path).lower()


def _dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )


def clear_saved_extras(op_dir: str | Path, arch_dir: str | None, *, run_id: str | None = None) -> None:
    for path in (extras_summary_path(op_dir, arch_dir),):
        if path.is_file():
            path.unlink()
    if run_id:
        run_p = extras_run_path(op_dir, arch_dir, run_id)
        if run_p.is_file():
            run_p.unlink()


def save_extras(
    ctx: Any,
    report: HealReport,
    *,
    run_id: str | None = None,
) -> Path | None:
    """Persist extra -I so extract/assemble_kb reload the same BuildContext."""
    op_dir = getattr(ctx, "op_dir", "") or ""
    arch_dir = getattr(ctx, "arch_dir", "") or ""
    if not op_dir or not arch_dir:
        return None
    payload = {
        "version": 1,
        "source": "uo_init.include_heal",
        "host": list(getattr(ctx, "extra_host_includes", None) or []),
        "kernel": list(getattr(ctx, "extra_kernel_includes", None) or []),
        "host_force_include": list(getattr(ctx, "extra_host_force_includes", None) or []),
        "kernel_force_include": list(getattr(ctx, "extra_kernel_force_includes", None) or []),
        **report.to_dict(),
    }
    summary = extras_summary_path(op_dir, arch_dir)
    _dump_yaml(summary, payload)
    if run_id:
        _dump_yaml(extras_run_path(op_dir, arch_dir, run_id), payload)
    return summary


def apply_saved_extras(ctx: Any) -> list[str]:
    """Merge persisted extras into ``ctx``. Returns newly applied dirs."""
    op_dir = getattr(ctx, "op_dir", "") or ""
    arch_dir = getattr(ctx, "arch_dir", "") or ""
    if not op_dir or not arch_dir:
        return []
    path = extras_summary_path(op_dir, arch_dir)
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    applied: list[str] = []
    for side, key in (("host", "host"), ("kernel", "kernel")):
        for item in data.get(key) or []:
            if ctx.add_include(str(item), side=side):
                applied.append(str(item))
    for side, key in (("host", "host_force_include"), ("kernel", "kernel_force_include")):
        for item in data.get(key) or []:
            add_fi = getattr(ctx, "add_force_include", None)
            if callable(add_fi) and add_fi(str(item), side=side):
                applied.append(str(item))
    return applied


def parse_missing_includes(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in MISSING_RE.finditer(str(text or "")):
        name = match.group(1).replace("\\", "/").strip().lstrip("./")
        if not name or ".." in name.split("/"):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def missing_includes_from_probes(
    probes: Iterable[dict[str, Any]] | None,
    errors: Iterable[str] | None = None,
) -> list[MissingInclude]:
    out: list[MissingInclude] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, side: str) -> None:
        side_n = "kernel" if str(side).lower() == "kernel" else "host"
        key = (name.lower(), side_n)
        if key in seen:
            return
        seen.add(key)
        out.append(MissingInclude(name=name, side=side_n))

    for row in probes or []:
        if not isinstance(row, dict):
            continue
        side = str(row.get("side") or "host")
        chunks = [str(s) for s in (row.get("samples") or [])]
        if row.get("error"):
            chunks.append(str(row.get("error")))
        for chunk in chunks:
            for name in parse_missing_includes(chunk):
                add(name, side)
    for err in errors or []:
        for name in parse_missing_includes(str(err)):
            add(name, "host")
    return out


def scan_source_includes(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for match in INCLUDE_RE.finditer(text):
        name = match.group(1).replace("\\", "/").strip()
        if not name or name in STD_HEADERS:
            continue
        if ".." in name.split("/"):
            continue
        base = name.rsplit("/", 1)[-1].lower()
        if base in STD_HEADERS:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def aliased_include_name(include_name: str) -> str | None:
    rel = include_name.replace("\\", "/").strip().lstrip("./")
    for old, new in INCLUDE_PREFIX_ALIASES:
        if rel.startswith(old):
            return new + rel[len(old):]
    return None


def alias_cache_root(ctx: Any) -> Path | None:
    op_dir = Path(getattr(ctx, "op_dir", "") or "")
    arch = str(getattr(ctx, "arch_dir", "") or "")
    if not op_dir or not arch:
        return None
    return op_dir / ".ascendc-pilot" / arch / "uo" / "cache" / "include_alias"


def materialize_include_alias(
    ctx: Any, include_name: str, aliased: str, *, side: str
) -> HealHit | None:
    """Forward ``lib/matrix/matmul/X`` to the file that exists as ``lib/matmul/X``."""
    root = alias_cache_root(ctx)
    if root is None:
        return None
    rel = include_name.replace("\\", "/").strip().lstrip("./")
    dest = root.joinpath(*rel.split("/"))
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f'#pragma once\n#include "{aliased}"\n', encoding="utf-8")
    except OSError:
        return None
    include_dir = _posix(root)
    return HealHit(
        include=rel,
        include_dir=include_dir,
        found=_posix(dest),
        side=side,
    )


def is_forbidden_include_dir(path: str | Path) -> bool:
    key = _norm_key(path)
    return any(tok in key for tok in FORBIDDEN_INCLUDE_SUBSTR)


def include_dir_for(found: Path, include_name: str) -> Path:
    """Directory to put on -I so ``#include "include_name"`` opens ``found``."""
    resolved = found.resolve() if found.exists() else found
    rel = include_name.replace("\\", "/").strip().strip("/")
    blob = _posix(resolved)
    suffix = "/" + rel
    if blob.lower().endswith(suffix.lower()):
        parent = blob[: -len(rel)].rstrip("/")
        return Path(parent)
    return resolved.parent


def header_resolves(ctx: Any, include_name: str, *, side: str, tu_dir: Path | None = None) -> bool:
    rel = include_name.replace("\\", "/").strip()
    if tu_dir is not None:
        local = tu_dir / rel
        if local.is_file():
            return True
    includes = ctx.kernel_includes() if side == "kernel" else ctx.host_includes()
    for root in includes:
        cand = Path(root) / rel
        if cand.is_file():
            return True
    return False


def search_roots(ctx: Any) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: str | Path | None) -> None:
        if not path:
            return
        p = Path(str(path))
        key = _norm_key(p)
        if key in seen:
            return
        try:
            if not p.is_dir():
                return
        except OSError:
            return
        seen.add(key)
        roots.append(p)

    for p in list(ctx.host_includes() or []) + list(ctx.kernel_includes() or []):
        add(p)
    cann = Path(getattr(ctx, "cann_root", "") or "")
    if cann.is_dir():
        try:
            packages = [p for p in cann.iterdir() if p.is_dir()]
        except OSError:
            packages = []
        for pkg in packages:
            for rel in CANN_PACKAGE_RELS:
                add(pkg / rel)
    ops = Path(getattr(ctx, "ops_root", "") or "")
    if ops.is_dir():
        add(ops)
        add(ops / "common")
        add(ops / "common" / "include")
        add(ops / "common" / "include" / "op_kernel")
        add(ops / "3rd")
        add(ops / "3rdparty")
        add(ops / "3rdparty" / "include")
        # Sibling family commons (ffn includes headers that live under mc2/common).
        try:
            for fam in ops.iterdir():
                if not fam.is_dir() or _skip_walk_dir(fam.name):
                    continue
                add(fam / "common")
                add(fam / "common" / "utils")
                add(fam / "common" / "inc")
                add(fam / "3rd")
                add(fam / "3rdparty")
        except OSError:
            pass
    op_dir = Path(getattr(ctx, "op_dir", "") or "")
    if op_dir.is_dir():
        add(op_dir)
        add(op_dir / "op_host")
        add(op_dir / "op_kernel")
        add(op_dir.parent)
        add(op_dir.parent / "common")
        add(op_dir.parent / "common" / "utils")
        add(op_dir.parent / "common" / "inc")
        add(op_dir.parent / "3rd")
        add(op_dir.parent / "3rdparty")
    return roots


def _skip_walk_dir(name: str) -> bool:
    return name.lower() in SKIP_DIR_NAMES or name.startswith(".")


def _basename_index(roots: list[Path]) -> dict[str, list[str]]:
    key = tuple(_norm_key(r) for r in roots)
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    idx: dict[str, list[str]] = {}
    for root in roots:
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not _skip_walk_dir(d)]
                for fn in filenames:
                    low = fn.lower()
                    if not low.endswith(HEADER_SUFFIXES):
                        continue
                    idx.setdefault(low, []).append(str(Path(dirpath) / fn))
        except OSError:
            continue
    _INDEX_CACHE[key] = idx
    return idx


def _posix_under_roots(found: Path, roots: list[Path] | None) -> str:
    """Path relative to the first matching search root.

    Scoring must not look at the absolute path: a checkout folder named
    ``TEST`` (``D:/PR-review/TEST/ops-transformer/...``) would otherwise
    match the ``/test/`` penalty and drop real family headers.
    """
    if not roots:
        return _posix(found).lower()
    try:
        resolved = found.resolve()
    except OSError:
        resolved = found
    for root in roots:
        try:
            return _posix(resolved.relative_to(Path(root).resolve())).lower()
        except (ValueError, OSError):
            continue
    return _posix(found).lower()


def _score_hit(
    found: Path,
    include_name: str,
    *,
    side: str,
    roots: list[Path] | None = None,
) -> int:
    posix = _posix(found).lower()
    rel = include_name.replace("\\", "/").strip().lower()
    if is_forbidden_include_dir(found.parent):
        return -10000
    scoped = "/" + _posix_under_roots(found, roots).replace("\\", "/").strip("/") + "/"
    if "/tests/" in scoped or "/test/" in scoped:
        return -50
    score = 0
    if posix.endswith("/" + rel):
        score += 100
    elif "/" in rel:
        return -1000
    if "cann-" in posix:
        score += 10
    if side == "kernel" and "/asc/" in posix:
        score += 5
    if "/3rd/" in posix:
        score += 2
    # Prefer shallower include dirs (less accidental capture).
    score -= min(posix.count("/"), 40)
    return score


def find_include_dir(ctx: Any, include_name: str, *, side: str) -> HealHit | None:
    rel = include_name.replace("\\", "/").strip().lstrip("./")
    if not rel or ".." in rel.split("/"):
        return None
    roots = search_roots(ctx)
    candidates: list[Path] = []
    seen: set[str] = set()

    def consider(path: Path) -> None:
        try:
            if not path.is_file():
                return
        except OSError:
            return
        key = _norm_key(path)
        if key in seen:
            return
        seen.add(key)
        candidates.append(path)

    for root in roots:
        consider(root / rel)
        if "/" not in rel:
            try:
                for child in root.iterdir():
                    if child.is_dir() and not _skip_walk_dir(child.name):
                        consider(child / rel)
            except OSError:
                continue

    aliased = aliased_include_name(rel)
    if aliased:
        for root in roots:
            consider(root / aliased)

    if not candidates:
        base = rel.rsplit("/", 1)[-1].lower()
        for raw in _basename_index(roots).get(base, []):
            consider(Path(raw))

    ranked = sorted(
        candidates,
        key=lambda p: _score_hit(
            p, aliased or rel, side=side, roots=roots
        ),
        reverse=True,
    )
    for found in ranked:
        posix = _posix(found).replace("\\", "/").lower()
        if aliased and posix.endswith("/" + aliased.lower()):
            hit = materialize_include_alias(ctx, rel, aliased, side=side)
            if hit is not None:
                return hit
        if _score_hit(found, rel, side=side, roots=roots) < 0:
            continue
        include_dir = include_dir_for(found, rel)
        if is_forbidden_include_dir(include_dir):
            continue
        if not include_dir.is_dir():
            continue
        return HealHit(
            include=rel,
            include_dir=_posix(include_dir),
            found=_posix(found),
            side=side,
        )
    return None


def heal_missing_includes(
    ctx: Any,
    missing: Iterable[MissingInclude],
    *,
    round_no: int = 0,
    source: str = "probe",
) -> list[HealHit]:
    hits: list[HealHit] = []
    for item in missing:
        hit = find_include_dir(ctx, item.name, side=item.side)
        if hit is None:
            continue
        hit.side = item.side
        hit.round = round_no
        hit.source = source
        if ctx.add_include(hit.include_dir, side=item.side):
            hits.append(hit)
        elif not any(h.include.lower() == hit.include.lower() and h.side == hit.side for h in hits):
            # Already on -I (maybe from yaml this round); still record if it was the miss.
            continue
    return hits


def bootstrap_operator_includes(ctx: Any, tus: Iterable[Path]) -> list[HealHit]:
    missing: list[MissingInclude] = []
    seen: set[tuple[str, str]] = set()
    for tu in tus:
        path = Path(tu)
        if not path.is_file():
            continue
        side = "kernel" if "op_kernel" in _posix(path).lower() else "host"
        tu_dir = path.parent
        for name in scan_source_includes(path):
            if header_resolves(ctx, name, side=side, tu_dir=tu_dir):
                continue
            key = (name.lower(), side)
            if key in seen:
                continue
            seen.add(key)
            missing.append(MissingInclude(name=name, side=side))
    return heal_missing_includes(ctx, missing, round_no=0, source="bootstrap")


def enrich_scope_with_heal(
    *,
    ctx: Any,
    host_tus: Iterable[Path],
    kernel_tu: Path | None,
    enrich_fn: Callable[[], Any],
    run_id: str | None = None,
) -> tuple[Any, HealReport]:
    """Run Clang include enrichment, healing ``file not found`` between rounds.

    ``enrich_fn`` must read ``ctx.host_args()`` / ``kernel_args()`` live so each
    retry sees newly added -I. Returns the last enrichment and a persistable
    report. Caller still owns probe fallback / candidates.yaml.
    """
    from uo_init.progress import emit

    report = HealReport(enabled=heal_enabled())
    tus = [Path(p) for p in host_tus if p is not None]
    if kernel_tu is not None:
        tus.append(Path(kernel_tu))

    if not report.enabled:
        enrichment = enrich_fn()
        save_extras(ctx, report, run_id=run_id)
        return enrichment, report

    boot = bootstrap_operator_includes(ctx, tus)
    if boot:
        report.healed.extend(boot)
        report.rounds = 1
        for hit in boot:
            bucket = report.added_kernel if hit.side == "kernel" else report.added_host
            if hit.include_dir not in bucket:
                bucket.append(hit.include_dir)
        emit(
            "prepare include-heal bootstrap "
            + ", ".join(f"{h.include} -> {h.include_dir}" for h in boot[:4])
        )

    enrichment = None
    last_missing: list[MissingInclude] = []
    rounds = max_rounds()
    for rnd in range(1, rounds + 1):
        enrichment = enrich_fn()
        probes = list(getattr(enrichment, "probes", None) or [])
        errors = list(getattr(enrichment, "errors", None) or [])
        last_missing = missing_includes_from_probes(probes, errors)
        if not last_missing:
            report.unresolved = []
            break
        added = heal_missing_includes(ctx, last_missing, round_no=rnd, source="probe")
        if not added:
            report.unresolved = last_missing
            break
        report.healed.extend(added)
        report.rounds = max(report.rounds, rnd)
        for hit in added:
            bucket = report.added_kernel if hit.side == "kernel" else report.added_host
            if hit.include_dir not in bucket:
                bucket.append(hit.include_dir)
        emit(
            f"prepare include-heal round {rnd}: "
            + ", ".join(f"{h.include} -> {h.include_dir}" for h in added[:4])
        )
    else:
        report.unresolved = last_missing

    if enrichment is None:
        enrichment = enrich_fn()
    save_extras(ctx, report, run_id=run_id)
    return enrichment, report


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    from uo_init.build_context import BuildContext
    from uo_init.op_spec import discover

    ap = argparse.ArgumentParser(
        prog="uo-heal-includes",
        description="Discover missing-header -I dirs and write build_context extras.",
    )
    ap.add_argument("--op-dir", required=True)
    ap.add_argument("--arch-dir", required=True)
    ap.add_argument("--cann-root", default=None)
    ap.add_argument("--ops-root", default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument(
        "--probe",
        action="store_true",
        help="Also run libclang include enrichment (same as prepare's heal loop).",
    )
    args = ap.parse_args(argv)
    spec = discover(args.op_dir, arch_dir=args.arch_dir)
    ctx = BuildContext.load(
        cann_root=args.cann_root,
        ops_root=args.ops_root,
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
        apply_saved_extras=False,
    )
    hosts = [p for p in spec.host_targets if p.exists()]
    kernel = spec.kernel_entry if spec.kernel_entry and spec.kernel_entry.exists() else None
    clear_saved_extras(spec.op_dir, spec.arch_dir, run_id=args.run_id)
    if args.probe:
        from uo_init import scope_scan as sscan

        base_scope = spec.scope
        if base_scope is None:
            base_scope = sscan.scan(spec.op_dir, arch_dir=spec.arch_dir)

        def _enrich():
            return sscan.enrich_with_clang(
                base_scope,
                host_args=ctx.host_args(),
                kernel_args=ctx.kernel_args(
                    dtype_variant="DT_FLOAT16", source_path=kernel
                ),
                host_tus=hosts,
                kernel_tu=kernel,
            )

        _enr, report = enrich_scope_with_heal(
            ctx=ctx,
            host_tus=hosts,
            kernel_tu=kernel,
            enrich_fn=_enrich,
            run_id=args.run_id,
        )
    else:
        tus = list(hosts) + ([kernel] if kernel is not None else [])
        report = HealReport(enabled=heal_enabled())
        boot = bootstrap_operator_includes(ctx, tus)
        report.healed.extend(boot)
        report.rounds = 1 if boot else 0
        for hit in boot:
            bucket = report.added_kernel if hit.side == "kernel" else report.added_host
            if hit.include_dir not in bucket:
                bucket.append(hit.include_dir)
        save_extras(ctx, report, run_id=args.run_id)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    extras = extras_summary_path(spec.op_dir, spec.arch_dir)
    if extras.is_file():
        print(f"wrote {extras.as_posix()}", file=__import__("sys").stderr)
    return 0 if not report.unresolved else 2


if __name__ == "__main__":
    raise SystemExit(main())
