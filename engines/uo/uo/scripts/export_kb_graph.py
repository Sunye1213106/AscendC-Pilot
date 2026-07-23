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
    "ir/entrypoint_graph.yaml",
    "ir/tilingkey_space.yaml",
    "ir/input_derivable.yaml",
    "tiling/key_space.yaml",
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
                "template_flags": ent.get("template_flags"),
                "condition": ent.get("condition"),
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

    # Variables come from tiling/key_space + kernel/variables (TG owns contracts).
    key_space = read_yaml(uo_root / "tiling" / "key_space.yaml")
    for field in (key_space.get("fields") or []) if isinstance(key_space, dict) else []:
        if not isinstance(field, dict):
            continue
        vid = str(field.get("id") or "")
        if not vid:
            continue
        by_id.setdefault(
            vid,
            {
                "id": vid,
                "kind": "key_field",
                "label": str(field.get("name") or vid),
                "layer": "tiling",
                "detail_ref": "tiling/key_space.yaml",
                "file_path": "",
                "start_line": None,
                "fields": {"domain": field.get("values") or field.get("domain"), "role": field.get("role")},
            },
        )

    _add_entrypoint_entities(uo_root, by_id)
    _add_tilingkey_entities(uo_root, by_id)
    return list(by_id.values())


def _add_tilingkey_entities(uo_root: Path, by_id: dict[str, dict[str, Any]]) -> None:
    """Ensure every legal template alias is a KTPL_* entity (full KEY assignment in fields)."""
    from uo.scripts._ir_io import stable_id

    tk = read_yaml(uo_root / "ir" / "tilingkey_space.yaml")
    if not isinstance(tk, dict):
        return
    for node in tk.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("node_type") or "")
        nid = str(node.get("id") or "")
        if ntype == "KernelTemplateArgument" or nid.startswith("KTPL_"):
            eid = nid if nid.startswith("KTPL_") else stable_id("KTPL_", str(node.get("name") or nid))
            fields = {
                "template_flags": node.get("template_flags") or {},
                "condition": node.get("condition"),
            }
            if eid in by_id:
                merged = dict(by_id[eid].get("fields") or {})
                merged.update({k: v for k, v in fields.items() if v is not None})
                by_id[eid]["fields"] = merged
                by_id[eid]["detail_ref"] = "ir/tilingkey_space.yaml"
                if node.get("file_path"):
                    by_id[eid]["file_path"] = str(node.get("file_path") or by_id[eid].get("file_path") or "")
                if node.get("start_line") is not None:
                    by_id[eid]["start_line"] = node.get("start_line")
            else:
                by_id[eid] = {
                    "id": eid,
                    "kind": "KernelTemplateArgument",
                    "label": str(node.get("name") or eid),
                    "layer": str(node.get("layer") or "bridge"),
                    "detail_ref": "ir/tilingkey_space.yaml",
                    "file_path": str(node.get("file_path") or ""),
                    "start_line": node.get("start_line"),
                    "fields": fields,
                }
        elif ntype == "TilingKey" or nid.startswith("KEY_"):
            eid = nid if nid.startswith("KEY_") else stable_id("KEY_", str(node.get("name") or nid))
            by_id.setdefault(
                eid,
                {
                    "id": eid,
                    "kind": "TilingKey",
                    "label": str(node.get("name") or eid),
                    "layer": str(node.get("layer") or "bridge"),
                    "detail_ref": "tiling/key_space.yaml",
                    "file_path": str(node.get("file_path") or ""),
                    "start_line": node.get("start_line"),
                    "fields": {"domain": node.get("domain")},
                },
            )
    for alias in tk.get("template_aliases") or []:
        if not isinstance(alias, dict):
            continue
        eid = stable_id("KTPL_", str(alias.get("name") or ""))
        if not eid or eid == "KTPL_":
            continue
        fields = {
            "template_flags": alias.get("flags") or {},
            "condition": alias.get("condition"),
        }
        if eid in by_id:
            merged = dict(by_id[eid].get("fields") or {})
            merged.update({k: v for k, v in fields.items() if v is not None})
            by_id[eid]["fields"] = merged
            by_id[eid]["detail_ref"] = "ir/tilingkey_space.yaml"
        else:
            by_id[eid] = {
                "id": eid,
                "kind": "KernelTemplateArgument",
                "label": str(alias.get("name") or eid),
                "layer": "bridge",
                "detail_ref": "ir/tilingkey_space.yaml",
                "file_path": str(alias.get("file_path") or ""),
                "start_line": alias.get("line") or alias.get("start_line"),
                "fields": fields,
            }


def _add_entrypoint_entities(uo_root: Path, by_id: dict[str, dict[str, Any]]) -> None:
    """Materialize EP_* identity nodes from entrypoint_graph (not ENTRY::{role})."""
    from uo.scripts.resolve_entrypoints import load_entrypoint_graph

    graph = load_entrypoint_graph(uo_root)
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id") or "")
        if not nid:
            continue
        loc = node.get("locator") if isinstance(node.get("locator"), dict) else {}
        sym = node.get("symbol_ref") if isinstance(node.get("symbol_ref"), dict) else {}
        name = node.get("name") or sym.get("qualified_name")
        if not name and not sym.get("qualified_name"):
            continue
        fpath = _strip_cbm_stage_path(
            str(loc.get("file_path") or sym.get("repo_relative_path") or "")
        )
        by_id[nid] = {
            "id": nid,
            "kind": "Entrypoint",
            "label": str(name or sym.get("qualified_name") or nid),
            "layer": "entry",
            "detail_ref": "ir/entrypoint_graph.yaml",
            "file_path": fpath,
            "start_line": loc.get("start_line"),
            "fields": {
                "role": node.get("role"),
                "status": node.get("status"),
                "qualified_name": sym.get("qualified_name"),
                "identity_key": sym.get("identity_key"),
                "architecture": node.get("architecture"),
                "path_family": node.get("path_family"),
                "class_or_namespace": sym.get("class_or_namespace"),
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


def _symbol_stub_key(ent: dict[str, Any]) -> str:
    """Unique symbol stub key via identity_key (not bare short name)."""
    fields = ent.get("fields") if isinstance(ent.get("fields"), dict) else {}
    ikey = fields.get("identity_key") or ent.get("identity_key")
    if ikey:
        return str(ikey)
    from uo.scripts.semantic_identity import mint_symbol_identity

    ident = mint_symbol_identity(
        kind=str(ent.get("kind") or "symbol"),
        name=str(ent.get("label") or ent.get("id") or "sym"),
        file_path=str(ent.get("file_path") or ""),
        qualified_name=str(fields.get("qualified_name") or ent.get("label") or ""),
        class_or_namespace=str(fields.get("class_or_namespace") or ""),
        architecture=str(fields.get("architecture") or ""),
        path_family=str(fields.get("path_family") or ""),
    )
    return ident.identity_key


def _detail_ref_for(ent: dict[str, Any]) -> str:
    eid = str(ent.get("id") or "")
    ntype = str(ent.get("type") or "")
    if eid.startswith("KTPL_") or ntype == "KernelTemplateArgument":
        return "ir/tilingkey_space.yaml"
    if eid.startswith("KEY_") or ntype == "TilingKey":
        return "tiling/key_space.yaml"
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
        extra: dict[str, Any] = {"original_type": etype}
        if "value" in edge:
            extra["value"] = edge.get("value")
        if edge.get("flag"):
            extra["flag"] = edge.get("flag")
        add(src, tgt, mapped, **extra)

    # Also materialize KTPL→KEY from ir/tilingkey_space when graph edges missing.
    tk = read_yaml(uo_root / "ir" / "tilingkey_space.yaml")
    if isinstance(tk, dict):
        for edge in tk.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("source_id") or edge.get("source") or "")
            tgt = str(edge.get("target_id") or edge.get("target") or "")
            etype = str(edge.get("edge_type") or edge.get("type") or "fixes_flag")
            extra = {}
            if "value" in edge:
                extra["value"] = edge.get("value")
            if edge.get("flag"):
                extra["flag"] = edge.get("flag")
            add(src, tgt, _map_edge_type(etype), **extra)
        for alias in tk.get("template_aliases") or []:
            if not isinstance(alias, dict):
                continue
            from uo.scripts._ir_io import stable_id

            kid = stable_id("KTPL_", str(alias.get("name") or ""))
            if kid in by_id:
                fields = dict(by_id[kid].get("fields") or {})
                fields["template_flags"] = alias.get("flags") or fields.get("template_flags")
                fields["condition"] = alias.get("condition") or fields.get("condition")
                by_id[kid]["fields"] = fields
                by_id[kid]["detail_ref"] = "ir/tilingkey_space.yaml"

    # Overlay compact input-derivable markers (one-hop parent + reaches_input).
    id_doc = read_yaml(uo_root / "ir" / "input_derivable.yaml")
    if isinstance(id_doc, dict):
        for marker in id_doc.get("graph_markers") or []:
            if not isinstance(marker, dict):
                continue
            src = str(marker.get("source") or "")
            tgt = str(marker.get("target") or "")
            mtype = str(marker.get("type") or "determined_by")
            add(
                src,
                tgt,
                _map_edge_type(mtype),
                evidence=marker.get("evidence") or "",
                from_input_derivable=True,
            )
        for key_id, entry in (id_doc.get("keys") or {}).items():
            if not isinstance(entry, dict) or key_id not in by_id:
                continue
            fields = dict(by_id[key_id].get("fields") or {})
            fields["input_derivable"] = entry.get("input_derivable")
            fields["host_parent"] = entry.get("host_parent")
            fields["not_input_derivable"] = entry.get("not_input_derivable")
            fields["needs_binding"] = entry.get("needs_binding")
            if entry.get("derivation_roots"):
                fields["derivation_roots"] = list(entry.get("derivation_roots") or [])[:16]
            by_id[key_id]["fields"] = fields

    for ent in list(by_id.values()):
        eid = ent["id"]
        fpath = ent.get("file_path") or ""
        if fpath and not str(eid).startswith("FILE::"):
            file_node = ensure_file_entity(str(fpath))
            add(eid, file_node, "maps_to_file")
            sym_key = _symbol_stub_key(ent)
            add(eid, f"SYM::{sym_key}", "anchors_to_symbol", symbol=ent.get("label") or eid, identity_key=sym_key)

    # contracts/testcase.yaml is retired — do not build constrains/covers from it.

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
    low = etype.lower().strip()
    # Preserve Host dataflow semantics for input-derivable walks / TG.
    if low in {"writes", "write"}:
        return "writes"
    if low in {"derives", "derive"}:
        return "derives"
    if low in {"determined_by", "reaches_input"}:
        return low
    if low in {"fixes_flag", "fixes", "template_fixes"}:
        return "fixes_flag"
    if low in {"selects", "select"}:
        return "selects"
    if low in {"calls", "call"}:
        return "calls"
    if low in {"dispatches", "dispatch"}:
        return "dispatches"
    if low in {"loads_into", "load"}:
        return "loads_into"
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
