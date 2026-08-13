# -*- coding: utf-8 -*-
"""Thin, optional read API for the finalized CodeMap ``.uo`` product."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _missing_product(project_root: Path | str, op_name: str, architecture: str) -> FileNotFoundError:
    return FileNotFoundError(
        f"missing finalized .uo product for op={op_name or '*'} "
        f"arch={architecture or '*'} under {project_root}"
    )


def _checked_view(path: Path, name: str) -> Any:
    from uo_init.store.reader import load_view_blob_checked

    checked = load_view_blob_checked(path, name)
    if not checked.get("ok"):
        reason = checked.get("reason_code") or "VIEW_UNUSABLE"
        raise RuntimeError(f"{reason}: {name} in {path}")
    return checked.get("view")


def product(
    project_root: Path | str, *, op_name: str = "", architecture: str = ""
) -> Path:
    """Return the finalized product, or raise when it is missing."""
    try:
        from uo_init.store.reader import find_uo_product
    except ImportError as exc:
        raise FileNotFoundError("uo_init is not installed; cannot locate .uo product") from exc
    found = find_uo_product(
        Path(project_root).expanduser().resolve(),
        op_name=op_name,
        architecture=architecture,
    )
    if found is None or found.suffix != ".uo" or not found.is_file():
        raise _missing_product(project_root, op_name, architecture)
    return found


def meta(
    project_root: Path | str, *, op_name: str = "", architecture: str = ""
) -> dict[str, Any]:
    """Read product metadata; raise when the product is missing."""
    p = product(project_root, op_name=op_name, architecture=architecture)
    from uo_init.store.reader import read_meta

    value = read_meta(p)
    return value if isinstance(value, dict) else {}


def view(
    project_root: Path | str,
    name: str,
    *,
    op_name: str = "",
    architecture: str = "",
) -> Any:
    """Load a named product view. Missing/stale products fail closed."""
    p = product(project_root, op_name=op_name, architecture=architecture)
    return _checked_view(p, name)


def identity(
    project_root: Path | str, *, op_name: str = "", architecture: str = ""
) -> dict[str, Any]:
    """Return stable identity fields for the selected CodeMap product."""
    p = product(project_root, op_name=op_name, architecture=architecture)
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
