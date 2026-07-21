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
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.extract_golden import extract_golden
from uo.scripts.extract_host_subgraph import extract_host_subgraph
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.extract_plan_io import load_extract_plan
from uo.scripts.extract_tilingkey_space import extract_tilingkey_space
from uo.scripts.reconcile_bridge import reconcile_bridge
from uo.scripts.resolve_entrypoints import apply_entrypoint_confirmation, collect_entrypoint_candidates


ALL_EXTRACT_LAYERS = ("entrypoints", "host", "kernel", "tilingkey", "golden", "bridge")


def build_layered_kb(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    confirmation_patch: dict[str, Any] | None = None,
    auto_confirm: bool = True,
    layers: set[str] | list[str] | None = None,
    allow_empty_plan: bool = False,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    ir_dir = uo_root / "ir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    selected = set(ALL_EXTRACT_LAYERS) if not layers else {str(item).strip().lower() for item in layers if str(item).strip()}
    if selected & {"host", "kernel", "tilingkey"}:
        selected.add("bridge")

    # entrypoints
    if "entrypoints" in selected:
        candidates = collect_entrypoint_candidates(
            repo_root, op_name, architecture=architecture, auto_confirm_high_confidence=auto_confirm
        )
        write_yaml(ir_dir / "entrypoint_candidates.yaml", candidates)
        if confirmation_patch:
            entrypoints = apply_entrypoint_confirmation(candidates, confirmation_patch)
        else:
            entrypoints = apply_entrypoint_confirmation(candidates, {"roles": {}})
            for role, body in candidates.get("roles", {}).items():
                entrypoints["roles"][role] = {
                    "selected": body.get("selected"),
                    "status": body.get("status"),
                    "candidate_count": len(body.get("candidates") or []),
                }
        write_yaml(ir_dir / "entrypoints.yaml", entrypoints)
    else:
        candidates = read_yaml(ir_dir / "entrypoint_candidates.yaml")
        entrypoints = read_yaml(ir_dir / "entrypoints.yaml")
        if not entrypoints:
            raise FileNotFoundError("ir/entrypoints.yaml missing; include entrypoints layer or run full build")

    llm_roles = [role for role, body in (entrypoints.get("roles") or {}).items() if not body.get("selected")]
    if llm_roles and not confirmation_patch:
        pass

    if "tilingkey" in selected:
        tilingkey = extract_tilingkey_space(repo_root, op_name, architecture=architecture)
        write_yaml(ir_dir / "tilingkey_space.yaml", tilingkey)
    else:
        tilingkey = read_yaml(ir_dir / "tilingkey_space.yaml") or {"nodes": [], "edges": [], "unresolved": [], "dimensions": [], "template_blocks": []}

    # Host/kernel require extract_plan (LLM-confirmed) unless explicitly allowed empty.
    if selected & {"host", "kernel"}:
        plan = load_extract_plan(uo_root)
        if plan is None and not allow_empty_plan:
            raise FileNotFoundError(
                "ir/extract_plan.yaml missing; run propose_extract_plan.py then "
                "uo-semantic-resolve extract-plan confirm, or pass --allow-empty-plan for tests"
            )

    if "host" in selected:
        host = extract_host_subgraph(
            repo_root,
            op_name,
            architecture=architecture,
            allow_empty_plan=allow_empty_plan,
        )
        write_yaml(ir_dir / "host_subgraph.yaml", host)
    else:
        host = read_yaml(ir_dir / "host_subgraph.yaml") or {"nodes": [], "edges": [], "unresolved": []}

    if "kernel" in selected:
        kernel = extract_kernel_subgraph(repo_root, op_name, architecture=architecture)
        write_yaml(ir_dir / "kernel_subgraph.yaml", kernel)
    else:
        kernel = read_yaml(ir_dir / "kernel_subgraph.yaml") or {"nodes": [], "edges": [], "unresolved": [], "branches": []}

    if "golden" in selected:
        golden = extract_golden(repo_root, op_name)
        write_yaml(ir_dir / "golden.yaml", golden)
    else:
        golden = read_yaml(ir_dir / "golden.yaml") or {"nodes": [], "unresolved": [], "golden": {}}

    if "bridge" in selected:
        bridge = reconcile_bridge(repo_root, op_name)
        write_yaml(ir_dir / "bridge.yaml", bridge)
    else:
        bridge = read_yaml(ir_dir / "bridge.yaml") or {"bridge_nodes": [], "bridge_edges": [], "unresolved": [], "diagnostics": []}

    nodes = _merge_nodes(
        host.get("nodes") or [],
        kernel.get("nodes") or [],
        tilingkey.get("nodes") or [],
        golden.get("nodes") or [],
        bridge.get("bridge_nodes") or [],
    )
    edges = _merge_edges(
        host.get("edges") or [],
        kernel.get("edges") or [],
        tilingkey.get("edges") or [],
        bridge.get("bridge_edges") or [],
    )
    unresolved = []
    for role in llm_roles:
        unresolved.append(
            {
                "id": f"UNRES_ENTRY_{role.upper()}",
                "kind": "entrypoint_needs_llm",
                "message": f"Entrypoint role {role} needs LLM confirmation",
                "file_path": "",
                "snippet": "",
                "role": role,
                "candidates": (candidates.get("roles") or {}).get(role, {}).get("candidates") or [],
            }
        )
    for block in (host, kernel, tilingkey, golden, bridge):
        unresolved.extend(block.get("unresolved") or [])

    graph = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "layers": ["host", "bridge", "kernel"],
        "rebuild_layers": sorted(selected),
        "entrypoints": entrypoints,
        "nodes": nodes,
        "edges": edges,
        "tilingkey": {
            "args_sel_count": tilingkey.get("args_sel_count"),
            "dimensions": tilingkey.get("dimensions") or [],
            "template_blocks": tilingkey.get("template_blocks") or [],
        },
        "kernel_branches": kernel.get("branches") or [],
        "golden": golden.get("golden"),
        "bridge_diagnostics": bridge.get("diagnostics") or [],
        "unresolved": unresolved,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "unresolved_count": len(unresolved),
            "host_nodes": len(host.get("nodes") or []),
            "kernel_nodes": len(kernel.get("nodes") or []),
            "bridge_nodes": len(bridge.get("bridge_nodes") or []),
            "args_sel_count": tilingkey.get("args_sel_count") or 0,
            "template_count": len(tilingkey.get("template_blocks") or []),
        },
    }
    write_yaml(ir_dir / "operator_graph.yaml", graph)
    write_yaml(ir_dir / "unresolved.yaml", {"version": 1, "op_name": op_name, "items": unresolved})

    from uo.scripts.kb_query_export import materialize_testcase_contract_files

    materialize_testcase_contract_files(uo_root, graph)

    try:
        from uo.scripts.export_kb_graph import export_kb_graph

        kb_graph_stats = export_kb_graph(repo_root, op_name, write=True)
        graph.setdefault("stats", {})["kb_graph"] = {
            "entity_count": kb_graph_stats.get("entity_count"),
            "relation_count": kb_graph_stats.get("relation_count"),
            "status": kb_graph_stats.get("status"),
        }
    except Exception as exc:  # noqa: BLE001
        graph.setdefault("stats", {})["kb_graph"] = {"status": "error", "error": str(exc)}

    if selected & {"host", "tilingkey"}:
        try:
            from uo.scripts.extract_key_predicates import extract_key_predicates, write_key_cards

            key_payload = extract_key_predicates(repo_root, op_name, architecture=architecture)
            write_key_cards(uo_root, key_payload)
            graph.setdefault("stats", {})["key_cards"] = key_payload.get("index") or {}
        except Exception as exc:  # noqa: BLE001
            unresolved.append(
                {
                    "id": "UNRES_KEY_PREDICATES",
                    "kind": "key_predicates_extract_failed",
                    "message": str(exc),
                    "file_path": "",
                    "snippet": "",
                }
            )
            write_yaml(ir_dir / "unresolved.yaml", {"version": 1, "op_name": op_name, "items": unresolved})
            graph["unresolved"] = unresolved
            graph.setdefault("stats", {})["unresolved_count"] = len(unresolved)

    try:
        from uo.scripts.export_human_views import export_human_views

        human_stats = export_human_views(uo_root, write=True)
        graph.setdefault("stats", {})["human_views"] = {
            "key_count": (human_stats.get("keys_table") or {}).get("key_count"),
            "export_profile": human_stats.get("export_profile"),
            "status": "ok",
        }
    except Exception as exc:  # noqa: BLE001
        graph.setdefault("stats", {})["human_views"] = {"status": "error", "error": str(exc)}

    return graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build layered Host/Bridge/Kernel operator KB IR")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--confirm-patch", help="Optional entrypoint confirmation YAML from LLM")
    parser.add_argument(
        "--layers",
        default="",
        help="Comma-separated layers to rebuild (default: all). "
        "Allowed: entrypoints,host,kernel,tilingkey,golden,bridge",
    )
    parser.add_argument(
        "--allow-empty-plan",
        action="store_true",
        help="Allow missing ir/extract_plan.yaml (tests / fail-soft only)",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    patch = read_yaml(Path(args.confirm_patch)) if args.confirm_patch else None
    layer_set = {part.strip() for part in str(args.layers).split(",") if part.strip()} or None
    graph = build_layered_kb(
        repo_root,
        op_name,
        architecture=args.architecture,
        confirmation_patch=patch,
        layers=layer_set,
        allow_empty_plan=bool(args.allow_empty_plan),
    )
    print(
        f"layered KB nodes={graph['stats']['node_count']} edges={graph['stats']['edge_count']} "
        f"sel={graph['stats']['args_sel_count']} unresolved={graph['stats']['unresolved_count']} "
        f"rebuild={graph.get('rebuild_layers')}"
    )
    return 0


def _merge_nodes(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group in groups:
        for node in group:
            nid = str(node.get("id") or "")
            if not nid:
                continue
            if nid not in out:
                out[nid] = node
            else:
                merged = dict(out[nid])
                for key, value in node.items():
                    if key not in merged or merged[key] in (None, "", [], {}):
                        merged[key] = value
                out[nid] = merged
    return list(out.values())


def _merge_edges(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group in groups:
        for edge in group:
            eid = str(edge.get("id") or "")
            if eid:
                out[eid] = edge
    return list(out.values())


if __name__ == "__main__":
    raise SystemExit(main())
