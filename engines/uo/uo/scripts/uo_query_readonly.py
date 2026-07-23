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

from uo._operator.artifacts import resolve_existing_operator_root, safe_op_name
from uo.scripts.kb_graph_query import index_status as kb_graph_index_status
from uo.scripts.kb_graph_query import query_kb_graph


EXPECTED_QUERY_ORDER = ["terminology", "symbol_index", "derived", "raw", "yaml", "source"]
IR_QUERY_ORDER = ["operator_graph", "contracts", "tiling_kernel_cross", "unresolved", "source"]
ROUTES_QUERY_ORDER = ["terminology", "routes", "hot_files", "key_cards", "source"]
KB_GRAPH_QUERY_ORDER = ["kb_graph", "detail_ref", "source"]


def _query_routes(
    uo_root: Path,
    entity: str,
    *,
    question_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any] | None:
    if yaml is None:
        return None
    routes_path = uo_root / "query" / "routes.yaml"
    terms_path = uo_root / "query" / "terminology.yaml"
    if not routes_path.exists() and not (uo_root / "tiling" / "key_cards").exists():
        return None

    routes_doc = yaml.safe_load(routes_path.read_text(encoding="utf-8")) if routes_path.exists() else {}
    terms_doc = yaml.safe_load(terms_path.read_text(encoding="utf-8")) if terms_path.exists() else {}
    terms = (terms_doc or {}).get("terms") if isinstance(terms_doc, dict) else {}
    if not isinstance(terms, dict):
        terms = {}

    needle = _normalize_term(entity)
    resolved_ids: list[str] = []
    aliases_hit: list[str] = []
    for term, entry in terms.items():
        if not isinstance(entry, dict):
            continue
        candidates = [term, *(entry.get("aliases") or []), *(entry.get("entity_ids") or [])]
        if any(_normalize_term(str(c)) == needle for c in candidates if c):
            aliases_hit.append(str(term))
            for eid in entry.get("entity_ids") or []:
                if eid and str(eid) not in resolved_ids:
                    resolved_ids.append(str(eid))

    explicit_qtype = bool((question_type or "").strip())
    qtype = (question_type or "").strip()
    if not qtype:
        if needle.startswith("key") or any(str(i).startswith("KEY_") for i in resolved_ids):
            qtype = "tiling_key_hit"
        elif "sparse" in needle or "runtime" in needle:
            qtype = "runtime_branch"
        elif "combin" in needle or "sel" in needle:
            qtype = "tiling_combinations"
        else:
            qtype = "tiling_key_what"

    route = ((routes_doc or {}).get("routes") or {}).get(qtype) if isinstance(routes_doc, dict) else None
    if not isinstance(route, dict):
        route = {"files": []}

    routed_files = [str(p) for p in (route.get("files") or []) if p]
    yaml_items: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    source_anchors: list[dict[str, Any]] = []

    card_dir = uo_root / "tiling" / "key_cards"
    card_candidates: list[Path] = []
    for eid in resolved_ids:
        if str(eid).startswith("KEY_"):
            p = card_dir / f"{eid}.yaml"
            if p.exists():
                card_candidates.append(p)
    if not card_candidates and needle:
        # fuzzy: KEY_<Entity> or filename contains entity
        for p in sorted(card_dir.glob("KEY_*.yaml")) if card_dir.exists() else []:
            if needle in _normalize_term(p.stem):
                card_candidates.append(p)
            if len(card_candidates) >= limit:
                break

    for path in card_candidates[:limit]:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        cards.append(data)
        rel = path.relative_to(uo_root).as_posix()
        yaml_items.append({"path": rel, "data": data})
        set_by = data.get("set_by") if isinstance(data.get("set_by"), dict) else {}
        if set_by.get("file_path"):
            source_anchors.append(
                {
                    "file_path": set_by.get("file_path"),
                    "start_line": set_by.get("start_line"),
                    "end_line": set_by.get("start_line"),
                    "qualified_name": data.get("key"),
                }
            )
        if data.get("id") and str(data["id"]) not in resolved_ids:
            resolved_ids.append(str(data["id"]))

    # Only load route hot-files when entity resolved/card hit, or caller set --question-type.
    entity_hit = bool(cards or resolved_ids or aliases_hit)
    if not entity_hit and not explicit_qtype:
        return None

    for rel in routed_files:
        path = uo_root / rel
        if not path.exists() or not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        yaml_items.append({"path": rel, "data": data})

    if not yaml_items and not cards:
        return None

    return {
        "query": {
            "entity": entity,
            "normalized": needle,
            "resolved_entities": resolved_ids,
            "mode": "readonly",
            "order": ROUTES_QUERY_ORDER,
            "question_type": qtype,
        },
        "query_trace": ROUTES_QUERY_ORDER,
        "resolved_entities": resolved_ids,
        "derived_entities": resolved_ids,
        "raw_entities": [],
        "aliases_hit": aliases_hit,
        "routed_files": routed_files,
        "key_cards": cards[:limit],
        "nodes": cards[:limit],
        "direct_relations": [],
        "neighbors": [],
        "yaml_items": yaml_items[:limit],
        "source_anchors": source_anchors,
        "source_refs": source_anchors,
        "writes": [],
        "cbm_writes": [],
        "index_status": "routes",
        "query_backend": "routes",
    }


def _query_layered_ir(uo_root: Path, entity: str, *, depth: int = 1, relation_type: str | None = None, limit: int = 50) -> dict[str, Any] | None:
    graph_path = uo_root / "ir" / "operator_graph.yaml"
    if not graph_path.exists() or yaml is None:
        return None
    graph = yaml.safe_load(graph_path.read_text(encoding="utf-8")) or {}
    if not isinstance(graph, dict) or not graph.get("nodes"):
        return None
    needle = _normalize_term(entity)
    matched = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        hay = " ".join(
            str(node.get(key) or "")
            for key in ("id", "name", "qualified_name", "node_type", "condition", "determinant_ref")
        )
        if needle and needle in _normalize_term(hay):
            matched.append(node)
        if len(matched) >= limit:
            break
    if not matched and needle:
        # fall through to legacy backends when IR has no hit
        return None
    if not matched:
        matched = list(graph.get("nodes") or [])[: min(limit, 5)]
    node_ids = {str(n.get("id")) for n in matched if n.get("id")}
    relations = []
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        if relation_type and str(edge.get("type") or "") != relation_type:
            continue
        if str(edge.get("source")) in node_ids or str(edge.get("target")) in node_ids:
            relations.append(edge)
        if len(relations) >= limit:
            break
    contract = {}
    contract_path = uo_root / "contracts" / "testcase.yaml"
    if contract_path.exists():
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    unresolved = graph.get("unresolved") or []
    source_anchors = [
        {
            "file_path": n.get("file_path"),
            "start_line": n.get("start_line"),
            "end_line": n.get("end_line"),
            "qualified_name": n.get("qualified_name"),
        }
        for n in matched
        if n.get("file_path")
    ]
    return {
        "query": {
            "entity": entity,
            "normalized": needle,
            "resolved_entities": sorted(node_ids),
            "mode": "readonly",
            "order": IR_QUERY_ORDER,
        },
        "query_trace": IR_QUERY_ORDER,
        "resolved_entities": sorted(node_ids),
        "derived_entities": sorted(node_ids),
        "raw_entities": [],
        "nodes": matched[:limit],
        "direct_relations": relations[:limit],
        "neighbors": relations[:limit],
        "contract": contract if depth > 0 else {},
        "unresolved": unresolved[:limit],
        "source_anchors": source_anchors,
        "source_refs": source_anchors,
        "yaml_items": [{"path": "ir/operator_graph.yaml", "entities": sorted(node_ids)}],
        "writes": [],
        "cbm_writes": [],
        "index_status": "ir",
        "query_backend": "layered_ir",
    }


def query_readonly(
    repo_root: Path,
    op_name: str,
    entity: str,
    *,
    depth: int = 1,
    relation_type: str | None = None,
    limit: int = 50,
    question_type: str | None = None,
) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    repo_root = repo_root.resolve()
    resolved = resolve_existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if resolved is None:
        raise FileNotFoundError(f"operator KB root not found via manifest/aliases for {op_name}")
    _resolved_name, uo_root = resolved
    # Prefer derived kb_graph when fresh (fast entity/neighbor lookup).
    graph_hit = _query_kb_graph(uo_root, entity, depth=depth, relation_type=relation_type, limit=limit)
    if graph_hit is not None:
        return graph_hit
    # Prefer query routes / key cards when present (avoid full operator_graph scan).
    routes_hit = _query_routes(uo_root, entity, question_type=question_type, limit=limit)
    if routes_hit is not None:
        return routes_hit
    # Prefer layered IR / contract exports (slim path).
    ir_hit = _query_layered_ir(uo_root, entity, depth=depth, relation_type=relation_type, limit=limit)
    if ir_hit is not None:
        return ir_hit
    # Legacy indexes/operator_kb.sqlite is obsolete; do not prefer it over yaml fallback.
    trace: list[str] = []
    resolved_entities = _resolve_entities(uo_root, entity, trace)
    derived = _query_derived(uo_root, entity, resolved_entities)
    trace.append("derived")
    raw_ids = set(derived.get("raw_node_refs") or []) | set(derived.get("raw_edge_refs") or [])
    raw = _query_raw(uo_root, entity, raw_ids | resolved_entities)
    trace.append("raw")
    yaml_refs = set(derived.get("yaml_refs") or []) | set(raw.get("yaml_refs") or [])
    yaml_items = [_read_yaml_ref(uo_root, ref) for ref in sorted(yaml_refs)]
    trace.append("yaml")
    source_refs = _source_refs_from_yaml_items(yaml_items)
    trace.append("source")
    return {
        "query": {
            "entity": entity,
            "normalized": _normalize_term(entity),
            "resolved_entities": sorted(resolved_entities),
            "mode": "readonly",
            "order": EXPECTED_QUERY_ORDER,
        },
        "query_trace": trace,
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
        "hint": "indexes/kb_graph.sqlite missing or stale; run export_kb_graph.py after /uo-init or /uo-update",
    }


def _query_kb_graph(
    uo_root: Path,
    entity: str,
    *,
    depth: int,
    relation_type: str | None,
    limit: int,
) -> dict[str, Any] | None:
    status = kb_graph_index_status(uo_root)
    if status.get("index_status") != "fresh":
        return None
    try:
        result = query_kb_graph(
            uo_root,
            pattern="neighbors_of",
            target=entity,
            depth=max(depth, 1),
            limit=limit,
            relation_type=relation_type,
        )
    except Exception:  # noqa: BLE001
        return None
    if result.get("index_status") != "fresh":
        return None
    if not result.get("resolved_entities") and not result.get("neighbors"):
        # Fall through to routes / YAML for better recall on fuzzy questions.
        return None

    detail_refs: list[str] = []
    for item in (result.get("resolved_entities") or []) + (result.get("neighbors") or []):
        ref = item.get("detail_ref") if isinstance(item, dict) else None
        if ref and ref not in detail_refs:
            detail_refs.append(str(ref))
    yaml_items = [_read_yaml_ref(uo_root, ref) for ref in detail_refs[:12]]
    source_refs = _source_refs_from_yaml_items(yaml_items)
    for item in result.get("resolved_entities") or []:
        if not isinstance(item, dict):
            continue
        if item.get("file_path"):
            source_refs.append(
                {
                    "file_path": item.get("file_path"),
                    "start_line": item.get("start_line"),
                    "entity_id": item.get("id"),
                }
            )

    return {
        "query": {
            "entity": entity,
            "normalized": _normalize_term(entity),
            "resolved_entities": [e.get("id") for e in (result.get("resolved_entities") or []) if isinstance(e, dict)],
            "mode": "readonly",
            "order": KB_GRAPH_QUERY_ORDER,
        },
        "query_trace": list(KB_GRAPH_QUERY_ORDER),
        "resolved_entities": result.get("resolved_entities") or [],
        "direct_relations": result.get("direct_relations") or [],
        "neighbors": result.get("neighbors") or [],
        "yaml_items": yaml_items,
        "source_refs": source_refs,
        "source_anchors": source_refs,
        "writes": [],
        "cbm_writes": [],
        "index_status": "fresh",
        "query_backend": "kb_graph",
        "kb_graph_status": status,
    }


def query_smoke(repo_root: Path, op_name: str) -> tuple[int, dict[str, Any]]:
    if yaml is None:
        return 2, {"status": "fail", "errors": ["PyYAML is required"]}
    repo_root = repo_root.resolve()
    resolved = resolve_existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if resolved is None:
        return 2, {"status": "fail", "errors": [f"operator KB root not found via manifest/aliases for {op_name}"]}
    resolved_name, uo_root = resolved
    before = _readonly_fingerprint(uo_root)
    cases = _select_smoke_cases(uo_root)
    if not all(cases.values()):
        return 2, {"status": "fail", "op_name": resolved_name, "cases": cases, "errors": ["missing stable_id, symbol, or terminology smoke case"]}
    errors: list[str] = []
    results: dict[str, Any] = {}
    for name, entity in cases.items():
        try:
            result = query_readonly(repo_root, resolved_name, str(entity))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            continue
        results[name] = result
        if result.get("writes") or result.get("cbm_writes"):
            errors.append(f"{name}: query reported write operations")
        backend = result.get("query_backend")
        if backend == "kb_graph":
            if result.get("query_trace") != KB_GRAPH_QUERY_ORDER:
                errors.append(f"{name}: kb_graph query trace mismatch")
            if not result.get("resolved_entities"):
                errors.append(f"{name}: resolved_entities is empty")
        elif backend == "layered_ir":
            if result.get("query_trace") != IR_QUERY_ORDER:
                errors.append(f"{name}: layered IR query trace mismatch")
            if not result.get("resolved_entities"):
                errors.append(f"{name}: resolved_entities is empty")
        elif backend == "routes":
            if not result.get("resolved_entities") and not result.get("yaml_items"):
                errors.append(f"{name}: routes backend returned empty payload")
        else:
            if result.get("query_trace") != EXPECTED_QUERY_ORDER:
                errors.append(f"{name}: query trace is not terminology -> symbol_index -> derived -> raw -> yaml -> source")
            if not result.get("resolved_entities"):
                errors.append(f"{name}: resolved_entities is empty")
            if not (result.get("derived_entities") or result.get("raw_entities")):
                errors.append(f"{name}: query did not hit derived or raw graph")
            if not result.get("yaml_items"):
                errors.append(f"{name}: yaml_items is empty")
            if not (result.get("source_refs") or result.get("source_anchors") or result.get("nodes")):
                errors.append(f"{name}: source anchors are empty")
    if before != _readonly_fingerprint(uo_root):
        errors.append("query changed KB files")
    payload = {"status": "fail" if errors else "pass", "op_name": resolved_name, "cases": {key: {"entity": value, "status": "pass" if key in results else "fail"} for key, value in cases.items()}, "errors": errors, "query": results.get("stable_id") or next(iter(results.values()), {})}
    return (2 if errors else 0), payload


def _select_smoke_entity(uo_root: Path) -> tuple[str, str]:
    ir = uo_root / "ir" / "operator_graph.yaml"
    if ir.exists() and yaml is not None:
        data = yaml.safe_load(ir.read_text(encoding="utf-8")) or {}
        for node in data.get("nodes") or []:
            entity = str(node.get("id") or node.get("name") or "")
            if entity:
                return entity, "layered_ir"
    for graph_level, rel in (("derived", "graphs/derived/nodes.yaml"), ("raw", "graphs/raw/nodes.yaml")):
        for node in _load_list(uo_root / rel, "nodes"):
            entity = str(node.get("id") or node.get("label") or "")
            if entity:
                return entity, graph_level
    for graph_level, rel in (("derived", "graphs/derived/edges.yaml"), ("raw", "graphs/raw/edges.yaml")):
        for edge in _load_list(uo_root / rel, "edges"):
            entity = str(edge.get("id") or edge.get("source_id") or edge.get("target_id") or "")
            if entity:
                return entity, graph_level
    return "", "none"


def _select_smoke_cases(uo_root: Path) -> dict[str, str]:
    stable, _source = _select_smoke_entity(uo_root)
    symbol = ""
    terminology = ""
    stable_norm = _normalize_term(stable)
    for node in _load_list(uo_root / "graphs" / "raw" / "nodes.yaml", "nodes") + _load_list(uo_root / "graphs" / "derived" / "nodes.yaml", "nodes"):
        fields = node.get("search_fields") if isinstance(node.get("search_fields"), dict) else node.get("fields") if isinstance(node.get("fields"), dict) else {}
        for key in ("qualified_symbol", "scope_symbol", "symbol", "name"):
            value = fields.get(key)
            if isinstance(value, str) and value and _normalize_term(value) != stable_norm:
                symbol = symbol or value
                break
        if symbol:
            break
    terms = _load_mapping(uo_root / "indexes" / "terminology.yaml", "terms")
    for term, entry in terms.items():
        if not isinstance(term, str) or not term:
            continue
        if _normalize_term(term) in {stable_norm, _normalize_term(symbol)}:
            continue
        if not isinstance(entry, dict) or not (entry.get("nodes") or entry.get("edges")):
            continue
        terminology = term
        break
    cases = {"stable_id": stable, "symbol": symbol, "terminology": terminology}
    normalized = [_normalize_term(value) for value in cases.values() if value]
    if len(normalized) != len(set(normalized)):
        cases["terminology"] = ""
    return cases


def _readonly_fingerprint(uo_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(uo_root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(uo_root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


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
    trace: list[str] = []
    trace_details: list[str] = []
    with sqlite3.connect(index) as db:
        db.row_factory=sqlite3.Row
        trace.append("terminology"); trace_details.append("terminology: sqlite_alias_lookup")
        trace.append("symbol_index"); trace_details.append("symbol_index: sqlite_entity_lookup")
        rows=db.execute("select * from entities where id=? or normalized_label=? or id in (select entity_id from aliases where normalized_alias=?) order by graph_level desc limit ?", (term,norm,norm,limit)).fetchall()
        trace.append("derived")
        ids={r["id"] for r in rows}; direct=[]; neighbors=[]
        frontier=set(ids)
        for _ in range(depth):
            if not frontier: break
            marks=','.join('?' for _ in frontier); params=list(frontier)+list(frontier)
            sql=f"select * from relations where (source_id in ({marks}) or target_id in ({marks}))" + (" and type=?" if relation_type else "") + " limit ?"
            if relation_type: params.append(relation_type)
            params.append(limit); rels=db.execute(sql,params).fetchall(); direct.extend(rels)
            next_ids={r["source_id"] for r in rels}|{r["target_id"] for r in rels}; next_ids-=ids; frontier=next_ids; ids|=next_ids
        expansion_entities: list[sqlite3.Row] = []
        expansion_relations: list[sqlite3.Row] = []
        if ids:
            marks=','.join('?' for _ in ids); neighbors=db.execute(f"select * from entities where id in ({marks}) limit ?", [*ids,limit]).fetchall()
            expansion_rows = db.execute(f"select * from expansions where derived_id in ({marks}) limit ?", [*ids, limit]).fetchall()
            trace.append("raw")
            raw_node_ids = [str(r["raw_id"]) for r in expansion_rows if r["raw_kind"] == "node" and r["raw_id"]]
            raw_edge_ids = [str(r["raw_id"]) for r in expansion_rows if r["raw_kind"] == "edge" and r["raw_id"]]
            if raw_node_ids:
                raw_marks = ','.join('?' for _ in raw_node_ids)
                expansion_entities = db.execute(f"select * from entities where id in ({raw_marks}) limit ?", [*raw_node_ids, limit]).fetchall()
            if raw_edge_ids:
                raw_marks = ','.join('?' for _ in raw_edge_ids)
                expansion_relations = db.execute(f"select * from relations where id in ({raw_marks}) limit ?", [*raw_edge_ids, limit]).fetchall()
    detail_refs = [str(r["detail_ref"]) for r in [*neighbors, *expansion_entities, *expansion_relations] if r["detail_ref"]]
    details = [_read_yaml_ref(root, ref) for ref in sorted(set(detail_refs))]
    trace.append("yaml")
    source_refs = _source_refs_from_yaml_items(details)
    trace.append("source")
    entities = [_row(r) for r in rows]
    neighbor_entities = [_row(r) for r in [*neighbors, *expansion_entities][:limit]]
    return {
        "query": {
            "entity": term,
            "normalized": norm,
            "resolved_entities": [str(item.get("id")) for item in entities],
            "mode": "readonly",
            "order": EXPECTED_QUERY_ORDER,
        },
        "query_trace": trace,
        "query_trace_details": trace_details,
        "resolved_entities": entities,
        "direct_relations": [_row(r) for r in direct[:limit]],
        "neighbors": neighbor_entities,
        "fact_details": details,
        "yaml_items": details,
        "source_refs": source_refs,
        "source_anchors": source_refs,
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


def _resolve_entities(uo_root: Path, entity: str, trace: list[str]) -> set[str]:
    candidates = {entity, _normalize_term(entity)}
    result: set[str] = {entity}
    terminology = _load_mapping(uo_root / "indexes" / "terminology.yaml", "terms")
    trace.append("terminology")
    for candidate in list(candidates):
        entry = terminology.get(candidate) if isinstance(terminology, dict) else None
        if isinstance(entry, dict):
            result.update(str(item) for item in entry.get("nodes") or [])
            result.update(str(item) for item in entry.get("edges") or [])
    symbol_index = _load_mapping(uo_root / "indexes" / "symbol_index.yaml", "symbol_index")
    trace.append("symbol_index")
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
    fields = node.get("search_fields") if isinstance(node.get("search_fields"), dict) else node.get("fields") if isinstance(node.get("fields"), dict) else {}
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
    parser.add_argument("--entity")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--relation-type")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--question-type", help="Route hint: tiling_key_hit, runtime_branch, ...")
    args = parser.parse_args(argv)
    try:
        if args.smoke:
            code, payload = query_smoke(Path(args.repo), args.op_name)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return code
        if not args.entity:
            parser.error("--entity is required unless --smoke is used")
        payload = query_readonly(
            Path(args.repo),
            args.op_name,
            args.entity,
            depth=args.depth,
            relation_type=args.relation_type,
            limit=args.limit,
            question_type=args.question_type,
        )
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
