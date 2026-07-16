from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
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
from understand_operator._operator.run_context import active_run_id


HOST_ROOT_TYPES = {"input", "optional_input", "attribute", "platform_property", "architecture_property", "constant", "macro", "constexpr"}
HOST_SINK_TYPES = {"tiling_key", "tiling_key_write", "tiling_data_write", "block_dim", "workspace", "kernel_dispatch", "kernel_entry_reference"}
HOST_KEEP_TYPES = HOST_ROOT_TYPES | HOST_SINK_TYPES | {
    "function_parameter",
    "local_variable",
    "derived_variable",
    "predicate",
    "comparison",
    "logical_expression",
    "host_branch",
    "switch_case",
    "function",
    "function_call",
    "tiling_data",
    "tiling_data_field",
    "template_binding",
}
KERNEL_ROOT_TYPES = {"tiling_key", "template_parameter", "template_binding", "compile_time_constant", "tiling_data", "tiling_data_field", "kernel_entry"}
KERNEL_SINK_TYPES = {"output", "copy_out", "store", "global_tensor"}
KERNEL_KEEP_TYPES = KERNEL_ROOT_TYPES | KERNEL_SINK_TYPES | {
    "kernel_function",
    "kernel_parameter",
    "kernel_variable",
    "derived_variable",
    "predicate",
    "kernel_branch",
    "loop",
    "copy_in",
    "compute",
    "local_tensor",
    "buffer",
    "queue",
    "pipe",
    "tensor_view",
    "reshape",
    "transpose",
    "cast",
    "offset",
    "slice",
    "load",
}
NON_ARCH_PATTERN = re.compile(r"arch(?:20|21|22|30|31|32|38)\b|__CCE_AICORE__\s*==\s*(?:200|210|220|300|310|320|380)", re.IGNORECASE)
ARCH35_PATTERN = re.compile(r"arch35\b|ARCH35\b|Arch35\b|__CCE_AICORE__\s*==\s*350|\b350\b", re.IGNORECASE)


@dataclass(frozen=True)
class SearchLimits:
    max_depth: int = 100
    max_paths_per_root: int = 1000
    max_total_nodes: int = 20000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase1 Host/Tiling and Kernel graph extraction from Phase0 anchors and CBM MCP graph.")
    parser.add_argument("repo", nargs="?", default=".", help="Project root")
    parser.add_argument("--op-name", help="Operator name")
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--mcp-raw-graph", help="YAML/JSON file exported from codebase-memory-mcp with nodes and edges")
    parser.add_argument("--cbm-db", help="SQLite database produced by the npm-installed codebase-memory-mcp package")
    parser.add_argument("--cbm-project", help="codebase-memory-mcp project name inside --cbm-db")
    parser.add_argument("--show-raw-graph", action="store_true")
    parser.add_argument("--show-processed-graph", action="store_true")
    parser.add_argument("--node-preview-limit", type=int, default=20)
    parser.add_argument("--edge-preview-limit", type=int, default=20)
    parser.add_argument("--max-depth", type=int, default=100)
    parser.add_argument("--max-paths-per-root", type=int, default=1000)
    parser.add_argument("--max-total-nodes", type=int, default=20000)
    args = parser.parse_args(argv)

    if yaml is None:
        print("PyYAML is required", file=sys.stderr)
        return 2
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    if not uo_root.exists():
        print(f"KB not found: {uo_root}", file=sys.stderr)
        return 2
    limits = SearchLimits(args.max_depth, args.max_paths_per_root, args.max_total_nodes)
    try:
        result = run_phase1_graph(
            repo_root,
            op_name,
            architecture=args.architecture,
            raw_graph_path=Path(args.mcp_raw_graph).resolve() if args.mcp_raw_graph else None,
            cbm_db_path=Path(args.cbm_db).resolve() if args.cbm_db else None,
            cbm_project=args.cbm_project,
            limits=limits,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    _print_summary(result, node_limit=args.node_preview_limit, edge_limit=args.edge_preview_limit, show_raw=args.show_raw_graph, show_processed=args.show_processed_graph)
    return 0


def run_phase1_graph(repo_root: Path, op_name: str, *, architecture: str, raw_graph_path: Path | None, limits: SearchLimits, cbm_db_path: Path | None = None, cbm_project: str | None = None) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    run_id = active_run_id(uo_root)
    phase0 = uo_root / "runs" / run_id / "phase0"
    scope = _load_phase0_scope(uo_root, phase0)
    cbm_meta = _read_mapping(uo_root / "cbm" / "index_meta.json")
    if cbm_meta.get("indexed_via") != "mcp":
        raise RuntimeError("Phase1 requires cbm/index_meta.json indexed_via: mcp")
    nodes, edges, issues, raw_source = _load_raw_candidate_graph(repo_root, scope, cbm_meta, raw_graph_path, cbm_db_path, cbm_project, architecture)
    nodes = _sort_nodes(nodes)
    edges = _sort_edges(edges)
    graph = _adjacency(nodes, edges)
    reverse = _reverse_adjacency(nodes, edges)
    raw_node_ids = {node["mcp_node_id"] for node in nodes}
    arch35_ids, arch_removed = _arch_filter(nodes, architecture)
    host_roots = [node["mcp_node_id"] for node in nodes if node["mcp_node_id"] in arch35_ids and node["semantic_type"] in HOST_ROOT_TYPES]
    host_sinks = [node["mcp_node_id"] for node in nodes if node["mcp_node_id"] in arch35_ids and node["semantic_type"] in HOST_SINK_TYPES]
    kernel_roots = [node["mcp_node_id"] for node in nodes if node["mcp_node_id"] in arch35_ids and node["semantic_type"] in KERNEL_ROOT_TYPES]
    kernel_sinks = [node["mcp_node_id"] for node in nodes if node["mcp_node_id"] in arch35_ids and node["semantic_type"] in KERNEL_SINK_TYPES]
    host = _extract_subgraph("host", nodes, edges, graph, reverse, host_roots, host_sinks, HOST_KEEP_TYPES, limits)
    kernel = _extract_subgraph("kernel", nodes, edges, graph, reverse, kernel_roots, kernel_sinks, KERNEL_KEEP_TYPES, limits)
    retained = set(host["kept_node_ids"]) | set(kernel["kept_node_ids"])
    removed_nodes = _removed_nodes(nodes, retained, arch_removed, host, kernel)
    removed_edges = _removed_edges(edges, retained, {edge["mcp_edge_id"] for edge in host["kept_edges"] + kernel["kept_edges"]})
    graph_dir = uo_root / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    payloads = _payloads(repo_root, op_name, architecture, scope, cbm_meta, raw_source, nodes, edges, host, kernel, removed_nodes, removed_edges, issues, limits)
    for filename, payload in payloads.items():
        _write_yaml(graph_dir / filename, payload)
    return {"graph_dir": graph_dir, **payloads}


def _load_phase0_scope(uo_root: Path, phase0: Path) -> dict[str, Any]:
    confirmed = _read_mapping(phase0 / "scope_confirmed.yaml")
    entry_points = _read_mapping(phase0 / "entry_points.yaml")
    if not confirmed:
        raise RuntimeError("Phase1 requires Phase0 scope_confirmed.yaml")
    files = confirmed.get("confirmed_file_list")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Phase1 requires non-empty confirmed_file_list")
    return {
        "operator": confirmed.get("operator") or uo_root.name,
        "confirmed_file_list": files,
        "excluded_files": confirmed.get("excluded_files") or [],
        "analysis_scope": confirmed.get("analysis_scope") or {},
        "entry_points": entry_points,
    }


def _load_raw_candidate_graph(repo_root: Path, scope: dict[str, Any], cbm_meta: dict[str, Any], raw_graph_path: Path | None, cbm_db_path: Path | None, cbm_project: str | None, architecture: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if raw_graph_path and raw_graph_path.exists():
        data = _read_mapping(raw_graph_path)
        nodes = [_normalize_node(item, index) for index, item in enumerate(data.get("nodes") or [], start=1)]
        edges = [_normalize_edge(item, index) for index, item in enumerate(data.get("edges") or [], start=1)]
        return nodes, edges, issues, {"type": "cbm_mcp", "input_file": raw_graph_path.as_posix(), "cbm_project": cbm_meta.get("cbm_project") or ""}
    db_path = cbm_db_path or _cbm_db_from_meta(cbm_meta)
    if db_path and db_path.exists():
        nodes, edges, source = _load_cbm_sqlite_graph(repo_root, scope, cbm_meta, db_path, cbm_project, architecture)
        if source.get("edge_read_error"):
            issues.append(
                {
                    "issue": "cbm_sqlite_edge_read_failed",
                    "severity": "warning",
                    "reason": source["edge_read_error"],
                    "action": "Used deterministic cbm_lexical_order edges derived from CBM node file/line metadata.",
                }
            )
        return nodes, edges, issues, source
    issues.append(
        {
            "issue": "mcp_raw_graph_unavailable",
            "severity": "error",
            "reason": "No connected codebase-memory-mcp graph tool is exposed to this runtime and no --mcp-raw-graph file was provided.",
            "action": "Provide MCP-exported nodes/edges or run inside an agent session where codebase-memory-mcp query_graph/get_edges tools are exposed.",
        }
    )
    nodes, edges = _scoped_fallback_graph(repo_root, scope)
    return nodes, edges, issues, {"type": "scoped_phase0_fallback", "cbm_project": cbm_meta.get("cbm_project") or ""}


def _cbm_db_from_meta(cbm_meta: dict[str, Any]) -> Path | None:
    value = cbm_meta.get("cbm_db_path") or cbm_meta.get("db_path")
    return Path(str(value)).expanduser() if value else None


def _load_cbm_sqlite_graph(repo_root: Path, scope: dict[str, Any], cbm_meta: dict[str, Any], db_path: Path, cbm_project: str | None, architecture: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    project = cbm_project or str(cbm_meta.get("cbm_project") or "")
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        if not project:
            rows = con.execute("select name from projects order by name").fetchall()
            project = str(rows[0]["name"]) if len(rows) == 1 else ""
        if not project:
            raise RuntimeError("Phase1 --cbm-db requires --cbm-project when the database contains multiple projects")
        project_row = con.execute("select root_path from projects where name=?", (project,)).fetchone()
        if project_row is None:
            raise RuntimeError(f"CBM project not found in --cbm-db: {project}")
        raw_rows = _candidate_cbm_rows(con, project, scope, architecture)
        nodes = [_normalize_cbm_node(row) for row in raw_rows]
        ids = [int(row["id"]) for row in raw_rows]
        edge_error = ""
        try:
            edges = _candidate_cbm_edges(con, project, ids)
        except sqlite3.DatabaseError as exc:
            edge_error = str(exc)
            edges = []
        edges.extend(_lexical_order_edges(nodes, len(edges) + 1))
    source = {
        "type": "codebase_memory_sqlite",
        "cbm_project": project,
        "db_path": db_path.as_posix(),
        "project_root": str(project_row["root_path"]),
        "selection": "phase0_scope_plus_operator_arch35_candidates",
    }
    if edge_error:
        source["edge_read_fallback"] = "cbm_lexical_order"
        source["edge_read_error"] = edge_error
    return nodes, _dedupe_edges(edges), source


def _candidate_cbm_rows(con: sqlite3.Connection, project: str, scope: dict[str, Any], architecture: str) -> list[sqlite3.Row]:
    op_name = str(scope.get("operator") or "").strip()
    op_snake = _snake_name(op_name)
    clauses = [
        "file_path not like '.understand-operator/%'",
        "file_path not like '%/tests/%'",
        "file_path not like '%/test/%'",
        "file_path not like '%/examples/%'",
        "file_path not like '%/third_party/%'",
        "file_path not like '%/build/%'",
        "file_path not like '%.md'",
        "file_path not like '%.yaml'",
        "file_path not like '%.yml'",
        "file_path not like '%.json'",
        "file_path not like '%.txt'",
        "file_path not like '%.cmake'",
        "name not like 'CMakeLists.txt'",
        "label not in ('Folder', 'Section')",
    ]
    params: list[Any] = [project]
    include_clauses: list[str] = []
    if op_snake:
        include_clauses.extend(["file_path like ?", "file_path like ?", "file_path like ?"])
        params.extend([op_snake + "/op_api/%", op_snake + "/op_host/%", op_snake + "/op_kernel/%"])
        include_clauses.extend(["qualified_name like ?", "name like ?"])
        params.extend(["%" + op_snake + "%", "%" + _camel_name(op_snake) + "%"])
    if architecture.lower() == "arch35":
        clauses.extend(["file_path not like '%/arch22/%'", "file_path not like '%/arch20/%'", "file_path not like '%/arch21/%'", "file_path not like '%/arch30/%'", "file_path not like '%/arch31/%'", "file_path not like '%/arch32/%'", "file_path not like '%/arch38/%'"])
        include_clauses.extend(["file_path like 'common/op_host/arch35/%'", "file_path like 'common/op_kernel/arch35/%'"])
    include_sql = " or ".join(include_clauses) if include_clauses else "1=1"
    sql = f"""
        select id, label, name, qualified_name, file_path, start_line, end_line
        from nodes
        where project=? and ({include_sql}) and {' and '.join(clauses)}
        order by file_path, start_line, label, name, id
    """
    return list(con.execute(sql, params))


def _candidate_cbm_edges(con: sqlite3.Connection, project: str, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    id_set = set(ids)
    edges: list[dict[str, Any]] = []
    chunk_size = 900
    for index in range(0, len(ids), chunk_size):
        chunk = ids[index : index + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = con.execute(
            f"""
            select id, source_id, target_id, type
            from edges
            where project=? and (source_id in ({placeholders}) or target_id in ({placeholders}))
            order by source_id, target_id, type, id
            """,
            [project, *chunk, *chunk],
        ).fetchall()
        for row in rows:
            source = int(row["source_id"])
            target = int(row["target_id"])
            if source not in id_set or target not in id_set:
                continue
            edges.append(
                {
                    "mcp_edge_id": f"CBM_EDGE_{int(row['id']):08d}",
                    "source": f"CBM_NODE_{source:08d}",
                    "target": f"CBM_NODE_{target:08d}",
                    "raw_type": str(row["type"]),
                    "direction_confirmed": True,
                }
            )
    return edges


def _normalize_cbm_node(row: sqlite3.Row) -> dict[str, Any]:
    path = str(row["file_path"] or "").replace("\\", "/")
    label = str(row["label"] or "unknown")
    name = str(row["name"] or "")
    qualified = str(row["qualified_name"] or "")
    symbol_text = " ".join([name, qualified])
    return {
        "mcp_node_id": f"CBM_NODE_{int(row['id']):08d}",
        "raw_type": label,
        "semantic_type": _semantic_from_cbm(label, name, qualified, path),
        "symbol": name,
        "path": path,
        "lines": f"{int(row['start_line'] or 0)}-{int(row['end_line'] or row['start_line'] or 0)}",
        "line_start": int(row["start_line"] or 0),
        "architecture_context": _architecture_context(path, symbol_text),
        "discovered_from": ["codebase-memory-mcp-sqlite"],
        "source_text": symbol_text[:240],
    }


def _semantic_from_cbm(label: str, name: str, qualified: str, path: str) -> str:
    lower = " ".join([label, name, qualified, path]).lower()
    role = _role_from_path(path)
    if "tilingkey" in lower or "tiling_key" in lower:
        return "tiling_key"
    if "tilingdata" in lower or "tiling_data" in lower:
        return "tiling_data_field" if label.lower() == "field" else "tiling_data"
    if label.lower() == "macro":
        return "macro" if role == "host" else "compile_time_constant"
    if role in {"host", "input_output"}:
        if any(token in lower for token in ("input", "query", "key", "value", "dy", "pse", "mask", "actual_seq")):
            return "input"
        if any(token in lower for token in ("attr", "scale", "dropout", "layout", "sparse", "inner_precise", "pse_type")):
            return "attribute"
        if any(token in lower for token in ("platform", "soc", "aicore", "core_num", "ub_size", "l1_size", "l0")):
            return "platform_property"
        if "workspace" in lower:
            return "workspace"
        if "blockdim" in lower or "block_dim" in lower or "numblocks" in lower:
            return "block_dim"
        if "kernel" in lower and any(token in lower for token in ("dispatch", "launch", "registry", "opimpl")):
            return "kernel_dispatch"
        if any(name.lower().startswith(prefix) for prefix in ("is", "check", "judge")):
            return "predicate"
        if any(name.lower().startswith(prefix) for prefix in ("calc", "get", "set", "init", "update", "do")):
            return "derived_variable"
        return _semantic_from_raw_type(label, path)
    if role == "kernel":
        if "kernel" in lower and label.lower() in {"class", "function", "method"}:
            return "kernel_entry"
        if any(token in lower for token in ("copyin", "copy_in", "datacopy", "load")):
            return "copy_in"
        if any(token in lower for token in ("copyout", "copy_out", "store")):
            return "copy_out"
        if any(token in lower for token in ("output", "dq", "dk", "dv", "dst")):
            return "output"
        if any(token in lower for token in ("compute", "matmul", "softmax", "mul", "add", "sub", "div", "calc", "process")):
            return "compute"
        if any(name.lower().startswith(prefix) for prefix in ("is", "check", "judge")):
            return "predicate"
        if label.lower() == "field":
            return "kernel_variable"
        return _semantic_from_raw_type(label, path)
    return _semantic_from_raw_type(label, path)


def _lexical_order_edges(nodes: list[dict[str, Any]], start_index: int) -> list[dict[str, Any]]:
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        if node.get("path") and int(node.get("line_start") or 0) > 0 and node.get("semantic_type") not in {"function", "kernel_function"}:
            by_file[node["path"]].append(node)
    edges: list[dict[str, Any]] = []
    index = start_index
    for path in sorted(by_file):
        ordered = sorted(by_file[path], key=_node_sort_key)
        for source, target in zip(ordered, ordered[1:]):
            edges.append(
                {
                    "mcp_edge_id": f"CBM_LEXICAL_EDGE_{index:08d}",
                    "source": source["mcp_node_id"],
                    "target": target["mcp_node_id"],
                    "raw_type": "cbm_lexical_order",
                    "direction_confirmed": True,
                }
            )
            index += 1
    return edges


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for edge in _sort_edges(edges):
        key = (edge["source"], edge["target"], edge["raw_type"])
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result


def _scoped_fallback_graph(repo_root: Path, scope: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fallback is intentionally limited to Phase0 confirmed files.

    It does not rediscover the repository or expand scope. It exists so Phase1
    can emit auditable graph artifacts and issues when MCP is not exposed.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    last_by_file: dict[str, str] = {}
    confirmed = [str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/") for item in scope["confirmed_file_list"]]
    for rel in sorted(path for path in confirmed if path):
        path = repo_root / rel
        if not path.exists() or not path.is_file():
            continue
        role = _role_from_path(rel)
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, text in enumerate(lines, start=1):
            semantic = _semantic_from_line(rel, text, role)
            if semantic is None:
                continue
            node_id = f"MCP_FALLBACK_NODE_{len(nodes) + 1:06d}"
            nodes.append(
                {
                    "mcp_node_id": node_id,
                    "raw_type": semantic,
                    "semantic_type": semantic,
                    "symbol": _symbol_from_line(text, semantic) or Path(rel).stem,
                    "path": rel,
                    "lines": f"{lineno}-{lineno}",
                    "line_start": lineno,
                    "architecture_context": _architecture_context(rel, text),
                    "discovered_from": ["phase0_confirmed_file"],
                    "source_text": text.strip()[:240],
                }
            )
            prev = last_by_file.get(rel)
            if prev:
                edges.append(
                    {
                        "mcp_edge_id": f"MCP_FALLBACK_EDGE_{len(edges) + 1:06d}",
                        "source": prev,
                        "target": node_id,
                        "raw_type": "lexical_next",
                        "direction_confirmed": True,
                    }
                )
            last_by_file[rel] = node_id
    return nodes, edges


def _semantic_from_line(rel: str, text: str, role: str) -> str | None:
    lower = text.lower()
    if role == "host":
        if "input" in lower or "getinput" in lower:
            return "input"
        if "attr" in lower or "getattr" in lower:
            return "attribute"
        if "platform" in lower or "soc" in lower or "aicore" in lower or "core" in lower:
            return "platform_property"
        if "tilingkey" in lower or "tiling_key" in lower or "settilingkey" in lower:
            return "tiling_key"
        if "tilingdata" in lower or "set_data" in lower or "setdata" in lower:
            return "tiling_data_write"
        if "blockdim" in lower or "block_dim" in lower:
            return "block_dim"
        if "workspace" in lower:
            return "workspace"
        if "<<<" in text or "kernel" in lower:
            return "kernel_dispatch"
        if any(token in lower for token in ("if", "switch", "case", "else")):
            return "host_branch"
        if "(" in text and ")" in text:
            return "function_call"
    if role == "kernel":
        if "__global__" in text or "kernel" in lower and "(" in text:
            return "kernel_entry"
        if "tilingdata" in lower or "get_tiling_data" in lower:
            return "tiling_data"
        if "copyin" in lower or "datacopy" in lower and "gm" in lower:
            return "copy_in"
        if "copyout" in lower or "store" in lower:
            return "copy_out"
        if any(token in lower for token in ("add", "mul", "matmul", "softmax", "compute", "sub", "div")):
            return "compute"
        if any(token in lower for token in ("if", "switch", "case", "else")):
            return "kernel_branch"
        if any(token in lower for token in ("output", "out", "dst")):
            return "output"
        if "(" in text and ")" in text:
            return "kernel_function"
    if role == "input_output" and ("input" in lower or "output" in lower or "attr" in lower):
        return "input" if "input" in lower else "output" if "output" in lower else "attribute"
    return None


def _normalize_node(item: Any, index: int) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    path = str(data.get("path") or data.get("file") or "")
    raw_type = str(data.get("raw_type") or data.get("type") or data.get("kind") or "unknown")
    return {
        "mcp_node_id": str(data.get("mcp_node_id") or data.get("node_id") or data.get("id") or f"MCP_NODE_{index:06d}"),
        "raw_type": raw_type,
        "semantic_type": str(data.get("semantic_type") or _semantic_from_raw_type(raw_type, path)),
        "symbol": str(data.get("symbol") or data.get("name") or ""),
        "path": path.replace("\\", "/"),
        "lines": str(data.get("lines") or _line_range(data)),
        "line_start": int(data.get("line_start") or data.get("start_line") or 0),
        "architecture_context": list(data.get("architecture_context") or _architecture_context(path, str(data.get("symbol") or ""))),
        "discovered_from": list(data.get("discovered_from") or []),
        "source_text": str(data.get("source_text") or ""),
    }


def _normalize_edge(item: Any, index: int) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    return {
        "mcp_edge_id": str(data.get("mcp_edge_id") or data.get("edge_id") or data.get("id") or f"MCP_EDGE_{index:06d}"),
        "source": str(data.get("source") or data.get("source_id") or ""),
        "target": str(data.get("target") or data.get("target_id") or ""),
        "raw_type": str(data.get("raw_type") or data.get("type") or data.get("relation") or "related"),
        "direction_confirmed": bool(data.get("direction_confirmed", True)),
    }


def _extract_subgraph(name: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], graph: dict[str, list[tuple[str, str]]], reverse: dict[str, list[tuple[str, str]]], roots: list[str], sinks: list[str], keep_types: set[str], limits: SearchLimits) -> dict[str, Any]:
    forward, forward_truncated = _reachable(graph, roots, limits)
    backward, backward_truncated = _reachable(reverse, sinks, limits)
    keep = (forward & backward) if sinks else forward
    node_by_id = {node["mcp_node_id"]: node for node in nodes}
    keep = {node_id for node_id in keep if node_by_id.get(node_id, {}).get("semantic_type") in keep_types}
    kept_edges = [edge for edge in edges if edge["source"] in keep and edge["target"] in keep]
    paths = _paths(graph, roots, sinks, keep, limits)
    semantic_nodes = [_semantic_node(name, node_by_id[node_id], index, paths) for index, node_id in enumerate(sorted(keep, key=lambda item: _node_sort_key(node_by_id[item])), start=1)]
    semantic_id_by_raw = {item["source_nodes"][0]: item["id"] for item in semantic_nodes if item.get("source_nodes")}
    semantic_edges = [_semantic_edge(name, edge, index, semantic_id_by_raw, paths) for index, edge in enumerate(_sort_edges(kept_edges), start=1) if edge["source"] in semantic_id_by_raw and edge["target"] in semantic_id_by_raw]
    return {
        "roots": roots,
        "sinks": sinks,
        "kept_node_ids": sorted(keep, key=lambda item: _node_sort_key(node_by_id[item])),
        "kept_edges": kept_edges,
        "nodes": semantic_nodes,
        "edges": semantic_edges,
        "paths": paths,
        "truncation": {"forward": forward_truncated, "backward": backward_truncated},
    }


def _reachable(adjacency: dict[str, list[tuple[str, str]]], roots: list[str], limits: SearchLimits) -> tuple[set[str], list[dict[str, Any]]]:
    seen: set[str] = set()
    truncated: list[dict[str, Any]] = []
    queue: deque[tuple[str, int]] = deque((root, 0) for root in roots)
    while queue:
        node_id, depth = queue.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        if len(seen) >= limits.max_total_nodes:
            truncated.append({"reason": "max_total_nodes", "limit": limits.max_total_nodes})
            break
        if depth >= limits.max_depth:
            truncated.append({"node": node_id, "reason": "max_depth", "limit": limits.max_depth})
            continue
        for next_id, _edge_id in adjacency.get(node_id, []):
            if next_id not in seen:
                queue.append((next_id, depth + 1))
    return seen, truncated


def _paths(adjacency: dict[str, list[tuple[str, str]]], roots: list[str], sinks: list[str], keep: set[str], limits: SearchLimits) -> list[dict[str, Any]]:
    sink_set = set(sinks)
    results: list[dict[str, Any]] = []
    for root in roots:
        queue: deque[tuple[str, list[str], list[str]]] = deque([(root, [root], [])])
        paths_for_root = 0
        expanded = 0
        while queue and paths_for_root < limits.max_paths_per_root:
            node_id, path_nodes, path_edges = queue.popleft()
            expanded += 1
            if expanded >= limits.max_total_nodes:
                break
            if node_id in sink_set and node_id != root:
                results.append({"id": f"PATH_{len(results) + 1:06d}", "root": root, "sink": node_id, "nodes": path_nodes, "edges": path_edges})
                paths_for_root += 1
                continue
            if len(path_nodes) > limits.max_depth:
                continue
            for next_id, edge_id in adjacency.get(node_id, []):
                if next_id not in keep or next_id in path_nodes:
                    continue
                queue.append((next_id, path_nodes + [next_id], path_edges + [edge_id]))
    return sorted(results, key=lambda item: (item["root"], item["sink"], ",".join(item["nodes"])))


def _arch_filter(nodes: list[dict[str, Any]], architecture: str) -> tuple[set[str], set[str]]:
    kept: set[str] = set()
    removed: set[str] = set()
    for node in nodes:
        text = " ".join([node.get("path", ""), node.get("symbol", ""), node.get("source_text", ""), " ".join(node.get("architecture_context") or [])])
        node_id = node["mcp_node_id"]
        if architecture.lower() == "arch35" and NON_ARCH_PATTERN.search(text) and not ARCH35_PATTERN.search(text):
            removed.add(node_id)
        else:
            kept.add(node_id)
    return kept, removed


def _payloads(repo_root: Path, op_name: str, architecture: str, scope: dict[str, Any], cbm_meta: dict[str, Any], raw_source: dict[str, Any], nodes: list[dict[str, Any]], edges: list[dict[str, Any]], host: dict[str, Any], kernel: dict[str, Any], removed_nodes: list[dict[str, Any]], removed_edges: list[dict[str, Any]], issues: list[dict[str, Any]], limits: SearchLimits) -> dict[str, Any]:
    base = {"version": 1, "op_name": op_name, "project_root": repo_root.as_posix(), "architecture": architecture}
    raw_nodes = [_raw_node_output(node, host, kernel, removed_nodes) for node in nodes]
    raw_edges = [_raw_edge_output(edge, host, kernel, removed_edges) for edge in edges]
    comparison = _comparison(base, raw_nodes, raw_edges, host, kernel, removed_nodes, removed_edges)
    return {
        "raw_candidate_graph.yaml": {**base, "source_graph": raw_source, "node_count": len(nodes), "edge_count": len(edges), "nodes": raw_nodes, "edges": raw_edges},
        "raw_candidate_nodes.yaml": {**base, "node_count": len(nodes), "nodes": raw_nodes},
        "raw_candidate_edges.yaml": {**base, "edge_count": len(edges), "edges": raw_edges},
        "host_tiling_graph.yaml": _processed_graph(base, "host_tiling", raw_source, host),
        "host_tiling_paths.yaml": {**base, "graph_type": "host_tiling", "path_count": len(host["paths"]), "paths": host["paths"], "search_limits": limits.__dict__, "truncation": host["truncation"]},
        "kernel_execution_graph.yaml": _processed_graph(base, "kernel_execution", raw_source, kernel),
        "kernel_execution_paths.yaml": {**base, "graph_type": "kernel_execution", "path_count": len(kernel["paths"]), "paths": kernel["paths"], "search_limits": limits.__dict__, "truncation": kernel["truncation"]},
        "removed_nodes.yaml": {**base, "node_count": len(removed_nodes), "nodes": removed_nodes},
        "removed_edges.yaml": {**base, "edge_count": len(removed_edges), "edges": removed_edges},
        "graph_comparison.yaml": comparison,
        "graph_pruning_report.yaml": {**base, "generated_at": datetime.now(tz=timezone.utc).isoformat(), "scope": scope, "cbm": cbm_meta, "raw_source": raw_source, "search_limits": limits.__dict__, "comparison": comparison},
        "graph_issues.yaml": {**base, "issues": _graph_issues(issues, host, kernel)},
    }


def _processed_graph(base: dict[str, Any], graph_type: str, raw_source: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "graph_type": graph_type,
        "source_graph": raw_source,
        "roots": graph["roots"],
        "sinks": graph["sinks"],
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "nodes": graph["nodes"],
        "edges": graph["edges"],
    }


def _raw_node_output(node: dict[str, Any], host: dict[str, Any], kernel: dict[str, Any], removed_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    node_id = node["mcp_node_id"]
    retained_in = []
    if node_id in host["kept_node_ids"]:
        retained_in.append("host_tiling_graph")
    if node_id in kernel["kept_node_ids"]:
        retained_in.append("kernel_execution_graph")
    removed = next((item for item in removed_nodes if item["mcp_node_id"] == node_id), None)
    return {
        "mcp_node_id": node_id,
        "raw_type": node["raw_type"],
        "semantic_type": node["semantic_type"],
        "symbol": node.get("symbol", ""),
        "path": node.get("path", ""),
        "lines": node.get("lines", ""),
        "architecture_context": node.get("architecture_context") or [],
        "discovered_from": node.get("discovered_from") or [],
        "retained": bool(retained_in),
        "retained_in": retained_in,
        "removal_reason": removed.get("removal_reason") if removed else "",
    }


def _raw_edge_output(edge: dict[str, Any], host: dict[str, Any], kernel: dict[str, Any], removed_edges: list[dict[str, Any]]) -> dict[str, Any]:
    edge_id = edge["mcp_edge_id"]
    retained_in = []
    if any(item["mcp_edge_id"] == edge_id for item in host["kept_edges"]):
        retained_in.append("host_tiling_graph")
    if any(item["mcp_edge_id"] == edge_id for item in kernel["kept_edges"]):
        retained_in.append("kernel_execution_graph")
    removed = next((item for item in removed_edges if item["mcp_edge_id"] == edge_id), None)
    return {**edge, "retained": bool(retained_in), "retained_in": retained_in, "removal_reason": removed.get("removal_reason") if removed else ""}


def _semantic_node(prefix: str, raw: dict[str, Any], index: int, paths: list[dict[str, Any]]) -> dict[str, Any]:
    raw_id = raw["mcp_node_id"]
    memberships = [path["id"] for path in paths if raw_id in path["nodes"]]
    return {
        "id": f"{prefix.upper()}_NODE_{index:06d}",
        "semantic_type": raw["semantic_type"],
        "label": raw.get("symbol") or raw["semantic_type"],
        "source_nodes": [raw_id],
        "source_locator": {"path": raw.get("path", ""), "symbol": raw.get("symbol", ""), "lines": raw.get("lines", "")},
        "architecture_context": raw.get("architecture_context") or [],
        "path_membership": memberships,
        "confidence": "medium" if raw_id.startswith("MCP_FALLBACK_") else "high",
    }


def _semantic_edge(prefix: str, raw: dict[str, Any], index: int, semantic_id_by_raw: dict[str, str], paths: list[dict[str, Any]]) -> dict[str, Any]:
    edge_id = raw["mcp_edge_id"]
    memberships = [path["id"] for path in paths if edge_id in path["edges"]]
    return {
        "id": f"{prefix.upper()}_EDGE_{index:06d}",
        "source": semantic_id_by_raw[raw["source"]],
        "target": semantic_id_by_raw[raw["target"]],
        "relation": _relation(raw["raw_type"]),
        "edge_origin": "mcp" if not edge_id.startswith("MCP_FALLBACK_") else "scoped_fallback",
        "source_edges": [edge_id],
        "derived_from_path": [raw["source"], raw["target"]],
        "path_membership": memberships,
    }


def _removed_nodes(nodes: list[dict[str, Any]], retained: set[str], arch_removed: set[str], host: dict[str, Any], kernel: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        node_id = node["mcp_node_id"]
        if node_id in retained:
            continue
        reason = "non_arch35_branch" if node_id in arch_removed else "cannot_reach_sink"
        if node_id not in set(host["roots"] + kernel["roots"]) and not host["sinks"] and not kernel["sinks"]:
            reason = "unreachable_from_root"
        result.append({"mcp_node_id": node_id, "symbol": node.get("symbol", ""), "path": node.get("path", ""), "removal_stage": "architecture_filter" if node_id in arch_removed else "reachability_pruning", "removal_reason": reason})
    return sorted(result, key=lambda item: (item["path"], item["symbol"], item["mcp_node_id"]))


def _removed_edges(edges: list[dict[str, Any]], retained_nodes: set[str], retained_edges: set[str]) -> list[dict[str, Any]]:
    result = []
    for edge in edges:
        if edge["mcp_edge_id"] in retained_edges:
            continue
        reason = "target_node_removed" if edge["target"] not in retained_nodes else "source_node_removed" if edge["source"] not in retained_nodes else "cannot_reach_sink"
        result.append({"mcp_edge_id": edge["mcp_edge_id"], "source": edge["source"], "target": edge["target"], "raw_type": edge["raw_type"], "removal_stage": "reachability_pruning", "removal_reason": reason})
    return sorted(result, key=lambda item: (item["source"], item["target"], item["raw_type"], item["mcp_edge_id"]))


def _comparison(base: dict[str, Any], raw_nodes: list[dict[str, Any]], raw_edges: list[dict[str, Any]], host: dict[str, Any], kernel: dict[str, Any], removed_nodes: list[dict[str, Any]], removed_edges: list[dict[str, Any]]) -> dict[str, Any]:
    raw_node_count = len(raw_nodes)
    raw_edge_count = len(raw_edges)
    removed_node_count = len(removed_nodes)
    removed_edge_count = len(removed_edges)
    summary: dict[str, dict[str, int]] = defaultdict(lambda: {"nodes": 0, "edges": 0})
    for node in removed_nodes:
        summary[node["removal_reason"]]["nodes"] += 1
    for edge in removed_edges:
        summary[edge["removal_reason"]]["edges"] += 1
    return {
        **base,
        "raw_candidate_graph": {"nodes": raw_node_count, "edges": raw_edge_count},
        "after_arch35_filter": {"nodes": raw_node_count - sum(1 for item in removed_nodes if item["removal_reason"] == "non_arch35_branch"), "edges": raw_edge_count},
        "host_tiling_graph": {"nodes": len(host["nodes"]), "edges": len(host["edges"]), "paths": len(host["paths"])},
        "kernel_execution_graph": {"nodes": len(kernel["nodes"]), "edges": len(kernel["edges"]), "paths": len(kernel["paths"])},
        "removed": {"nodes": removed_node_count, "edges": removed_edge_count},
        "reduction": {
            "node_reduction_count": removed_node_count,
            "node_reduction_ratio": round(removed_node_count / raw_node_count, 4) if raw_node_count else 0,
            "edge_reduction_count": removed_edge_count,
            "edge_reduction_ratio": round(removed_edge_count / raw_edge_count, 4) if raw_edge_count else 0,
        },
        "removal_summary": dict(sorted(summary.items())),
    }


def _graph_issues(issues: list[dict[str, Any]], host: dict[str, Any], kernel: dict[str, Any]) -> list[dict[str, Any]]:
    result = list(issues)
    if not host["paths"]:
        result.append({"issue": "missing_host_path", "severity": "warning", "reason": "No retained path from Host roots to Host sinks."})
    if not kernel["paths"]:
        result.append({"issue": "missing_kernel_path", "severity": "warning", "reason": "No retained path from Kernel roots to Kernel sinks."})
    if not any(node["semantic_type"] == "tiling_key" for node in host["nodes"] + kernel["nodes"]):
        result.append({"issue": "missing_tiling_key", "severity": "warning", "reason": "No tiling_key node retained."})
    return result


def _adjacency(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    ids = {node["mcp_node_id"] for node in nodes}
    graph: dict[str, list[tuple[str, str]]] = {node_id: [] for node_id in ids}
    for edge in edges:
        if edge["source"] in ids and edge["target"] in ids:
            graph[edge["source"]].append((edge["target"], edge["mcp_edge_id"]))
    for values in graph.values():
        values.sort()
    return graph


def _reverse_adjacency(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    ids = {node["mcp_node_id"] for node in nodes}
    graph: dict[str, list[tuple[str, str]]] = {node_id: [] for node_id in ids}
    for edge in edges:
        if edge["source"] in ids and edge["target"] in ids:
            graph[edge["target"]].append((edge["source"], edge["mcp_edge_id"]))
    for values in graph.values():
        values.sort()
    return graph


def _role_from_path(path: str) -> str:
    lower = path.lower()
    if "op_host" in lower or "tiling" in lower:
        return "host"
    if "op_kernel" in lower or "kernel" in lower:
        return "kernel"
    if "op_api" in lower or "op_graph" in lower or "proto" in lower:
        return "input_output"
    return "other"


def _snake_name(value: str) -> str:
    text = value.replace("-", "_").replace(" ", "_")
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", text).lower()
    return re.sub(r"_+", "_", text).strip("_")


def _camel_name(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in value.split("_") if part)


def _architecture_context(path: str, text: str) -> list[str]:
    joined = f"{path} {text}"
    if ARCH35_PATTERN.search(joined):
        return ["arch35"]
    match = NON_ARCH_PATTERN.search(joined)
    return [match.group(0).lower()] if match else []


def _symbol_from_line(text: str, semantic: str) -> str:
    func = re.search(r"([A-Za-z_][A-Za-z0-9_:<>]*)\s*\(", text)
    if func:
        return func.group(1)
    assign = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|\.|->)", text)
    if assign:
        return assign.group(1)
    return semantic


def _semantic_from_raw_type(raw_type: str, path: str) -> str:
    lower = raw_type.lower()
    if lower in HOST_KEEP_TYPES | KERNEL_KEEP_TYPES:
        return lower
    if "call" in lower:
        return "function_call"
    if "branch" in lower or "condition" in lower:
        return "predicate"
    return "kernel_function" if _role_from_path(path) == "kernel" else "function"


def _relation(raw_type: str) -> str:
    lower = raw_type.lower()
    if "data" in lower or "flow" in lower or "lexical" in lower:
        return "flows_to"
    if "call" in lower:
        return "calls"
    if "control" in lower:
        return "controls"
    return "relates_to"


def _line_range(data: dict[str, Any]) -> str:
    start = data.get("start_line") or data.get("line") or ""
    end = data.get("end_line") or start
    return f"{start}-{end}" if start else ""


def _sort_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(nodes, key=_node_sort_key)


def _node_sort_key(node: dict[str, Any]) -> tuple[str, int, str, str]:
    return (str(node.get("path") or ""), int(node.get("line_start") or 0), str(node.get("symbol") or ""), str(node.get("mcp_node_id") or ""))


def _sort_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(edges, key=lambda edge: (str(edge.get("source") or ""), str(edge.get("target") or ""), str(edge.get("raw_type") or ""), str(edge.get("mcp_edge_id") or "")))


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _print_summary(result: dict[str, Any], *, node_limit: int, edge_limit: int, show_raw: bool, show_processed: bool) -> None:
    comparison = result["graph_comparison.yaml"]
    print("Phase1 图裁剪测试完成")
    print(f"测试项目：{comparison['project_root']}")
    print(f"分析架构：{comparison['architecture']}")
    raw_source = result["raw_candidate_graph.yaml"]["source_graph"]
    print(f"MCP 项目：{raw_source.get('cbm_project') or '<unknown>'}")
    print(f"原始候选图：节点 {comparison['raw_candidate_graph']['nodes']}，边 {comparison['raw_candidate_graph']['edges']}")
    print(f"arch35 过滤后：节点 {comparison['after_arch35_filter']['nodes']}，边 {comparison['after_arch35_filter']['edges']}")
    print(f"Host/Tiling 图：节点 {comparison['host_tiling_graph']['nodes']}，边 {comparison['host_tiling_graph']['edges']}，路径 {comparison['host_tiling_graph']['paths']}")
    print(f"Kernel 执行图：节点 {comparison['kernel_execution_graph']['nodes']}，边 {comparison['kernel_execution_graph']['edges']}，路径 {comparison['kernel_execution_graph']['paths']}")
    print(f"删除：节点 {comparison['removed']['nodes']}，边 {comparison['removed']['edges']}")
    print(f"输出目录：{result['graph_dir']}")
    if show_raw:
        _preview("原始节点", result["raw_candidate_nodes.yaml"]["nodes"], ["mcp_node_id", "raw_type", "symbol", "path", "lines", "retained", "removal_reason"], node_limit)
        _preview("原始边", result["raw_candidate_edges.yaml"]["edges"], ["mcp_edge_id", "source", "raw_type", "target", "retained", "removal_reason"], edge_limit)
    if show_processed:
        _preview("Host/Tiling 处理后节点", result["host_tiling_graph.yaml"]["nodes"], ["id", "semantic_type", "label", "source_nodes", "source_locator"], node_limit)
        _preview("Host/Tiling 处理后边", result["host_tiling_graph.yaml"]["edges"], ["id", "source", "relation", "target", "source_edges"], edge_limit)
        _preview("Kernel 处理后节点", result["kernel_execution_graph.yaml"]["nodes"], ["id", "semantic_type", "label", "source_nodes", "source_locator"], node_limit)
        _preview("Kernel 处理后边", result["kernel_execution_graph.yaml"]["edges"], ["id", "source", "relation", "target", "source_edges"], edge_limit)


def _preview(title: str, rows: list[dict[str, Any]], fields: list[str], limit: int) -> None:
    print(f"\n[{title}]")
    print(" | ".join(fields))
    for row in rows[:limit]:
        print(" | ".join(_cell(row.get(field)) for field in fields))


def _cell(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
