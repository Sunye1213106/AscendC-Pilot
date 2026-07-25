"""Template-aware call-site resolution (fail-closed)."""
from __future__ import annotations

from typing import Any

from uo.scripts.function_body import CallSite, FunctionDefinition, extract_call_sites
from uo.scripts.semantic_identity import mint_edge_id, mint_scoped_node_id


_CALL_NOISE = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "else",
        "try",
        "constexpr",
        "consteval",
        "constinit",
        "requires",
        "noexcept",
        "static_assert",
        "static_cast",
        "reinterpret_cast",
        "const_cast",
        "dynamic_cast",
        "sizeof",
        "alignof",
        "decltype",
        "typeid",
        "return",
        "ASCENDC_TPL_ARGS_SEL",
        "GET_TILING_DATA",
        "GET_TPL_TILING_KEY",
    }
)


def build_call_edges_for_functions(
    functions: list[FunctionDefinition],
    *,
    unresolved: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Emit CallSite/ExternalFunction nodes and calls edges.

    Missing internal definitions are kept unresolved. Calls that carry explicit
    external evidence (object receiver, namespace/class qualification, or a
    conventional exported/API-style capitalized symbol) are represented as
    auditable ExternalFunction nodes rather than false internal missing targets.
    """
    by_id = {fn.stable_id: fn for fn in functions}
    by_name: dict[str, list[FunctionDefinition]] = {}
    by_qn: dict[str, list[FunctionDefinition]] = {}
    for fn in functions:
        by_name.setdefault(fn.name, []).append(fn)
        by_qn.setdefault(fn.qualified_name, []).append(fn)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    external_nodes: dict[str, dict[str, Any]] = {}

    for fn in functions:
        sites = extract_call_sites(fn, noise=_CALL_NOISE)
        for site in sites:
            edge, site_node, unres = resolve_call_site(
                site, fn, by_name=by_name, by_qn=by_qn, by_id=by_id
            )
            if site_node:
                nodes.append(site_node)
            if edge:
                ext_node = edge.pop("_external_target_node", None)
                if isinstance(ext_node, dict) and ext_node.get("id"):
                    external_nodes.setdefault(str(ext_node["id"]), ext_node)
                edges.append(edge)
            if unres:
                unresolved.append(unres)
    nodes.extend(external_nodes.values())
    return nodes, edges


def resolve_call_site(
    site: CallSite,
    caller: FunctionDefinition,
    *,
    by_name: dict[str, list[FunctionDefinition]],
    by_qn: dict[str, list[FunctionDefinition]],
    by_id: dict[str, FunctionDefinition],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve one CallSite into a verified, candidate, external, or missing edge."""
    del by_id  # reserved for future CBM edge join
    site_id = mint_scoped_node_id(
        "CALL",
        caller.identity_key,
        site.file_path,
        line=site.line,
        extra=site.snippet_hash,
        ordinal=site.ordinal_in_function,
        normalized_expression=site.call_expression,
    )
    site_node = {
        "id": site_id,
        "layer": "kernel",
        "node_type": "CallSite",
        "name": site.callee_name,
        "qualified_name": site.callee_qualified_hint or site.callee_name,
        "file_path": site.file_path,
        "start_line": site.line,
        "end_line": site.line,
        "caller_function_id": caller.stable_id,
        "callee_name": site.callee_name,
        "call_expression": site.call_expression,
        "receiver_type_or_object": site.receiver_type_or_object,
        "template_args": site.template_args,
        "argument_count": site.argument_count,
        "ordinal_in_function": site.ordinal_in_function,
        "snippet_hash": site.snippet_hash,
        "owning_function_id": caller.stable_id,
        "owning_identity_key": caller.identity_key,
    }

    candidates = _candidate_callees(site, caller, by_name=by_name, by_qn=by_qn)
    base_edge: dict[str, Any] = {
        "type": "calls",
        "source": caller.stable_id,
        "locator": {
            "file_path": site.file_path,
            "start_line": site.line,
            "end_line": site.line,
            "call_expression": site.call_expression,
        },
        "call_site_id": site_id,
        "callee_name": site.callee_name,
    }

    if not candidates:
        external_reason = _external_symbol_reason(site)
        if external_reason:
            qualified = site.callee_qualified_hint or site.callee_name
            ext_id = mint_scoped_node_id(
                "EXTFN",
                qualified,
                "external",
                normalized_expression=qualified,
            )
            ext_node = {
                "id": ext_id,
                "layer": "kernel",
                "node_type": "ExternalFunction",
                "name": site.callee_name,
                "qualified_name": qualified,
                "symbol_scope": "external_or_unindexed",
                "resolution_status": "external",
                "classification_reason": external_reason,
            }
            edge = {
                **base_edge,
                "id": mint_edge_id("calls", caller.stable_id, ext_id, site_id),
                "target": ext_id,
                "target_status": "external",
                "candidate_ids": [],
                "confidence": "structurally_inferred",
                "verification_source": external_reason,
                "_external_target_node": ext_node,
            }
            return edge, site_node, None

        edge = {
            **base_edge,
            "id": mint_edge_id("calls", caller.stable_id, f"missing:{site.callee_name}", site_id),
            "target": None,
            "target_status": "missing",
            "candidate_ids": [],
            "confidence": "unresolved",
            "verification_source": "source_scan",
        }
        unres = {
            "id": f"UNRES_CALL_{site_id[-12:]}",
            "kind": "internal_definition_not_indexed",
            "message": f"No internal FunctionDefinition candidate for call {site.call_expression}",
            "file_path": site.file_path,
            "start_line": site.line,
            "caller_function_id": caller.stable_id,
            "callee_name": site.callee_name,
        }
        return edge, site_node, unres

    if len(candidates) == 1:
        tgt = candidates[0]
        if site.receiver_type_or_object or (
            site.callee_qualified_hint and "::" in site.callee_qualified_hint
        ):
            conf = "source_verified"
            vsrc = "class_scope"
        elif tgt.class_or_namespace and tgt.class_or_namespace == caller.class_or_namespace:
            conf = "source_verified"
            vsrc = "class_scope"
        else:
            conf = "structurally_inferred"
            vsrc = "unique_candidate"
        edge = {
            **base_edge,
            "id": mint_edge_id("calls", caller.stable_id, tgt.stable_id, site_id),
            "target": tgt.stable_id,
            "target_status": "resolved",
            "candidate_ids": [tgt.stable_id],
            "confidence": conf,
            "verification_source": vsrc,
        }
        return edge, site_node, None

    ids = [c.stable_id for c in candidates]
    edge = {
        **base_edge,
        "id": mint_edge_id("calls", caller.stable_id, "candidate_set", site_id),
        "target": None,
        "target_status": "candidate_set",
        "candidate_ids": ids,
        "confidence": "candidate",
        "verification_source": "ambiguous_overloads",
    }
    unres = {
        "id": f"UNRES_CALL_AMBIG_{site_id[-12:]}",
        "kind": "call_target_ambiguous",
        "message": f"Ambiguous callee for {site.call_expression}",
        "file_path": site.file_path,
        "start_line": site.line,
        "caller_function_id": caller.stable_id,
        "callee_name": site.callee_name,
        "candidate_ids": ids,
        "unresolved_reason": "overloaded_or_multi_class_callee",
    }
    return edge, site_node, unres


def _external_symbol_reason(site: CallSite) -> str:
    """Return conservative structural evidence that a missing target is external.

    This is operator-agnostic: no API or operator name allowlist is used.
    """
    recv = (site.receiver_type_or_object or "").strip()
    hint = (site.callee_qualified_hint or "").replace(" ", "")
    if recv and recv not in {".", "->", "this->"}:
        return "object_receiver_without_internal_definition"
    if "::" in hint and not hint.startswith("this::"):
        return "qualified_symbol_without_internal_definition"
    name = site.callee_name or ""
    if name and name[0].isupper():
        return "api_style_symbol_without_internal_definition"
    return ""


def _candidate_callees(
    site: CallSite,
    caller: FunctionDefinition,
    *,
    by_name: dict[str, list[FunctionDefinition]],
    by_qn: dict[str, list[FunctionDefinition]],
) -> list[FunctionDefinition]:
    hint = (site.callee_qualified_hint or "").replace(" ", "")
    if hint and "::" in hint and not hint.endswith("::"):
        qn_hits = by_qn.get(hint) or []
        if qn_hits:
            return list(qn_hits)
        short = hint.split("::")[-1]
        name_hits = by_name.get(short) or []
        cls_hint = hint.rsplit("::", 1)[0]
        scoped = [c for c in name_hits if c.class_or_namespace == cls_hint]
        if scoped:
            return scoped

    name_hits = list(by_name.get(site.callee_name) or [])
    if not name_hits:
        return []

    recv = (site.receiver_type_or_object or "").strip()
    if recv.startswith("this") or recv in {".", "->", "this->"}:
        same = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]
        if same:
            return _filter_by_arity(same, site.argument_count)

    if recv and ("." in recv or "->" in recv):
        return _filter_by_arity(name_hits, site.argument_count)

    same_cls = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]
    if same_cls:
        return _filter_by_arity(same_cls, site.argument_count)

    return _filter_by_arity(name_hits, site.argument_count)


def _filter_by_arity(
    candidates: list[FunctionDefinition], argument_count: int
) -> list[FunctionDefinition]:
    if len(candidates) <= 1:
        return candidates
    hits = [fn for fn in candidates if _signature_arity(fn.normalized_signature) == argument_count]
    return hits or candidates


def _signature_arity(signature: str) -> int:
    text = str(signature or "").strip()
    if not text.startswith("(") or not text.endswith(")"):
        return -1
    inner = text[1:-1].strip()
    if not inner or inner == "void":
        return 0
    depth = 0
    count = 1
    for ch in inner:
        if ch in "(<[{":
            depth += 1
        elif ch in ")>]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            count += 1
    return count
