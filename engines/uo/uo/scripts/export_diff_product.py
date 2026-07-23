from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml, stable_id

KB_REFS = {
    "testcase_contract": "tiling/coverage_model.yaml",
    "operator_graph": "ir/operator_graph.yaml",
    "tiling_constraints": "tiling/constraints.yaml",
    "kernel_branches": "kernel/branches.yaml",
    "impact_graph": "cross_layer/impact_graph.yaml",
}


def export_diff_product(
    repo_root: Path,
    op_name: str,
    *,
    change_set: dict[str, Any] | None = None,
    update_plan: dict[str, Any] | None = None,
    status: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    change_set = change_set or read_yaml(uo_root / "diff" / "change_set.yaml") or read_yaml(uo_root / "summary" / "change_set.yaml")
    update_plan = update_plan or read_yaml(uo_root / "summary" / "update_plan.yaml")
    if not change_set:
        raise FileNotFoundError("change_set.yaml missing")
    if not update_plan:
        raise FileNotFoundError("update_plan.yaml missing")

    graph = read_yaml(uo_root / "ir" / "operator_graph.yaml")
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    branches = [b for b in (graph.get("kernel_branches") or []) if isinstance(b, dict)]

    changed_paths = {
        str(item.get("path") or "").replace("\\", "/")
        for item in (change_set.get("files") or [])
        if isinstance(item, dict) and item.get("in_scope")
    }

    entities = {
        "families": [],
        "kernel_paths": [],
        "branches": [],
        "variables": [],
        "tiling_key_fields": [],
    }
    coverage_hints: list[dict[str, Any]] = []
    unresolved_items: list[dict[str, Any]] = []
    matched_files: set[str] = set()
    graph_node_ids: list[str] = []

    for node in nodes:
        fpath = str(node.get("file_path") or "").replace("\\", "/")
        if not fpath or not _path_matches(fpath, changed_paths):
            continue
        matched_files.add(_match_changed(fpath, changed_paths) or fpath)
        nid = str(node.get("id") or "")
        if nid:
            graph_node_ids.append(nid)
        _classify_entity(node, entities)
        hint = _hint_from_node(node, fpath)
        if hint:
            coverage_hints.append(hint)

    for branch in branches:
        fpath = str(branch.get("file_path") or "").replace("\\", "/")
        if fpath and _path_matches(fpath, changed_paths):
            bid = str(branch.get("id") or "")
            if bid and bid not in entities["branches"]:
                entities["branches"].append(bid)
            coverage_hints.append(
                {
                    "kind": "kernel_branch",
                    "entity_ref": bid,
                    "reason": "predicate_in_changed_file",
                    "confidence": "high",
                    "evidence": {"files": [fpath], "graph_node_ids": [bid] if bid else []},
                }
            )
            matched_files.add(_match_changed(fpath, changed_paths) or fpath)

    # Dedup entity lists
    for key in entities:
        entities[key] = sorted(dict.fromkeys(entities[key]))

    affected_layers = list(update_plan.get("affected_layers") or [])
    primary_layers = {"host", "kernel", "tilingkey", "golden"}
    for layer in affected_layers:
        if layer not in primary_layers:
            continue
        layer_files = [
            str(f.get("path"))
            for f in (change_set.get("files") or [])
            if isinstance(f, dict) and f.get("in_scope") and _role_to_layer(str(f.get("role") or "")) == layer
        ]
        if not layer_files:
            continue
        has_entity_hint = any(
            h.get("confidence") in {"high", "medium"} and layer in _hint_layers(h) for h in coverage_hints
        )
        if has_entity_hint or _layer_has_entities(layer, entities):
            continue
        coverage_hints.append(
            {
                "kind": "layer_only",
                "layer": layer,
                "reason": "file_changed_entity_unresolved",
                "confidence": "low",
                "kb_lookup": _kb_lookup_for_layer(layer),
                "evidence": {"files": layer_files[:20], "graph_node_ids": []},
            }
        )
        unresolved_items.append(
            {
                "id": stable_id("DIFF_UNRES_", layer),
                "kind": "entity_not_resolved",
                "message": f"变更命中 {layer} 层，但未能绑定到具体稳定实体 ID",
                "files": layer_files[:20],
                "kb_lookup": _kb_lookup_for_layer(layer),
            }
        )

    # Files in scope with zero node matches
    unmatched = sorted(changed_paths - matched_files)
    for path in unmatched:
        role = next(
            (str(f.get("role") or "") for f in (change_set.get("files") or []) if str(f.get("path")) == path),
            "",
        )
        layer = _role_to_layer(role) or "host"
        if not any(item.get("files") and path in item.get("files", []) for item in unresolved_items):
            unresolved_items.append(
                {
                    "id": stable_id("DIFF_UNRES_FILE_", path),
                    "kind": "entity_not_resolved",
                    "message": f"变更文件未绑定到 graph 节点: {path}",
                    "files": [path],
                    "kb_lookup": _kb_lookup_for_layer(layer),
                }
            )

    plan_mode = str(update_plan.get("mode") or "")
    blocked = plan_mode == "blocked_scope" or bool(update_plan.get("needs_scope_review") and not changed_paths)
    if status is None:
        status = "blocked" if blocked or plan_mode == "blocked_scope" else "ready"

    impact = {
        "version": 1,
        "op_name": op_name,
        "base_revision": change_set.get("base_revision"),
        "head_revision": change_set.get("head_revision"),
        "affected_layers": affected_layers,
        "affected_entities": entities,
        "coverage_hints": coverage_hints,
        "recommended_test_level": "L1",
    }
    unresolved_doc = {"version": 1, "op_name": op_name, "items": unresolved_items}
    index = {
        "version": 1,
        "kind": "uo_diff_product",
        "op_name": op_name,
        "base_revision": change_set.get("base_revision"),
        "head_revision": change_set.get("head_revision"),
        "kb_root": ".ascendc-agent/uo/",
        "status": status,
        "files": {
            "change_set": "diff/change_set.yaml",
            "impact": "diff/impact.yaml",
            "unresolved": "diff/unresolved.yaml",
        },
        "kb_refs": dict(KB_REFS),
        "update_mode": plan_mode,
    }

    if write:
        diff_dir = uo_root / "diff"
        diff_dir.mkdir(parents=True, exist_ok=True)
        # Preserve / refresh change_set in diff/
        write_yaml(diff_dir / "change_set.yaml", change_set)
        write_yaml(diff_dir / "impact.yaml", impact)
        write_yaml(diff_dir / "unresolved.yaml", unresolved_doc)
        write_yaml(diff_dir / "index.yaml", index)

    return {"index": index, "impact": impact, "unresolved": unresolved_doc, "change_set": change_set}


def _path_matches(file_path: str, changed: set[str]) -> bool:
    return _match_changed(file_path, changed) is not None


def _match_changed(file_path: str, changed: set[str]) -> str | None:
    fp = file_path.replace("\\", "/")
    if fp in changed:
        return fp
    for item in changed:
        if fp.endswith(item) or item.endswith(fp) or fp.endswith("/" + item) or item.endswith("/" + fp):
            return item
    return None


def _classify_entity(node: dict[str, Any], entities: dict[str, list[str]]) -> None:
    nid = str(node.get("id") or "")
    ntype = str(node.get("node_type") or "")
    if not nid:
        return
    if nid.startswith("FAM_") or ntype in {"Family", "TilingFamily"}:
        entities["families"].append(nid if nid.startswith("FAM_") else stable_id("FAM_", nid))
    elif nid.startswith("KPATH_") or ntype in {"KernelPath", "KernelEntry"}:
        entities["kernel_paths"].append(nid if nid.startswith("KPATH_") else nid)
    elif nid.startswith("KBR_") or ntype in {"KernelBranch", "Branch"}:
        entities["branches"].append(nid if nid.startswith("KBR_") else nid)
    elif nid.startswith("VAR_") or ntype in {"Attribute", "RuntimeVariable", "OptionalInputPresence"}:
        entities["variables"].append(nid if nid.startswith("VAR_") else stable_id("VAR_", nid))
    elif nid.startswith("KEY_") or ntype in {"TilingKeyField", "TilingKeyDim"}:
        entities["tiling_key_fields"].append(nid if nid.startswith("KEY_") else nid)
    elif ntype == "TilingKey":
        # dimension-level IDs may live on tilingkey space; keep node id as soft ref via variables skip
        pass


def _hint_from_node(node: dict[str, Any], fpath: str) -> dict[str, Any] | None:
    nid = str(node.get("id") or "")
    ntype = str(node.get("node_type") or "")
    if not nid:
        return None
    if ntype in {"KernelBranch", "Branch"} or nid.startswith("KBR_"):
        return {
            "kind": "kernel_branch",
            "entity_ref": nid,
            "reason": "predicate_in_changed_file",
            "confidence": "high",
            "evidence": {"files": [fpath], "graph_node_ids": [nid]},
        }
    if ntype in {"Attribute", "RuntimeVariable"} or nid.startswith("VAR_"):
        return {
            "kind": "runtime_variable",
            "entity_ref": nid if nid.startswith("VAR_") else stable_id("VAR_", nid),
            "reason": "variable_in_changed_file",
            "confidence": "medium",
            "evidence": {"files": [fpath], "graph_node_ids": [nid]},
        }
    if ntype in {"TilingKeyField", "TilingKeyDim"} or nid.startswith("KEY_"):
        return {
            "kind": "tiling_key_field",
            "entity_ref": nid,
            "reason": "key_field_in_changed_file",
            "confidence": "high",
            "evidence": {"files": [fpath], "graph_node_ids": [nid]},
        }
    return {
        "kind": "graph_node",
        "entity_ref": nid,
        "reason": "node_in_changed_file",
        "confidence": "medium",
        "evidence": {"files": [fpath], "graph_node_ids": [nid]},
    }


def _role_to_layer(role: str) -> str:
    role = role.lower()
    if role in {"host", "tiling", "api"}:
        return "host"
    if role == "kernel":
        return "kernel"
    if role == "tilingkey":
        return "tilingkey"
    if role == "golden":
        return "golden"
    if role in {"common", "headers"}:
        return "bridge"
    return ""


def _layer_has_entities(layer: str, entities: dict[str, list[str]]) -> bool:
    if layer == "host":
        return bool(entities["variables"] or entities["families"])
    if layer == "kernel":
        return bool(entities["branches"] or entities["kernel_paths"])
    if layer == "tilingkey":
        return bool(entities["tiling_key_fields"])
    return False


def _hint_layers(hint: dict[str, Any]) -> set[str]:
    kind = str(hint.get("kind") or "")
    if kind == "layer_only":
        return {str(hint.get("layer") or "")}
    if kind == "kernel_branch":
        return {"kernel"}
    if kind in {"runtime_variable", "graph_node"}:
        return {"host", "kernel"}
    if kind == "tiling_key_field":
        return {"tilingkey"}
    return set()


def _kb_lookup_for_layer(layer: str) -> list[str]:
    mapping = {
        "host": ["tiling/coverage_model.yaml", "ir/host_subgraph.yaml", "ir/operator_graph.yaml"],
        "kernel": ["kernel/branches.yaml", "ir/kernel_subgraph.yaml", "tiling/key_space.yaml"],
        "tilingkey": ["tiling/constraints.yaml", "ir/tilingkey_space.yaml", "tiling/key_space.yaml"],
        "golden": ["flow/golden_model.yaml", "ir/golden.yaml"],
        "bridge": ["ir/bridge.yaml", "cross_layer/impact_graph.yaml", "tiling/key_space.yaml"],
        "entrypoints": ["ir/entrypoints.yaml", "ir/operator_graph.yaml"],
    }
    return mapping.get(layer, ["ir/operator_graph.yaml", "tiling/key_space.yaml"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export dedicated diff/ product for PR test generation")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--status", choices=["ready", "blocked"], default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    result = export_diff_product(repo_root, op_name, status=args.status, write=not args.no_write)
    index = result["index"]
    impact = result["impact"]
    print(
        f"diff_product status={index['status']} layers={impact['affected_layers']} "
        f"hints={len(impact['coverage_hints'])} unresolved={len(result['unresolved']['items'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
