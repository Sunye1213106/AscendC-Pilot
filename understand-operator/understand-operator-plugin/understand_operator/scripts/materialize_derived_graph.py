from __future__ import annotations

import argparse
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

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.spec import spec_bundle_hash


def materialize_derived_graph(repo_root: Path, op_name: str) -> tuple[int, list[str]]:
    if yaml is None:
        return 2, ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        return 2, [f"operator KB root not found: {uo_root}"]
    rules_path = uo_root / "graphs" / "derived" / "abstraction_rules.yaml"
    raw_nodes_path = uo_root / "graphs" / "raw" / "nodes.yaml"
    raw_edges_path = uo_root / "graphs" / "raw" / "edges.yaml"
    if not rules_path.exists():
        return 2, ["graphs/derived/abstraction_rules.yaml is missing"]
    if not raw_nodes_path.exists() or not raw_edges_path.exists():
        return 2, ["raw graph is missing"]
    rules_doc = _read_yaml(rules_path)
    rules = rules_doc.get("rules") or rules_doc.get("items") or []
    raw_nodes = _load_list(raw_nodes_path, "nodes")
    raw_edges = _load_list(raw_edges_path, "edges")
    errors = _rule_errors(uo_root, rules, raw_nodes, raw_edges)
    if errors:
        _write_validation(uo_root, "fail", errors)
        return 2, errors
    nodes = [_derived_node(rule) for rule in rules if isinstance(rule, dict) and rule.get("node_id")]
    edges = [_derived_edge(rule) for rule in rules if isinstance(rule, dict) and rule.get("edge_id")]
    errors = _derived_graph_errors(nodes, edges)
    if errors:
        _write_validation(uo_root, "fail", errors)
        return 2, errors
    expansions = [
        {
            "id": rule.get("id"),
            "derived_id": rule.get("node_id") or rule.get("edge_id"),
            "raw_node_refs": rule.get("raw_node_refs") or [],
            "raw_edge_refs": rule.get("raw_edge_refs") or [],
            "yaml_refs": rule.get("yaml_refs") or [],
        }
        for rule in rules
        if isinstance(rule, dict)
    ]
    root = uo_root / "graphs" / "derived"
    _write_yaml(root / "nodes.yaml", _doc("graph.derived.nodes", {"nodes": nodes}))
    _write_yaml(root / "edges.yaml", _doc("graph.derived.edges", {"edges": edges}))
    _write_yaml(root / "expansions.yaml", _doc("graph.derived.expansions", {"expansions": expansions}))
    _write_yaml(root / "indexes.yaml", _doc("graph.derived.indexes", {"by_raw_node": _index_by(expansions, "raw_node_refs"), "by_raw_edge": _index_by(expansions, "raw_edge_refs")}))
    _write_validation(uo_root, "pass", [])
    return 0, [f"materialized derived graph: nodes={len(nodes)} edges={len(edges)}"]


def _rule_errors(uo_root: Path, rules: Any, raw_nodes: list[dict[str, Any]], raw_edges: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not isinstance(rules, list):
        return ["abstraction rules must be a list"]
    raw_node_ids = {str(node.get("id")) for node in raw_nodes if node.get("id")}
    raw_edge_by_id = {str(edge.get("id")): edge for edge in raw_edges if edge.get("id")}
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rules[{index}] must be a mapping")
            continue
        rule_id = str(rule.get("id") or "")
        node_id = str(rule.get("node_id") or "")
        edge_id = str(rule.get("edge_id") or "")
        if not rule_id.startswith("ARULE_"):
            errors.append(f"rules[{index}].id must start with ARULE_")
        if node_id and not node_id.startswith("DVIEW_"):
            errors.append(f"rules[{index}].node_id must start with DVIEW_")
        if edge_id and not edge_id.startswith("DVIEW_"):
            errors.append(f"rules[{index}].edge_id must start with DVIEW_")
        if rule.get("reversible") is not True:
            errors.append(f"rules[{index}] must set reversible: true")
        raw_node_refs = [str(ref) for ref in rule.get("raw_node_refs") or []]
        raw_edge_refs = [str(ref) for ref in rule.get("raw_edge_refs") or []]
        yaml_refs = [str(ref) for ref in rule.get("yaml_refs") or []]
        if not (raw_node_refs or raw_edge_refs):
            errors.append(f"rules[{index}] must reference raw nodes or edges")
        if not yaml_refs:
            errors.append(f"rules[{index}] must include yaml_refs")
        for ref in raw_node_refs:
            if ref not in raw_node_ids:
                errors.append(f"rules[{index}].raw_node_refs references missing raw node {ref}")
        for ref in raw_edge_refs:
            edge = raw_edge_by_id.get(ref)
            if not edge:
                errors.append(f"rules[{index}].raw_edge_refs references missing raw edge {ref}")
                continue
            if edge.get("source_id") not in raw_node_ids or edge.get("target_id") not in raw_node_ids:
                errors.append(f"rules[{index}].raw_edge_refs includes edge with invalid endpoints {ref}")
        for ref in yaml_refs:
            if _read_yaml_ref(uo_root, ref) is None:
                errors.append(f"rules[{index}].yaml_refs references missing YAML location {ref}")
        if raw_edge_refs and not _raw_subgraph_connected(raw_node_refs, raw_edge_refs, raw_edge_by_id):
            errors.append(f"rules[{index}] raw refs do not form a connected reversible subgraph")
    return errors


def _derived_graph_errors(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [str(item.get("id")) for item in nodes + edges if item.get("id")]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        errors.append("duplicate derived id(s): " + ", ".join(duplicates))
    node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    for edge in edges:
        source = edge.get("source_id")
        target = edge.get("target_id")
        if source not in node_ids:
            errors.append(f"derived edge {edge.get('id')} source_id missing: {source}")
        if target not in node_ids:
            errors.append(f"derived edge {edge.get('id')} target_id missing: {target}")
    return errors


def _raw_subgraph_connected(raw_node_refs: list[str], raw_edge_refs: list[str], raw_edge_by_id: dict[str, dict[str, Any]]) -> bool:
    nodes = set(raw_node_refs)
    adjacency: dict[str, set[str]] = {}
    for ref in raw_edge_refs:
        edge = raw_edge_by_id.get(ref) or {}
        source = str(edge.get("source_id") or "")
        target = str(edge.get("target_id") or "")
        if not source or not target:
            return False
        nodes.update({source, target})
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    if not nodes:
        return True
    seen: set[str] = set()
    stack = [next(iter(nodes))]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(sorted(adjacency.get(current, set()) - seen))
    return nodes <= seen


def _read_yaml_ref(uo_root: Path, ref: str) -> Any:
    rel, _, pointer = ref.partition("#")
    path = uo_root / rel
    if not path.exists():
        return None
    data = _read_yaml(path)
    value: Any = data
    for part in [part for part in pointer.strip("/").split("/") if part]:
        if isinstance(value, list) and part.isdigit():
            value = value[int(part)] if int(part) < len(value) else None
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _load_list(path: Path, key: str) -> list[dict[str, Any]]:
    data = _read_yaml(path)
    values = data.get(key) if isinstance(data, dict) else []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _derived_node(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule["node_id"],
        "kind": rule.get("abstract_type") or "derived",
        "label": rule.get("abstract_name") or rule["node_id"],
        "rule_id": rule.get("id"),
        "raw_node_refs": rule.get("raw_node_refs") or [],
        "raw_edge_refs": rule.get("raw_edge_refs") or [],
        "yaml_refs": rule.get("yaml_refs") or [],
    }


def _derived_edge(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule["edge_id"],
        "type": rule.get("relation_type") or rule.get("abstract_type") or "derived",
        "source_id": rule.get("source_id"),
        "target_id": rule.get("target_id"),
        "rule_id": rule.get("id"),
        "raw_node_refs": rule.get("raw_node_refs") or [],
        "raw_edge_refs": rule.get("raw_edge_refs") or [],
        "yaml_refs": rule.get("yaml_refs") or [],
    }


def _index_by(expansions: list[dict[str, Any]], key: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in expansions:
        for ref in item.get(key) or []:
            result.setdefault(str(ref), []).append(str(item.get("derived_id")))
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _doc(artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": "derived-graph-materializer"},
        "snapshot": {"run_id": "UO_RUN_DERIVED", "source_snapshot_id": "SOURCE_DERIVED", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()},
        **payload,
        "items": [],
        "relations": [],
        "unresolved": [],
    }


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _write_validation(uo_root: Path, status: str, errors: list[str]) -> None:
    _write_yaml(uo_root / "checks" / "derived_validation.yaml", _doc("checks.derived_validation", {"status": status, "errors": errors}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize reversible derived graph from abstraction rules.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = materialize_derived_graph(repo_root, op_name)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
