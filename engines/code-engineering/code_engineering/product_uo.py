# -*- coding: utf-8 -*-
"""Thin, optional read API for the finalized CodeMap ``.uo`` product."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def product(
    project_root: Path | str, *, op_name: str = "", architecture: str = ""
) -> Path:
    """Return the finalized product, or an empty ``Path`` without ``uo_init``."""
    try:
        from uo_init.store.reader import find_uo_product
    except ImportError:
        return Path()
    try:
        found = find_uo_product(
            Path(project_root).expanduser().resolve(),
            op_name=op_name,
            architecture=architecture,
        )
    except ImportError:
        return Path()
    return found if found is not None and found.suffix == ".uo" and found.is_file() else Path()


def meta(
    project_root: Path | str, *, op_name: str = "", architecture: str = ""
) -> dict[str, Any]:
    """Read product metadata; return an empty mapping when unavailable."""
    p = product(project_root, op_name=op_name, architecture=architecture)
    if not p.is_file():
        return {}
    try:
        from uo_init.store.reader import read_meta
    except ImportError:
        return {}
    try:
        value = read_meta(p)
    except ImportError:
        return {}
    return value if isinstance(value, dict) else {}


def view(
    project_root: Path | str,
    name: str,
    *,
    op_name: str = "",
    architecture: str = "",
) -> Any:
    """Load a named product view, returning ``None`` when unavailable."""
    p = product(project_root, op_name=op_name, architecture=architecture)
    if not p.is_file():
        return None
    try:
        from uo_init.store.reader import load_view_blob
    except ImportError:
        return None
    try:
        return load_view_blob(p, name)
    except ImportError:
        return None


def identity(
    project_root: Path | str, *, op_name: str = "", architecture: str = ""
) -> dict[str, Any]:
    """Return stable identity fields for the selected CodeMap product."""
    p = product(project_root, op_name=op_name, architecture=architecture)
    if not p.is_file():
        return {}
    values = meta(project_root, op_name=op_name, architecture=architecture)
    graph = view(
        project_root,
        "ir/operator_graph.yaml",
        op_name=op_name,
        architecture=architecture,
    )
    graph = graph if isinstance(graph, dict) else {}
    return {
        "path": p.as_posix(),
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "schema": str(values.get("schema") or ""),
        "op_name": str(values.get("op_name") or op_name),
        "architecture": str(values.get("architecture") or architecture),
        "revision": str(values.get("revision") or values.get("source_revision") or ""),
        "graph_fingerprint": str(
            graph.get("fingerprint")
            or values.get("cm_graph_fingerprint")
            or values.get("graph_fingerprint")
            or ""
        ),
    }
