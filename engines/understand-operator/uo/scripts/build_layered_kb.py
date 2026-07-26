from __future__ import annotations

import argparse
import sys
import time
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
from uo.scripts.resolve_entrypoints import (
    apply_entrypoint_confirmation,
    collect_entrypoint_candidates,
    load_valid_confirmation_ledger,
    write_confirmation_ledger,
)


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
    build_t0 = time.perf_counter()
    timing_ms: dict[str, int] = {}
    macro_materialization: dict[str, Any] = {}
    uo_root = existing_operator_root(repo_root, op_name)
    ir_dir = uo_root / "ir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    selected = set(ALL_EXTRACT_LAYERS) if not layers else {str(item).strip().lower() for item in layers if str(item).strip()}
    if selected & {"host", "kernel", "tilingkey"}:
        selected.add("bridge")
    # entrypoints → ir/entrypoint_graph.yaml (unique confirmation fact source)
    if "entrypoints" in selected:
        t_ep = time.perf_counter()
        candidates = collect_entrypoint_candidates(
            repo_root, op_name, architecture=architecture, auto_confirm_high_confidence=auto_confirm
        )
        write_yaml(
            ir_dir / "entrypoint_candidates.yaml",
            {k: v for k, v in candidates.items() if k != "entrypoint_graph"},
        )
        patch = confirmation_patch
        if patch is None:
            # Rebuild must not overwrite LLM-confirmed edges: re-apply valid ledger.
            patch = load_valid_confirmation_ledger(uo_root, repo_root)
        if patch:
            entrypoint_graph = apply_entrypoint_confirmation(candidates, patch)
            if confirmation_patch is not None:
                write_confirmation_ledger(uo_root, repo_root, confirmation_patch)
        else:
            entrypoint_graph = dict(candidates.get("entrypoint_graph") or {})
        write_yaml(ir_dir / "entrypoint_graph.yaml", entrypoint_graph)
        legacy = ir_dir / "entrypoints.yaml"
        if legacy.exists():
            legacy.unlink()
        # Optional supporting evidence extracts (best-effort).
        try:
            from uo.scripts.extract_operator_boundary import extract_operator_boundary

            extract_operator_boundary(repo_root, op_name, architecture=architecture)
        except Exception:  # noqa: BLE001
            pass
        try:
            from uo.scripts.extract_build_evidence import extract_build_evidence

            extract_build_evidence(repo_root, op_name)
        except Exception:  # noqa: BLE001
            pass
        try:
            from uo.scripts.cann_doc_evidence import collect_doc_evidence_bundle

            collect_doc_evidence_bundle(repo_root, op_name)
        except Exception:  # noqa: BLE001
            pass
        timing_ms["entrypoints"] = int((time.perf_counter() - t_ep) * 1000)
    else:
        candidates = read_yaml(ir_dir / "entrypoint_candidates.yaml") or {}
        entrypoint_graph = read_yaml(ir_dir / "entrypoint_graph.yaml")
        if not entrypoint_graph:
            raise FileNotFoundError(
                "ir/entrypoint_graph.yaml missing; include entrypoints layer or run full build"
            )

    # Macro semantic materialization: typed facts before host/kernel / post-score.
    t_macro = time.perf_counter()
    try:
        from uo.scripts.macro_semantic_materializer import materialize_macro_semantics

        macro_result = materialize_macro_semantics(
            repo_root, op_name, architecture=architecture, uo_root=uo_root
        )
        macro_materialization = dict(macro_result.get("macro_materialization") or {})
        if isinstance(macro_result.get("entrypoint_graph"), dict):
            entrypoint_graph = macro_result["entrypoint_graph"]
    except Exception as exc:  # noqa: BLE001
        macro_materialization = {
            "status": "error",
            "error": str(exc)[:300],
            "timing_ms": int((time.perf_counter() - t_macro) * 1000),
        }
    else:
        macro_materialization.setdefault(
            "timing_ms", int((time.perf_counter() - t_macro) * 1000)
        )
    timing_ms["macro_semantics"] = int(macro_materialization.get("timing_ms") or 0)

    closure = entrypoint_graph.get("closure") or {}
    llm_needed = (
        closure.get("host_main_chain") != "closed" or closure.get("kernel_main_chain") != "closed"
    )
    if llm_needed and not confirmation_patch:
        pass

    if "tilingkey" in selected:
        t0 = time.perf_counter()
        tilingkey = extract_tilingkey_space(repo_root, op_name, architecture=architecture)
        write_yaml(ir_dir / "tilingkey_space.yaml", tilingkey)
        timing_ms["tilingkey"] = int((time.perf_counter() - t0) * 1000)
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
        t0 = time.perf_counter()
        host = extract_host_subgraph(
            repo_root,
            op_name,
            architecture=architecture,
            allow_empty_plan=allow_empty_plan,
        )
        write_yaml(ir_dir / "host_subgraph.yaml", host)
        timing_ms["host"] = int((time.perf_counter() - t0) * 1000)
    else:
        host = read_yaml(ir_dir / "host_subgraph.yaml") or {"nodes": [], "edges": [], "unresolved": []}

    if "kernel" in selected:
        t0 = time.perf_counter()
        kernel = extract_kernel_subgraph(repo_root, op_name, architecture=architecture)
        write_yaml(ir_dir / "kernel_subgraph.yaml", kernel)
        timing_ms["kernel"] = int((time.perf_counter() - t0) * 1000)
    else:
        kernel = read_yaml(ir_dir / "kernel_subgraph.yaml") or {"nodes": [], "edges": [], "unresolved": [], "branches": []}

    if "golden" in selected:
        golden = extract_golden(repo_root, op_name)
        write_yaml(ir_dir / "golden.yaml", golden)
    else:
        golden = read_yaml(ir_dir / "golden.yaml") or {"nodes": [], "unresolved": [], "golden": {}}

    if "bridge" in selected:
        t0 = time.perf_counter()
        bridge = reconcile_bridge(repo_root, op_name)
        write_yaml(ir_dir / "bridge.yaml", bridge)
        timing_ms["bridge"] = int((time.perf_counter() - t0) * 1000)
    else:
        bridge = read_yaml(ir_dir / "bridge.yaml") or {"bridge_nodes": [], "bridge_edges": [], "unresolved": [], "diagnostics": []}
    nodes = _merge_nodes(
        _entrypoint_nodes_as_graph(entrypoint_graph),
        _boundary_nodes(ir_dir),
        host.get("nodes") or [],
        kernel.get("nodes") or [],
        tilingkey.get("nodes") or [],
        golden.get("nodes") or [],
        bridge.get("bridge_nodes") or [],
    )
    merge_diags = list(_MERGE_NODE_DIAGNOSTICS)
    macro_doc = read_yaml(ir_dir / "macro_semantics.yaml") or {}
    macro_edges = list(macro_doc.get("emitted_edges") or [])
    edges = _merge_edges(
        _entrypoint_edges_as_graph(entrypoint_graph),
        macro_edges,
        _boundary_edges(ir_dir),
        _def_use_edges(host),
        host.get("edges") or [],
        kernel.get("edges") or [],
        tilingkey.get("edges") or [],
        bridge.get("bridge_edges") or [],
    )
    # Attach operator capabilities if declared (⑧); never infer from absence.
    caps = read_yaml(ir_dir / "operator_capabilities.yaml") or {}
    if not caps:
        caps = {
            "has_tilingkey": None,
            "has_tilingdata": None,
            "note": "must be declared explicitly; absence of KEY does not imply simple op",
        }
        write_yaml(ir_dir / "operator_capabilities.yaml", caps)
    unresolved: list[dict[str, Any]] = []
    if llm_needed:
        for block in closure.get("blocking_unresolved") or []:
            if not isinstance(block, dict):
                continue
            unresolved.append(
                {
                    "id": f"UNRES_ENTRY_{str(block.get('code') or 'closure').upper()}",
                    "kind": "entrypoint_needs_llm",
                    "severity": block.get("severity") or "blocking",
                    "message": block.get("reason") or "Entrypoint graph closure incomplete",
                    "file_path": "",
                    "snippet": "",
                    "code": block.get("code"),
                    "candidates": (candidates.get("role_candidates") or {}),
                }
            )
        if not (closure.get("blocking_unresolved") or []):
            unresolved.append(
                {
                    "id": "UNRES_ENTRY_CLOSURE",
                    "kind": "entrypoint_needs_llm",
                    "severity": "blocking",
                    "message": (
                        f"Entrypoint closure incomplete "
                        f"(host={closure.get('host_main_chain')}, "
                        f"kernel={closure.get('kernel_main_chain')})"
                    ),
                    "file_path": "",
                    "snippet": "",
                }
            )
    for block in (host, kernel, tilingkey, golden, bridge):
        unresolved.extend(block.get("unresolved") or [])
    for diag in merge_diags:
        unresolved.append(
            {
                "id": f"UNRES_{diag.get('code')}_{diag.get('node_id')}",
                "kind": str(diag.get("code") or "SEMANTIC_ID_COLLISION").lower(),
                "severity": diag.get("severity") or "blocking",
                "message": diag.get("message"),
                "identity_keys": diag.get("identity_keys"),
                "file_path": "",
                "snippet": "",
            }
        )

    graph = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "layers": ["host", "bridge", "kernel"],
        "rebuild_layers": sorted(selected),
        "entrypoint_graph": entrypoint_graph,
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
        "merge_diagnostics": merge_diags,
        "operator_capabilities": caps,
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
            "host_main_chain": closure.get("host_main_chain"),
            "kernel_main_chain": closure.get("kernel_main_chain"),
            "verified_edge_count": sum(
                1
                for e in edges
                if str(e.get("confidence") or "").casefold()
                in {"verified", "source_verified", "semantic_verified"}
            ),
            "candidate_edge_count": sum(
                1 for e in edges if str(e.get("confidence") or "").casefold() in {"candidate", "structurally_inferred"}
            ),
            "semantic_collision_count": sum(
                1 for d in merge_diags if d.get("code") == "SEMANTIC_ID_COLLISION"
            ),
            "function_count": sum(
                1
                for n in nodes
                if n.get("kind") == "FunctionDefinition"
                or n.get("node_type") in {"Process", "Init", "Compute", "FunctionDefinition"}
            ),
            "call_edge_count": sum(1 for e in edges if e.get("type") == "calls"),
            "branch_count": sum(1 for n in nodes if n.get("node_type") == "KernelBranch"),
            "loop_count": sum(1 for n in nodes if n.get("node_type") == "Loop"),
            "candidate_call_count": sum(
                1
                for e in edges
                if e.get("type") == "calls" and e.get("target_status") == "candidate_set"
            ),
            "unresolved_call_count": sum(
                1
                for e in edges
                if e.get("type") == "calls" and e.get("target_status") == "missing"
            ),
        },
    }
    write_yaml(ir_dir / "operator_graph.yaml", graph)
    write_yaml(ir_dir / "unresolved.yaml", {"version": 1, "op_name": op_name, "items": unresolved})

    # Classify input_derivable from graph markers (no key_cards product).
    try:
        from uo.scripts.classify_input_derivable import classify_and_write

        id_payload = classify_and_write(uo_root, graph)
        graph.setdefault("stats", {})["input_derivable"] = id_payload.get("stats") or {}
    except Exception as exc:  # noqa: BLE001
        graph.setdefault("stats", {})["input_derivable"] = {"status": "error", "error": str(exc)}

    from uo.scripts.kb_query_export import materialize_testcase_contract_files

    materialize_testcase_contract_files(uo_root, graph)

    t_export = time.perf_counter()
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

    try:
        from uo.scripts.export_human_views import export_human_views

        human_stats = export_human_views(uo_root, write=True)
        graph.setdefault("stats", {})["human_views"] = {
            "key_count": (human_stats.get("keys_table") or {}).get("key_count"),
            "ktpl_count": human_stats.get("ktpl_count"),
            "status": "ok",
        }
    except Exception as exc:  # noqa: BLE001
        graph.setdefault("stats", {})["human_views"] = {"status": "error", "error": str(exc)}
    timing_ms["yaml_export"] = int((time.perf_counter() - t_export) * 1000)
    timing_ms["total"] = int((time.perf_counter() - build_t0) * 1000)
    graph.setdefault("stats", {})["timing_ms"] = timing_ms
    graph.setdefault("stats", {})["macro_materialization"] = macro_materialization
    write_yaml(ir_dir / "build_layered_timing.yaml", {"version": 1, "timing_ms": timing_ms})

    # Seed rebuild + layer fingerprints so post-adjudicate rebuild can skip / select layers.
    try:
        from uo.scripts.evidence_score import require_source_snapshot
        from uo.scripts.semantic_resolution_ledger import (
            compute_layer_input_fingerprints,
            compute_rebuild_input_fingerprint,
            persist_layer_input_fingerprints,
        )

        manifest = read_yaml(uo_root / "manifest.yaml") or {}
        run_id = str(manifest.get("current_run_id") or manifest.get("current_run") or "")
        snap_res = require_source_snapshot(uo_root, run_id=run_id or None)
        if snap_res.get("ok") and run_id:
            snap = str(snap_res.get("hash") or "")
            fp = compute_rebuild_input_fingerprint(
                uo_root,
                architecture=architecture,
                source_snapshot=snap,
                current_run_id=run_id,
            )
            write_yaml(ir_dir / "rebuild_input_fingerprint.yaml", {"version": 1, **fp})
            graph.setdefault("stats", {})["rebuild_input_fingerprint"] = fp.get("fingerprint")
            layer_fps = compute_layer_input_fingerprints(
                uo_root, architecture=architecture, source_snapshot=snap
            )
            persist_layer_input_fingerprints(uo_root, layer_fps, rebuilt_layers=sorted(selected))
            graph.setdefault("stats", {})["layer_input_fingerprints"] = layer_fps
    except Exception:  # noqa: BLE001
        pass

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


_MERGE_NODE_DIAGNOSTICS: list[dict[str, Any]] = []


def _merge_nodes(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for group in groups:
        for node in group:
            nid = str(node.get("id") or "")
            if not nid:
                continue
            sym = node.get("symbol_ref") if isinstance(node.get("symbol_ref"), dict) else {}
            ikey = str(node.get("identity_key") or sym.get("identity_key") or "").strip()
            if nid not in out:
                out[nid] = node
                continue
            prev = out[nid]
            prev_sym = prev.get("symbol_ref") if isinstance(prev.get("symbol_ref"), dict) else {}
            prev_ikey = str(prev.get("identity_key") or prev_sym.get("identity_key") or "").strip()
            if ikey and prev_ikey and ikey != prev_ikey:
                diagnostics.append(
                    {
                        "code": "SEMANTIC_ID_COLLISION",
                        "node_id": nid,
                        "identity_keys": [prev_ikey, ikey],
                        "qualified_names": [
                            prev.get("qualified_name") or prev.get("name"),
                            node.get("qualified_name") or node.get("name"),
                        ],
                        "severity": "blocking",
                        "message": (
                            f"Same node id {nid} maps to distinct identity_key values; "
                            "refusing silent rename"
                        ),
                    }
                )
                continue
            merged = dict(prev)
            for key, value in node.items():
                if key == "locator" and isinstance(value, dict):
                    locs = merged.get("locators")
                    if not isinstance(locs, list):
                        locs = []
                        if isinstance(merged.get("locator"), dict):
                            locs.append(merged["locator"])
                    locs.append(value)
                    seen: set[tuple[Any, Any]] = set()
                    uniq: list[dict[str, Any]] = []
                    for loc in locs:
                        if not isinstance(loc, dict):
                            continue
                        k = (loc.get("file_path"), loc.get("start_line"))
                        if k in seen:
                            continue
                        seen.add(k)
                        uniq.append(loc)
                    merged["locators"] = uniq
                    if uniq:
                        merged["locator"] = uniq[0]
                    continue
                if key not in merged or merged[key] in (None, "", [], {}):
                    merged[key] = value
            out[nid] = merged
    _MERGE_NODE_DIAGNOSTICS.clear()
    _MERGE_NODE_DIAGNOSTICS.extend(diagnostics)
    return list(out.values())


def _merge_edges(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from uo.scripts.semantic_identity import mint_edge_id

    out: dict[str, dict[str, Any]] = {}
    for group in groups:
        for edge in group:
            if not isinstance(edge, dict):
                continue
            eid = str(edge.get("id") or "")
            if not eid:
                src = str(edge.get("source_id") or edge.get("source") or edge.get("from") or "")
                tgt = str(edge.get("target_id") or edge.get("target") or edge.get("to") or "")
                etype = str(edge.get("edge_type") or edge.get("type") or "edge")
                qual = str(
                    edge.get("qualifier")
                    or edge.get("flag")
                    or edge.get("call_site_id")
                    or edge.get("target_status")
                    or ""
                )
                eid = mint_edge_id(etype, src, tgt or "none", qual)
            if eid:
                out[eid] = {**edge, "id": eid}
    return list(out.values())


def _entrypoint_nodes_as_graph(entrypoint_graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = []
    for n in entrypoint_graph.get("nodes") or []:
        if not isinstance(n, dict) or not n.get("id"):
            continue
        nodes.append(
            {
                **n,
                "layer": "entrypoint",
                "kind": n.get("kind") or f"EP::{n.get('role')}",
            }
        )
    return nodes


def _entrypoint_edges_as_graph(entrypoint_graph: dict[str, Any]) -> list[dict[str, Any]]:
    edges = []
    for e in entrypoint_graph.get("edges") or []:
        if not isinstance(e, dict):
            continue
        edges.append(
            {
                **e,
                "source": e.get("source") or e.get("source_id"),
                "target": e.get("target") or e.get("target_id"),
                "layer": "entrypoint",
            }
        )
    return edges


def _boundary_nodes(ir_dir: Path) -> list[dict[str, Any]]:
    boundary = read_yaml(ir_dir / "operator_boundary.yaml") or {}
    nodes: list[dict[str, Any]] = []
    seen_accessors: set[str] = set()
    for inp in boundary.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        name = inp.get("name") or f"input_slot[{inp.get('slot')}]"
        nodes.append(
            {
                "id": f"INPUT_{name}",
                "kind": "INPUT",
                "name": name,
                "slot": inp.get("slot"),
                "layer": "boundary",
                "binding_status": inp.get("binding_status"),
                "confidence": "source_verified" if inp.get("binding_status") == "verified" else "candidate",
            }
        )
        for acc in inp.get("host_accessors") or []:
            aid = f"ACCESSOR_{acc.get('api')}_{acc.get('line')}"
            if aid in seen_accessors:
                continue
            seen_accessors.add(aid)
            nodes.append(
                {
                    "id": aid,
                    "kind": "ACCESSOR",
                    "name": acc.get("api"),
                    "layer": "boundary",
                    "file_path": acc.get("file_path"),
                    "line": acc.get("line"),
                    "confidence": "source_verified",
                }
            )
    for attr in boundary.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        name = attr.get("slot_or_name") or "attr"
        nodes.append(
            {
                "id": f"ATTR_{name}",
                "kind": "ATTR",
                "name": name,
                "layer": "boundary",
                "binding_status": attr.get("binding_status"),
                "confidence": "source_verified" if attr.get("binding_status") == "verified" else "candidate",
            }
        )
        for acc in attr.get("host_accessors") or []:
            aid = f"ACCESSOR_{acc.get('api')}_{acc.get('line')}"
            if aid in seen_accessors:
                continue
            seen_accessors.add(aid)
            nodes.append(
                {
                    "id": aid,
                    "kind": "ACCESSOR",
                    "name": acc.get("api"),
                    "layer": "boundary",
                    "file_path": acc.get("file_path"),
                    "line": acc.get("line"),
                    "confidence": "source_verified",
                }
            )
    return nodes


def _boundary_edges(ir_dir: Path) -> list[dict[str, Any]]:
    boundary = read_yaml(ir_dir / "operator_boundary.yaml") or {}
    edges: list[dict[str, Any]] = []
    for inp in boundary.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        name = inp.get("name") or f"input_slot[{inp.get('slot')}]"
        for acc in inp.get("host_accessors") or []:
            edges.append(
                {
                    "id": f"reaches_input:INPUT_{name}->{acc.get('api')}:{acc.get('line')}",
                    "type": "reaches_input",
                    "source": f"INPUT_{name}",
                    "target": f"ACCESSOR_{acc.get('api')}_{acc.get('line')}",
                    "confidence": "source_verified",
                    "verification_source": "source",
                    "layer": "boundary",
                }
            )
    for attr in boundary.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        name = attr.get("slot_or_name")
        for acc in attr.get("host_accessors") or []:
            edges.append(
                {
                    "id": f"determined_by:ATTR_{name}->{acc.get('api')}:{acc.get('line')}",
                    "type": "determined_by",
                    "source": f"ATTR_{name}",
                    "target": f"ACCESSOR_{acc.get('api')}_{acc.get('line')}",
                    "confidence": "source_verified",
                    "verification_source": "source",
                    "layer": "boundary",
                }
            )
    return edges


def _def_use_edges(host: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge host def-use flows; preserve confidence tiers (⑫)."""
    flows: list[dict[str, Any]] = []
    flows.extend(host.get("def_use_flows") or [])
    flows.extend(host.get("flows") or [])
    # Host subgraph nests flows under def_use: [{definitions, flows, ...}, ...]
    for block in host.get("def_use") or []:
        if isinstance(block, dict):
            flows.extend(block.get("flows") or [])
    edges: list[dict[str, Any]] = []
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        edges.append(
            {
                **flow,
                "source": flow.get("source") or flow.get("from"),
                "target": flow.get("target") or flow.get("to"),
                "type": flow.get("type") or "derives",
                "layer": "def_use",
                "confidence": flow.get("confidence") or "candidate",
            }
        )
    return edges


if __name__ == "__main__":
    raise SystemExit(main())
