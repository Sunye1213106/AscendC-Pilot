# -*- coding: utf-8 -*-
"""Read the finalized CodeMap product from TG without touching UO work exports."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _checked_view(path: Path, name: str) -> Any:
    from uo_init.store.reader import load_view_blob_checked

    checked = load_view_blob_checked(path, name)
    if not checked.get("ok"):
        reason = checked.get("reason_code") or "VIEW_UNUSABLE"
        raise RuntimeError(f"{reason}: {name} in {path}")
    return checked.get("view")


def product(project_root: Path | str, *, op_name: str = "", architecture: str = "") -> Path:
    from uo_init.store.reader import find_uo_product

    root = Path(project_root).expanduser().resolve()
    found = find_uo_product(root, op_name=op_name, architecture=architecture)
    if found is None or found.suffix != ".uo" or not found.is_file():
        raise FileNotFoundError(
            f"missing finalized .uo product for op={op_name or '*'} arch={architecture or '*'} under {root}"
        )
    return found


def view(project_root: Path | str, name: str, *, op_name: str = "", architecture: str = "") -> Any:
    p = product(project_root, op_name=op_name, architecture=architecture)
    return _checked_view(p, name)


def meta(project_root: Path | str, *, op_name: str = "", architecture: str = "") -> dict[str, Any]:
    from uo_init.store.reader import read_meta

    return read_meta(product(project_root, op_name=op_name, architecture=architecture))


def identity(project_root: Path | str, *, op_name: str = "", architecture: str = "") -> dict[str, Any]:
    p = product(project_root, op_name=op_name, architecture=architecture)
    m = meta(project_root, op_name=op_name, architecture=architecture)
    graph = view(project_root, "ir/operator_graph.yaml", op_name=op_name, architecture=architecture)
    graph = graph if isinstance(graph, dict) else {}
    return {
        "path": p.as_posix(),
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "schema": str(m.get("schema") or ""),
        "op_name": str(m.get("op_name") or op_name),
        "architecture": str(m.get("architecture") or architecture),
        "revision": str(m.get("revision") or m.get("source_revision") or ""),
        "graph_fingerprint": str(
            graph.get("fingerprint")
            or m.get("cm_graph_fingerprint")
            or m.get("graph_fingerprint")
            or ""
        ),
    }


def legal_key_rows(project_root: Path | str, *, op_name: str = "", architecture: str = "") -> list[dict[str, Any]]:
    raw = view(project_root, "tiling/legal_key_index.jsonl", op_name=op_name, architecture=architecture)
    if isinstance(raw, dict):
        rows = raw.get("rows") or raw.get("keys") or []
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def replay_observe_fields(project_root: Path | str, *, op_name: str = "", architecture: str = "") -> set[str] | None:
    """Known Replay/TilingData leaf names, or None when the UO view is unavailable."""
    names = {"tiling_key", "key", "ok", "reject"}
    try:
        doc = view(project_root, "views/tilingdata.yaml", op_name=op_name, architecture=architecture)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(doc, dict):
        return None
    structs = doc.get("structs") or []
    if not isinstance(structs, list):
        return names
    for struct in structs:
        if not isinstance(struct, dict):
            continue
        for field in struct.get("fields") or []:
            if isinstance(field, dict):
                name = str(field.get("name") or "").strip()
            else:
                name = str(field or "").strip()
            if name:
                names.add(name)
    return names


def declared_keys(project_root: Path | str, *, op_name: str = "", architecture: str = "") -> set[int]:
    out: set[int] = set()
    for row in legal_key_rows(project_root, op_name=op_name, architecture=architecture):
        raw = row.get("tiling_key") if row.get("tiling_key") is not None else row.get("key")
        try:
            out.add(int(str(raw), 0))
        except (TypeError, ValueError):
            continue
    if out:
        return out
    space = view(project_root, "tiling/exhaustive_key_space.yaml", op_name=op_name, architecture=architecture)
    if isinstance(space, dict):
        for raw in space.get("keys") or space.get("declared_keys") or []:
            if isinstance(raw, dict):
                raw = raw.get("tiling_key") if raw.get("tiling_key") is not None else raw.get("key")
            try:
                out.add(int(str(raw), 0))
            except (TypeError, ValueError):
                continue
    return out
