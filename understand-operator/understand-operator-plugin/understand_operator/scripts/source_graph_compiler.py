from __future__ import annotations

import argparse
import fnmatch
import hashlib
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
            _index_edge(rel, edge, yaml_to_graph, graph_to_yaml, source_index)

    synthetic_edges = _deterministic_cross_layer_edges(nodes)
    for edge in synthetic_edges:
        edges.append(edge)
        _index_synthetic_edge(edge, yaml_to_graph, graph_to_yaml, source_index)

    nodes = sorted(nodes, key=lambda item: str(item.get("id") or ""))
    edges = sorted(edges, key=lambda item: str(item.get("id") or ""))
    for values in (yaml_to_graph, source_index):
        for key, items in values.items():
            values[key] = sorted(set(items))
    graph_to_yaml = dict(sorted(graph_to_yaml.items()))
    symbol_index = {key: {"nodes": sorted(set(value.get("nodes") or [])), "edges": sorted(set(value.get("edges") or []))} for key, value in sorted(symbol_index.items())}
    validation_errors = _raw_graph_errors(nodes, edges, spec) + _cross_layer_reference_errors(nodes)
    if validation_errors:
        return 2, validation_errors
    paths = _derive_paths(edges, nodes)
    terminology = _terminology(nodes)
    raw_root = uo_root / "graphs" / "raw"
    index_root = uo_root / "indexes"
    _write_yaml(raw_root / "nodes.yaml", _raw_doc("graph.raw.nodes", {"_uo_root": uo_root, "nodes": nodes}))
    _write_yaml(raw_root / "edges.yaml", _raw_doc("graph.raw.edges", {"_uo_root": uo_root, "edges": edges}))
    _write_yaml(raw_root / "paths.yaml", _raw_doc("graph.raw.paths", {"_uo_root": uo_root, "paths": paths}))
    _write_yaml(raw_root / "indexes.yaml", _raw_doc("graph.raw.indexes", {"_uo_root": uo_root, "by_kind": _by_key(nodes, "kind"), "by_relation_type": _by_key(edges, "type")}))
    _write_yaml(index_root / "graph_to_yaml.yaml", _raw_doc("indexes.graph_to_yaml", {"_uo_root": uo_root, "graph_to_yaml": graph_to_yaml}))
    _write_yaml(index_root / "yaml_to_graph.yaml", _raw_doc("indexes.yaml_to_graph", {"_uo_root": uo_root, "yaml_to_graph": yaml_to_graph}))
    _write_yaml(index_root / "source_index.yaml", _raw_doc("indexes.source_index", {"_uo_root": uo_root, "source_index": source_index}))
    _write_yaml(index_root / "symbol_index.yaml", _raw_doc("indexes.symbol_index", {"_uo_root": uo_root, "symbol_index": symbol_index}))
    _write_yaml(index_root / "terminology.yaml", _raw_doc("indexes.terminology", {"_uo_root": uo_root, "terms": terminology}))
    output_hashes = {
        rel: _sha256(uo_root / rel)
        for rel in (
            "graphs/raw/nodes.yaml",
            "graphs/raw/edges.yaml",
            "graphs/raw/paths.yaml",
            "graphs/raw/indexes.yaml",
            "indexes/graph_to_yaml.yaml",
            "indexes/yaml_to_graph.yaml",
            "indexes/source_index.yaml",
            "indexes/symbol_index.yaml",
            "indexes/terminology.yaml",
        )
    }
    _write_yaml(raw_root / "manifest.yaml", _raw_doc("graph.raw.manifest", {"_uo_root": uo_root, "compiler": "source_graph_compiler", "input_facts_hash": _combined_hash(facts_hashes_for(uo_root)), "node_count": len(nodes), "edge_count": len(edges), "output_hashes": output_hashes}))
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
        "fields": {key: value for key, value in item.items() if key not in {"sources"}},
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
    fields = node.get("fields") if isinstance(node.get("fields"), dict) else {}
    for key in ("symbol", "path", "file", "field_ref", "struct_ref", "operation_ref", "buffer_ref", "event_identifier"):
        value = fields.get(key)
        if isinstance(value, str) and value:
            symbol_index.setdefault(value, {"nodes": []})["nodes"].append(str(node["id"]))


def _index_edge(
    rel: str,
    edge: dict[str, Any],
    yaml_to_graph: dict[str, list[str]],
    graph_to_yaml: dict[str, str],
    source_index: dict[str, list[str]],
) -> None:
    detail_ref = str(edge["detail_ref"])
    yaml_to_graph.setdefault(detail_ref, []).append(str(edge["id"]))
    graph_to_yaml[str(edge["id"])] = detail_ref
    for source_id in edge.get("source_refs") or []:
        source_index.setdefault(source_id, []).append(str(edge["id"]))


def _index_synthetic_edge(
    edge: dict[str, Any],
    yaml_to_graph: dict[str, list[str]],
    graph_to_yaml: dict[str, str],
    source_index: dict[str, list[str]],
) -> None:
    detail_refs = [str(ref) for ref in edge.get("detail_refs") or [] if ref]
    graph_to_yaml[str(edge["id"])] = detail_refs[0] if detail_refs else str(edge.get("detail_ref") or "")
    for ref in detail_refs:
        yaml_to_graph.setdefault(ref, []).append(str(edge["id"]))
    for source_id in edge.get("source_refs") or []:
        source_index.setdefault(str(source_id), []).append(str(edge["id"]))


def _deterministic_cross_layer_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    edges.extend(_match_field(nodes, "tilingdata_write", "tilingdata_read", "tilingdata_write_to_read", ("struct_ref", "field_ref")))
    edges.extend(_match_tiling_key_setters(nodes))
    edges.extend(_compute_kernel_edges(nodes))
    edges.extend(_buffer_edges(nodes))
    edges.extend(_signal_wait_edges(nodes))
    edges.extend(_kernel_entry_output_edges(nodes))
    unique: dict[str, dict[str, Any]] = {}
    for edge in edges:
        unique.setdefault(str(edge.get("id")), edge)
    return list(unique.values())


def _match_tiling_key_setters(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    setters = [node for node in nodes if _normalize_kind(str(node.get("kind") or "")) == "call" and str(node.get("kind")) == "tiling_key_setter_call"]
    fields = [node for node in nodes if str(node.get("kind")) == "tiling_key_field"]
    for setter in setters:
        sfields = setter.get("fields") if isinstance(setter.get("fields"), dict) else {}
        field_refs = set(_as_list(sfields.get("field_refs")))
        encoding_ref = str(sfields.get("encoding_ref") or "")
        if not field_refs or not encoding_ref:
            continue
        for target in fields:
            tfields = target.get("fields") if isinstance(target.get("fields"), dict) else {}
            target_refs = {str(target.get("id") or ""), str(tfields.get("field_ref") or "")}
            if not (field_refs & target_refs):
                continue
            if encoding_ref != str(tfields.get("encoding_call_ref") or ""):
                continue
            result.append(_synthetic_edge("tiling_key_setter_to_field", setter, target, "deterministic_tiling_key_refs"))
    return result


def _compute_kernel_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    api_nodes = [node for node in nodes if str(node.get("kind")) in {"compute_api_call", "kernel_call"} or _normalize_kind(str(node.get("kind") or "")) == "api"]
    for op in [node for node in nodes if str(node.get("kind")) == "compute_operation"]:
        ofields = op.get("fields") if isinstance(op.get("fields"), dict) else {}
        execution = ofields.get("execution") if isinstance(ofields.get("execution"), dict) else {}
        api_refs: list[str] = []
        for path in execution.get("paths") or []:
            if isinstance(path, dict):
                api_refs.extend(_as_list(path.get("api_refs")))
        for ref in sorted(set(api_refs)):
            target = by_id.get(ref)
            if target:
                result.append(_synthetic_edge("compute_to_kernel", op, target, "deterministic_execution_api_refs"))
    for api in api_nodes:
        fields = api.get("fields") if isinstance(api.get("fields"), dict) else {}
        op_ref = str(fields.get("compute_operation_ref") or "")
        source = by_id.get(op_ref)
        if source:
            result.append(_synthetic_edge("compute_to_kernel", source, api, "deterministic_compute_operation_ref"))
    return result


def _synthetic_edge(edge_type: str, source: dict[str, Any], target: dict[str, Any], generated_by: str) -> dict[str, Any]:
    edge_id = "REL_AUTO_" + edge_type.upper() + "_" + _stable_suffix(str(source["id"]), str(target["id"]))
    return {
        "id": edge_id,
        "type": edge_type,
        "source_id": source["id"],
        "target_id": target["id"],
        "detail_ref": source["detail_ref"],
        "detail_refs": [source["detail_ref"], target["detail_ref"]],
        "source_refs": sorted(set((source.get("source_refs") or []) + (target.get("source_refs") or []))),
        "generated_by": generated_by,
    }


def _match_field(
    nodes: list[dict[str, Any]],
    source_kind: str,
    target_kind: str,
    edge_type: str,
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    source_nodes = [node for node in nodes if str(node.get("kind")) == source_kind]
    target_nodes = [node for node in nodes if str(node.get("kind")) == target_kind]
    for source in source_nodes:
        for target in target_nodes:
            if source["id"] == target["id"]:
                continue
            if not _stable_match(source, target, fields):
                continue
            edge_id = "REL_AUTO_" + edge_type.upper() + "_" + _stable_suffix(str(source["id"]), str(target["id"]))
            result.append(
                {
                    "id": edge_id,
                    "type": edge_type,
                    "source_id": source["id"],
                    "target_id": target["id"],
                    "detail_ref": source["detail_ref"],
                    "detail_refs": [source["detail_ref"], target["detail_ref"]],
                    "source_refs": sorted(set((source.get("source_refs") or []) + (target.get("source_refs") or []))),
                    "generated_by": "deterministic_cross_layer_match",
                }
            )
    return result


def _match_list_ref(
    nodes: list[dict[str, Any]],
    source_kind: str,
    target_kind: str,
    edge_type: str,
    source_field: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    source_nodes = [node for node in nodes if str(node.get("kind")) == source_kind]
    target_by_id = {str(node.get("id")): node for node in nodes if str(node.get("kind")) == target_kind}
    seen: set[tuple[str, str]] = set()
    for source in source_nodes:
        fields = source.get("fields") if isinstance(source.get("fields"), dict) else {}
        refs = fields.get(source_field)
        if isinstance(refs, str):
            ref_values = [refs]
        elif isinstance(refs, list):
            ref_values = [str(ref) for ref in refs if ref]
        else:
            ref_values = []
        for ref in ref_values:
            target = target_by_id.get(ref)
            if not target or (str(source["id"]), str(target["id"])) in seen:
                continue
            seen.add((str(source["id"]), str(target["id"])))
            edge_id = "REL_AUTO_" + edge_type.upper() + "_" + _stable_suffix(str(source["id"]), str(target["id"]))
            result.append(
                {
                    "id": edge_id,
                    "type": edge_type,
                    "source_id": source["id"],
                    "target_id": target["id"],
                    "detail_ref": source["detail_ref"],
                    "detail_refs": [source["detail_ref"], target["detail_ref"]],
                    "source_refs": sorted(set((source.get("source_refs") or []) + (target.get("source_refs") or []))),
                    "generated_by": f"deterministic_{source_field}_match",
                }
            )
    return result


def _buffer_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    for resource in nodes:
        if _normalize_kind(str(resource.get("kind") or "")) != "memory_resource":
            continue
        fields = resource.get("fields") if isinstance(resource.get("fields"), dict) else {}
        producers = _as_list(fields.get("producer_refs"))
        consumers = _as_list(fields.get("consumer_refs"))
        for producer_id in producers:
            for consumer_id in consumers:
                producer = by_id.get(producer_id)
                consumer = by_id.get(consumer_id)
                if not producer or not consumer:
                    continue
                edge_id = "REL_AUTO_BUFFER_PRODUCER_TO_CONSUMER_" + _stable_suffix(producer_id, consumer_id)
                result.append(
                    {
                        "id": edge_id,
                        "type": "buffer_producer_to_consumer",
                        "source_id": producer_id,
                        "target_id": consumer_id,
                        "detail_ref": resource["detail_ref"],
                        "detail_refs": [producer["detail_ref"], resource["detail_ref"], consumer["detail_ref"]],
                        "source_refs": sorted(set((producer.get("source_refs") or []) + (resource.get("source_refs") or []) + (consumer.get("source_refs") or []))),
                        "buffer_resource_ref": resource["id"],
                        "queue_operation_refs": sorted(set(_as_list(fields.get("queue_operation_refs")))),
                        "generated_by": "deterministic_memory_resource_refs",
                    }
                )
    return result


def _signal_wait_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    for event in nodes:
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        if not fields.get("event_identifier"):
            continue
        signals = _as_list(fields.get("signal_call_refs"))
        waits = _as_list(fields.get("wait_call_refs"))
        for signal_id in signals:
            signal = by_id.get(signal_id)
            if not signal:
                continue
            for wait_id in waits:
                wait = by_id.get(wait_id)
                if not wait:
                    continue
                edge = _synthetic_edge("signal_to_wait", signal, wait, "deterministic_event_call_refs")
                edge["event_identifier"] = fields.get("event_identifier")
                edge["detail_refs"] = [signal["detail_ref"], event["detail_ref"], wait["detail_ref"]]
                edge["source_refs"] = sorted(set((signal.get("source_refs") or []) + (event.get("source_refs") or []) + (wait.get("source_refs") or [])))
                result.append(edge)
    return result


def _kernel_entry_output_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    for interface in nodes:
        if str(interface.get("kind")) not in {"kernel_slice", "slice_interface", "kernel_entry"}:
            continue
        fields = interface.get("fields") if isinstance(interface.get("fields"), dict) else {}
        entry_ref = str(fields.get("kernel_entry_ref") or interface.get("id") or "")
        entry = by_id.get(entry_ref)
        if not entry:
            continue
        for output_id in _as_list(fields.get("output_tensor_refs")) + _as_list(fields.get("output_write_refs")):
            target = by_id.get(output_id)
            if not target:
                continue
            edge_id = "REL_AUTO_KERNEL_ENTRY_TO_OUTPUT_" + _stable_suffix(entry_ref, output_id)
            result.append(
                {
                    "id": edge_id,
                    "type": "kernel_entry_to_output",
                    "source_id": entry_ref,
                    "target_id": output_id,
                    "detail_ref": interface["detail_ref"],
                    "detail_refs": [entry["detail_ref"], interface["detail_ref"], target["detail_ref"]],
                    "source_refs": sorted(set((entry.get("source_refs") or []) + (interface.get("source_refs") or []) + (target.get("source_refs") or []))),
                    "generated_by": "deterministic_kernel_interface_refs",
                }
            )
    return result


def _stable_match(source: dict[str, Any], target: dict[str, Any], fields: tuple[str, ...]) -> bool:
    sfields = source.get("fields") if isinstance(source.get("fields"), dict) else {}
    tfields = target.get("fields") if isinstance(target.get("fields"), dict) else {}
    for field in fields:
        sval = sfields.get(field)
        tval = tfields.get(field)
        if not _value_matches(sval, tval):
            return False
    return True


def _value_matches(source_value: Any, target_value: Any) -> bool:
    source_values = set(_as_list(source_value))
    target_values = set(_as_list(target_value))
    if not source_values or not target_values:
        return False
    return bool(source_values & target_values)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str) and value:
        return [value]
    return []


def _stable_suffix(source_id: str, target_id: str) -> str:
    return hashlib.sha1(f"{source_id}->{target_id}".encode("utf-8")).hexdigest()[:12].upper()


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


def _cross_layer_reference_errors(nodes: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    compute_ids = {str(node.get("id")) for node in nodes if str(node.get("kind")) == "compute_operation"}
    api_ids = {str(node.get("id")) for node in nodes if str(node.get("kind")) in {"compute_api_call", "kernel_call"} or _normalize_kind(str(node.get("kind") or "")) == "api"}
    for op in [node for node in nodes if str(node.get("kind")) == "compute_operation"]:
        fields = op.get("fields") if isinstance(op.get("fields"), dict) else {}
        execution = fields.get("execution") if isinstance(fields.get("execution"), dict) else {}
        for path_index, path in enumerate(execution.get("paths") or []):
            if not isinstance(path, dict):
                continue
            for api_ref in _as_list(path.get("api_refs")):
                target = by_id.get(api_ref)
                if not target:
                    errors.append(f"CROSS_LAYER_REFERENCE_MISSING: {op.get('id')} execution.paths[{path_index}].api_refs -> {api_ref}")
                elif str(target.get("id")) not in api_ids:
                    errors.append(f"CROSS_LAYER_REFERENCE_CONFLICT: {op.get('id')} api_refs target is not a kernel/API call: {api_ref}")
    for api in [node for node in nodes if str(node.get("id")) in api_ids]:
        fields = api.get("fields") if isinstance(api.get("fields"), dict) else {}
        op_ref = fields.get("compute_operation_ref")
        if op_ref and str(op_ref) not in compute_ids:
            errors.append(f"CROSS_LAYER_REFERENCE_MISSING: {api.get('id')} compute_operation_ref -> {op_ref}")
    for event in nodes:
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        if not fields.get("event_identifier"):
            continue
        for key in ("signal_call_refs", "wait_call_refs"):
            for ref in _as_list(fields.get(key)):
                if ref not in by_id:
                    errors.append(f"CROSS_LAYER_REFERENCE_MISSING: {event.get('id')} {key} -> {ref}")
    return errors


def _derive_paths(edges: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    controlled_types = {
        "input_to_tiling_key": {"sets_tiling_key", "tiling_key_setter_to_field"},
        "tilingdata_write_to_read": {"tilingdata_write_to_read"},
        "kernel_entry_to_output": {"kernel_entry_to_output", "writes_output"},
        "compute_to_kernel": {"compute_to_kernel"},
        "buffer_producer_to_consumer": {"buffer_producer_to_consumer"},
        "signal_to_wait": {"signal_to_wait"},
    }
    max_depth = 6
    max_paths_per_type = 50
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source = str(edge.get("source_id") or "")
        target = str(edge.get("target_id") or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, []).append(edge)
    paths: list[dict[str, Any]] = []
    for path_type, allowed_types in controlled_types.items():
        starts = sorted({str(edge.get("source_id")) for edge in edges if edge.get("type") in allowed_types})
        selected: list[dict[str, Any]] = []
        truncated = False
        for start in starts:
            _walk_controlled_paths(path_type, start, start, adjacency, allowed_types, [], set(), selected, max_depth, max_paths_per_type)
            if len(selected) >= max_paths_per_type:
                truncated = True
                break
        for index, path in enumerate(selected[:max_paths_per_type], start=1):
            paths.append(
                {
                    "id": f"RAW_PATH_{path_type.upper()}_{index:04d}",
                    "path_type": path_type,
                    "max_depth": max_depth,
                    "max_paths_per_type": max_paths_per_type,
                    "truncated": truncated or len(selected) > max_paths_per_type,
                    **path,
                }
            )
    paths.extend(_execution_engine_paths(nodes, len(paths)))
    return sorted(paths, key=lambda item: str(item.get("id") or ""))


def _execution_engine_paths(nodes: list[dict[str, Any]], offset: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in nodes:
        if str(node.get("kind")) != "compute_operation":
            continue
        fields = node.get("fields") if isinstance(node.get("fields"), dict) else {}
        execution = fields.get("execution") if isinstance(fields.get("execution"), dict) else {}
        raw_paths = [path for path in execution.get("paths") or [] if isinstance(path, dict)]
        signatures = {(str(path.get("engine") or ""), tuple(_as_list(path.get("condition_refs")))) for path in raw_paths}
        if len(signatures) >= 2:
            offset += 1
            result.append({"id": f"RAW_PATH_CONDITIONAL_ENGINE_PATH_{offset:04d}", "path_type": "conditional_engine_path", "source_id": node["id"], "target_id": node["id"], "engine_paths": sorted(str(engine) for engine, _ in signatures)})
        if any(path.get("architecture_variants") for path in raw_paths):
            offset += 1
            result.append({"id": f"RAW_PATH_ARCHITECTURE_ENGINE_PATH_{offset:04d}", "path_type": "architecture_engine_path", "source_id": node["id"], "target_id": node["id"], "engine_paths": sorted(set(str(path.get("engine") or "") for path in raw_paths))})
        engines = [str(path.get("engine") or "") for path in raw_paths]
        if "cube" in engines and "vector" in engines and all(any(path.get("engine") == engine and path.get("api_refs") for path in raw_paths) for engine in ("cube", "vector")):
            offset += 1
            result.append({"id": f"RAW_PATH_MIXED_ENGINE_PATH_{offset:04d}", "path_type": "mixed_engine_path", "source_id": node["id"], "target_id": node["id"], "engine_paths": engines})
    return result


def _walk_controlled_paths(
    path_type: str,
    root: str,
    current: str,
    adjacency: dict[str, list[dict[str, Any]]],
    allowed_types: set[str],
    edge_ids: list[str],
    seen: set[str],
    paths: list[dict[str, Any]],
    max_depth: int,
    max_paths: int,
) -> None:
    if len(paths) >= max_paths or len(edge_ids) >= max_depth:
        if edge_ids:
            paths.append({"source_id": root, "target_id": current, "edge_ids": list(edge_ids), "depth_limited": len(edge_ids) >= max_depth})
        return
    if current in seen:
        if edge_ids:
            paths.append({"source_id": root, "target_id": current, "edge_ids": list(edge_ids), "cycle": True})
        return
    outgoing = [edge for edge in adjacency.get(current) or [] if edge.get("type") in allowed_types]
    if not outgoing and edge_ids:
        paths.append({"source_id": root, "target_id": current, "edge_ids": list(edge_ids)})
        return
    for edge in outgoing:
        _walk_controlled_paths(path_type, root, str(edge.get("target_id")), adjacency, allowed_types, edge_ids + [str(edge.get("id"))], seen | {current}, paths, max_depth, max_paths)


def _terminology(nodes: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    terms: dict[str, dict[str, list[str]]] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        fields = node.get("fields") if isinstance(node.get("fields"), dict) else {}
        candidates = [node_id, str(node.get("label") or ""), str(node.get("kind") or "")]
        for key in ("name", "symbol", "path", "file", "field_ref", "struct_ref", "operation_ref", "buffer_ref", "event_identifier"):
            value = fields.get(key)
            if isinstance(value, str):
                candidates.append(value)
        aliases = fields.get("aliases")
        if isinstance(aliases, list):
            candidates.extend(str(alias) for alias in aliases if alias)
        for value in candidates:
            for term in _term_variants(value):
                terms.setdefault(term, {"nodes": []})["nodes"].append(node_id)
    for value in terms.values():
        value["nodes"] = sorted(set(value["nodes"]))
    return dict(sorted(terms.items()))


def _term_variants(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    lowered = text.lower()
    compact = "".join(ch for ch in lowered if ch.isalnum())
    parts = [part for part in fnmatch.re.split(r"[^A-Za-z0-9]+", text) if part] if False else []
    variants = {lowered, compact}
    camel = "".join(ch if ch.isalnum() else " " for ch in text).split()
    if len(camel) > 1:
        variants.add("".join(part[0].lower() for part in camel if part))
    return sorted(item for item in variants if item)


def _kind_matches(actual: str, expected: str) -> bool:
    if expected == "any" or actual == expected:
        return True
    aliases = {
        "argument": {"input_tensor", "output_tensor", "optional_input", "attribute"},
        "variable": {"variable", "runtime_variable", "host_variable", "tilingdata", "key"},
        "symbol": {"symbol", "host_entry", "tiling_entry", "kernel_entry", "function", "call"},
        "expression": {"expression"},
        "branch": {"branch"},
        "outcome": {"outcome"},
        "loop": {"loop"},
        "call": {"call"},
        "key": {"key"},
        "tilingdata": {"tilingdata"},
        "tensor": {"tensor", "input_tensor", "output_tensor"},
        "operation": {"operation"},
        "api": {"api", "call"},
        "sync": {"sync"},
        "source_file": {"source_file", "dependency_file"},
        "memory_resource": {"memory_resource"},
    }
    return actual in aliases.get(expected, set())


def _normalize_kind(kind: str) -> str:
    lowered = kind.lower()
    if lowered.startswith(("input_", "output_")):
        return lowered
    if "outcome" in lowered:
        return "outcome"
    for token, normalized in (
        ("tensor", "tensor"),
        ("operation", "operation"),
        ("resource", "memory_resource"),
        ("source_file", "source_file"),
        ("dependency_file", "source_file"),
        ("branch", "branch"),
        ("loop", "loop"),
        ("call", "call"),
        ("api", "api"),
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
    snapshot = _snapshot_from_manifest(payload.pop("_uo_root", None))
    return {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": "raw-graph-compiler"},
        "snapshot": snapshot,
        **payload,
        "items": [],
        "relations": [],
        "unresolved": [],
    }


def _snapshot_from_manifest(uo_root: Any) -> dict[str, str]:
    if isinstance(uo_root, Path):
        data = _read_yaml(uo_root / "manifest.yaml")
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        return {
            "run_id": str(data.get("current_run_id") or "UO_RUN_UNKNOWN"),
            "source_snapshot_id": str(source.get("snapshot_id") or "SOURCE_UNKNOWN"),
            "source_revision": str(source.get("revision") or "unknown"),
            "spec_bundle_hash": str((data.get("spec") or {}).get("bundle_hash") or spec_bundle_hash()),
        }
    return {"run_id": "UO_RUN_UNKNOWN", "source_snapshot_id": "SOURCE_UNKNOWN", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


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
