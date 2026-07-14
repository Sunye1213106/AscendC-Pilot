from __future__ import annotations

import argparse
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
from understand_operator._operator.spec import spec_bundle_hash
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

    docs = _load_fact_docs(uo_root)
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
            node = _node_from_item(rel, f"/relations/{index}", relation, kind="relation")
            nodes.append(node)
            _index_node(rel, node, yaml_to_graph, graph_to_yaml, source_index, symbol_index)
            edge = {
                "id": relation["id"],
                "type": relation.get("type"),
                "source_id": relation.get("source_id"),
                "target_id": relation.get("target_id"),
                "detail_ref": f"{rel}#/relations/{index}",
                "source_refs": _source_refs(relation),
            }
            edges.append(edge)

    paths = _derive_simple_paths(edges)
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


def _load_fact_docs(uo_root: Path) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for path in sorted((uo_root / "facts").rglob("*.yaml")):
        rel = path.relative_to(uo_root).as_posix()
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


def _derive_simple_paths(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"RAW_PATH_{index + 1:04d}",
            "source_id": edge.get("source_id"),
            "target_id": edge.get("target_id"),
            "edge_ids": [edge.get("id")],
        }
        for index, edge in enumerate(edges)
        if edge.get("source_id") and edge.get("target_id")
    ]


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
