from __future__ import annotations

import argparse
import fnmatch
import hashlib
import sys
from datetime import datetime, timezone
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

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.spec import catalog_entries, load_spec, spec_bundle_hash
from understand_operator.scripts.build_compile_gate import compile_gate_errors, facts_hashes_for


def compile_source_graph(repo_root: Path, op_name: str) -> tuple[int, list[str]]:
    if yaml is None:
        return 2, ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        return 2, [f"operator KB root not found: {uo_root}"]
    gate_errors = compile_gate_errors(uo_root)
    if gate_errors:
        return 2, gate_errors

    spec = load_spec()
    docs = _load_fact_docs(uo_root, spec)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    yaml_to_graph: dict[str, list[str]] = {}
    graph_to_yaml: dict[str, str] = {}
    source_index: dict[str, list[str]] = {}
    symbol_index: dict[str, dict[str, list[str]]] = {}

    for rel, doc in docs.items():
        for index, item in enumerate(doc.get("items") or []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            node = _node_from_item(rel, f"/items/{index}", item)
            nodes.append(node)
            _index_node(rel, node, yaml_to_graph, graph_to_yaml, source_index, symbol_index)
        for index, relation in enumerate(doc.get("relations") or []):
            if not isinstance(relation, dict) or not relation.get("id"):
                continue
            edge = {
                "id": relation["id"],
                "type": relation.get("type"),
                "source_id": relation.get("source_id"),
                "target_id": relation.get("target_id"),
                "detail_ref": f"{rel}#/relations/{index}",
                "source_refs": _source_refs(relation),
            }
            edges.append(edge)

    validation_errors = _raw_graph_errors(nodes, edges, spec)
    if validation_errors:
        return 2, validation_errors
    paths = _derive_paths(edges)
    raw_root = uo_root / "graphs" / "raw"
    index_root = uo_root / "indexes"
    _write_yaml(raw_root / "manifest.yaml", _raw_doc("graph.raw.manifest", {"compiler": "source_graph_compiler", "input_facts_hash": _combined_hash(facts_hashes_for(uo_root)), "node_count": len(nodes), "edge_count": len(edges), "built_at": datetime.now(tz=timezone.utc).isoformat()}))
    _write_yaml(raw_root / "nodes.yaml", _raw_doc("graph.raw.nodes", {"nodes": nodes}))
    _write_yaml(raw_root / "edges.yaml", _raw_doc("graph.raw.edges", {"edges": edges}))
    _write_yaml(raw_root / "paths.yaml", _raw_doc("graph.raw.paths", {"paths": paths}))
    _write_yaml(raw_root / "indexes.yaml", _raw_doc("graph.raw.indexes", {"by_kind": _by_key(nodes, "kind"), "by_relation_type": _by_key(edges, "type")}))
    _write_yaml(index_root / "graph_to_yaml.yaml", _raw_doc("indexes.graph_to_yaml", {"graph_to_yaml": graph_to_yaml}))
    _write_yaml(index_root / "yaml_to_graph.yaml", _raw_doc("indexes.yaml_to_graph", {"yaml_to_graph": yaml_to_graph}))
    _write_yaml(index_root / "source_index.yaml", _raw_doc("indexes.source_index", {"source_index": source_index}))
    _write_yaml(index_root / "symbol_index.yaml", _raw_doc("indexes.symbol_index", {"symbol_index": symbol_index}))
    _write_yaml(index_root / "terminology.yaml", _raw_doc("indexes.terminology", {"terms": {}}))
    return 0, [f"compiled raw graph: nodes={len(nodes)} edges={len(edges)}"]


def _load_fact_docs(uo_root: Path, spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    raw_patterns = [
        str(entry.get("path") or "").replace("\\", "/")
        for entry in catalog_entries(spec)
        if entry.get("raw_graph_input") is True
    ]
    for path in sorted((uo_root / "facts").rglob("*.yaml")):
        rel = path.relative_to(uo_root).as_posix()
        if not any(fnmatch.fnmatch(rel, pattern) for pattern in raw_patterns):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            docs[rel] = data
    return docs


def _node_from_item(rel: str, pointer: str, item: dict[str, Any], *, kind: str | None = None) -> dict[str, Any]:
    return {
        "id": item["id"],
        "kind": kind or item.get("kind") or "fact",
        "label": item.get("name") or item.get("id"),
        "detail_ref": f"{rel}#{pointer}",
        "source_refs": _source_refs(item),
    }


def _source_refs(item: dict[str, Any]) -> list[str]:
    refs = []
    for source in item.get("sources") or []:
        if isinstance(source, dict) and source.get("id"):
            refs.append(str(source["id"]))
    return refs


def _index_node(
    rel: str,
    node: dict[str, Any],
    yaml_to_graph: dict[str, list[str]],
    graph_to_yaml: dict[str, str],
    source_index: dict[str, list[str]],
    symbol_index: dict[str, dict[str, list[str]]],
) -> None:
    detail_ref = str(node["detail_ref"])
    yaml_to_graph.setdefault(detail_ref, []).append(str(node["id"]))
    graph_to_yaml[str(node["id"])] = detail_ref
    for source_id in node.get("source_refs") or []:
        source_index.setdefault(source_id, []).append(str(node["id"]))
    label = str(node.get("label") or "")
    if label:
        symbol_index.setdefault(label, {"nodes": []})["nodes"].append(str(node["id"]))


def _raw_graph_errors(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    node_ids = [str(node.get("id")) for node in nodes if node.get("id")]
    edge_ids = [str(edge.get("id")) for edge in edges if edge.get("id")]
    for label, values in (("node", node_ids), ("edge", edge_ids)):
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            errors.append(f"duplicate raw graph {label} id(s): {', '.join(duplicates)}")
    node_by_id = {str(node["id"]): node for node in nodes if node.get("id")}
    relation_types = (spec.get("relation_types") or {}).get("relation_types") or {}
    for node in nodes:
        if not node.get("detail_ref"):
            errors.append(f"node {node.get('id')} missing detail_ref")
        node_id = str(node.get("id") or "")
        kind = str(node.get("kind") or "")
        if node_id.startswith(("DVIEW_", "FAMILY_", "L0_", "L1_", "L2_")) or kind in {"derived_view", "family", "l0", "l1", "l2"}:
            errors.append(f"raw graph contains non-source node {node_id or kind}")
    for edge in edges:
        edge_id = str(edge.get("id") or "")
        if not edge.get("detail_ref"):
            errors.append(f"edge {edge_id} missing detail_ref")
        source_id = str(edge.get("source_id") or "")
        target_id = str(edge.get("target_id") or "")
        if source_id not in node_by_id:
            errors.append(f"edge {edge_id} source_id does not exist: {source_id}")
        if target_id not in node_by_id:
            errors.append(f"edge {edge_id} target_id does not exist: {target_id}")
        rtype = edge.get("type")
        rule = relation_types.get(rtype) if isinstance(relation_types, dict) else None
        if isinstance(rule, dict) and source_id in node_by_id and target_id in node_by_id:
            source_kind = _normalize_kind(str(node_by_id[source_id].get("kind") or ""))
            target_kind = _normalize_kind(str(node_by_id[target_id].get("kind") or ""))
            if not _kind_matches(source_kind, str(rule.get("source") or "any")):
                errors.append(f"edge {edge_id} source kind mismatch: expected {rule.get('source')}, got {source_kind}")
            if not _kind_matches(target_kind, str(rule.get("target") or "any")):
                errors.append(f"edge {edge_id} target kind mismatch: expected {rule.get('target')}, got {target_kind}")
    return errors


def _derive_paths(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    incoming: dict[str, int] = {}
    nodes: set[str] = set()
    for edge in edges:
        source = str(edge.get("source_id") or "")
        target = str(edge.get("target_id") or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, []).append(edge)
        incoming[target] = incoming.get(target, 0) + 1
        nodes.update({source, target})
    starts = sorted(node for node in nodes if incoming.get(node, 0) == 0) or sorted(nodes)
    paths: list[dict[str, Any]] = []
    for start in starts:
        _walk_paths(start, start, adjacency, [], set(), paths)
    return [
        {"id": f"RAW_PATH_{index + 1:04d}", **path}
        for index, path in enumerate(paths)
        if path.get("edge_ids")
    ]


def _walk_paths(
    root: str,
    current: str,
    adjacency: dict[str, list[dict[str, Any]]],
    edge_ids: list[str],
    seen: set[str],
    paths: list[dict[str, Any]],
) -> None:
    outgoing = adjacency.get(current) or []
    if not outgoing:
        if edge_ids:
            paths.append({"source_id": root, "target_id": current, "edge_ids": list(edge_ids)})
        return
    if current in seen:
        if edge_ids:
            paths.append({"source_id": root, "target_id": current, "edge_ids": list(edge_ids), "cycle": True})
        return
    for edge in outgoing:
        _walk_paths(root, str(edge.get("target_id")), adjacency, edge_ids + [str(edge.get("id"))], seen | {current}, paths)


def _kind_matches(actual: str, expected: str) -> bool:
    if expected == "any" or actual == expected:
        return True
    aliases = {
        "argument": {"input_tensor", "output_tensor", "optional_input", "attribute"},
        "variable": {"variable", "source_fact", "runtime_variable", "host_variable", "tilingdata", "key"},
        "symbol": {"symbol", "source_fact", "host_entry", "tiling_entry", "kernel_entry", "function", "call"},
        "expression": {"expression", "source_fact"},
        "branch": {"branch", "source_fact"},
        "loop": {"loop", "source_fact"},
        "call": {"call", "source_fact"},
        "key": {"key", "source_fact"},
        "tilingdata": {"tilingdata", "source_fact"},
        "tensor": {"tensor", "input_tensor", "output_tensor", "source_fact"},
        "operation": {"operation", "source_fact"},
        "api": {"api", "call", "source_fact"},
        "sync": {"sync", "source_fact"},
    }
    return actual in aliases.get(expected, set())


def _normalize_kind(kind: str) -> str:
    lowered = kind.lower()
    if lowered.startswith(("input_", "output_")):
        return lowered
    for token, normalized in (
        ("tensor", "tensor"),
        ("operation", "operation"),
        ("branch", "branch"),
        ("loop", "loop"),
        ("call", "call"),
        ("key", "key"),
        ("tilingdata", "tilingdata"),
        ("sync", "sync"),
        ("entry", "symbol"),
        ("function", "symbol"),
        ("symbol", "symbol"),
        ("expr", "expression"),
        ("var", "variable"),
    ):
        if token in lowered:
            return normalized
    return lowered or "fact"


def _raw_doc(artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": "raw-graph-compiler"},
        "snapshot": {
            "run_id": "UO_RUN_GRAPH",
            "source_snapshot_id": "SOURCE_GRAPH",
            "source_revision": "unknown",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        **payload,
        "items": [],
        "relations": [],
        "unresolved": [],
    }


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _combined_hash(values: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for key, value in sorted(values.items()):
        digest.update(key.encode("utf-8"))
        digest.update(value.encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def _by_key(items: list[dict[str, Any]], key: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        result.setdefault(value, []).append(str(item.get("id")))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile validated source facts into raw behavior graph.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = compile_source_graph(repo_root, op_name)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
