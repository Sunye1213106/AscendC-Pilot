from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, snippet, stable_id, write_yaml
from uo.scripts.cbm_client import CbmClient, read_source_snippet

KEEP_HELPERS = {
    "processoptionalinput",
    "setsplitaxis",
    "dosplit",
    "dosparse",
    "checkexceedl2cache",
    "determinemode",
    "inittilingdata",
    "gettilingkey",
    "savetotilingdata",
    "settilingkey",
    "setblockdim",
    "setworkspacesize",
    "posttiling",
    "dopretiling",
    "doposttiling",
}

IF_RE = re.compile(r"\bif\s*(?:constexpr\s*)?\((.+?)\)\s*\{", re.DOTALL)
# Only direct writes onto tiling data / *Params_ receivers (not host intermediates like fBaseParams).
FIELD_WRITE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:tilingData|tiling_data|"
    r"(?:s1s2|split|block|pre|post|deter|tnd)\w*Params_?|baseParams_?)"
    r"(?:->|\.)\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*=",
    re.IGNORECASE,
)
# AscendC TilingData writers are usually set_fieldName(...)
SET_FIELD_RE = re.compile(r"\bset_([A-Za-z_][A-Za-z0-9_]*)\s*\(")
TILING_SETTER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:tilingData|tiling_data|"
    r"(?:s1s2|split|block|pre|post|deter|tnd)\w*Params_?|baseParams_?)"
    r"(?:->|\.)\s*set_([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
HOST_INTERMEDIATE_ROOTS = frozenset(
    {
        "fbaseparams",
        "tndbaseinfo",
        "baseinfo",
        "splitinfo",
        "fuzzybaseinfoparamsregbase",
    }
)
WRITES_TILING_HELPERS = frozenset(
    {
        "savetotilingdata",
        "inittilingdata",
        "settilingdata",
    }
)
HELPER_CALL_RE = re.compile(
    r"\b(ProcessOptionalInput|SetSplitAxis|DoSplit|DoSparse|CheckExceedL2Cache|"
    r"DetermineMode|InitTilingData|GetTilingKey|SaveToTilingData|SetTilingKey|"
    r"SetBlockDim|SetWorkspaceSize|PostTiling|DoPreTiling|DoPostTiling)\s*\("
)
ATTR_RE = re.compile(r"GetAttr(?:Optional)?\s*<[^>]*>\s*\(\s*\"([^\"]+)\"")
INPUT_RE = re.compile(r"Get(?:Optional)?Input(?:Desc|Shape|Dtype)?\s*\(\s*([^\)]+)\)")
PLATFORM_RE = re.compile(r"\b(ubSize|l1Size|l0[abc]Size|coreNum|aicNum|aivNum|socVersion|l2CacheSize)\b")


def extract_host_subgraph(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    entrypoints = read_yaml(uo_root / "ir" / "entrypoints.yaml")
    roles = entrypoints.get("roles") or {}
    root_role = roles.get("host_tiling_entry") or {}
    selected = root_role.get("selected")
    unresolved: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # seed inputs / platform placeholders
    for name in ("Input", "OptionalInputPresence", "Attribute", "InputShape", "InputDType", "InputLayout", "PlatformInfo", "CompileTimeConfig"):
        nodes.append(
            {
                "id": stable_id("HOST_START_", name),
                "layer": "host",
                "node_type": name,
                "name": name,
                "qualified_name": name,
                "file_path": "",
                "start_line": 0,
                "end_line": 0,
            }
        )

    if not selected:
        unresolved.append(
            {
                "id": "UNRES_HOST_ENTRY",
                "kind": "entrypoint_missing",
                "message": "host_tiling_entry not confirmed",
                "file_path": "",
                "snippet": "",
            }
        )
        return _payload(op_name, architecture, nodes, edges, unresolved)

    client = CbmClient(uo_root)
    root_sym = None
    if client.available and selected.get("qualified_name"):
        root_sym = client.resolve_qn(selected["qualified_name"], file_contains=architecture)
        if root_sym is None and selected.get("name"):
            root_sym = client.resolve_qn(selected["name"], file_contains=architecture)

    chain: list[dict[str, Any]] = []
    if root_sym is not None:
        traced = client.bounded_trace(root_sym, keep_names=KEEP_HELPERS, max_depth=5, max_nodes=60)
        for sym in traced:
            chain.append(sym.as_dict())
    else:
        chain.append(selected)

    # always include confirmed bridge writers if present
    for role in ("get_tiling_key", "save_tiling_data", "init_tiling_data"):
        sel = (roles.get(role) or {}).get("selected")
        if sel and not any(item.get("qualified_name") == sel.get("qualified_name") for item in chain):
            chain.append(sel)

    # CBM CALLS often miss helpers invoked from DoOpTiling body; seed from source text.
    entry_body = read_source_snippet(
        repo_root,
        str(selected.get("file_path") or ""),
        int(selected.get("start_line") or 0),
        int(selected.get("end_line") or selected.get("start_line") or 0) + 200,
        pad=0,
    )
    for helper_name in HELPER_CALL_RE.findall(entry_body):
        if any(str(item.get("name") or "") == helper_name for item in chain):
            continue
        hit = None
        if client.available:
            hit = client.resolve_qn(helper_name, file_contains=architecture)
        if hit is not None:
            chain.append(hit.as_dict())
        else:
            chain.append(
                {
                    "name": helper_name,
                    "qualified_name": helper_name,
                    "file_path": selected.get("file_path") or "",
                    "start_line": selected.get("start_line") or 0,
                    "end_line": selected.get("end_line") or 0,
                    "label": "helper_call_seed",
                }
            )

    prev_branch_id = None
    for item in chain:
        file_path = str(item.get("file_path") or "")
        start = int(item.get("start_line") or 0)
        end = int(item.get("end_line") or start)
        body, start, end = _helper_body(repo_root, file_path, item, start, end)
        helper_id = stable_id("HOST_HELPER_", item.get("name") or "fn")
        nodes.append(
            {
                "id": helper_id,
                "layer": "host",
                "node_type": "HelperCall",
                "name": item.get("name"),
                "qualified_name": item.get("qualified_name"),
                "file_path": file_path,
                "start_line": start,
                "end_line": end,
            }
        )
        if prev_branch_id:
            edges.append({"id": stable_id("E_", prev_branch_id, helper_id), "type": "branch_selects", "source": prev_branch_id, "target": helper_id})

        for attr in ATTR_RE.findall(body):
            attr_id = stable_id("HOST_ATTR_", attr)
            nodes.append({"id": attr_id, "layer": "host", "node_type": "Attribute", "name": attr, "qualified_name": attr, "file_path": file_path, "start_line": start, "end_line": end})
            edges.append({"id": stable_id("E_", attr_id, helper_id), "type": "derives", "source": attr_id, "target": helper_id})

        for plat in sorted(set(PLATFORM_RE.findall(body))):
            plat_id = stable_id("HOST_PLAT_", plat)
            nodes.append({"id": plat_id, "layer": "host", "node_type": "PlatformInfo", "name": plat, "qualified_name": plat, "file_path": file_path, "start_line": start, "end_line": end})
            edges.append({"id": stable_id("E_", plat_id, helper_id), "type": "derives", "source": plat_id, "target": helper_id})

        for idx, cond in enumerate(IF_RE.findall(body)):
            cond_s = " ".join(cond.split())
            pred_id = stable_id("HOST_PRED_", item.get("name") or "fn", str(idx))
            branch_id = stable_id("HOST_BR_", item.get("name") or "fn", str(idx))
            nodes.append(
                {
                    "id": pred_id,
                    "layer": "host",
                    "node_type": "Predicate",
                    "name": f"{item.get('name')}_pred_{idx}",
                    "qualified_name": f"{item.get('qualified_name')}#pred{idx}",
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                    "condition": cond_s,
                    "binding_time": "compile_time" if "constexpr" in body[body.find(cond): body.find(cond) + 40] else "runtime",
                }
            )
            nodes.append(
                {
                    "id": branch_id,
                    "layer": "host",
                    "node_type": "HostBranch",
                    "name": f"{item.get('name')}_branch_{idx}",
                    "qualified_name": f"{item.get('qualified_name')}#branch{idx}",
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                    "condition": cond_s,
                }
            )
            edges.append({"id": stable_id("E_", helper_id, pred_id), "type": "predicate_of", "source": helper_id, "target": pred_id})
            edges.append({"id": stable_id("E_", pred_id, branch_id), "type": "branch_selects", "source": pred_id, "target": branch_id})
            if len(cond_s) < 4 or "?" in cond_s and len(cond_s) > 180:
                unresolved.append(
                    {
                        "id": stable_id("UNRES_PRED_", item.get("name") or "fn", str(idx)),
                        "kind": "predicate_semantics_unclear",
                        "message": "Host predicate needs semantic labeling",
                        "file_path": file_path,
                        "start_line": start,
                        "snippet": snippet(cond_s),
                        "target_node": pred_id,
                    }
                )
            prev_branch_id = branch_id

        name_l = str(item.get("name") or "").lower()
        if "gettilingkey" in name_l or "settilingkey" in name_l:
            key_id = "KEY_TILINGKEY"
            nodes.append({"id": key_id, "layer": "bridge", "node_type": "TilingKey", "name": "TilingKey", "qualified_name": item.get("qualified_name"), "file_path": file_path, "start_line": start, "end_line": end})
            src = prev_branch_id or helper_id
            edges.append({"id": stable_id("E_", src, key_id), "type": "writes", "source": src, "target": key_id})
        writes_tiling_data = name_l in WRITES_TILING_HELPERS or any(
            token == name_l for token in ("savetotilingdata", "settilingdata", "inittilingdata")
        )
        if writes_tiling_data:
            fields = list(TILING_SETTER_RE.findall(body)) + list(SET_FIELD_RE.findall(body)) + list(FIELD_WRITE_RE.findall(body))
            if not fields and name_l in WRITES_TILING_HELPERS:
                fields = ["base_params", "split_core", "block_list"]
            seen_fields: set[str] = set()
            for field in fields:
                field_name = field.split(".")[-1]
                root = field.split(".")[0].casefold()
                if root in HOST_INTERMEDIATE_ROOTS:
                    continue
                key = field_name.casefold()
                if not field_name or key in seen_fields:
                    continue
                seen_fields.add(key)
                tdf_id = stable_id("TDF_", field_name)
                nodes.append(
                    {
                        "id": tdf_id,
                        "layer": "bridge",
                        "node_type": "TilingDataField",
                        "name": field_name,
                        "qualified_name": field if "." in field else field_name,
                        "file_path": file_path,
                        "start_line": start,
                        "end_line": end,
                    }
                )
                src = prev_branch_id or helper_id
                edges.append({"id": stable_id("E_", src, tdf_id), "type": "writes", "source": src, "target": tdf_id})
        if "setblockdim" in name_l or "blockdim" in body.lower():
            node_id = "BRIDGE_BLOCKDIM"
            nodes.append({"id": node_id, "layer": "bridge", "node_type": "BlockDim", "name": "BlockDim", "qualified_name": "BlockDim", "file_path": file_path, "start_line": start, "end_line": end})
            edges.append({"id": stable_id("E_", helper_id, node_id), "type": "sets", "source": helper_id, "target": node_id})
        if "workspace" in name_l or "workspace" in body.lower():
            node_id = "BRIDGE_WORKSPACE"
            nodes.append({"id": node_id, "layer": "bridge", "node_type": "Workspace", "name": "Workspace", "qualified_name": "Workspace", "file_path": file_path, "start_line": start, "end_line": end})
            edges.append({"id": stable_id("E_", helper_id, node_id), "type": "reserves", "source": helper_id, "target": node_id})

    # kernel dispatch candidate bridge
    nodes.append({"id": "BRIDGE_KERNEL_DISPATCH", "layer": "bridge", "node_type": "KernelDispatch", "name": "KernelDispatch", "qualified_name": "KernelDispatch", "file_path": "", "start_line": 0, "end_line": 0})
    if any(n.get("id") == "KEY_TILINGKEY" for n in nodes):
        edges.append({"id": "E_KEY_TO_DISPATCH", "type": "dispatches", "source": "KEY_TILINGKEY", "target": "BRIDGE_KERNEL_DISPATCH"})

    client.close()
    return _payload(op_name, architecture, _dedupe_nodes(nodes), _dedupe_edges(edges), unresolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract host tiling subgraph into layered IR nodes/edges")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = extract_host_subgraph(repo_root, op_name, architecture=args.architecture)
    if args.write:
        write_yaml(existing_operator_root(repo_root, op_name) / "ir" / "host_subgraph.yaml", payload)
    print(f"host nodes={len(payload['nodes'])} edges={len(payload['edges'])} unresolved={len(payload['unresolved'])}")
    return 0


def _helper_body(repo_root: Path, file_path: str, item: dict[str, Any], start: int, end: int) -> tuple[str, int, int]:
    """Prefer function definition body for SaveToTilingData-like helpers (CBM often points at call sites)."""
    name = str(item.get("name") or "")
    name_l = name.lower()
    body = read_source_snippet(repo_root, file_path, start, max(end, start + 120), pad=0)
    if name_l not in WRITES_TILING_HELPERS:
        return body, start, end
    # Call-site heuristic: body contains Foo( but not a definition opening with {
    if f"{name}(" in body and f"::{name}(" not in body and "set_" not in body:
        resolved = _find_definition_in_file(repo_root, file_path, name)
        if resolved is not None:
            def_start, def_end, def_body = resolved
            return def_body, def_start, def_end
    # Even at a definition, expand window for long SaveToTilingData bodies
    if "set_" not in body:
        expanded = read_source_snippet(repo_root, file_path, start, start + 400, pad=0)
        if "set_" in expanded:
            return expanded, start, start + 400
    return body, start, end


def _find_definition_in_file(repo_root: Path, file_path: str, name: str) -> tuple[int, int, str] | None:
    path = Path(file_path)
    if not path.is_absolute():
        path = repo_root / file_path
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    # Match Class::SaveToTilingData(...) {  or  void SaveToTilingData(...) {
    pattern = re.compile(
        rf"^([^\n]*\b{re.escape(name)}\s*\([^;]*\)\s*(?:const\s*)?\{{)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None
    def_start = text.count("\n", 0, match.start()) + 1
    # Scan forward ~500 lines for setters
    def_end = min(len(text.splitlines()), def_start + 500)
    body = read_source_snippet(repo_root, file_path, def_start, def_end, pad=0)
    return def_start, def_end, body


def _payload(op_name: str, architecture: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], unresolved: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "layer": "host",
        "nodes": nodes,
        "edges": edges,
        "unresolved": unresolved,
    }


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in nodes:
        out[str(node.get("id"))] = node
    return list(out.values())


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for edge in edges:
        out[str(edge.get("id"))] = edge
    return list(out.values())


if __name__ == "__main__":
    raise SystemExit(main())
