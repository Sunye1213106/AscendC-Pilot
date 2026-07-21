"""Export layered YAML KB into indexes/kb_graph.sqlite (read-only derived graph)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml
from uo.scripts.kb_query_export import _entities_from_graph

SCHEMA_VERSION = "1"
HASH_PATHS = (
    "ir/operator_graph.yaml",
    "contracts/testcase.yaml",
    "query/terminology.yaml",
    "kernel/branches.yaml",
    "tiling/constraints.yaml",
)


def export_kb_graph(repo_root: Path, op_name: str, *, write: bool = True) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    graph_path = uo_root / "ir" / "operator_graph.yaml"
    graph = read_yaml(graph_path)
    if not graph:
        raise FileNotFoundError(f"missing {graph_path}; run /uo-init extract first")

    entities = _collect_entities(uo_root, graph)
    relations = _collect_relations(uo_root, graph, entities)
    aliases = _collect_aliases(uo_root, entities)
    source_hashes = _source_hashes(uo_root)
    db_path = uo_root / "indexes" / "kb_graph.sqlite"

    payload = {
        "op_name": op_name,
        "db_path": str(db_path),
        "entity_count": len(entities),
        "relation_count": len(relations),
        "alias_count": len(aliases),
        "source_hashes": source_hashes,
        "schema_version": SCHEMA_VERSION,
    }
    if not write:
        return payload

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as db:
        _init_schema(db)
        _insert_entities(db, entities)
        _insert_relations(db, relations)
        _insert_aliases(db, aliases)
        meta = {
            "schema_version": SCHEMA_VERSION,
            "built_at": datetime.now(tz=timezone.utc).isoformat(),
            "op_name": op_name,
            "source_hashes": json.dumps(source_hashes, sort_keys=True),
            "entity_count": str(len(entities)),
            "relation_count": str(len(relations)),
            "alias_count": str(len(aliases)),
        }
        db.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", list(meta.items()))
        db.commit()
    payload["status"] = "ok"
    return payload


def _init_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            kind TEXT,
            label TEXT,
            layer TEXT,
            detail_ref TEXT,
            file_path TEXT,
            start_line INTEGER,
            fields_json TEXT
        );
        CREATE TABLE relations (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            type TEXT NOT NULL,
            fields_json TEXT
        );
        CREATE TABLE aliases (
            normalized_alias TEXT NOT NULL,
            alias TEXT NOT NULL,
            entity_id TEXT NOT NULL
        );
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE INDEX idx_entities_kind ON entities(kind);
        CREATE INDEX idx_entities_file ON entities(file_path);
        CREATE INDEX idx_relations_src ON relations(source_id);
        CREATE INDEX idx_relations_tgt ON relations(target_id);
        CREATE INDEX idx_relations_type ON relations(type);
        CREATE INDEX idx_aliases_norm ON aliases(normalized_alias);
        """
    )


def _collect_entities(uo_root: Path, graph: dict[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for ent in _entities_from_graph(graph):
        eid = str(ent.get("id") or "")
        if not eid:
            continue
        file_path = str(ent.get("file_path") or "")
        detail_ref = _detail_ref_for(ent)
        by_id[eid] = {
            "id": eid,
            "kind": str(ent.get("type") or "entity"),
            "label": str(ent.get("name") or eid),
            "layer": str(ent.get("layer") or ""),
            "detail_ref": detail_ref,
            "file_path": file_path,
            "start_line": ent.get("start_line"),
            "fields": {
                "domain": ent.get("domain"),
                "binding_time": ent.get("binding_time"),
                "data_type": ent.get("data_type"),
            },
        }

    # Also keep raw graph nodes that have file anchors (for maps_to_file even if not typed).
    for node in graph.get("nodes") or []:
        nid = str(node.get("id") or "")
        if not nid or nid in by_id:
            continue
        ntype = str(node.get("node_type") or node.get("type") or "node")
        by_id[nid] = {
            "id": nid,
            "kind": ntype,
            "label": str(node.get("name") or nid),
            "layer": str(node.get("layer") or ""),
            "detail_ref": "ir/operator_graph.yaml",
            "file_path": str(node.get("file_path") or ""),
            "start_line": node.get("start_line"),
            "fields": {"from": "operator_graph_node"},
        }

    contract = read_yaml(uo_root / "contracts" / "testcase.yaml")
    for var in (contract.get("variables") or []) if isinstance(contract, dict) else []:
        if not isinstance(var, dict):
            continue
        vid = str(var.get("id") or "")
        if not vid:
            continue
        by_id.setdefault(
            vid,
            {
                "id": vid,
                "kind": str(var.get("type") or "variable"),
                "label": str(var.get("name") or vid),
                "layer": "contract",
                "detail_ref": "contracts/testcase.yaml",
                "file_path": "",
                "start_line": None,
                "fields": {"domain": var.get("domain"), "shape": var.get("shape")},
            },
        )
        if var.get("shape") is not None:
            by_id[vid]["fields"]["shape"] = var.get("shape")

    _add_entrypoint_entities(uo_root, by_id)
    return list(by_id.values())


def _add_entrypoint_entities(uo_root: Path, by_id: dict[str, dict[str, Any]]) -> None:
    """Materialize confirmed entrypoints so entity_of(name) works for host/kernel."""
    entrypoints = read_yaml(uo_root / "ir" / "entrypoints.yaml") or {}
    roles = entrypoints.get("roles") if isinstance(entrypoints.get("roles"), dict) else {}
    if not roles:
        for role in ("host_tiling_entry", "kernel_entry", "get_tiling_key", "save_tiling_data", "init_tiling_data"):
            if isinstance(entrypoints.get(role), dict):
                roles[role] = entrypoints[role]
    for role, body in roles.items():
        if not isinstance(body, dict):
            continue
        selected = body.get("selected") if isinstance(body.get("selected"), dict) else {}
        name = selected.get("name") or body.get("name")
        qn = selected.get("qualified_name") or body.get("qualified_name")
        if not name and not qn:
            continue
        eid = f"ENTRY::{role}"
        fpath = _strip_cbm_stage_path(str(selected.get("file_path") or body.get("file_path") or ""))
        by_id[eid] = {
            "id": eid,
            "kind": "Entrypoint",
            "label": str(name or qn),
            "layer": "entry",
            "detail_ref": "ir/entrypoints.yaml",
            "file_path": fpath,
            "start_line": selected.get("start_line") or body.get("start_line"),
            "fields": {
                "role": role,
                "status": body.get("status"),
                "qualified_name": qn,
                "confirmed_by": selected.get("confirmed_by") or body.get("confirmed_by"),
            },
        }


def _strip_cbm_stage_path(fpath: str) -> str:
    """Map staged CBM mirror paths back to package-relative source paths."""
    norm = fpath.replace("\\", "/")
    marker = "/cbm/index_stage/"
    if marker not in norm:
        return fpath
    rest = norm.split(marker, 1)[-1]
    # rest: <op_name>/op_host/... or op_host/...
    segs = [s for s in rest.split("/") if s]
    for i, seg in enumerate(segs):
        if seg in {"op_host", "op_kernel", "op_api", "op_graph"}:
            return "/".join(segs[i:])
    return rest


def _detail_ref_for(ent: dict[str, Any]) -> str:
    eid = str(ent.get("id") or "")
    ntype = str(ent.get("type") or "")
    if eid.startswith("KEY_") or ntype == "TilingKey":
        card = f"tiling/key_cards/{eid}.yaml"
        return card
    if ntype in {"KernelBranch", "KernelVariable"} or eid.startswith(("KBR_", "KVAR_", "VAR_")):
        return "kernel/branches.yaml" if eid.startswith("KBR_") else "kernel/variables.yaml"
    if ntype in {"TilingDataField"} or eid.startswith("TDF_"):
        return "tiling/data_model.yaml"
    return "ir/operator_graph.yaml"


def _collect_relations(
    uo_root: Path,
    graph: dict[str, Any],
    entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {e["id"]: e for e in entities}
    relations: list[dict[str, Any]] = []
    seen: set[str] = set()

    def ensure_file_entity(fpath: str) -> str:
        norm = fpath.replace("\\", "/")
        file_node = f"FILE::{norm}"
        if file_node not in by_id:
            by_id[file_node] = {
                "id": file_node,
                "kind": "File",
                "label": fpath,
                "layer": "source",
                "detail_ref": "",
                "file_path": fpath,
                "start_line": None,
                "fields": {},
            }
        return file_node

    def ensure_stub_entity(eid: str, *, kind: str, label: str, layer: str = "index") -> None:
        if not eid or eid in by_id:
            return
        by_id[eid] = {
            "id": eid,
            "kind": kind,
            "label": label,
            "layer": layer,
            "detail_ref": "",
            "file_path": "",
            "start_line": None,
            "fields": {"stub": True},
        }

    def add(source: str, target: str, rel_type: str, **fields: Any) -> None:
        if not source or not target:
            return
        # Materialize missing endpoints so sqlite has no orphan edges.
        if source not in by_id:
            if source.startswith("COV_"):
                ensure_stub_entity(source, kind="CoverageObligation", label=source, layer="contract")
            elif source.startswith("SYM::"):
                ensure_stub_entity(source, kind="Symbol", label=source[5:], layer="source")
            elif source.startswith("FILE::"):
                ensure_stub_entity(source, kind="File", label=source[6:], layer="source")
            else:
                ensure_stub_entity(source, kind="Stub", label=source)
        if target not in by_id:
            if target.startswith("COV_"):
                ensure_stub_entity(target, kind="CoverageObligation", label=target, layer="contract")
            elif target.startswith("SYM::"):
                ensure_stub_entity(target, kind="Symbol", label=target[5:], layer="source")
            elif target.startswith("FILE::"):
                ensure_stub_entity(target, kind="File", label=target[6:], layer="source")
            else:
                ensure_stub_entity(target, kind="Stub", label=target)
        rid = f"{rel_type}:{source}->{target}"
        if rid in seen:
            return
        seen.add(rid)
        relations.append(
            {
                "id": rid,
                "source_id": source,
                "target_id": target,
                "type": rel_type,
                "fields": fields,
            }
        )

    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("source_id") or edge.get("source") or "")
        tgt = str(edge.get("target_id") or edge.get("target") or "")
        etype = str(edge.get("edge_type") or edge.get("type") or "graph_edge")
        mapped = _map_edge_type(etype)
        add(src, tgt, mapped, original_type=etype)

    for ent in list(by_id.values()):
        eid = ent["id"]
        fpath = ent.get("file_path") or ""
        if fpath and not str(eid).startswith("FILE::"):
            file_node = ensure_file_entity(str(fpath))
            add(eid, file_node, "maps_to_file")
            sym = ent.get("label") or eid
            add(eid, f"SYM::{sym}", "anchors_to_symbol", symbol=sym)

    contract = read_yaml(uo_root / "contracts" / "testcase.yaml")
    if isinstance(contract, dict):
        for con in contract.get("typed_constraints") or []:
            if not isinstance(con, dict):
                continue
            cid = str(con.get("id") or "")
            var = str(con.get("var") or "")
            if cid and var:
                add(cid, var, "constrains")
        obligations = contract.get("coverage_obligations") or {}
        if isinstance(obligations, dict):
            for _bucket, items in obligations.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    oid = str(item.get("id") or "")
                    for ref in item.get("target_refs") or []:
                        add(oid, str(ref), "covers")

    constraints = read_yaml(uo_root / "tiling" / "constraints.yaml")
    for item in (constraints.get("items") or constraints.get("constraints") or []) if isinstance(constraints, dict) else []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "")
        for ref in item.get("target_refs") or item.get("vars") or []:
            add(cid, str(ref), "constrains")
        key_ref = str(item.get("key_id") or item.get("tiling_key") or "")
        if cid and key_ref:
            add(key_ref, cid, "belongs_to_key")

    branches = read_yaml(uo_root / "kernel" / "branches.yaml")
    for br in (branches.get("branches") or branches.get("items") or []) if isinstance(branches, dict) else []:
        if not isinstance(br, dict):
            continue
        bid = str(br.get("id") or "")
        key_ref = str(br.get("key_id") or br.get("tiling_key") or "")
        if bid and key_ref:
            add(key_ref, bid, "enables_branch")
        for ref in br.get("var_refs") or br.get("depends_on") or []:
            add(str(ref), bid, "enables_branch")

    entities[:] = list(by_id.values())
    return relations


def _map_edge_type(etype: str) -> str:
    low = etype.lower()
    if "constrain" in low:
        return "constrains"
    if "branch" in low or "enable" in low:
        return "enables_branch"
    if "key" in low and "belong" in low:
        return "belongs_to_key"
    if "cover" in low:
        return "covers"
    return "graph_edge"


def _collect_aliases(uo_root: Path, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aliases: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(alias: str, entity_id: str) -> None:
        alias = str(alias or "").strip()
        if not alias or not entity_id:
            return
        norm = _normalize(alias)
        key = (norm, entity_id)
        if key in seen:
            return
        seen.add(key)
        aliases.append({"normalized_alias": norm, "alias": alias, "entity_id": entity_id})

    for ent in entities:
        add(ent["id"], ent["id"])
        add(ent.get("label") or "", ent["id"])

    terms_doc = read_yaml(uo_root / "query" / "terminology.yaml")
    terms = (terms_doc.get("terms") or {}) if isinstance(terms_doc, dict) else {}
    if isinstance(terms, dict):
        for term, entry in terms.items():
            if not isinstance(entry, dict):
                continue
            for eid in entry.get("entity_ids") or []:
                add(str(term), str(eid))
                for a in entry.get("aliases") or []:
                    add(str(a), str(eid))
    return aliases


def _source_hashes(uo_root: Path) -> dict[str, str]:
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


def _insert_entities(db: sqlite3.Connection, entities: list[dict[str, Any]]) -> None:
    # De-dupe by id (file entities may be appended during relation build)
    by_id = {e["id"]: e for e in entities}
    rows = [
        (
            e["id"],
            e.get("kind"),
            e.get("label"),
            e.get("layer"),
            e.get("detail_ref"),
            e.get("file_path"),
            e.get("start_line"),
            json.dumps(e.get("fields") or {}, ensure_ascii=False),
        )
        for e in by_id.values()
    ]
    db.executemany(
        "INSERT OR REPLACE INTO entities(id, kind, label, layer, detail_ref, file_path, start_line, fields_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _insert_relations(db: sqlite3.Connection, relations: list[dict[str, Any]]) -> None:
    rows = [
        (
            r["id"],
            r["source_id"],
            r["target_id"],
            r["type"],
            json.dumps(r.get("fields") or {}, ensure_ascii=False),
        )
        for r in relations
    ]
    db.executemany(
        "INSERT OR REPLACE INTO relations(id, source_id, target_id, type, fields_json) VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def _insert_aliases(db: sqlite3.Connection, aliases: list[dict[str, Any]]) -> None:
    rows = [(a["normalized_alias"], a["alias"], a["entity_id"]) for a in aliases]
    db.executemany(
        "INSERT INTO aliases(normalized_alias, alias, entity_id) VALUES (?, ?, ?)",
        rows,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export YAML KB to indexes/kb_graph.sqlite")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    try:
        result = export_kb_graph(repo_root, op_name, write=not args.dry_run)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"uo-export-kb-graph failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"uo-export-kb-graph op={op_name} entities={result.get('entity_count')} "
        f"relations={result.get('relation_count')} aliases={result.get('alias_count')} "
        f"db={result.get('db_path')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
