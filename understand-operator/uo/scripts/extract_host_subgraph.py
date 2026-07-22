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
from uo.scripts.cbm_client import CbmClient
from uo.scripts.extract_plan_io import (
    load_extract_plan,
    plan_chain_names,
    plan_non_sink_roots,
    plan_tiling_sink_receivers,
    plan_tiling_writer_names,
)
from uo.scripts.function_body import extract_callee_names, resolve_helper_body
from uo.scripts.macro_regions import analyze_macros, classify_macro_condition
from uo.scripts.source_path import resolve_repo_source_path

IF_RE = re.compile(r"\bif\s*(?:constexpr\s*)?\((.+?)\)\s*\{", re.DOTALL)
MACRO_IF_RE = re.compile(r"^\s*#\s*if(?:n?def)?\s+(.+)$", re.MULTILINE)
# Generic tilingData / tiling_data field assigns
FIELD_WRITE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:tilingData|tiling_data)"
    r"(?:->|\.)\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*=",
    re.IGNORECASE,
)
SET_FIELD_RE = re.compile(r"\bset_([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# Any receiver leaf: recv->set_field( or recv.set_field(
RECV_SETTER_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*set_([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
NOISE_CALLS = frozenset(
    {
        "GetAttr",
        "GetAttrOptional",
        "GetInputDesc",
        "GetInputShape",
        "GetInputDtype",
        # Optional input APIs are instantiated below (not noise).
        "OP_LOGI",
        "OP_LOGD",
        "OP_LOGW",
        "OP_LOGE",
        "ASCENDC_ASSERT",
        "sizeof",
        "static_cast",
        "dynamic_cast",
        "const_cast",
        "reinterpret_cast",
    }
)
ATTR_RE = re.compile(r"GetAttr(?:Optional)?\s*<[^>]*>\s*\(\s*\"([^\"]+)\"")
# GetOptionalInputDesc(3) / GetOptionalInputShape("pse") / GetOptionalInputDesc(IDX_PSE)
OPTIONAL_INPUT_RE = re.compile(
    r"\bGetOptionalInput(?:Desc|Shape|Dtype)\s*(?:<[^>]*>)?\s*\(\s*"
    r"(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))\s*\)"
)
PLATFORM_RE = re.compile(r"\b(ubSize|l1Size|l0[abc]Size|coreNum|aicNum|aivNum|socVersion|l2CacheSize)\b")
BRIDGE_ROLE_HINTS = frozenset({"get_tiling_key", "save_tiling_data", "init_tiling_data"})


def extract_host_subgraph(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    allow_empty_plan: bool = False,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    entrypoints = read_yaml(uo_root / "ir" / "entrypoints.yaml")
    roles = entrypoints.get("roles") or {}
    root_role = roles.get("host_tiling_entry") or {}
    selected = root_role.get("selected")
    unresolved: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for name in (
        "Input",
        "OptionalInputPresence",
        "Attribute",
        "InputShape",
        "InputDType",
        "InputLayout",
        "PlatformInfo",
        "CompileTimeConfig",
    ):
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

    plan = load_extract_plan(uo_root)
    if plan is None and not allow_empty_plan:
        unresolved.append(
            {
                "id": "UNRES_EXTRACT_PLAN_MISSING",
                "kind": "extract_plan_missing",
                "message": "ir/extract_plan.yaml missing; propose+LLM confirm before host TDF writes",
                "file_path": "",
                "snippet": "",
            }
        )
        # Fail soft: still emit helper chain structure without TDF write edges.
        plan = {"writers": [], "receivers": [], "aliases": [], "non_sink_roots": []}

    writer_keep = plan_chain_names(plan) if plan else set()
    tiling_writers = plan_tiling_writer_names(plan) if plan else set()
    sink_recvs = plan_tiling_sink_receivers(plan) if plan else set()
    non_sink_roots = plan_non_sink_roots(plan) if plan else set()
    # Also treat receivers with is_tiling_sink false as non-sink roots
    for item in (plan or {}).get("receivers") or []:
        if isinstance(item, dict) and item.get("is_tiling_sink") is False:
            n = str(item.get("name") or "").strip()
            if n:
                non_sink_roots.add(n.casefold())

    writer_roles = {
        str(w.get("name") or "").casefold(): str(w.get("role") or "")
        for w in (plan or {}).get("writers") or []
        if isinstance(w, dict)
    }

    client = CbmClient(uo_root)
    root_sym = None
    if client.available and selected.get("qualified_name"):
        root_sym = client.resolve_qn(selected["qualified_name"], file_contains=architecture)
        if root_sym is None and selected.get("name"):
            root_sym = client.resolve_qn(selected["name"], file_contains=architecture)

    chain: list[dict[str, Any]] = []
    keep_for_trace = {n for n in writer_keep if n} | {
        str(selected.get("name") or "").casefold()
    }
    if root_sym is not None:
        traced = client.bounded_trace(
            root_sym,
            keep_names=keep_for_trace or None,
            max_depth=5,
            max_nodes=60,
        )
        for sym in traced:
            chain.append(sym.as_dict())
    else:
        chain.append(selected)

    for role in BRIDGE_ROLE_HINTS:
        sel = (roles.get(role) or {}).get("selected")
        if sel and not any(item.get("qualified_name") == sel.get("qualified_name") for item in chain):
            chain.append(sel)

    # Seed helpers named in plan chain roles + entry-body CamelCase calls
    entry_body, _, _ = resolve_helper_body(repo_root, selected, prefer_definition=True)
    seed_names: list[str] = []
    for item in (plan or {}).get("writers") or []:
        if isinstance(item, dict) and str(item.get("role") or "") in {
            "tiling_writer",
            "key_writer",
            "workspace_writer",
            "provenance_helper",
        }:
            n = str(item.get("name") or "").strip()
            if n:
                seed_names.append(n)
    for helper_name in extract_callee_names(entry_body, noise=NOISE_CALLS):
        if helper_name.casefold() in writer_keep or not writer_keep:
            seed_names.append(helper_name)
    for helper_name in seed_names:
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

    # Optional extra host entries from plan
    for entry in (plan or {}).get("extra_host_entries") or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            meta = entry
        else:
            name = str(entry).strip()
            meta = {"name": name}
        if not name:
            continue
        if any(str(item.get("name") or "") == name for item in chain):
            continue
        hit = None
        if client.available:
            hit = client.resolve_qn(name, file_contains=architecture)
        chain.append(hit.as_dict() if hit is not None else meta)

    prev_branch_id = None
    # Optional KEY index for host macro provenance (best-effort).
    key_index: dict = {}
    try:
        from uo.scripts.provenance import load_key_dimension_index, load_tilingkey_space

        key_index = load_key_dimension_index(
            load_tilingkey_space(uo_root, repo_root, op_name, architecture=architecture)
        )
    except Exception:
        key_index = {}

    file_macro_cache: dict[str, Any] = {}
    soft_undefined = {str(k) for k in (key_index or {})}

    for item in chain:
        file_path = str(item.get("file_path") or "")
        name_l = str(item.get("name") or "").casefold()
        role = writer_roles.get(name_l, "")
        prefer_def = True  # always brace-bound when definition exists; else tight window
        body, start, end = resolve_helper_body(repo_root, item, prefer_definition=prefer_def)
        file_path = str(item.get("file_path") or file_path)

        macro_info = file_macro_cache.get(file_path)
        if macro_info is None:
            resolved = resolve_repo_source_path(repo_root, file_path)
            if resolved is not None:
                try:
                    macro_info = analyze_macros(
                        resolved.read_text(encoding="utf-8", errors="ignore"),
                        soft_undefined=soft_undefined,
                    )
                except OSError:
                    macro_info = analyze_macros("", soft_undefined=soft_undefined)
            else:
                macro_info = analyze_macros(body, soft_undefined=soft_undefined)
            file_macro_cache[file_path] = macro_info

        # Blank preprocessor-dead lines inside the helper span for if/set scans.
        body_lines = body.splitlines()
        scan_lines: list[str] = []
        for i, line_text in enumerate(body_lines):
            abs_line = start + i
            if macro_info.is_active_line(abs_line):
                scan_lines.append(line_text)
            else:
                scan_lines.append("")
        scan_body = "\n".join(scan_lines)

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
            edges.append(
                {
                    "id": stable_id("E_", prev_branch_id, helper_id),
                    "type": "branch_selects",
                    "source": prev_branch_id,
                    "target": helper_id,
                }
            )

        # Host preprocessor branches overlapping this helper
        for directive in macro_info.directives:
            if directive.kind not in {"if", "ifdef", "ifndef", "elif"}:
                continue
            if directive.line < start or directive.line > end:
                continue
            cond = directive.condition or directive.name or ""
            source, ref, domain = classify_macro_condition(cond, key_index=key_index or None)
            macro_id = stable_id("HOST_MACRO_", item.get("name") or "fn", str(directive.line))
            node = {
                "id": macro_id,
                "layer": "host",
                "node_type": "HostMacroBranch",
                "name": f"{item.get('name')}_macro_{directive.line}",
                "qualified_name": f"{item.get('qualified_name')}#macro{directive.line}",
                "file_path": file_path,
                "start_line": directive.line,
                "end_line": directive.line,
                "condition": cond,
                "binding_time": "compile_time",
                "determinant_source": source,
                "determinant_ref": ref,
                "domain": domain,
            }
            if directive.eval_result is not None:
                node["macro_eval"] = bool(directive.eval_result)
            nodes.append(node)
            edges.append(
                {
                    "id": stable_id("E_", helper_id, macro_id),
                    "type": "contains",
                    "source": helper_id,
                    "target": macro_id,
                }
            )

        for attr in ATTR_RE.findall(scan_body):
            attr_id = stable_id("HOST_ATTR_", attr)
            nodes.append(
                {
                    "id": attr_id,
                    "layer": "host",
                    "node_type": "Attribute",
                    "name": attr,
                    "qualified_name": attr,
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                }
            )
            edges.append(
                {
                    "id": stable_id("E_", attr_id, helper_id),
                    "type": "derives",
                    "source": attr_id,
                    "target": helper_id,
                }
            )

        for opt_match in OPTIONAL_INPUT_RE.finditer(scan_body):
            opt_name = (opt_match.group(1) or opt_match.group(2) or "").strip()
            if not opt_name:
                continue
            opt_id = stable_id("HOST_OPT_", opt_name)
            nodes.append(
                {
                    "id": opt_id,
                    "layer": "host",
                    "node_type": "OptionalInput",
                    "name": opt_name,
                    "qualified_name": opt_name,
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                }
            )
            edges.append(
                {
                    "id": stable_id("E_", opt_id, helper_id),
                    "type": "derives",
                    "source": opt_id,
                    "target": helper_id,
                }
            )
            # Link category stub → instance for walk roots
            opt_start = stable_id("HOST_START_", "OptionalInputPresence")
            edges.append(
                {
                    "id": stable_id("E_", opt_start, opt_id),
                    "type": "derives",
                    "source": opt_start,
                    "target": opt_id,
                }
            )

        for plat in sorted(set(PLATFORM_RE.findall(scan_body))):
            plat_id = stable_id("HOST_PLAT_", plat)
            nodes.append(
                {
                    "id": plat_id,
                    "layer": "host",
                    "node_type": "PlatformInfo",
                    "name": plat,
                    "qualified_name": plat,
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                }
            )
            edges.append(
                {
                    "id": stable_id("E_", plat_id, helper_id),
                    "type": "derives",
                    "source": plat_id,
                    "target": helper_id,
                }
            )

        for idx, cond in enumerate(IF_RE.findall(scan_body)):
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
                    "binding_time": "compile_time"
                    if "constexpr" in scan_body[scan_body.find(cond) : scan_body.find(cond) + 40]
                    else "runtime",
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
            edges.append(
                {
                    "id": stable_id("E_", helper_id, pred_id),
                    "type": "predicate_of",
                    "source": helper_id,
                    "target": pred_id,
                }
            )
            edges.append(
                {
                    "id": stable_id("E_", pred_id, branch_id),
                    "type": "branch_selects",
                    "source": pred_id,
                    "target": branch_id,
                }
            )
            if len(cond_s) < 4 or ("?" in cond_s and len(cond_s) > 180):
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

        if role == "key_writer" or "tilingkey" in name_l or "gettilingkey" in name_l or "settilingkey" in name_l:
            key_id = "KEY_TILINGKEY"
            nodes.append(
                {
                    "id": key_id,
                    "layer": "bridge",
                    "node_type": "TilingKey",
                    "name": "TilingKey",
                    "qualified_name": item.get("qualified_name"),
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                }
            )
            src = prev_branch_id or helper_id
            edges.append({"id": stable_id("E_", src, key_id), "type": "writes", "source": src, "target": key_id})

        # TDF writes for tiling_writer and workspace_writer (offsets often land on tiling sinks)
        if role in {"tiling_writer", "workspace_writer"} or (
            name_l in tiling_writers and role != "provenance_helper"
        ):
            fields = _collect_tdf_fields(scan_body, sink_recvs, non_sink_roots)
            seen_fields: set[str] = set()
            for field_name in fields:
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
                        "qualified_name": field_name,
                        "file_path": file_path,
                        "start_line": start,
                        "end_line": end,
                    }
                )
                src = prev_branch_id or helper_id
                edges.append({"id": stable_id("E_", src, tdf_id), "type": "writes", "source": src, "target": tdf_id})

        if role == "workspace_writer" or "workspace" in name_l or "workspace" in scan_body.lower():
            node_id = "BRIDGE_WORKSPACE"
            nodes.append(
                {
                    "id": node_id,
                    "layer": "bridge",
                    "node_type": "Workspace",
                    "name": "Workspace",
                    "qualified_name": "Workspace",
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                }
            )
            edges.append(
                {
                    "id": stable_id("E_", helper_id, node_id),
                    "type": "reserves",
                    "source": helper_id,
                    "target": node_id,
                }
            )
        if "blockdim" in name_l or "blockdim" in scan_body.lower() or "block_dim" in scan_body.lower():
            node_id = "BRIDGE_BLOCKDIM"
            nodes.append(
                {
                    "id": node_id,
                    "layer": "bridge",
                    "node_type": "BlockDim",
                    "name": "BlockDim",
                    "qualified_name": "BlockDim",
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                }
            )
            edges.append(
                {
                    "id": stable_id("E_", helper_id, node_id),
                    "type": "sets",
                    "source": helper_id,
                    "target": node_id,
                }
            )

    nodes.append(
        {
            "id": "BRIDGE_KERNEL_DISPATCH",
            "layer": "bridge",
            "node_type": "KernelDispatch",
            "name": "KernelDispatch",
            "qualified_name": "KernelDispatch",
            "file_path": "",
            "start_line": 0,
            "end_line": 0,
        }
    )
    if any(n.get("id") == "KEY_TILINGKEY" for n in nodes):
        edges.append(
            {
                "id": "E_KEY_TO_DISPATCH",
                "type": "dispatches",
                "source": "KEY_TILINGKEY",
                "target": "BRIDGE_KERNEL_DISPATCH",
            }
        )

    client.close()
    return _payload(op_name, architecture, _dedupe_nodes(nodes), _dedupe_edges(edges), unresolved)


def _collect_tdf_fields(body: str, sink_recvs: set[str], non_sink_roots: set[str]) -> list[str]:
    """Generic field extraction; filter by plan sinks / non-sink roots."""
    fields: list[str] = []
    # tilingData->path =
    for path in FIELD_WRITE_RE.findall(body):
        leaf = path.split(".")[-1]
        root = path.split(".")[0].casefold()
        if root in non_sink_roots:
            continue
        fields.append(leaf)
    # recv->set_field — only sinks (or all set_ if no sinks confirmed yet)
    for recv, field in RECV_SETTER_RE.findall(body):
        if recv.casefold() in non_sink_roots:
            continue
        if sink_recvs and recv.casefold() not in sink_recvs and recv not in sink_recvs:
            continue
        fields.append(field)
    # Bare set_field in tiling_writer body when no recv prefix (common AscendC style)
    if not fields:
        for field in SET_FIELD_RE.findall(body):
            fields.append(field)
    elif sink_recvs:
        # Also allow bare set_ alongside recv sinks inside tiling writers
        pass
    else:
        for field in SET_FIELD_RE.findall(body):
            if field not in fields:
                fields.append(field)
    return fields


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract host tiling subgraph into layered IR nodes/edges")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--allow-empty-plan",
        action="store_true",
        help="Allow missing extract_plan (tests only); still no closed-name TDF writes",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = extract_host_subgraph(
        repo_root,
        op_name,
        architecture=args.architecture,
        allow_empty_plan=args.allow_empty_plan,
    )
    if args.write:
        write_yaml(existing_operator_root(repo_root, op_name) / "ir" / "host_subgraph.yaml", payload)
    print(f"host nodes={len(payload['nodes'])} edges={len(payload['edges'])} unresolved={len(payload['unresolved'])}")
    return 0


def _payload(
    op_name: str,
    architecture: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> dict[str, Any]:
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
