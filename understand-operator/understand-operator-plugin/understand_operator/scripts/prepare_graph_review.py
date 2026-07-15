from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name, write_text
from understand_operator._operator.spec import spec_bundle_hash


def prepare_graph_review(repo_root: Path, op_name: str) -> tuple[int, dict[str, Any]]:
    root = existing_operator_root(repo_root.resolve(), safe_op_name(op_name, repo_root))
    raw_nodes = _list(root / "graphs/raw/nodes.yaml", "nodes")
    raw_edges = _list(root / "graphs/raw/edges.yaml", "edges")
    raw_paths = _list(root / "graphs/raw/paths.yaml", "paths")
    derived_nodes = _list(root / "graphs/derived/nodes.yaml", "nodes")
    derived_edges = _list(root / "graphs/derived/edges.yaml", "edges")
    completeness = _read(root / "checks/completeness.yaml")
    raw_hash = _tree_hash(root / "graphs/raw")
    derived_hash = _tree_hash(root / "graphs/derived")
    payload = {
        "version": 1,
        "artifact": {"type": "checks.graph_review_trigger", "schema_version": 1, "owner": "facts-validator"},
        "snapshot": _snapshot(root),
        "status": "ready",
        "input_hashes": {"graphs/raw": raw_hash, "graphs/derived": derived_hash, "checks/completeness.yaml": _file_hash(root / "checks/completeness.yaml")},
        "counts": {
            "raw_nodes": len(raw_nodes),
            "raw_edges": len(raw_edges),
            "raw_paths": len(raw_paths),
            "derived_nodes": len(derived_nodes),
            "derived_edges": len(derived_edges),
        },
        "kind_counts": {"raw": dict(Counter(str(n.get("kind") or "") for n in raw_nodes)), "derived": dict(Counter(str(n.get("kind") or n.get("type") or "") for n in derived_nodes))},
        "type_counts": {"raw_edges": dict(Counter(str(e.get("type") or "") for e in raw_edges)), "derived_edges": dict(Counter(str(e.get("type") or "") for e in derived_edges))},
        "top_degree_nodes": _top_degree(raw_edges + derived_edges),
        "path_summary": {"total": len(raw_paths), "truncated": sum(1 for p in raw_paths if p.get("truncated") or p.get("depth_limited")), "cycles": sum(1 for p in raw_paths if p.get("cycle"))},
        "orphan_summary": _orphan_summary(raw_nodes + derived_nodes, raw_edges + derived_edges),
        "cross_layer_edge_summary": dict(Counter(str(e.get("type") or "") for e in raw_edges if str(e.get("id") or "").startswith("REL_AUTO_"))),
        "samples": {"raw_nodes": _sample(raw_nodes), "raw_edges": _sample(raw_edges), "derived_nodes": _sample(derived_nodes), "derived_edges": _sample(derived_edges)},
        "high_risk_detail_refs": sorted({str(item.get("detail_ref")) for item in raw_nodes + raw_edges if item.get("detail_ref")})[:30],
        "completeness_summary": {"status": completeness.get("status"), "blocking_count": len(completeness.get("blocking_findings") or [])},
        "deterministic_verifier_status": {"raw": _status(root / "checks/raw_validation.yaml"), "derived": _status(root / "checks/derived_validation.yaml")},
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    write_text(root / "checks/graph_review_trigger.yaml", yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    return 0, payload


def _sample(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("id", "kind", "type", "label", "detail_ref", "source_id", "target_id", "raw_node_refs", "raw_edge_refs", "yaml_refs")
    return [{key: item[key] for key in keys if key in item} for item in items[:10]]


def _top_degree(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for edge in edges:
        for key in ("source_id", "target_id"):
            if edge.get(key):
                counts[str(edge[key])] += 1
    return [{"id": key, "degree": value} for key, value in counts.most_common(20)]


def _orphan_summary(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, int]:
    node_ids = {str(n.get("id")) for n in nodes if n.get("id")}
    linked = {str(e.get("source_id")) for e in edges if e.get("source_id")} | {str(e.get("target_id")) for e in edges if e.get("target_id")}
    return {"node_count": len(node_ids), "orphan_count": len(node_ids - linked), "dangling_edge_count": sum(1 for e in edges if str(e.get("source_id")) not in node_ids or str(e.get("target_id")) not in node_ids)}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _list(path: Path, key: str) -> list[dict[str, Any]]:
    data = _read(path)
    values = data.get(key)
    return [v for v in values if isinstance(v, dict)] if isinstance(values, list) else []


def _status(path: Path) -> str:
    data = _read(path)
    return str(data.get("status") or ("missing" if not path.exists() else "unknown"))


def _file_hash(path: Path) -> str:
    return "missing" if not path.exists() else "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.yaml")) if folder.exists() else []:
        digest.update(path.relative_to(folder).as_posix().encode("utf-8")); digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _snapshot(root: Path) -> dict[str, str]:
    manifest = _read(root / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {"run_id": str(manifest.get("current_run_id") or ""), "source_snapshot_id": str(source.get("snapshot_id") or ""), "source_revision": str(source.get("revision") or "unknown"), "spec_bundle_hash": spec_bundle_hash()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    args = parser.parse_args(argv)
    code, payload = prepare_graph_review(Path(args.repo), args.op_name)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
