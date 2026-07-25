from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import snippet, stable_id, write_yaml
from uo.scripts.cbm_client import CbmClient
from uo.scripts.def_use import extract_def_use_from_text
from uo.scripts.extract_plan_io import (
    load_extract_plan,
    plan_chain_names,
    plan_non_sink_roots,
    plan_tiling_sink_receivers,
    plan_tiling_writer_names,
)
from uo.scripts.function_body import extract_callee_names, resolve_helper_body
from uo.scripts.macro_regions import analyze_macros, classify_macro_condition
from uo.scripts.resolve_entrypoints import entrypoint_units, load_entrypoint_graph, nodes_for_role
from uo.scripts.semantic_identity import mint_field_identity, mint_symbol_identity
from uo.scripts.source_path import resolve_repo_source_path

def _chain_item_key(item: dict[str, Any]) -> str:
    if item.get("identity_key"):
        return str(item["identity_key"]).casefold()
    fp = str(item.get("file_path") or "").replace("\\", "/")
    qn = str(item.get("qualified_name") or item.get("name") or "")
    cls = str(item.get("class_or_namespace") or "")
    sig = str(item.get("normalized_signature") or item.get("signature") or "")
    tpl = str(item.get("template_arity_or_signature") or "")
    return f"{fp}|{qn}|{cls}|{sig}|{tpl}".casefold()

def _has_precise_identity(item: dict[str, Any]) -> bool:
    if item.get("identity_key"):
        return True
    return bool(
        item.get("file_path")
        and (item.get("qualified_name") or item.get("class_or_namespace"))
        and (
            item.get("start_line")
            or item.get("normalized_signature")
            or item.get("signature")
            or item.get("template_arity_or_signature")
        )
    )


def _writer_role_indexes(
    plan: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    by_identity: dict[str, str] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for writer in plan.get("writers") or []:
        if not isinstance(writer, dict):
            continue
        role = str(writer.get("role") or "")
        if not role or role == "ignore":
            continue
        by_identity[_chain_item_key(writer)] = role
        name = str(writer.get("name") or "").casefold()
        if name:
            grouped.setdefault(name, []).append(writer)
    by_name: dict[str, str] = {}
    incomplete_duplicates: set[str] = set()
    for name, writers in grouped.items():
        roles = {str(w.get("role") or "") for w in writers}
        if len(roles) == 1:
            by_name[name] = next(iter(roles))
        if len(writers) > 1 and not all(_has_precise_identity(w) for w in writers):
            incomplete_duplicates.add(name)
    return by_identity, by_name, incomplete_duplicates


def _add_chain_item(
    chain: list[dict[str, Any]], chain_keys: set[str], item: dict[str, Any]
) -> bool:
    key = _chain_item_key(item)
    if key in chain_keys:
        return False
    chain_keys.add(key)
    chain.append(item)
    return True


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


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


PLATFORM_RE = re.compile(r"\b(ubSize|l1Size|l0[abc]Size|coreNum|aicNum|aivNum|socVersion|l2CacheSize)\b")
BRIDGE_ROLE_HINTS = frozenset({"get_tiling_key", "save_tiling_data", "init_tiling_data"})
TILING_TYPE_DECL_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_:]*)\s*\*?\s*(?:tilingData|tiling_data)\b"
)
GET_TILING_DATA_RE = re.compile(r"GetTilingData\s*<\s*([A-Za-z_][A-Za-z0-9_:]*)\s*>")


def extract_host_subgraph(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    allow_empty_plan: bool = False,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    graph = load_entrypoint_graph(uo_root)
    seed_nodes = _seed_host_nodes(graph)
    unresolved: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    def_use_blocks: list[dict[str, Any]] = []

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

    if not seed_nodes:
        unresolved.append(
            {
                "id": "UNRES_HOST_ENTRY",
                "kind": "entrypoint_missing",
                "message": "entrypoint_graph has no public_host_entry / impl units",
                "file_path": "",
                "snippet": "",
            }
        )
        return _payload(op_name, architecture, nodes, edges, unresolved, def_use_blocks)

    # Prefer a callable host entry over registration-only nodes for body seeding.
    primary_node = next(
        (
            n
            for n in seed_nodes
            if str(n.get("role") or "")
            in {
                "public_host_entry",
                "normal_impl",
                "varlen_impl",
                "empty_impl",
                "host_tiling_entry",
            }
        ),
        seed_nodes[0] if seed_nodes else {},
    )
    primary = _item_from_ep_node(primary_node) if primary_node else {}
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

    writer_roles_by_identity, writer_roles_by_name, incomplete_duplicate_writers = (
        _writer_role_indexes(plan or {})
    )
    for duplicate_name in sorted(incomplete_duplicate_writers):
        unresolved.append(
            {
                "id": stable_id("UNRES_HOST_WRITER_ID_", duplicate_name),
                "kind": "writer_identity_incomplete",
                "severity": "blocking",
                "message": (
                    f"duplicate host writer {duplicate_name!r} lacks file/class/signature identity; "
                    "short-name role assignment is disabled"
                ),
                "file_path": "",
                "snippet": "",
            }
        )

    client = CbmClient(uo_root)
    root_sym = None
    if client.available and primary.get("qualified_name"):
        pcls = str(primary.get("class_or_namespace") or "")
        root_sym = client.resolve_qn(
            primary["qualified_name"],
            file_contains=architecture,
            class_qn=pcls or None,
        )
        if root_sym is None and primary.get("name"):
            root_sym = client.resolve_qn(
                primary["name"],
                file_contains=architecture,
                class_qn=pcls or None,
            )

    chain: list[dict[str, Any]] = []
    chain_keys: set[str] = set()
    for node in seed_nodes:
        _add_chain_item(chain, chain_keys, _item_from_ep_node(node))

    keep_for_trace = {n for n in writer_keep if n} | {str(primary.get("name") or "").casefold()}
    if root_sym is not None:
        trace_max_depth = _env_int("UO_HOST_TRACE_MAX_DEPTH", 6, 1, 12)
        trace_max_nodes = _env_int("UO_HOST_TRACE_MAX_NODES", 200, 20, 4000)
        traced = client.bounded_trace(
            root_sym,
            keep_names=keep_for_trace or None,
            max_depth=trace_max_depth,
            max_nodes=trace_max_nodes,
        )
        for sym in traced:
            _add_chain_item(chain, chain_keys, sym.as_dict())
        if len(traced) >= trace_max_nodes:
            unresolved.append(
                {
                    "id": "UNRES_HOST_TRACE_TRUNCATED",
                    "kind": "host_trace_truncated",
                    "severity": "blocking",
                    "message": (
                        f"CBM host trace reached max_nodes={trace_max_nodes}; "
                        "raise UO_HOST_TRACE_MAX_NODES and rebuild"
                    ),
                    "file_path": str(primary.get("file_path") or ""),
                    "snippet": "",
                }
            )

    for role in BRIDGE_ROLE_HINTS:
        for node in nodes_for_role(graph, role):
            _add_chain_item(chain, chain_keys, _item_from_ep_node(node))

    # Seed exact plan writers first. This preserves Normal/Varlen/Empty helpers
    # that share a short name but differ by class, signature, or source location.
    body_cache: dict[str, tuple[str, int, int]] = {}
    entry_body, entry_start, entry_end = resolve_helper_body(
        repo_root, primary, prefer_definition=True
    )
    body_cache[_chain_item_key(primary)] = (entry_body, entry_start, entry_end)
    seed_names: list[str] = []
    for item in (plan or {}).get("writers") or []:
        if isinstance(item, dict) and str(item.get("role") or "") in {
            "tiling_writer",
            "key_writer",
            "workspace_writer",
            "provenance_helper",
        }:
            n = str(item.get("name") or "").strip()
            if not n:
                continue
            _add_chain_item(chain, chain_keys, dict(item))
            if not _has_precise_identity(item):
                seed_names.append(n)
    for helper_name in extract_callee_names(entry_body, noise=NOISE_CALLS):
        if helper_name.casefold() in writer_keep or not writer_keep:
            seed_names.append(helper_name)
    for helper_name in seed_names:
        hit = None
        if client.available:
            hit = client.resolve_qn(
                helper_name,
                file_contains=architecture,
                class_qn=str(primary.get("class_or_namespace") or "") or None,
            )
        if hit is not None:
            child = hit.as_dict()
        else:
            child = {
                "name": helper_name,
                "qualified_name": helper_name,
                "file_path": primary.get("file_path") or "",
                "start_line": primary.get("start_line") or 0,
                "end_line": primary.get("end_line") or 0,
                "class_or_namespace": primary.get("class_or_namespace") or "",
                "label": "helper_call_seed",
            }
        _add_chain_item(chain, chain_keys, child)

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
        hit = None
        if client.available:
            hit = client.resolve_qn(name, file_contains=architecture)
        _add_chain_item(chain, chain_keys, hit.as_dict() if hit is not None else meta)

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
        item_key_before = _chain_item_key(item)
        role = writer_roles_by_identity.get(
            item_key_before, writer_roles_by_name.get(name_l, "")
        )
        prefer_def = True  # always brace-bound when definition exists; else tight window
        cached_body = body_cache.get(item_key_before)
        if cached_body is None:
            body, start, end = resolve_helper_body(
                repo_root, item, prefer_definition=prefer_def
            )
            body_cache[item_key_before] = (body, start, end)
            body_cache[_chain_item_key(item)] = (body, start, end)
        else:
            body, start, end = cached_body
        file_path = str(item.get("file_path") or file_path)

        if body:
            scope = str(item.get("qualified_name") or item.get("name") or "helper")
            try:
                def_use_blocks.append(
                    extract_def_use_from_text(
                        body,
                        file_path=file_path,
                        scope_symbol=scope,
                        start_line=int(start or 1) or 1,
                    )
                )
            except Exception:  # noqa: BLE001
                pass

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
        scan_body_cf = scan_body.casefold()

        helper_ident = mint_symbol_identity(
            kind="helper",
            name=str(item.get("name") or "fn"),
            file_path=file_path,
            qualified_name=str(item.get("qualified_name") or item.get("name") or "fn"),
            class_or_namespace=str(item.get("class_or_namespace") or ""),
            signature=str(item.get("normalized_signature") or item.get("signature") or ""),
            template_arity_or_signature=str(item.get("template_arity_or_signature") or ""),
            specialization_kind=str(item.get("specialization_kind") or "none"),
            architecture=architecture,
            prefix="HOST",
        )
        helper_id = helper_ident.stable_id
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
                "identity_key": helper_ident.identity_key,
                "class_or_namespace": item.get("class_or_namespace") or "",
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

        owning_type = _detect_owning_type(scan_body, item)

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

        for idx, match in enumerate(IF_RE.finditer(scan_body)):
            cond = match.group(1)
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
                    if "constexpr" in match.group(0).split("(", 1)[0]
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
                ot = owning_type or "UnknownType"
                tdf_ident = mint_field_identity(
                    owning_type=ot,
                    field_path=field_name,
                    file_path=file_path,
                )
                tdf_id = tdf_ident.stable_id
                tdf_node: dict[str, Any] = {
                    "id": tdf_id,
                    "layer": "bridge",
                    "node_type": "TilingDataField",
                    "name": field_name,
                    "qualified_name": tdf_ident.qualified_name,
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                    "owning_type": ot,
                    "field_path": field_name,
                    "identity_key": tdf_ident.identity_key,
                    "symbol_ref": tdf_ident.as_dict(),
                }
                nodes.append(tdf_node)
                src = prev_branch_id or helper_id
                edges.append({"id": stable_id("E_", src, tdf_id), "type": "writes", "source": src, "target": tdf_id})

        if role == "workspace_writer" or "workspace" in name_l or "workspace" in scan_body_cf:
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
        if "blockdim" in name_l or "blockdim" in scan_body_cf or "block_dim" in scan_body_cf:
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
    return _payload(op_name, architecture, _dedupe_nodes(nodes), _dedupe_edges(edges), unresolved, def_use_blocks)


def _seed_host_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {str(n.get("id")): n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(node: dict[str, Any] | None) -> None:
        if not isinstance(node, dict):
            return
        nid = str(node.get("id") or "")
        if nid and nid in seen:
            return
        if nid:
            seen.add(nid)
        out.append(node)

    for unit in entrypoint_units(graph):
        if not isinstance(unit, dict):
            continue
        # Prefer host-side units (skip pure kernel units).
        root = by_id.get(str(unit.get("entry_root") or ""))
        role = str((root or {}).get("role") or "")
        if role in {"public_kernel_entry", "concrete_kernel_impl", "kernel_family"}:
            continue
        _add(root)
        for mid in unit.get("member_nodes") or []:
            member = by_id.get(str(mid))
            mrole = str((member or {}).get("role") or "")
            if mrole in {
                "operator_registration",
                "public_kernel_entry",
                "concrete_kernel_impl",
                "kernel_family",
            }:
                continue
            _add(member)

    for role in ("public_host_entry", "normal_impl", "varlen_impl", "empty_impl"):
        for node in nodes_for_role(graph, role):
            _add(node)
    return out


def _item_from_ep_node(node: dict[str, Any]) -> dict[str, Any]:
    loc = node.get("locator") if isinstance(node.get("locator"), dict) else {}
    sym = node.get("symbol_ref") if isinstance(node.get("symbol_ref"), dict) else {}
    name = str(node.get("name") or "")
    qn = str(sym.get("qualified_name") or node.get("qualified_name") or name)
    cls = str(sym.get("class_or_namespace") or node.get("class_or_namespace") or "")
    if not cls and "::" in qn:
        prefix = qn.rsplit("::", 1)[0]
        if "/" not in prefix:
            cls = prefix
    return {
        "id": node.get("id"),
        "name": name or (qn.rsplit("::", 1)[-1] if qn else ""),
        "qualified_name": qn,
        "file_path": str(loc.get("file_path") or sym.get("repo_relative_path") or node.get("file_path") or "").replace(
            "\\", "/"
        ),
        "start_line": int(loc.get("start_line") or node.get("start_line") or 0),
        "end_line": int(loc.get("end_line") or node.get("end_line") or 0),
        "class_or_namespace": cls,
        "role": node.get("role"),
    }


def _detect_owning_type(body: str, item: dict[str, Any]) -> str:
    """Best-effort owning type for TilingDataField (GetTilingData<T> / decl / class)."""
    for match in GET_TILING_DATA_RE.finditer(body or ""):
        typ = match.group(1).strip()
        if typ:
            return typ.split("::")[-1]
    for match in TILING_TYPE_DECL_RE.finditer(body or ""):
        typ = match.group(1).strip()
        if typ and typ not in {"auto", "const", "static", "constexpr"}:
            return typ.split("::")[-1]
    cls = str(item.get("class_or_namespace") or "").strip()
    if cls and "tiling" in cls.casefold():
        return cls.split("::")[-1]
    return ""


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
    def_use: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "layer": "host",
        "nodes": nodes,
        "edges": edges,
        "unresolved": unresolved,
        "def_use": def_use or [],
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
