# -*- coding: utf-8 -*-
"""Deterministic Code Engineering graph and key-space primitives."""

from __future__ import annotations

import itertools
import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from code_engineering.evidence_tier import classify_entity, classify_relation
from code_engineering.product_uo import product, view


def _connect(project_root: Path | str, architecture: str) -> sqlite3.Connection | None:
    p = product(project_root, architecture=architecture)
    if not p.is_file():
        return None
    conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    try:
        data = json.loads(record.pop("data", "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        data = {}
    record["attrs"] = data if isinstance(data, dict) else {}
    return record


def _path_matches(left: str, right: str) -> bool:
    left, right = left.replace("\\", "/"), right.replace("\\", "/")
    return left == right or left.endswith("/" + right) or right.endswith("/" + left)


def anchor_resolve(
    diff_spans: dict[str, list[tuple[int, int]]],
    *,
    project_root: Path | str = ".",
    architecture: str = "",
) -> list[dict[str, Any]]:
    """Resolve changed source ranges to intersecting CodeMap entities."""
    conn = _connect(project_root, architecture)
    if conn is None:
        return []
    try:
        # Query by ranges to retain SQLite index-friendly predicates.
        found: dict[str, dict[str, Any]] = {}
        for path, spans in sorted(diff_spans.items()):
            for start, end in spans:
                for row in conn.execute(
                    """SELECT DISTINCT e.*, COALESCE(s.file, e.file, '') AS span_file
                       FROM entity e LEFT JOIN source_span s ON s.entity_id = e.id
                       WHERE COALESCE(s.line_end, e.line_end, e.line_start, 0) >= ?
                         AND COALESCE(s.line_start, e.line_start, 0) <= ?""",
                    (int(start), int(end)),
                ):
                    if _path_matches(str(row["span_file"] or ""), path):
                        item = _decode(row)
                        item.pop("span_file", None)
                        item["evidence_tier"] = classify_entity(item)
                        found[str(item["id"])] = item
        return [found[key] for key in sorted(found)]
    finally:
        conn.close()


def _slice(
    seed_ids: Iterable[str],
    edge_kinds: Iterable[str],
    depth: int,
    *,
    forward: bool,
    project_root: Path | str,
    architecture: str,
    budget: int,
) -> dict[str, Any]:
    conn = _connect(project_root, architecture)
    if conn is None:
        return {"entity_ids": [], "relations": [], "truncated": False}
    kinds = {str(kind) for kind in edge_kinds}
    seen = {str(value) for value in seed_ids}
    queue = deque((value, 0) for value in sorted(seen))
    relations: dict[str, dict[str, Any]] = {}
    truncated = False
    try:
        while queue:
            current, level = queue.popleft()
            if level >= max(0, depth):
                continue
            column = "src" if forward else "dst"
            for row in conn.execute(f"SELECT * FROM relation WHERE {column} = ? ORDER BY id", (current,)):
                if kinds and str(row["kind"]) not in kinds:
                    continue
                item = _decode(row)
                item["evidence_tier"] = classify_relation(item)
                relations[str(item["id"])] = item
                neighbor = str(row["dst" if forward else "src"])
                if neighbor not in seen:
                    if len(seen) >= max(1, budget):
                        truncated = True
                        queue.clear()
                        break
                    seen.add(neighbor)
                    queue.append((neighbor, level + 1))
        return {
            "entity_ids": sorted(seen),
            "relations": [relations[key] for key in sorted(relations)],
            "truncated": truncated,
        }
    finally:
        conn.close()


def slice_forward(
    seed_ids: Iterable[str],
    edge_kinds: Iterable[str],
    depth: int,
    *,
    project_root: Path | str = ".",
    architecture: str = "",
    budget: int = 10_000,
) -> dict[str, Any]:
    """Traverse outgoing relations with deterministic breadth-first search."""
    return _slice(
        seed_ids, edge_kinds, depth, forward=True, project_root=project_root,
        architecture=architecture, budget=budget,
    )


def slice_backward(
    seed_ids: Iterable[str],
    edge_kinds: Iterable[str],
    depth: int,
    *,
    project_root: Path | str = ".",
    architecture: str = "",
    budget: int = 10_000,
) -> dict[str, Any]:
    """Traverse incoming relations with deterministic breadth-first search."""
    return _slice(
        seed_ids, edge_kinds, depth, forward=False, project_root=project_root,
        architecture=architecture, budget=budget,
    )


def key_subset(
    affected_key_dims: dict[str, Iterable[Any]],
    *,
    project_root: Path | str = ".",
    architecture: str = "",
) -> list[int]:
    """Select legal tiling keys matching dimension values, or pack a schema."""
    raw = view(project_root, "tiling/legal_key_index.jsonl", architecture=architecture)
    rows = raw.get("rows", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    wanted = {name: {str(v) for v in values} for name, values in affected_key_dims.items()}
    keys: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dims") if isinstance(row.get("dims"), dict) else row
        if not all(str(dims.get(name)) in values for name, values in wanted.items()):
            continue
        try:
            keys.add(int(str(row.get("tiling_key", row.get("key"))), 0))
        except (TypeError, ValueError):
            pass
    if keys or rows:
        return sorted(keys)

    schema = view(project_root, "tiling/tpl_schema.yaml", architecture=architecture)
    dims = schema.get("dims", []) if isinstance(schema, dict) else []
    if not dims:
        return []
    choices = [list(wanted.get(str(dim.get("name")), {"0"})) for dim in dims]
    for values in itertools.product(*choices):
        key = 0
        try:
            for dim, value in zip(dims, values):
                domain = [str(v) for v in dim.get("value_domain", [])]
                encoded = domain.index(str(value)) if domain else int(str(value), 0)
                key |= encoded << int(dim.get("bit_lo", 0))
            keys.add(key)
        except (ValueError, TypeError):
            continue
    return sorted(keys)


def edge_audit(
    entity_ids: Iterable[str],
    *,
    project_root: Path | str = ".",
    architecture: str = "",
) -> list[dict[str, Any]]:
    """Return unresolved or partial relations incident to selected entities."""
    ids = sorted({str(value) for value in entity_ids})
    conn = _connect(project_root, architecture)
    if conn is None or not ids:
        return []
    marks = ",".join("?" for _ in ids)
    try:
        rows = conn.execute(
            f"""SELECT * FROM relation
                WHERE (src IN ({marks}) OR dst IN ({marks}))
                  AND lower(status) IN ('partial', 'unresolved', 'missing')
                ORDER BY id""",
            ids + ids,
        )
        return [_decode(row) for row in rows]
    finally:
        conn.close()


def test_scope(impact: Any) -> list[dict[str, Any]]:
    """Normalize impact fields and tiling keys for TG handoff."""
    get = impact.get if isinstance(impact, dict) else lambda key, default=None: getattr(impact, key, default)
    keys = get("affected_keys", []) or get("affected_keys_sample", []) or []
    fields = get("key_dims", []) or get("fields", []) or []
    out = [{"kind": "tiling_key", "value": int(key)} for key in sorted({int(k) for k in keys})]
    out.extend({"kind": "field", "value": str(name)} for name in sorted({str(f) for f in fields}))
    return out
