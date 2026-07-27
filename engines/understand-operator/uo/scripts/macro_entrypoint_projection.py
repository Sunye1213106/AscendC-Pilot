"""将部分 macro_facts 投影到 entrypoint_graph。

仅投影：
  REG_OP / IMPL_OP_OPTILING / DEVICE_IMPL_OP_OPTILING /
  REGISTER_TILING_TEMPLATE / REGISTER_TILING_TEMPLATE_WITH_ARCH

模板声明、TilingData schema、Key 编码事实不得写入 entrypoint_graph。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.ascendc_macro_facts import ENTRYPOINT_PROJECTION_MACROS, load_macro_facts

PROJECTION_VERSION = "1.0.0"


def _edge_id(etype: str, source: str, target: str, *extra: str) -> str:
    raw = "|".join([etype, source, target, *extra])
    return "E_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _find_ep_nodes(
    nodes: dict[str, dict[str, Any]],
    *,
    macro: str,
    file_path: str,
    line: int,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for node in nodes.values():
        node_macro = str(node.get("macro") or "")
        loc = node.get("locator") or {}
        fp = str(loc.get("file_path") or "").replace("\\", "/")
        if node_macro != macro and not node_macro.startswith(macro + "."):
            continue
        if fp and fp != file_path:
            continue
        node_line = int(loc.get("start_line") or loc.get("line") or 0)
        if node_line and abs(node_line - line) > 5:
            continue
        hits.append(node)
    return hits


def project_macro_facts_to_entrypoint(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
    macro_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """升级 entrypoint_graph，返回投影摘要。"""
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    ir_dir = root / "ir"
    facts = macro_facts if macro_facts is not None else load_macro_facts(root)
    entrypoint = read_yaml(ir_dir / "entrypoint_graph.yaml") or {
        "nodes": [],
        "edges": [],
        "unresolved": [],
    }

    nodes = {
        str(n.get("id")): dict(n)
        for n in (entrypoint.get("nodes") or [])
        if isinstance(n, dict) and n.get("id")
    }
    edges = [dict(e) for e in (entrypoint.get("edges") or []) if isinstance(e, dict)]
    edge_ids = {str(e.get("id")) for e in edges if e.get("id")}
    emitted_edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    upgraded = 0

    for inv in facts.get("invocations") or []:
        if not isinstance(inv, dict):
            continue
        macro = str(inv.get("macro") or "")
        if macro not in ENTRYPOINT_PROJECTION_MACROS:
            continue
        fp = str(inv.get("file_path") or "")
        line = int(inv.get("start_line") or 0)
        args = list((inv.get("normalized_args") or {}).get("positional") or inv.get("raw_args") or [])
        matched = _find_ep_nodes(nodes, macro=macro, file_path=fp, line=line)

        if macro == "REG_OP" and args:
            op_type = args[0].strip()
            for node in matched:
                node["confidence"] = "source_verified"
                node["macro_fact_id"] = inv.get("fact_id")
                nodes[str(node["id"])] = node
                upgraded += 1
                eid = _edge_id("declares_operator", str(node["id"]), op_type, fp, str(line))
                if eid not in edge_ids:
                    edge = {
                        "id": eid,
                        "type": "declares_operator",
                        "source": str(node["id"]),
                        "target": op_type,
                        "evidence": {"macro_fact_id": inv.get("fact_id"), "file_path": fp, "start_line": line},
                    }
                    edges.append(edge)
                    edge_ids.add(eid)
                    emitted_edges.append(edge)

        elif macro in {"IMPL_OP_OPTILING", "DEVICE_IMPL_OP_OPTILING"}:
            for node in matched:
                node["confidence"] = "source_verified"
                node["macro_fact_id"] = inv.get("fact_id")
                nodes[str(node["id"])] = node
                upgraded += 1
            host_id = str(matched[0]["id"]) if matched else ""
            for method in inv.get("chained_methods") or []:
                mname = str(method.get("name") or "")
                margs = list(method.get("args") or [])
                if mname == "Tiling" and margs and host_id:
                    target = margs[0].strip()
                    eid = _edge_id("binds_tiling", host_id, target, fp, str(line))
                    if eid not in edge_ids:
                        edge = {
                            "id": eid,
                            "type": "binds_tiling",
                            "source": host_id,
                            "target": target,
                            "evidence": {"macro_fact_id": inv.get("fact_id")},
                        }
                        edges.append(edge)
                        edge_ids.add(eid)
                        emitted_edges.append(edge)
                elif mname == "TilingParse" and margs and host_id:
                    target = margs[0].strip()
                    eid = _edge_id("binds_tiling_parse", host_id, target, fp, str(line))
                    if eid not in edge_ids:
                        edge = {
                            "id": eid,
                            "type": "binds_tiling_parse",
                            "source": host_id,
                            "target": target,
                            "evidence": {"macro_fact_id": inv.get("fact_id")},
                        }
                        edges.append(edge)
                        edge_ids.add(eid)
                        emitted_edges.append(edge)
            if not matched:
                unresolved.append(
                    {
                        "reason_code": "ENTRYPOINT_NODE_MISSING",
                        "macro": macro,
                        "file_path": fp,
                        "start_line": line,
                        "message": "macro_facts 命中但 entrypoint 无对应节点",
                    }
                )

        elif macro in {"REGISTER_TILING_TEMPLATE", "REGISTER_TILING_TEMPLATE_WITH_ARCH"}:
            for node in matched:
                node["confidence"] = "source_verified"
                node["macro_fact_id"] = inv.get("fact_id")
                nodes[str(node["id"])] = node
                upgraded += 1
            if len(args) >= 2:
                op_type = args[0].strip()
                template = args[1].strip()
                arch = args[2].strip() if len(args) > 2 else architecture
                src = str(matched[0]["id"]) if matched else f"template:{template}"
                eid = _edge_id("registers_template", src, template, op_type, arch)
                if eid not in edge_ids:
                    edge = {
                        "id": eid,
                        "type": "registers_template",
                        "source": src,
                        "target": template,
                        "architecture": arch,
                        "evidence": {"macro_fact_id": inv.get("fact_id")},
                    }
                    edges.append(edge)
                    edge_ids.add(eid)
                    emitted_edges.append(edge)
                eid2 = _edge_id("available_on_arch", template, arch)
                if eid2 not in edge_ids:
                    edge2 = {
                        "id": eid2,
                        "type": "available_on_arch",
                        "source": template,
                        "target": arch,
                        "evidence": {"macro_fact_id": inv.get("fact_id")},
                    }
                    edges.append(edge2)
                    edge_ids.add(eid2)
                    emitted_edges.append(edge2)

    entrypoint["nodes"] = list(nodes.values())
    entrypoint["edges"] = edges
    meta = entrypoint.setdefault("macro_entrypoint_projection", {})
    meta.update(
        {
            "version": PROJECTION_VERSION,
            "upgraded_nodes": upgraded,
            "emitted_edge_count": len(emitted_edges),
            "unresolved": unresolved,
        }
    )
    write_yaml(ir_dir / "entrypoint_graph.yaml", entrypoint)
    return {
        "entrypoint_graph": entrypoint,
        "upgraded_nodes": upgraded,
        "emitted_edges": emitted_edges,
        "unresolved": unresolved,
    }
