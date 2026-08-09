# -*- coding: utf-8 -*-
"""Transitional importer for legacy ``kb_graph.sqlite`` products.

This exists so real previously-extracted compiler facts can be audited against
new ``.uo`` semantics without requiring CANN on the machine doing the audit.
It does not make the legacy DB authoritative again.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind
from uo_init.store.writer import write_codemap

_ENTITY_KIND = {
    "file": EntityKind.FILE,
    "function": EntityKind.FUNCTION,
    "method": EntityKind.METHOD,
    "variable": EntityKind.VARIABLE,
    "var": EntityKind.VARIABLE,
    "variable_state": EntityKind.VARIABLE,
    "predicate_variable": EntityKind.VARIABLE,
    "field": EntityKind.FIELD,
    "type": EntityKind.TYPE,
    "input": EntityKind.INPUT,
    "api_input": EntityKind.INPUT,
    "output": EntityKind.OUTPUT,
    "api_output": EntityKind.OUTPUT,
    "macro": EntityKind.MACRO,
    "compiledefine": EntityKind.COMPILE_VAR,
    "compile_var": EntityKind.COMPILE_VAR,
    "compilevar": EntityKind.COMPILE_VAR,
    "template": EntityKind.TEMPLATE,
    "template_decl": EntityKind.TEMPLATE,
    "templatearg": EntityKind.TEMPLATE_ARG,
    "template_arg": EntityKind.TEMPLATE_ARG,
    "templateinstance": EntityKind.TEMPLATE_INSTANCE,
    "template_instance": EntityKind.TEMPLATE_INSTANCE,
    "instantiation": EntityKind.TEMPLATE_INSTANCE,
    "branch": EntityKind.BRANCH,
    "ctrl": EntityKind.BRANCH,
    "kernelbranch": EntityKind.BRANCH,
    "kernel_branch": EntityKind.BRANCH,
    "if": EntityKind.BRANCH,
    "switch": EntityKind.BRANCH,
    "predicate": EntityKind.PREDICATE,
    "condition": EntityKind.PREDICATE,
    "guard": EntityKind.PREDICATE,
    "tilingkey": EntityKind.TILING_KEY,
    "tiling_key": EntityKind.TILING_KEY,
    "tilingkeydim": EntityKind.TILING_KEY,
    "key_dimension": EntityKind.TILING_KEY,
    "key": EntityKind.TILING_KEY,
    "tilingfield": EntityKind.TILING_FIELD,
    "tiling_field": EntityKind.TILING_FIELD,
    "tilingdatafield": EntityKind.TILING_FIELD,
    "kernel": EntityKind.KERNEL,
    "kernel_entry": EntityKind.KERNEL,
    "arch": EntityKind.ARCH,
    "architecture": EntityKind.ARCH,
    "buildvariant": EntityKind.BUILD_VARIANT,
    "build_variant": EntityKind.BUILD_VARIANT,
}

_REL_KIND = {kind.value.lower(): kind for kind in RelationKind}


def _entity_kind(raw: Any) -> EntityKind:
    text = str(raw or "").strip()
    return _ENTITY_KIND.get(text.lower(), EntityKind.OTHER)


def _relation_kind(raw: Any) -> RelationKind:
    text = str(raw or "").strip().lower()
    aliases = {
        "flows-to": "flows_to",
        "flowsto": "flows_to",
        "guardedby": "guarded_by",
        "activeunder": "active_under",
        "availableon": "available_on",
    }
    text = aliases.get(text, text)
    return _REL_KIND.get(text, RelationKind.OTHER)


def _json(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return dict(text)
    if not text:
        return {}
    try:
        value = json.loads(str(text))
        return value if isinstance(value, dict) else {"value": value}
    except Exception:
        return {"raw": str(text)}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _meta(conn: sqlite3.Connection, tables: set[str]) -> dict[str, str]:
    if "meta" not in tables:
        return {}
    return {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM meta")}


def read_legacy_codemap(
    db_path: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
) -> CodeMap:
    """Read legacy graph tables without adding any new semantic edges."""
    db = Path(db_path).expanduser().resolve()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        tables = _tables(conn)
        if "nodes" not in tables or "edges" not in tables:
            raise ValueError(f"not a legacy UO graph DB: {db}")
        meta = _meta(conn, tables)
        cm = CodeMap(
            op_name=op_name or meta.get("op_name", ""),
            architecture=architecture or meta.get("architecture", ""),
        )
        cm.meta.update({"legacy_import": True, "legacy_meta": meta})

        node_evidence: dict[str, list[dict[str, Any]]] = {}
        edge_evidence: dict[str, list[dict[str, Any]]] = {}
        evidence: dict[str, dict[str, Any]] = {}
        if "evidence" in tables:
            for row in conn.execute("SELECT * FROM evidence"):
                keys = set(row.keys())
                evidence[str(row["id"])] = {
                    "file": str(row["file"] or "") if "file" in keys else "",
                    "line": int(row["line"] or 0) if "line" in keys else 0,
                    "excerpt": str(row["excerpt"] or "") if "excerpt" in keys else "",
                    **(_json(row["payload"]) if "payload" in keys else {}),
                }
        if "node_evidence" in tables:
            for row in conn.execute("SELECT node_id, evidence_id FROM node_evidence"):
                ev = evidence.get(str(row["evidence_id"]))
                if ev:
                    node_evidence.setdefault(str(row["node_id"]), []).append(ev)
        if "edge_evidence" in tables:
            for row in conn.execute("SELECT edge_id, evidence_id FROM edge_evidence"):
                ev = evidence.get(str(row["evidence_id"]))
                if ev:
                    edge_evidence.setdefault(str(row["edge_id"]), []).append(ev)

        for row in conn.execute("SELECT * FROM nodes"):
            keys = set(row.keys())
            node_id = str(row["id"])
            payload = _json(row["payload"]) if "payload" in keys else {}
            evs = node_evidence.get(node_id, [])
            file = str(row["file"] or "") if "file" in keys else ""
            line = int(row["line"] or 0) if "line" in keys else 0
            if not file and evs:
                file = str(evs[0].get("file") or "")
                line = int(evs[0].get("line") or 0)
            if evs:
                payload["evidence"] = evs
            cm.add_entity(
                Entity(
                    id=node_id,
                    kind=_entity_kind(row["kind"] if "kind" in keys else ""),
                    name=str(row["name"] or "") if "name" in keys else node_id,
                    attrs=payload,
                    file=file,
                    line_start=line,
                    line_end=line,
                    status=str(payload.get("status") or "extracted"),
                    confidence=float(payload.get("confidence") or 1.0),
                )
            )

        for row in conn.execute("SELECT * FROM edges"):
            keys = set(row.keys())
            edge_id = str(row["id"])
            src = str(row["src"])
            dst = str(row["dst"])
            if src not in cm.entities or dst not in cm.entities:
                continue
            payload = _json(row["payload"]) if "payload" in keys else {}
            if "expr" in keys and row["expr"]:
                payload.setdefault("expr", str(row["expr"]))
            if "file" in keys and row["file"]:
                payload.setdefault("file", str(row["file"]))
            if "line" in keys and row["line"]:
                payload.setdefault("line", int(row["line"]))
            evs = edge_evidence.get(edge_id, [])
            if evs:
                payload["evidence"] = evs
            payload.setdefault("provenance", "legacy_compiler_facts")
            cm.relations[edge_id] = Relation(
                id=edge_id,
                kind=_relation_kind(row["kind"] if "kind" in keys else ""),
                src=src,
                dst=dst,
                attrs=payload,
                status=str(payload.get("status") or "extracted"),
                confidence=float(payload.get("confidence") or 1.0),
            )
        return cm
    finally:
        conn.close()


def legacy_db_to_uo(
    db_path: str | Path,
    dest: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
) -> dict[str, Any]:
    cm = read_legacy_codemap(db_path, op_name=op_name, architecture=architecture)
    written = write_codemap(
        cm,
        dest,
        meta={"imported_from": str(Path(db_path)), "import_kind": "legacy_kb_graph"},
    )
    written["summary"] = cm.summary()
    return written
