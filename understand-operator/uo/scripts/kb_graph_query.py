"""Read-only query API over indexes/kb_graph.sqlite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo.scripts.export_kb_graph import HASH_PATHS

PATTERNS = (
    "entity_of",
    "neighbors_of",
    "constraints_for",
    "branches_for_key",
    "entities_in_files",
    "affected_shapes",
)


def kb_graph_path(uo_root: Path) -> Path:
    return uo_root / "indexes" / "kb_graph.sqlite"


def index_status(uo_root: Path) -> dict[str, Any]:
    path = kb_graph_path(uo_root)
    if not path.exists():
        return {"index_status": "missing", "db_path": str(path)}
    meta = _read_metadata(path)
    expected = _current_hashes(uo_root)
    stored_raw = meta.get("source_hashes") or "{}"
    try:
        stored = json.loads(stored_raw) if isinstance(stored_raw, str) else stored_raw
    except json.JSONDecodeError:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    stale_keys = [k for k, v in expected.items() if stored.get(k) != v]
    status = "fresh" if not stale_keys else "stale"
    return {
        "index_status": status,
        "db_path": str(path),
        "schema_version": meta.get("schema_version"),
        "built_at": meta.get("built_at"),
        "stale_keys": stale_keys,
        "entity_count": meta.get("entity_count"),
        "relation_count": meta.get("relation_count"),
    }


def query_kb_graph(
    uo_root: Path,
    *,
    pattern: str,
    target: str | None = None,
    depth: int = 1,
    limit: int = 50,
    relation_type: str | None = None,
) -> dict[str, Any]:
    pattern = (pattern or "").strip()
    if pattern not in PATTERNS:
        raise ValueError(f"unsupported pattern {pattern!r}; expected one of {PATTERNS}")
    status = index_status(uo_root)
    base = {
        "pattern": pattern,
        "target": target,
        "depth": depth,
        "limit": limit,
        "query_backend": "kb_graph",
        **status,
    }
    if status["index_status"] == "missing":
        return {**base, "resolved_entities": [], "direct_relations": [], "neighbors": [], "error": "kb_graph missing; run export_kb_graph"}
    if status["index_status"] == "stale":
        return {**base, "resolved_entities": [], "direct_relations": [], "neighbors": [], "error": "kb_graph stale; re-run export_kb_graph"}

    limit = max(1, min(int(limit), 200))
    depth = max(0, min(int(depth), 3))
    path = kb_graph_path(uo_root)

    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        if pattern == "entity_of":
            entities = _resolve_entities(db, target or "", limit=limit)
            return {**base, "resolved_entities": [_row(r) for r in entities], "direct_relations": [], "neighbors": []}
        if pattern == "entities_in_files":
            files = [p.strip().replace("\\", "/") for p in (target or "").split(",") if p.strip()]
            entities = _entities_in_files(db, files, limit=limit)
            return {**base, "resolved_entities": [_row(r) for r in entities], "files": files, "direct_relations": [], "neighbors": []}
        if pattern == "neighbors_of":
            seeds = _resolve_entities(db, target or "", limit=limit)
            ids = {r["id"] for r in seeds}
            rels, neighbors = _expand(db, ids, depth=depth, limit=limit, relation_type=relation_type)
            return {
                **base,
                "resolved_entities": [_row(r) for r in seeds],
                "direct_relations": [_row(r) for r in rels],
                "neighbors": [_row(r) for r in neighbors],
            }
        if pattern == "constraints_for":
            seeds = _resolve_entities(db, target or "", limit=limit)
            ids = {r["id"] for r in seeds}
            rels, neighbors = _expand(db, ids, depth=max(depth, 1), limit=limit, relation_type="constrains")
            return {
                **base,
                "resolved_entities": [_row(r) for r in seeds],
                "direct_relations": [_row(r) for r in rels],
                "neighbors": [_row(r) for r in neighbors],
            }
        if pattern == "branches_for_key":
            seeds = _resolve_entities(db, target or "", limit=limit)
            ids = {r["id"] for r in seeds}
            rels, neighbors = _expand(db, ids, depth=max(depth, 1), limit=limit, relation_type="enables_branch")
            return {
                **base,
                "resolved_entities": [_row(r) for r in seeds],
                "direct_relations": [_row(r) for r in rels],
                "neighbors": [_row(r) for r in neighbors],
            }
        if pattern == "affected_shapes":
            return _affected_shapes(db, target or "", depth=depth, limit=limit, base=base)
    return base


def _affected_shapes(
    db: sqlite3.Connection,
    target: str,
    *,
    depth: int,
    limit: int,
    base: dict[str, Any],
) -> dict[str, Any]:
    files = [p.strip().replace("\\", "/") for p in target.split(",") if p.strip() and ("/" in p or "\\" in p or p.endswith((".cpp", ".h", ".py", ".cc")))]
    if files:
        seeds = _entities_in_files(db, files, limit=limit)
    else:
        seeds = _resolve_entities(db, target, limit=limit)
    ids = {r["id"] for r in seeds}
    rels, neighbors = _expand(db, ids, depth=max(depth, 2), limit=limit, relation_type=None)
    shape_like: list[dict[str, Any]] = []
    for row in [*seeds, *neighbors]:
        item = _row(row)
        kind = str(item.get("kind") or "")
        fields = item.get("fields") or {}
        label = str(item.get("label") or "")
        eid = str(item.get("id") or "")
        if (
            fields.get("shape") is not None
            or "shape" in label.lower()
            or kind in {"TilingDataField", "KernelVariable", "variable"}
            or eid.startswith(("VAR_", "KVAR_", "TDF_"))
        ):
            shape_like.append(item)
    # de-dupe
    seen: set[str] = set()
    shapes = []
    for item in shape_like:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        shapes.append(item)
    return {
        **base,
        "resolved_entities": [_row(r) for r in seeds],
        "direct_relations": [_row(r) for r in rels],
        "neighbors": [_row(r) for r in neighbors],
        "affected_shapes": shapes[:limit],
    }


def _resolve_entities(db: sqlite3.Connection, term: str, *, limit: int) -> list[sqlite3.Row]:
    term = str(term or "").strip()
    if not term:
        return []
    norm = _normalize(term)
    rows = db.execute(
        """
        SELECT * FROM entities
        WHERE id = ?
           OR id IN (SELECT entity_id FROM aliases WHERE normalized_alias = ?)
           OR lower(label) = lower(?)
        ORDER BY kind
        LIMIT ?
        """,
        (term, norm, term, limit),
    ).fetchall()
    if rows:
        return rows
    return db.execute(
        """
        SELECT * FROM entities
        WHERE id LIKE ? OR lower(label) LIKE ?
        LIMIT ?
        """,
        (f"%{term}%", f"%{term.lower()}%", limit),
    ).fetchall()


def _entities_in_files(db: sqlite3.Connection, files: list[str], *, limit: int) -> list[sqlite3.Row]:
    if not files:
        return []
    out: list[sqlite3.Row] = []
    seen: set[str] = set()
    for fpath in files:
        norm = fpath.replace("\\", "/")
        base = Path(norm).name
        rows = db.execute(
            """
            SELECT * FROM entities
            WHERE replace(file_path, '\\', '/') = ?
               OR replace(file_path, '\\', '/') LIKE ?
               OR replace(file_path, '\\', '/') LIKE ?
            LIMIT ?
            """,
            (norm, f"%/{base}", f"%{norm}", limit),
        ).fetchall()
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            out.append(row)
            if len(out) >= limit:
                return out
    return out


def _expand(
    db: sqlite3.Connection,
    seed_ids: set[str],
    *,
    depth: int,
    limit: int,
    relation_type: str | None,
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if not seed_ids:
        return [], []
    all_ids = set(seed_ids)
    frontier = set(seed_ids)
    rels: list[sqlite3.Row] = []
    for _ in range(depth):
        if not frontier:
            break
        marks = ",".join("?" for _ in frontier)
        params: list[Any] = list(frontier) + list(frontier)
        sql = f"SELECT * FROM relations WHERE (source_id IN ({marks}) OR target_id IN ({marks}))"
        if relation_type:
            sql += " AND type = ?"
            params.append(relation_type)
        sql += " LIMIT ?"
        params.append(limit)
        batch = db.execute(sql, params).fetchall()
        rels.extend(batch)
        nxt: set[str] = set()
        for r in batch:
            nxt.add(r["source_id"])
            nxt.add(r["target_id"])
        nxt -= all_ids
        all_ids |= nxt
        frontier = nxt
    neighbor_ids = all_ids - seed_ids
    neighbors: list[sqlite3.Row] = []
    if neighbor_ids:
        marks = ",".join("?" for _ in neighbor_ids)
        neighbors = db.execute(
            f"SELECT * FROM entities WHERE id IN ({marks}) LIMIT ?",
            [*neighbor_ids, limit],
        ).fetchall()
    return rels[:limit], neighbors[:limit]


def _read_metadata(db_path: Path) -> dict[str, str]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT key, value FROM metadata").fetchall()
    return {str(k): str(v) for k, v in rows}


def _current_hashes(uo_root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in HASH_PATHS:
        path = uo_root / rel
        if path.exists():
            out[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            out[rel] = "missing"
    return out


def _normalize(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, dict):
        result = dict(row)
    else:
        result = dict(row)
    raw = result.pop("fields_json", None)
    if raw:
        try:
            result["fields"] = json.loads(raw)
        except json.JSONDecodeError:
            result["fields"] = {}
    elif "fields" not in result:
        result["fields"] = {}
    return result
