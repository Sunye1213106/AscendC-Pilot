from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import resolve_existing_operator_root, safe_op_name


def query_readonly(repo_root: Path, op_name: str, entity: str, *, depth: int = 1, relation_type: str | None = None, limit: int = 50) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    repo_root = repo_root.resolve()
    resolved = resolve_existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if resolved is None:
        raise FileNotFoundError(f"operator KB root not found via manifest/aliases for {op_name}")
    _resolved_name, uo_root = resolved
    index = uo_root / "indexes" / "operator_kb.sqlite"
    if index.exists():
        if not _index_fresh(index, uo_root):
            return {"resolved_entities": [], "direct_relations": [], "neighbors": [], "fact_details": [], "source_anchors": [], "unresolved": [], "index_status": "stale", "query_backend": "sqlite"}
        return _query_sqlite(index, uo_root, entity, depth=depth, relation_type=relation_type, limit=limit)
    resolved_entities = _resolve_entities(uo_root, entity)
    derived = _query_derived(uo_root, entity, resolved_entities)
    raw_ids = set(derived.get("raw_node_refs") or []) | set(derived.get("raw_edge_refs") or [])
    raw = _query_raw(uo_root, entity, raw_ids | resolved_entities)
    yaml_refs = set(derived.get("yaml_refs") or []) | set(raw.get("yaml_refs") or [])
    yaml_items = [_read_yaml_ref(uo_root, ref) for ref in sorted(yaml_refs)]
    source_refs = _source_refs_from_yaml_items(yaml_items)
    return {
        "query": {
            "entity": entity,
            "normalized": _normalize_term(entity),
            "resolved_entities": sorted(resolved_entities),
            "mode": "readonly",
            "order": ["terminology", "symbol_index", "derived", "raw", "yaml", "source"],
        },
        "resolved_entities": sorted(resolved_entities),
        "derived_entities": sorted({str(item.get("id")) for item in (derived.get("nodes") or []) + (derived.get("edges") or []) if item.get("id")}),
        "raw_entities": sorted({str(item.get("id")) for item in (raw.get("nodes") or []) + (raw.get("edges") or []) if item.get("id")}),
        "derived": derived,
        "raw": raw,
        "yaml_items": yaml_items,
        "source_refs": source_refs,
        "writes": [],
        "cbm_writes": [],
        "index_status": "missing",
        "query_backend": "yaml_fallback",
    }


def _index_fresh(index: Path, root: Path) -> bool:
    def digest(folder: Path) -> str:
        h=hashlib.sha256()
        for p in sorted(folder.rglob("*.yaml")) if folder.exists() else []: h.update(p.read_bytes())
        return "sha256:"+h.hexdigest()
    with sqlite3.connect(index) as db:
        values = dict(db.execute("select key,value from metadata"))
    return values.get("facts_hash") == digest(root / "facts") and values.get("raw_graph_hash") == digest(root / "graphs" / "raw") and values.get("derived_graph_hash") == digest(root / "graphs" / "derived")


def _query_sqlite(index: Path, root: Path, term: str, *, depth: int, relation_type: str | None, limit: int) -> dict[str, Any]:
    norm = _normalize_term(term); limit=max(1,min(limit,200)); depth=max(0,min(depth,2))
    with sqlite3.connect(index) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute("select * from entities where id=? or normalized_label=? or id in (select entity_id from aliases where normalized_alias=?) order by graph_level desc limit ?", (term,norm,norm,limit)).fetchall()
        ids={r["id"] for r in rows}; direct=[]; neighbors=[]
        frontier=set(ids)
        for _ in range(depth):
            if not frontier: break
            marks=','.join('?' for _ in frontier); params=list(frontier)+list(frontier)
            sql=f"select * from relations where (source_id in ({marks}) or target_id in ({marks}))" + (" and type=?" if relation_type else "") + " limit ?"
            if relation_type: params.append(relation_type)
            params.append(limit); rels=db.execute(sql,params).fetchall(); direct.extend(rels)
            next_ids={r["source_id"] for r in rels}|{r["target_id"] for r in rels}; next_ids-=ids; frontier=next_ids; ids|=next_ids
        if ids:
            marks=','.join('?' for _ in ids); neighbors=db.execute(f"select * from entities where id in ({marks}) limit ?", [*ids,limit]).fetchall()
    details = [_read_yaml_ref(root, str(r["detail_ref"])) for r in neighbors if r["detail_ref"]]
    entities = [_row(r) for r in rows]
    neighbor_entities = [_row(r) for r in neighbors[:limit]]
    return {
        "query": {
            "entity": term,
            "normalized": norm,
            "resolved_entities": [str(item.get("id")) for item in entities],
            "mode": "readonly",
            "order": ["terminology", "symbol_index", "derived", "raw", "yaml", "source"],
        },
        "resolved_entities": entities,
        "direct_relations": [_row(r) for r in direct[:limit]],
        "neighbors": neighbor_entities,
        "fact_details": details,
        "yaml_items": details,
        "source_refs": _source_refs_from_yaml_items(details),
        "source_anchors": _source_refs_from_yaml_items(details),
        "derived_entities": [str(item.get("id")) for item in neighbor_entities if item.get("graph_level") == "derived"],
        "raw_entities": [str(item.get("id")) for item in neighbor_entities if item.get("graph_level") == "raw"],
        "unresolved": [],
        "writes": [],
        "cbm_writes": [],
        "index_status": "fresh",
        "query_backend": "sqlite",
    }


def _row(row: sqlite3.Row) -> dict[str, Any]:
    result=dict(row)
    if result.get("fields_json"):
        result["fields"] = json.loads(result.pop("fields_json"))
    return result


def _resolve_entities(uo_root: Path, entity: str) -> set[str]:
    candidates = {entity, _normalize_term(entity)}
    result: set[str] = {entity}
    terminology = _load_mapping(uo_root / "indexes" / "terminology.yaml", "terms")
    for candidate in list(candidates):
        entry = terminology.get(candidate) if isinstance(terminology, dict) else None
        if isinstance(entry, dict):
            result.update(str(item) for item in entry.get("nodes") or [])
            result.update(str(item) for item in entry.get("edges") or [])
    symbol_index = _load_mapping(uo_root / "indexes" / "symbol_index.yaml", "symbol_index")
    for key, entry in symbol_index.items():
        if _normalize_term(str(key)) in candidates and isinstance(entry, dict):
            result.update(str(item) for item in entry.get("nodes") or [])
            result.update(str(item) for item in entry.get("edges") or [])
    graph_to_yaml = _load_mapping(uo_root / "indexes" / "graph_to_yaml.yaml", "graph_to_yaml")
    if entity in graph_to_yaml:
        result.add(entity)
    return {item for item in result if item}


def _query_derived(uo_root: Path, entity: str, resolved_entities: set[str]) -> dict[str, Any]:
    nodes = _load_list(uo_root / "graphs" / "derived" / "nodes.yaml", "nodes")
    edges = _load_list(uo_root / "graphs" / "derived" / "edges.yaml", "edges")
    expansions = _load_list(uo_root / "graphs" / "derived" / "expansions.yaml", "expansions")
    selected_nodes = [
        node
        for node in nodes
        if str(node.get("id")) in resolved_entities or _normalize_term(str(node.get("label") or "")) == _normalize_term(entity)
    ]
    selected_edges = [
        edge
        for edge in edges
        if {str(edge.get("id")), str(edge.get("source_id")), str(edge.get("target_id"))} & resolved_entities
    ]
    selected_ids = {str(item.get("id")) for item in selected_nodes + selected_edges if item.get("id")}
    selected_expansions = [item for item in expansions if str(item.get("derived_id")) in selected_ids or str(item.get("id")) == entity]
    raw_node_refs: list[str] = []
    raw_edge_refs: list[str] = []
    yaml_refs: list[str] = []
    for item in selected_nodes + selected_edges + selected_expansions:
        raw_node_refs.extend(str(ref) for ref in item.get("raw_node_refs") or [])
        raw_edge_refs.extend(str(ref) for ref in item.get("raw_edge_refs") or [])
        yaml_refs.extend(str(ref) for ref in item.get("yaml_refs") or [])
    return {
        "nodes": selected_nodes,
        "edges": selected_edges,
        "expansions": selected_expansions,
        "raw_node_refs": sorted(set(raw_node_refs)),
        "raw_edge_refs": sorted(set(raw_edge_refs)),
        "yaml_refs": sorted(set(yaml_refs)),
    }


def _query_raw(uo_root: Path, entity: str, raw_ids: set[str]) -> dict[str, Any]:
    nodes = _load_list(uo_root / "graphs" / "raw" / "nodes.yaml", "nodes")
    edges = _load_list(uo_root / "graphs" / "raw" / "edges.yaml", "edges")
    selected_nodes = [
        node
        for node in nodes
        if str(node.get("id")) == entity
        or str(node.get("id")) in raw_ids
        or _normalize_term(str(node.get("label") or "")) == _normalize_term(entity)
        or _fields_match(node, entity)
    ]
    selected_node_ids = {str(node.get("id")) for node in selected_nodes if node.get("id")}
    selected_edges = [
        edge
        for edge in edges
        if str(edge.get("id")) == entity
        or str(edge.get("id")) in raw_ids
        or str(edge.get("source_id")) == entity
        or str(edge.get("target_id")) == entity
        or str(edge.get("source_id")) in raw_ids
        or str(edge.get("target_id")) in raw_ids
        or str(edge.get("source_id")) in selected_node_ids
        or str(edge.get("target_id")) in selected_node_ids
    ]
    yaml_refs = [str(item.get("detail_ref")) for item in selected_nodes + selected_edges if item.get("detail_ref")]
    return {"nodes": selected_nodes, "edges": selected_edges, "yaml_refs": sorted(set(yaml_refs))}


def _read_yaml_ref(uo_root: Path, ref: str) -> dict[str, Any]:
    rel, _, pointer = ref.partition("#")
    path = uo_root / rel
    if not path.exists():
        return {"ref": ref, "missing": True}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    value: Any = data
    for part in [part for part in pointer.strip("/").split("/") if part]:
        if isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break
    return {"ref": ref, "value": value}


def _source_refs_from_yaml_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in items:
        value = item.get("value")
        if isinstance(value, dict):
            for source in value.get("sources") or []:
                if isinstance(source, dict):
                    refs.append(source)
    return refs


def _load_list(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    values = data.get(key) if isinstance(data, dict) else []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _load_mapping(path: Path, key: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    values = data.get(key) if isinstance(data, dict) else {}
    return values if isinstance(values, dict) else {}


def _fields_match(node: dict[str, Any], entity: str) -> bool:
    fields = node.get("fields") if isinstance(node.get("fields"), dict) else {}
    target = _normalize_term(entity)
    for key in ("name", "symbol", "path", "file", "field_ref", "struct_ref", "operation_ref", "buffer_ref", "event_identifier"):
        value = fields.get(key)
        if isinstance(value, str) and _normalize_term(value) == target:
            return True
    aliases = fields.get("aliases")
    return isinstance(aliases, list) and any(_normalize_term(str(alias)) == target for alias in aliases)


def _normalize_term(text: str) -> str:
    return "".join(ch for ch in text.lower().strip() if ch.isalnum())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only UO query: Derived Graph -> Raw Graph -> YAML -> source anchors.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--relation-type")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    try:
        payload = query_readonly(Path(args.repo), args.op_name, args.entity, depth=args.depth, relation_type=args.relation_type, limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
