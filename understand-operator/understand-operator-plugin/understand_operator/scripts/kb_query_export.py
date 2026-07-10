from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML optional at runtime
    yaml = None  # type: ignore[assignment]

from understand_operator._operator.artifacts import operator_root, read_text, safe_op_name
from understand_operator._operator.kb_compiler import build_entity_index

EXPORT_VIEWS: dict[str, list[str]] = {
    "tiling-test": [
        "tiling/variables.yaml",
        "tiling/key_space.yaml",
        "tiling/constraints.yaml",
        "tiling/families.yaml",
        "tiling/data_model.yaml",
        "tiling/coverage_model.yaml",
        "quality.yaml",
    ],
    "golden-gen": [
        "operator.yaml",
        "tiling/data_model.yaml",
        "flow/compute_graph.yaml",
        "flow/dataflow.yaml",
        "flow/golden_model.yaml",
        "flow/numerical_model.yaml",
        "evidence/fact_index.yaml",
        "quality.yaml",
    ],
    "testgenerate": [
        "operator.yaml",
        "tiling/variables.yaml",
        "tiling/key_space.yaml",
        "tiling/constraints.yaml",
        "tiling/families.yaml",
        "tiling/data_model.yaml",
        "tiling/coverage_model.yaml",
        "flow/compute_graph.yaml",
        "flow/dataflow.yaml",
        "flow/golden_model.yaml",
        "flow/numerical_model.yaml",
        "kernel/paths.yaml",
        "kernel/pipeline.yaml",
        "kernel/resources.yaml",
        "test/contract.yaml",
        "quality.yaml",
        "evidence/issues.yaml",
    ],
    "kernel-debug": [
        "kernel/paths.yaml",
        "kernel/pipeline.yaml",
        "kernel/resources.yaml",
        "flow/compute_graph.yaml",
        "flow/dataflow.yaml",
        "evidence/fact_index.yaml",
        "evidence/source_index.yaml",
    ],
    "human": [
        "route.md",
        "human/review.md",
        "quality.yaml",
        "evidence/issues.yaml",
    ],
    "query": [
        "query/routes.yaml",
        "contracts/query.yaml",
        "registry/variables.yaml",
        "cross_layer/variable_lineage.yaml",
        "quality.yaml",
    ],
    "code-change": [
        "contracts/code_change.yaml",
        "cross_layer/impact_graph.yaml",
        "registry/symbols.yaml",
        "registry/variables.yaml",
        "evidence/artifact_dependencies.yaml",
        "quality.yaml",
    ],
    "pr-review": [
        "contracts/pr_review.yaml",
        "cross_layer/impact_graph.yaml",
        "evidence/issues.yaml",
        "quality.yaml",
    ],
    "testcase-contract": [
        "contracts/testcase.yaml",
        "test/contract.yaml",
        "tiling/coverage_model.yaml",
        "kernel/branches.yaml",
        "cross_layer/impact_graph.yaml",
        "quality.yaml",
    ],
}

CONTEXT_VIEWS = {
    "operator-understanding",
    "variable-trace",
    "tiling-field-trace",
    "tilingdata-trace",
    "kernel-path-trace",
    "code-change-impact",
    "pr-review",
    "testcase-contract",
    "evidence-conflict",
}
ENTITY_REQUIRED_VIEWS = {
    "variable-trace",
    "tiling-field-trace",
    "tilingdata-trace",
    "kernel-path-trace",
    "code-change-impact",
}
DETAIL_LIMITS = {
    "summary": {"entities": 20, "relations": 20, "evidence": 10},
    "normal": {"entities": 80, "relations": 80, "evidence": 30},
    "full": {"entities": 10_000, "relations": 10_000, "evidence": 10_000},
}

LEGACY_MARKERS = [
    "summary/operator_io.yaml",
    "summary/operator_manifest.yaml",
    "flows/compute_flow.yaml",
    "testing_hints/golden_hint.yaml",
    "route.json",
    "quality_gate.yaml",
    "tiling/tiling_branch_families.yaml",
    "kernel/kernel_task_plan.yaml",
]


def _parse_yaml(text: str, path: Path) -> Any:
    if not text.strip():
        raise ValueError(f"{path.as_posix()} is empty")
    if yaml is None:
        raise RuntimeError("PyYAML is required for yaml parsing; install with: pip install pyyaml")
    data = yaml.safe_load(text)
    if data is None:
        raise ValueError(f"{path.as_posix()} parsed to null")
    return data


def _load_file(uo_root: Path, rel: str) -> Any:
    path = uo_root / rel
    if not path.exists():
        raise FileNotFoundError(rel)
    text = read_text(path)
    if rel.endswith((".yaml", ".yml")):
        return _parse_yaml(text, path)
    return text


def _legacy_hint(uo_root: Path, missing: list[str]) -> str:
    has_legacy = any((uo_root / marker).exists() for marker in LEGACY_MARKERS)
    if has_legacy:
        return (
            " This KB uses legacy artifacts. Run /uo-update or /uo-init to regenerate canonical KB files."
        )
    if missing:
        return " Run /uo-init or /uo-update for this operator first."
    return ""


def export_view(uo_root: Path, op_name: str, view: str) -> dict[str, Any]:
    if view not in EXPORT_VIEWS:
        raise ValueError(f"Unsupported view: {view}")

    # Never read archive/ by default
    required = EXPORT_VIEWS[view]
    missing = [rel for rel in required if not (uo_root / rel).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing canonical files for view '{view}': {', '.join(missing)}."
            + _legacy_hint(uo_root, missing)
        )

    files: dict[str, Any] = {}
    for rel in required:
        files[rel] = _load_file(uo_root, rel)

    return {
        "op_name": op_name,
        "uo_root": uo_root.as_posix(),
        "view": view,
        "files": files,
    }


def export_context_slice(
    uo_root: Path,
    op_name: str,
    view: str,
    entity: str | None = None,
    *,
    detail_level: str = "summary",
) -> dict[str, Any]:
    if detail_level not in DETAIL_LIMITS:
        raise ValueError(f"Unsupported detail level: {detail_level}")
    if view in ENTITY_REQUIRED_VIEWS and not entity:
        raise ValueError(json.dumps({"status": "error", "code": "ENTITY_REQUIRED", "view": view}, ensure_ascii=False))
    docs = _load_context_docs(uo_root)
    entity_index = build_entity_index(docs)
    graph = _load_graph(docs, "cross_layer/behavior_graph.yaml")
    impact = _load_graph(docs, "cross_layer/impact_graph.yaml")
    selected = set[str]()

    if entity:
        if entity not in entity_index:
            suggestions = _entity_suggestions(entity, entity_index)
            raise ValueError(
                json.dumps(
                    {"status": "error", "code": "ENTITY_NOT_FOUND", "view": view, "entity": entity, "suggestions": suggestions},
                    ensure_ascii=False,
                )
            )
        selected.add(entity)
        selected.update(_neighbors(entity, graph, direction="both", depth=2))
        if view in {"code-change-impact", "pr-review"}:
            selected.update(_neighbors(entity, impact, direction="downstream", depth=4))
    elif view == "operator-understanding":
        if detail_level == "summary":
            selected.update(_ids_by_kind(entity_index, {"symbol", "variable", "family"}))
        elif detail_level == "normal":
            selected.update(_ids_by_kind(entity_index, {"symbol", "variable", "key", "family", "kernel_path"}))
        else:
            selected.update(entity_index.keys())
    elif view == "testcase-contract":
        selected.update(_ids_by_kind(entity_index, {"key", "family", "template_binding", "kernel_branch", "compute_step"}))
    elif view == "evidence-conflict":
        selected.update(_ids_by_kind(entity_index, {"evidence", "relation"}))
    else:
        selected.update(_ids_by_kind(entity_index, {"evidence", "relation"}))

    entities = [entity_index[eid] for eid in sorted(selected) if eid in entity_index]
    relations = _filter_edges(graph.get("edges", []) + impact.get("edges", []) + impact.get("impacts", []), selected)
    upstream = _filter_edges(graph.get("edges", []), selected, incoming=True)
    downstream = _filter_edges(graph.get("edges", []) + impact.get("impacts", []), selected, outgoing=True)
    evidence = _collect_evidence(docs, entities, relations)
    unresolved, conflicts = _collect_unresolved_conflicts(docs)
    entities, entity_omitted = _limit_list(entities, DETAIL_LIMITS[detail_level]["entities"])
    relations, relation_omitted = _limit_list(relations, DETAIL_LIMITS[detail_level]["relations"])
    upstream, _ = _limit_list(upstream, DETAIL_LIMITS[detail_level]["relations"])
    downstream, _ = _limit_list(downstream, DETAIL_LIMITS[detail_level]["relations"])
    evidence, evidence_omitted = _limit_list(evidence, DETAIL_LIMITS[detail_level]["evidence"])

    return {
        "query": {
            "intent": view,
            "entity_id": entity,
            "kb_first": True,
            "archive_read": False,
            "detail_level": detail_level,
        },
        "entities": entities,
        "relations": relations,
        "upstream": upstream,
        "downstream": downstream,
        "paths": _paths_for_entities(docs, selected),
        "evidence": evidence,
        "unresolved": unresolved,
        "conflicts": conflicts,
        "source_artifacts": sorted(_source_artifacts(entities, relations)),
        "truncated": any((entity_omitted, relation_omitted, evidence_omitted)),
        "omitted_counts": {
            "entities": entity_omitted,
            "relations": relation_omitted,
            "evidence": evidence_omitted,
        },
    }


def _entity_suggestions(entity: str, entity_index: dict[str, Any]) -> list[str]:
    needle = entity.lower()
    candidates: list[str] = []
    for eid, meta in sorted(entity_index.items()):
        names = [eid, str(meta.get("canonical_name") or ""), *(str(alias) for alias in meta.get("aliases") or [])]
        if any(needle in name.lower() or name.lower() in needle for name in names if name):
            candidates.append(eid)
    return candidates[:5]


def _limit_list(items: list[Any], limit: int) -> tuple[list[Any], int]:
    if len(items) <= limit:
        return items, 0
    return items[:limit], len(items) - limit


def _load_context_docs(uo_root: Path) -> dict[str, Any]:
    rels = set(
        [
            "registry/symbols.yaml",
            "registry/variables.yaml",
            "registry/aliases.yaml",
            "registry/evidence.yaml",
            "cross_layer/variable_lineage.yaml",
            "cross_layer/behavior_graph.yaml",
            "cross_layer/impact_graph.yaml",
            "cross_layer/input_to_tiling.yaml",
            "cross_layer/tiling_to_kernel.yaml",
            "contracts/query.yaml",
            "contracts/code_change.yaml",
            "contracts/pr_review.yaml",
            "contracts/testcase.yaml",
            "kernel/paths.yaml",
            "kernel/branches.yaml",
            "tiling/key_space.yaml",
            "tiling/families.yaml",
            "tiling/data_model.yaml",
            "flow/compute_graph.yaml",
            "evidence/issues.yaml",
        ]
    )
    docs: dict[str, Any] = {}
    for rel in sorted(rels):
        path = uo_root / rel
        if path.exists():
            try:
                docs[rel] = _load_file(uo_root, rel)
            except Exception:  # noqa: BLE001
                docs[rel] = {}
    return docs


def _load_graph(docs: dict[str, Any], rel: str) -> dict[str, Any]:
    data = docs.get(rel)
    return data if isinstance(data, dict) else {}


def _neighbors(entity: str, graph: dict[str, Any], *, direction: str, depth: int) -> set[str]:
    edges = graph.get("edges") or graph.get("impacts") or []
    adjacency: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    for edge in edges if isinstance(edges, list) else []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("source_id") or edge.get("source") or "")
        dst = str(edge.get("target_id") or edge.get("target") or "")
        if not src or not dst:
            continue
        adjacency.setdefault(src, set()).add(dst)
        reverse.setdefault(dst, set()).add(src)
    result: set[str] = set()
    frontier = {entity}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for node in frontier:
            if direction in {"both", "downstream"}:
                next_frontier.update(adjacency.get(node, set()))
            if direction in {"both", "upstream"}:
                next_frontier.update(reverse.get(node, set()))
        next_frontier -= result
        result.update(next_frontier)
        frontier = next_frontier
    return result


def _ids_by_kind(entity_index: dict[str, Any], kinds: set[str]) -> set[str]:
    return {eid for eid, meta in entity_index.items() if meta.get("kind") in kinds}


def _filter_edges(edges: Any, selected: set[str], *, incoming: bool = False, outgoing: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for edge in edges if isinstance(edges, list) else []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("source_id") or edge.get("source") or "")
        dst = str(edge.get("target_id") or edge.get("target") or "")
        if incoming and dst in selected:
            out.append(edge)
        elif outgoing and src in selected:
            out.append(edge)
        elif not incoming and not outgoing and (src in selected or dst in selected):
            out.append(edge)
    return out


def _collect_evidence(docs: dict[str, Any], entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = {ref for item in entities + relations for ref in (item.get("evidence_refs") or [])}
    evidence_entries = docs.get("registry/evidence.yaml", {})
    evidence = evidence_entries.get("evidence") if isinstance(evidence_entries, dict) else []
    return [item for item in evidence if isinstance(item, dict) and item.get("id") in refs]


def _collect_unresolved_conflicts(docs: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    unresolved: list[Any] = []
    conflicts: list[Any] = []
    for rel, data in docs.items():
        if not isinstance(data, dict):
            continue
        for item in data.get("unresolved") or data.get("unknowns") or []:
            unresolved.append({"artifact": rel, "item": item})
        for item in data.get("conflicts") or []:
            conflicts.append({"artifact": rel, "item": item})
    issues = docs.get("evidence/issues.yaml")
    if isinstance(issues, dict):
        conflicts.extend({"artifact": "evidence/issues.yaml", "item": item} for item in issues.get("conflicts") or [])
        unresolved.extend({"artifact": "evidence/issues.yaml", "item": item} for item in issues.get("unknowns") or [])
    return unresolved, conflicts


def _paths_for_entities(docs: dict[str, Any], selected: set[str]) -> list[dict[str, Any]]:
    paths = docs.get("kernel/paths.yaml", {})
    items = paths.get("kernel_paths") if isinstance(paths, dict) else []
    out = []
    for item in items.values() if isinstance(items, dict) else items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        blob = json.dumps(item, ensure_ascii=False)
        if any(eid in blob for eid in selected):
            out.append(item)
    return out


def _source_artifacts(entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> set[str]:
    out = set()
    for item in entities + relations:
        artifact = item.get("artifact")
        if artifact:
            out.add(str(artifact))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export canonical operator KB views (no source reads, no CBM, no archive)."
    )
    parser.add_argument("repo_root", type=Path, help="AscendC operator repository root")
    parser.add_argument("--op-name", required=True, help="Operator name")
    parser.add_argument(
        "--view",
        choices=sorted(set(EXPORT_VIEWS) | CONTEXT_VIEWS),
        default="tiling-test",
        help="Export view",
    )
    parser.add_argument("--entity", help="Stable entity id for focused context-slice views")
    parser.add_argument(
        "--detail-level",
        choices=sorted(DETAIL_LIMITS),
        default="summary",
        help="Context slice size for operator-understanding and other context views",
    )
    parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="json",
        help="Output format (default: json)",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = operator_root(repo_root, op_name)

    try:
        if args.view in CONTEXT_VIEWS:
            payload = export_context_slice(uo_root, op_name, args.view, args.entity, detail_level=args.detail_level)
        else:
            payload = export_view(uo_root, op_name, args.view)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if yaml is None:
            print(
                "PyYAML is required for yaml output; use --format json or pip install pyyaml",
                file=sys.stderr,
            )
            return 1
        print(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
