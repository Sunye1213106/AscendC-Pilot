# -*- coding: utf-8 -*-
"""Inventory current operator source files into the unified CodeMap.

A CodeMap should represent files even when a particular file contributes no
entity selected by a narrower semantic parser.  This prevents source coverage
from depending on incidental extraction hits and gives impact/navigation queries
stable FILE roots.  Only the requested architecture and shared operator entry
files that explicitly include/reference that architecture are admitted.
"""
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind

_SOURCE_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}


def inventory_source_files(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    archs = codemap.by_name(architecture, kind=EntityKind.ARCH)
    arch = archs[0] if archs else codemap.upsert(EntityKind.ARCH, architecture)

    files: dict[Path, str] = {}
    for role, directory in (
        ("api", root / "op_graph"),
        ("host", root / "op_host" / architecture),
        ("kernel", root / "op_kernel" / architecture),
    ):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES:
                files[path.resolve()] = role

    # Architecture-neutral top-level kernel entry files often dispatch into an
    # arch-specific implementation. Include only files with explicit source
    # evidence that they reference the requested architecture.
    kernel_root = root / "op_kernel"
    if kernel_root.is_dir():
        for path in kernel_root.iterdir():
            if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if f'"{architecture}/' in text or f"<{architecture}/" in text:
                files[path.resolve()] = "kernel-entry"

    for path, role in sorted(files.items(), key=lambda item: item[0].as_posix()):
        rel = _rel(root, path)
        ent = codemap.upsert(
            EntityKind.FILE,
            rel,
            eid=f"FILE::{rel}",
            attrs={
                "role": role,
                "architecture": architecture if role != "api" else "shared",
                "provenance": "source_inventory",
            },
            file=rel,
            line=1,
            status="confirmed",
        )
        if role != "api":
            codemap.link(
                RelationKind.AVAILABLE_ON,
                ent.id,
                arch.id,
                attrs={"provenance": "source_inventory"},
                status="confirmed",
            )

    codemap.meta["source_inventory_file_count"] = len(files)
    codemap.meta["source_inventory_roles"] = {
        role: sum(1 for value in files.values() if value == role)
        for role in sorted(set(files.values()))
    }
    return codemap


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()
