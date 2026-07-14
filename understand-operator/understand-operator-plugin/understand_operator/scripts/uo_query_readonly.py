from __future__ import annotations

import argparse
import json
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


def query_readonly(repo_root: Path, op_name: str, entity: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    repo_root = repo_root.resolve()
    resolved = resolve_existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if resolved is None:
        raise FileNotFoundError(f"operator KB root not found via manifest/aliases for {op_name}")
    _resolved_name, uo_root = resolved
    derived = _query_derived(uo_root, entity)
    raw_ids = set(derived.get("raw_node_refs") or []) | set(derived.get("raw_edge_refs") or [])
    raw = _query_raw(uo_root, entity, raw_ids)
    yaml_refs = set(derived.get("yaml_refs") or []) | set(raw.get("yaml_refs") or [])
    yaml_items = [_read_yaml_ref(uo_root, ref) for ref in sorted(yaml_refs)]
    source_refs = _source_refs_from_yaml_items(yaml_items)
    return {
        "query": {"entity": entity, "mode": "readonly", "order": ["derived", "raw", "yaml", "source"]},
        "derived": derived,
        "raw": raw,
        "yaml_items": yaml_items,
        "source_refs": source_refs,
        "writes": [],
        "cbm_writes": [],
    }


def _query_derived(uo_root: Path, entity: str) -> dict[str, Any]:
    nodes = _load_list(uo_root / "graphs" / "derived" / "nodes.yaml", "nodes")
    edges = _load_list(uo_root / "graphs" / "derived" / "edges.yaml", "edges")
    expansions = _load_list(uo_root / "graphs" / "derived" / "expansions.yaml", "expansions")
    selected_nodes = [node for node in nodes if entity in {str(node.get("id")), str(node.get("label"))}]
    selected_edges = [edge for edge in edges if entity in {str(edge.get("id")), str(edge.get("source_id")), str(edge.get("target_id"))}]
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
    selected_nodes = [node for node in nodes if str(node.get("id")) == entity or str(node.get("id")) in raw_ids]
    selected_edges = [
        edge
        for edge in edges
        if str(edge.get("id")) == entity
        or str(edge.get("id")) in raw_ids
        or str(edge.get("source_id")) == entity
        or str(edge.get("target_id")) == entity
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only UO query: Derived Graph -> Raw Graph -> YAML -> source anchors.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--entity", required=True)
    args = parser.parse_args(argv)
    try:
        payload = query_readonly(Path(args.repo), args.op_name, args.entity)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
