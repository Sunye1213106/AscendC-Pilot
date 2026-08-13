# -*- coding: utf-8 -*-
"""Deterministic Code Engineering graph and key-space primitives."""

from __future__ import annotations

import itertools
import json
import re
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Iterable

import yaml

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
    from uo_init.query.evidence import project_record

    hit = project_record(record)
    hit["evidence_tier"] = classify_entity(record)
    if record.get("located_via"):
        hit["located_via"] = record["located_via"]
    return hit


def _path_matches(left: str, right: str) -> bool:
    left, right = left.replace("\\", "/"), right.replace("\\", "/")
    return left == right or left.endswith("/" + right) or right.endswith("/" + left)


def _scope_root(project_root: Path | str, architecture: str) -> Path:
    pilot = Path(project_root).expanduser().resolve() / ".ascendc-pilot"
    return pilot / architecture if architecture else pilot


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


_INTENT_ANCHOR_KEYS = {
    "anchor", "anchors", "candidate_anchor", "candidate_anchors",
    "target", "targets", "symbol", "symbols", "entity_id", "entity_ids",
}


def _flatten_anchor_values(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
    elif isinstance(value, dict):
        for key in ("id", "entity_id", "name", "symbol", "target"):
            if value.get(key):
                out.extend(_flatten_anchor_values(value[key]))
    elif isinstance(value, list):
        for item in value:
            out.extend(_flatten_anchor_values(item))
    return out


def _intent_tokens(doc: Any) -> list[str]:
    found: list[str] = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            if str(key).lower() in _INTENT_ANCHOR_KEYS:
                found.extend(_flatten_anchor_values(value))
            if isinstance(value, (dict, list)):
                found.extend(_intent_tokens(value))
    elif isinstance(doc, list):
        for item in doc:
            found.extend(_intent_tokens(item))
    return sorted({value for value in found if value})


def _intent_source_tokens(scope: Path) -> list[str]:
    """Tokens from reviewed decomposition, then staging, then raw intent."""
    reviewed = _load_yaml(scope / "ce" / "intent" / "feature_decomposition.yaml")
    tokens = sorted(_intent_tokens(reviewed))
    if not tokens:
        staging_docs: list[Any] = []
        for path in sorted(scope.glob("runs/*/actions/feature_decompose/staging.yaml")):
            staging_docs.append(_load_yaml(path))
        for path in sorted(scope.glob("runs/*/actions/feature_decompose/parts/*.yaml")):
            staging_docs.append(_load_yaml(path))
        tokens = sorted({token for doc in staging_docs for token in _intent_tokens(doc)})
    if not tokens:
        tokens = sorted(_intent_tokens(_load_yaml(scope / "ce" / "intent" / "intent.yaml")))
    return tokens


def _intent_anchor_resolve(
    conn: sqlite3.Connection,
    project_root: Path | str,
    architecture: str,
) -> list[dict[str, Any]]:
    """Resolve reviewed intent targets, then walk backward to candidate edit points.

    A leftover impact ``change_capture.yaml`` must not suppress intent location.
    Prefer canonical reviewed decomposition, then staging parts, then raw intent.
    """
    scope = _scope_root(project_root, architecture)
    tokens = _intent_source_tokens(scope)
    if not tokens:
        return []

    seeds: dict[str, dict[str, Any]] = {}
    for token in tokens:
        rows = conn.execute(
            "SELECT * FROM entity WHERE id = ? OR name = ? OR lower(name) = lower(?) "
            "ORDER BY id LIMIT 32",
            (token, token, token),
        ).fetchall()
        heuristic = False
        if not rows and re.fullmatch(r"[A-Za-z_]\w*(?:::\w+)*", token):
            rows = conn.execute(
                "SELECT * FROM entity WHERE lower(name) LIKE ? ORDER BY id LIMIT 8",
                (f"%{token.lower()}%",),
            ).fetchall()
            heuristic = True
        for row in rows:
            item = _decode(row)
            item["evidence_tier"] = "C" if heuristic else classify_entity(item)
            item["located_via"] = "intent_name_hint" if heuristic else "intent_seed"
            seeds[str(item["id"])] = item

    if not seeds:
        return []

    allowed_edges = {
        "WRITES", "READS", "CONTROLS", "BINDS", "SELECTS", "LAUNCHES",
        "CALLS", "DERIVES", "FLOWS_TO",
    }
    seen = set(seeds)
    queue = deque((eid, 0) for eid in sorted(seen))
    while queue and len(seen) < 128:
        current, depth = queue.popleft()
        if depth >= 2:
            continue
        for row in conn.execute(
            "SELECT * FROM relation WHERE dst = ? ORDER BY id", (current,)
        ):
            if str(row["kind"]).upper() not in allowed_edges:
                continue
            src = str(row["src"])
            if src not in seen:
                seen.add(src)
                queue.append((src, depth + 1))
                if len(seen) >= 128:
                    break

    if len(seen) > len(seeds):
        marks = ",".join("?" for _ in seen)
        for row in conn.execute(
            f"SELECT * FROM entity WHERE id IN ({marks}) ORDER BY id", sorted(seen)
        ):
            eid = str(row["id"])
            if eid in seeds:
                continue
            item = _decode(row)
            item["evidence_tier"] = classify_entity(item)
            item["located_via"] = "intent_backward_slice"
            seeds[eid] = item
    return [seeds[key] for key in sorted(seeds)]


def anchor_resolve(
    diff_spans: dict[str, list[tuple[int, int]]],
    *,
    project_root: Path | str = ".",
    architecture: str = "",
) -> list[dict[str, Any]]:
    """Resolve source ranges, or reviewed intent targets before a diff exists."""
    conn = _connect(project_root, architecture)
    if conn is None:
        return []
    try:
        if not diff_spans:
            return _intent_anchor_resolve(conn, project_root, architecture)

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
        return {"entity_ids": [], "nodes": [], "relations": [], "truncated": False}
    kinds = {str(kind) for kind in edge_kinds}
    if not kinds:
        from uo_init.query.evidence import USEFUL_EDGE_KINDS

        kinds = set(USEFUL_EDGE_KINDS)
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
                rel = {
                    "id": str(row["id"]),
                    "kind": str(row["kind"]),
                    "src": str(row["src"]),
                    "dst": str(row["dst"]),
                    "status": str(row["status"] or ""),
                }
                try:
                    data = json.loads(row["data"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    data = {}
                rel["attrs"] = data if isinstance(data, dict) else {}
                rel["evidence_tier"] = classify_relation(rel)
                from uo_init.query.evidence import project_relation

                relations[rel["id"]] = {
                    **project_relation(rel),
                    "evidence_tier": rel.get("evidence_tier") or "",
                }
                neighbor = str(row["dst" if forward else "src"])
                if neighbor not in seen:
                    if len(seen) >= max(1, budget):
                        truncated = True
                        queue.clear()
                        break
                    seen.add(neighbor)
                    queue.append((neighbor, level + 1))
        nodes: list[dict[str, Any]] = []
        if seen:
            marks = ",".join("?" for _ in seen)
            for row in conn.execute(
                f"SELECT * FROM entity WHERE id IN ({marks}) ORDER BY id", sorted(seen)
            ):
                nodes.append(_decode(row))
        return {
            "entity_ids": sorted(seen),
            "nodes": nodes,
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
        from uo_init.query.evidence import project_relation

        out: list[dict[str, Any]] = []
        for row in rows:
            rel = {
                "id": str(row["id"]),
                "kind": str(row["kind"]),
                "src": str(row["src"]),
                "dst": str(row["dst"]),
                "status": str(row["status"] or ""),
            }
            rel["evidence_tier"] = classify_relation(rel)
            out.append({**project_relation(rel), "evidence_tier": rel["evidence_tier"]})
        return out
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
