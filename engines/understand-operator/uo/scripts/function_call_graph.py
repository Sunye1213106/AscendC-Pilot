"""Evidence-driven, template-aware call-site resolution (fail closed)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from uo.scripts.function_body import CallSite, FunctionDefinition, extract_call_sites
from uo.scripts.macro_regions import analyze_macros
from uo.scripts.receiver_type_facts import (
    ReceiverTypeFacts,
    build_receiver_type_facts,
    infer_receiver_type as infer_receiver_type_from_facts,
)
from uo.scripts.semantic_identity import mint_edge_id, mint_scoped_node_id


_CALL_NOISE = frozenset(
    {
        "if", "for", "while", "switch", "catch", "else", "elif", "try",
        "constexpr", "consteval", "constinit", "requires", "noexcept", "static_assert",
        "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast",
        "sizeof", "alignof", "decltype", "typeid", "return",
    }
)

_STANDARD_EXTERNAL_SYMBOLS = frozenset(
    {
        "abs", "acos", "asin", "atan", "atan2", "ceil", "cos", "exp", "floor",
        "fmax", "fmin", "log", "log2", "max", "memcpy", "memmove", "memset",
        "min", "pow", "printf", "sin", "sqrt", "tan",
    }
)
_COMPILER_MACRO_SYMBOLS = frozenset(
    {"likely", "unlikely", "__builtin_expect", "__builtin_assume", "__builtin_unreachable"}
)
_DEFAULT_EXTERNAL_NAMESPACES = frozenset({"std", "AscendC", "MicroAPI"})
_USING_NAMESPACE_RE = re.compile(r"\busing\s+namespace\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*;")
_DECL_TYPE_RE_TEMPLATE = (
    r"(?:^|[;{{}},(])\s*"
    r"(?:(?:const|volatile|static|mutable|typename|struct|class)\s+)*"
    r"(?P<type>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*(?:\s*<[^;{{}}\n]{{0,240}}>)?)"
    r"\s*(?:[*&]\s*)*\b{receiver}\b"
)


@dataclass
class CallResolutionFacts:
    source_macros: set[str] = field(default_factory=set)
    source_macro_definitions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    documented_macros: set[str] = field(default_factory=set)
    documented_external: set[str] = field(default_factory=set)
    official_contracts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    standard_external: set[str] = field(default_factory=lambda: set(_STANDARD_EXTERNAL_SYMBOLS))
    compiler_macros: set[str] = field(default_factory=lambda: set(_COMPILER_MACRO_SYMBOLS))
    external_namespaces: set[str] = field(default_factory=lambda: set(_DEFAULT_EXTERNAL_NAMESPACES))
    using_namespaces_by_file: dict[str, set[str]] = field(default_factory=dict)
    source_text_by_file: dict[str, str] = field(default_factory=dict)
    internal_classes: set[str] = field(default_factory=set)
    receiver_type_facts: ReceiverTypeFacts | None = None


def collect_call_resolution_facts(
    functions: list[FunctionDefinition],
    *,
    source_texts: Mapping[Any, str] | None = None,
    doc_evidence: dict[str, Any] | None = None,
) -> CallResolutionFacts:
    """Collect deterministic macro, documentation, namespace, and source facts."""
    facts = CallResolutionFacts()
    facts.internal_classes = {
        _normalize_type_name(fn.class_or_namespace)
        for fn in functions
        if _normalize_type_name(fn.class_or_namespace)
    }
    function_paths = {fn.file_path for fn in functions if fn.file_path}
    for raw_path, text in (source_texts or {}).items():
        path = Path(str(raw_path)).as_posix()
        rel = next((candidate for candidate in function_paths if path.endswith(candidate)), path)
        source = str(text or "")
        facts.source_text_by_file[rel] = source
        info = analyze_macros(source)
        facts.source_macros.update(info.function_macros)
        for macro_name, definition in info.function_macros.items():
            payload = dict(definition)
            payload["file_path"] = rel
            facts.source_macro_definitions.setdefault(macro_name, []).append(payload)
        namespaces = {m.group(1) for m in _USING_NAMESPACE_RE.finditer(source)}
        if namespaces:
            facts.using_namespaces_by_file.setdefault(rel, set()).update(namespaces)

    if not doc_evidence:
        from uo.scripts.cann_doc_evidence import packaged_doc_evidence_bundle

        doc_evidence = packaged_doc_evidence_bundle()
    for item in (doc_evidence or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol_or_macro") or "").strip()
        if not symbol:
            continue
        names = [symbol] + [str(alias or "").strip() for alias in item.get("aliases") or []]
        for name in names:
            if name:
                facts.official_contracts.setdefault(name, []).append(item)
        kind = _official_contract_kind(item)
        if kind == "macro":
            facts.documented_macros.add(symbol)
        elif kind in {"function", "method", "interface", "api"}:
            facts.documented_external.add(symbol)
        for qualified in item.get("qualified_names") or []:
            root = str(qualified).split("::", 1)[0].strip()
            if root:
                facts.external_namespaces.add(root)
    facts.receiver_type_facts = build_receiver_type_facts(
        functions,
        facts.source_text_by_file,
        official_contracts=facts.official_contracts,
    )
    return facts


def build_call_edges_for_functions(
    functions: list[FunctionDefinition],
    *,
    unresolved: list[dict[str, Any]],
    facts: CallResolutionFacts | None = None,
    source_texts: Mapping[Any, str] | None = None,
    doc_evidence: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Emit CallSite/target nodes and calls edges without name-style guessing."""
    by_id = {fn.stable_id: fn for fn in functions}
    by_name: dict[str, list[FunctionDefinition]] = {}
    by_qn: dict[str, list[FunctionDefinition]] = {}
    for fn in functions:
        by_name.setdefault(fn.name, []).append(fn)
        by_qn.setdefault(fn.qualified_name, []).append(fn)
    facts = facts or collect_call_resolution_facts(
        functions, source_texts=source_texts, doc_evidence=doc_evidence
    )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    target_nodes: dict[str, dict[str, Any]] = {}
    for fn in functions:
        for site in extract_call_sites(fn, noise=_CALL_NOISE):
            edge, site_node, unres = resolve_call_site(
                site, fn, by_name=by_name, by_qn=by_qn, by_id=by_id, facts=facts
            )
            if site_node:
                nodes.append(site_node)
            if edge:
                target_node = edge.pop("_target_node", None)
                if isinstance(target_node, dict) and target_node.get("id"):
                    target_nodes.setdefault(str(target_node["id"]), target_node)
                edges.append(edge)
            if unres:
                unresolved.append(unres)
    nodes.extend(target_nodes.values())
    return nodes, edges


def resolve_call_site(
    site: CallSite,
    caller: FunctionDefinition,
    *,
    by_name: dict[str, list[FunctionDefinition]],
    by_qn: dict[str, list[FunctionDefinition]],
    by_id: dict[str, FunctionDefinition],
    facts: CallResolutionFacts | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve one CallSite using source facts; uncertain targets stay unresolved."""
    del by_id
    facts = facts or CallResolutionFacts(
        internal_classes={
            _normalize_type_name(fn.class_or_namespace)
            for values in by_name.values()
            for fn in values
            if _normalize_type_name(fn.class_or_namespace)
        }
    )
    site_id = mint_scoped_node_id(
        "CALL", caller.identity_key, site.file_path, line=site.line,
        extra=site.snippet_hash, ordinal=site.ordinal_in_function,
        normalized_expression=site.call_expression,
    )
    receiver_type = _infer_receiver_type(site, caller, facts)
    site_node = {
        "id": site_id, "layer": "kernel", "node_type": "CallSite",
        "name": site.callee_name,
        "qualified_name": site.callee_qualified_hint or site.callee_name,
        "file_path": site.file_path, "start_line": site.line, "end_line": site.line,
        "caller_function_id": caller.stable_id, "callee_name": site.callee_name,
        "call_expression": site.call_expression,
        "receiver_type_or_object": site.receiver_type_or_object,
        "receiver_object": _receiver_object(site.receiver_type_or_object),
        "receiver_type": receiver_type,
        "template_args": site.template_args, "argument_count": site.argument_count,
        "ordinal_in_function": site.ordinal_in_function, "snippet_hash": site.snippet_hash,
        "owning_function_id": caller.stable_id, "owning_identity_key": caller.identity_key,
    }
    base_edge: dict[str, Any] = {
        "type": "calls", "source": caller.stable_id,
        "locator": {
            "file_path": site.file_path, "start_line": site.line, "end_line": site.line,
            "call_expression": site.call_expression,
        },
        "call_site_id": site_id, "callee_name": site.callee_name,
    }

    # A precise receiver may prove an official method before generic short-name
    # lookup sees unrelated project helpers with the same name (for example TBuf::Get).
    method_contract, method_reason = _matching_official_contract(site, receiver_type, facts)
    if method_contract is not None and (site.receiver_type_or_object or "").strip():
        method_kind = _official_contract_kind(method_contract)
        method_style = str(
            method_contract.get("call_style")
            or ("method" if method_kind == "method" else "free_function")
        )
        if method_style == "method" or method_contract.get("receiver_types"):
            typed_source = [
                candidate
                for candidate in _filter_by_arity(
                    list(by_name.get(site.callee_name) or []), site.argument_count
                )
                if _type_matches_scope(receiver_type, candidate.class_or_namespace)
            ]
            if not typed_source:
                return _emit_target(
                    site,
                    caller,
                    site_id,
                    site_node,
                    base_edge,
                    node_type="ExternalFunction",
                    status="external",
                    reason=method_reason,
                    confidence="documented",
                    contract=method_contract,
                )

    candidates = _candidate_callees(
        site, caller, by_name=by_name, by_qn=by_qn, receiver_type=receiver_type
    )
    chosen, score_rows = _choose_candidate(site, caller, candidates, receiver_type)
    if chosen is not None:
        evidence = score_rows[0][2] if score_rows else ["unique_candidate"]
        edge = {
            **base_edge,
            "id": mint_edge_id("calls", caller.stable_id, chosen.stable_id, site_id),
            "target": chosen.stable_id, "target_status": "resolved",
            "candidate_ids": [chosen.stable_id],
            "confidence": "source_verified" if any(
                e in {"exact_qualified_name", "receiver_type", "same_class"} for e in evidence
            ) else "structurally_inferred",
            "verification_source": "+".join(evidence) if evidence else "unique_candidate",
            "candidate_scores": _score_payload(score_rows),
        }
        return edge, site_node, None

    if candidates:
        ids = [c.stable_id for c in candidates]
        edge = {
            **base_edge,
            "id": mint_edge_id("calls", caller.stable_id, "candidate_set", site_id),
            "target": None, "target_status": "candidate_set", "candidate_ids": ids,
            "confidence": "candidate", "verification_source": "ranked_ambiguous_candidates",
            "candidate_scores": _score_payload(score_rows),
        }
        unres = {
            "id": f"UNRES_CALL_AMBIG_{site_id[-12:]}", "kind": "call_target_ambiguous",
            "message": f"Ambiguous callee for {site.call_expression}",
            "file_path": site.file_path, "start_line": site.line,
            "caller_function_id": caller.stable_id, "callee_name": site.callee_name,
            "candidate_ids": ids, "candidate_scores": edge["candidate_scores"],
            "unresolved_reason": "ranked_candidates_without_safe_winner",
        }
        return edge, site_node, unres

    return _classify_unindexed_target(site, caller, site_id, site_node, base_edge, receiver_type, facts)


def _classify_unindexed_target(
    site: CallSite,
    caller: FunctionDefinition,
    site_id: str,
    site_node: dict[str, Any],
    base_edge: dict[str, Any],
    receiver_type: str,
    facts: CallResolutionFacts,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    name = site.callee_name
    if name in facts.source_macros or name in facts.compiler_macros:
        reason = "source_function_macro" if name in facts.source_macros else "compiler_builtin_macro"
        confidence = "source_verified" if name in facts.source_macros else "structurally_inferred"
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="CompileMacro", status="macro", reason=reason, confidence=confidence,
            source_definitions=facts.source_macro_definitions.get(name),
        )

    contract, contract_reason = _matching_official_contract(site, receiver_type, facts)
    if contract is not None:
        kind = _official_contract_kind(contract)
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="CompileMacro" if kind == "macro" else "ExternalFunction",
            status="macro" if kind == "macro" else "external",
            reason=contract_reason,
            confidence="documented",
            contract=contract,
        )

    if name in facts.standard_external:
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="ExternalFunction", status="external",
            reason="standard_library_symbol", confidence="structurally_inferred",
        )

    hint = (site.callee_qualified_hint or "").replace(" ", "")
    namespace_root = hint.split("::", 1)[0] if "::" in hint else ""
    if namespace_root in facts.external_namespaces:
        return _emit_target(
            site, caller, site_id, site_node, base_edge,
            node_type="ExternalFunction", status="external",
            reason="known_external_namespace", confidence="source_verified",
        )

    # A using-directive expands lookup candidates; it does not prove symbol ownership.
    if site.receiver_type_or_object:
        receiver_base = _normalize_type_name(receiver_type)
        if receiver_base and receiver_base not in facts.internal_classes and (
            _type_namespace_root(receiver_type) in facts.external_namespaces
        ):
            return _emit_target(
                site, caller, site_id, site_node, base_edge,
                node_type="ExternalFunction", status="external",
                reason="receiver_type_outside_internal_index",
                confidence="structurally_inferred",
            )
        return _emit_missing(
            site, caller, site_id, site_node, base_edge,
            kind="member_target_not_indexed",
            reason="receiver_type_unresolved_or_internal_definition_missing",
            receiver_type=receiver_type,
        )

    if "::" in hint:
        return _emit_missing(
            site, caller, site_id, site_node, base_edge,
            kind="qualified_target_not_indexed",
            reason="qualified_symbol_has_no_indexed_definition_or_external_contract",
            receiver_type=receiver_type,
        )
    return _emit_missing(
        site, caller, site_id, site_node, base_edge,
        kind="internal_definition_not_indexed",
        reason="unqualified_symbol_has_no_indexed_definition",
        receiver_type=receiver_type,
    )


def _matching_official_contract(
    site: CallSite,
    receiver_type: str,
    facts: CallResolutionFacts,
) -> tuple[dict[str, Any] | None, str]:
    # Match by call style, arity, qualification, and owner type.
    hint = (site.callee_qualified_hint or "").replace(" ", "")
    has_receiver = bool((site.receiver_type_or_object or "").strip())
    for contract in facts.official_contracts.get(site.callee_name, []):
        counts = {int(value) for value in contract.get("argument_counts") or []}
        if counts and site.argument_count not in counts:
            continue
        kind = _official_contract_kind(contract)
        style = str(contract.get("call_style") or ("method" if kind == "method" else "free_function"))
        qualified = {str(value or "").replace(" ", "") for value in contract.get("qualified_names") or []}
        if kind == "macro":
            return contract, "official_contract:macro"
        if style == "method" or contract.get("receiver_types"):
            if not has_receiver:
                continue
            allowed_types = [str(value or "") for value in contract.get("receiver_types") or []]
            if not receiver_type or not any(_type_matches_scope(receiver_type, value) for value in allowed_types):
                continue
            return contract, "official_contract:receiver_type"
        if "::" in hint:
            if qualified and hint not in qualified and not any(
                hint.endswith("::" + value.split("::")[-1]) for value in qualified
            ):
                continue
            return contract, "official_contract:qualified_name"
        if bool(contract.get("allow_unqualified")):
            return contract, "official_contract:unqualified_free_function"
    return None, ""


def _emit_target(
    site: CallSite,
    caller: FunctionDefinition,
    site_id: str,
    site_node: dict[str, Any],
    base_edge: dict[str, Any],
    *,
    node_type: str,
    status: str,
    reason: str,
    confidence: str,
    contract: dict[str, Any] | None = None,
    source_definitions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], None]:
    canonical_names = list(contract.get("qualified_names") or []) if contract else []
    qualified = str(canonical_names[0]) if canonical_names else (site.callee_qualified_hint or site.callee_name)
    prefix = "MACRO" if node_type == "CompileMacro" else "EXTFN"
    target_id = mint_scoped_node_id(
        prefix, qualified, status, normalized_expression=qualified
    )
    target_node = {
        "id": target_id, "layer": "kernel", "node_type": node_type,
        "name": site.callee_name, "qualified_name": qualified,
        "symbol_scope": status, "resolution_status": status,
        "classification_reason": reason,
    }
    if source_definitions:
        target_node["source_macro_definitions"] = [
            {
                "file_path": item.get("file_path"),
                "line": item.get("line"),
                "end_line": item.get("end_line"),
                "parameters": item.get("parameters") or [],
                "variadic": bool(item.get("variadic")),
                "expands_to_symbols": item.get("expands_to_symbols") or [],
                "body": item.get("body") or "",
            }
            for item in source_definitions
        ]
    if contract:
        target_node["official_contract"] = {
            "symbol_kind": contract.get("symbol_kind"),
            "qualified_names": contract.get("qualified_names") or [],
            "receiver_types": contract.get("receiver_types") or [],
            "argument_counts": contract.get("argument_counts") or [],
            "document_title": contract.get("document_title"),
            "document_url": contract.get("document_url"),
            "cann_version": contract.get("cann_version"),
            "cann_versions": contract.get("cann_versions") or [],
            "semantic_summary": contract.get("semantic_summary"),
            "source_authority": contract.get("source_authority"),
        }
    edge = {
        **base_edge,
        "id": mint_edge_id("calls", caller.stable_id, target_id, site_id),
        "target": target_id, "target_status": status, "candidate_ids": [],
        "confidence": confidence, "verification_source": reason,
        "_target_node": target_node,
    }
    return edge, site_node, None


def _emit_missing(
    site: CallSite,
    caller: FunctionDefinition,
    site_id: str,
    site_node: dict[str, Any],
    base_edge: dict[str, Any],
    *,
    kind: str,
    reason: str,
    receiver_type: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    edge = {
        **base_edge,
        "id": mint_edge_id("calls", caller.stable_id, f"missing:{site.callee_name}", site_id),
        "target": None, "target_status": "missing", "candidate_ids": [],
        "confidence": "unresolved", "verification_source": reason,
    }
    unres = {
        "id": f"UNRES_CALL_{site_id[-12:]}", "kind": kind,
        "message": f"No safe target for call {site.call_expression}",
        "file_path": site.file_path, "start_line": site.line,
        "caller_function_id": caller.stable_id, "callee_name": site.callee_name,
        "receiver_object": _receiver_object(site.receiver_type_or_object),
        "receiver_type": receiver_type, "unresolved_reason": reason,
    }
    return edge, site_node, unres


def _candidate_callees(
    site: CallSite,
    caller: FunctionDefinition,
    *,
    by_name: dict[str, list[FunctionDefinition]],
    by_qn: dict[str, list[FunctionDefinition]],
    receiver_type: str = "",
) -> list[FunctionDefinition]:
    hint = (site.callee_qualified_hint or "").replace(" ", "")
    if hint and "::" in hint and not hint.endswith("::"):
        qn_hits = list(by_qn.get(hint) or [])
        if qn_hits:
            return _filter_by_arity(qn_hits, site.argument_count)
        short = hint.split("::")[-1]
        scoped = [
            c for c in (by_name.get(short) or [])
            if _type_matches_scope(hint.rsplit("::", 1)[0], c.class_or_namespace)
        ]
        if scoped:
            return _filter_by_arity(scoped, site.argument_count)

    name_hits = list(by_name.get(site.callee_name) or [])
    if not name_hits:
        return []
    if receiver_type:
        typed = [c for c in name_hits if _type_matches_scope(receiver_type, c.class_or_namespace)]
        if typed:
            return _filter_by_arity(typed, site.argument_count)
    recv = (site.receiver_type_or_object or "").strip()
    if recv.startswith("this"):
        same = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]
        if same:
            return _filter_by_arity(same, site.argument_count)
    if not recv:
        same = [c for c in name_hits if c.class_or_namespace == caller.class_or_namespace]
        if same:
            return _filter_by_arity(same, site.argument_count)
    return _filter_by_arity(name_hits, site.argument_count)


def _choose_candidate(
    site: CallSite,
    caller: FunctionDefinition,
    candidates: list[FunctionDefinition],
    receiver_type: str,
) -> tuple[FunctionDefinition | None, list[tuple[FunctionDefinition, int, list[str]]]]:
    rows: list[tuple[FunctionDefinition, int, list[str]]] = []
    hint = (site.callee_qualified_hint or "").replace(" ", "")
    for candidate in candidates:
        score = 0
        evidence: list[str] = []
        if hint and hint == candidate.qualified_name.replace(" ", ""):
            score += 1000; evidence.append("exact_qualified_name")
        if receiver_type and _type_matches_scope(receiver_type, candidate.class_or_namespace):
            score += 800; evidence.append("receiver_type")
        if (site.receiver_type_or_object or "").strip().startswith("this") and candidate.class_or_namespace == caller.class_or_namespace:
            score += 700; evidence.append("this_receiver")
        if candidate.class_or_namespace and candidate.class_or_namespace == caller.class_or_namespace:
            score += 400; evidence.append("same_class")
        if candidate.file_path == caller.file_path:
            score += 220; evidence.append("same_file")
        if _signature_arity(candidate.normalized_signature) == site.argument_count:
            score += 120; evidence.append("arity")
        rows.append((candidate, score, evidence))
    rows.sort(key=lambda row: (-row[1], row[0].stable_id))
    if not rows:
        return None, rows
    if len(rows) == 1:
        return rows[0][0], rows
    top, second = rows[0], rows[1]
    if top[1] >= 700 and top[1] > second[1]:
        return top[0], rows
    if top[1] >= 500 and top[1] - second[1] >= 250:
        return top[0], rows
    return None, rows


def _score_payload(rows: list[tuple[FunctionDefinition, int, list[str]]]) -> list[dict[str, Any]]:
    return [
        {"function_id": fn.stable_id, "score": score, "evidence": evidence}
        for fn, score, evidence in rows
    ]


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


def _infer_receiver_type(
    site: CallSite, caller: FunctionDefinition, facts: CallResolutionFacts
) -> str:
    receiver_facts = facts.receiver_type_facts
    if receiver_facts is None:
        receiver_facts = build_receiver_type_facts(
            [caller],
            facts.source_text_by_file,
            official_contracts=facts.official_contracts,
        )
    structured = infer_receiver_type_from_facts(
        site,
        caller,
        receiver_facts,
        official_contracts=facts.official_contracts,
    )
    legacy = _legacy_receiver_type(site, caller, facts)
    if _receiver_type_supported(site, structured, facts):
        return structured
    if _receiver_type_supported(site, legacy, facts):
        return legacy
    # Preserve previous fail-closed behavior for aliases the lightweight parser
    # cannot bind to a concrete class; structured facts are preferred only when
    # they carry source/API support.
    return legacy or structured


def _receiver_type_supported(
    site: CallSite, receiver_type: str, facts: CallResolutionFacts
) -> bool:
    if not receiver_type:
        return False
    if any(_type_matches_scope(receiver_type, scope) for scope in facts.internal_classes):
        return True
    for contract in facts.official_contracts.get(site.callee_name, []):
        counts = {int(value) for value in contract.get("argument_counts") or []}
        if counts and site.argument_count not in counts:
            continue
        allowed = [str(value or "") for value in contract.get("receiver_types") or []]
        if allowed and any(_type_matches_scope(receiver_type, value) for value in allowed):
            return True
    return False


def _legacy_receiver_type(
    site: CallSite, caller: FunctionDefinition, facts: CallResolutionFacts
) -> str:
    receiver = _receiver_object(site.receiver_type_or_object)
    if not receiver:
        return ""
    if receiver == "this":
        return caller.class_or_namespace
    if receiver.endswith("()"):
        accessor = receiver[:-2].split("::")[-1]
        for contract in facts.official_contracts.get(accessor, []):
            return_type = _normalize_declared_type(str(contract.get("return_type") or ""))
            if return_type:
                return return_type
    pattern = re.compile(
        _DECL_TYPE_RE_TEMPLATE.format(receiver=re.escape(receiver)), re.MULTILINE
    )
    sources = [caller.header_text or "", caller.body_text or ""]
    full = facts.source_text_by_file.get(site.file_path, "")
    if full:
        line_prefix = "\n".join(full.splitlines()[: max(0, site.line)])
        sources.append(line_prefix)
    matches: list[str] = []
    for source in sources:
        for match in pattern.finditer(source):
            type_name = _normalize_declared_type(match.group("type"))
            if type_name and _normalize_type_name(type_name).casefold() not in {
                "return", "if", "for", "while", "switch", "case", "auto"
            }:
                matches.append(type_name)
    return matches[-1] if matches else ""


def _receiver_object(receiver: str) -> str:
    text = str(receiver or "").strip()
    text = text[:-2] if text.endswith("->") else text[:-1] if text.endswith(".") else text
    text = re.sub(r"\[[^\]]*\]$", "", text)
    return text.split("::")[-1].strip()


def _normalize_declared_type(type_name: str) -> str:
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|struct|class)\b", " ", str(type_name))
    return re.sub(r"\s+", "", text).strip("*& ")


def _normalize_type_name(type_name: str) -> str:
    text = _normalize_declared_type(type_name)
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
            continue
        if ch == ">":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip()


def _type_matches_scope(type_name: str, scope: str) -> bool:
    left = _normalize_type_name(type_name)
    right = _normalize_type_name(scope)
    if not left or not right:
        return False
    return left == right or left.split("::")[-1] == right.split("::")[-1]


def _type_namespace_root(type_name: str) -> str:
    normalized = _normalize_type_name(type_name)
    return normalized.split("::", 1)[0] if "::" in normalized else ""


def _official_contract_kind(item: dict[str, Any]) -> str:
    explicit = str(item.get("symbol_kind") or item.get("kind") or "").casefold()
    if explicit in {"macro", "function", "method", "interface", "api"}:
        return explicit
    text = " ".join(
        str(item.get(key) or "")
        for key in ("document_title", "semantic_summary", "return_semantics")
    ).casefold()
    if "macro" in text or "declaration only" in text or "registration side-effect" in text:
        return "macro"
    return "function"
