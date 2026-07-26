"""Deterministic kernel entry and dispatch materialization for AscendC sources.

The resolver deliberately implements a bounded source model rather than a full C++
preprocessor. It recognizes real ``__aicore__`` function definitions, function-like
macro bodies, direct dispatcher calls, and concrete ``*Kernel<...>`` template
instantiations inside confirmed source scope.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from uo.scripts.resolve_entrypoints import _apply_link_status, _build_extraction_units, _evaluate_closure

_VERIFIED = "source_verified"


@dataclass(frozen=True)
class FunctionFact:
    name: str
    file_path: str
    start_line: int
    body: str
    declaration: str
    is_global: bool


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16].upper()}"


def _norm(value: str) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _balanced(text: str, open_idx: int, opening: str, closing: str) -> tuple[str, int] | None:
    if open_idx < 0 or open_idx >= len(text) or text[open_idx] != opening:
        return None
    depth = 0
    i = open_idx
    in_string = ""
    escaped = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = ""
            i += 1
            continue
        if ch in {'"', "'"}:
            in_string = ch
            i += 1
            continue
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i], i + 1
        i += 1
    return None


_FUNCTION_RE = re.compile(
    r"(?P<decl>"
    r"(?:template\s*<[^;{}]{0,2500}>\s*)?"
    r"(?:(?:extern\s+\"C\"\s+)?__global__\s+__aicore__\s+void|"
    r"(?:inline\s+)?__aicore__\s+void)"
    r"\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE | re.DOTALL,
)


def _functions(file_path: str, text: str) -> list[FunctionFact]:
    out: list[FunctionFact] = []
    for match in _FUNCTION_RE.finditer(text):
        open_paren = text.find("(", match.start("name"))
        args = _balanced(text, open_paren, "(", ")")
        if not args:
            continue
        _, after_args = args
        brace = text.find("{", after_args)
        if brace < 0 or ";" in text[after_args:brace]:
            continue
        body = _balanced(text, brace, "{", "}")
        if not body:
            continue
        body_text, _ = body
        declaration = " ".join(match.group("decl").split())
        out.append(
            FunctionFact(
                name=match.group("name"),
                file_path=file_path,
                start_line=_line(text, match.start()),
                body=body_text,
                declaration=declaration,
                is_global="__global__" in declaration,
            )
        )
    return out


def _macro_definitions(text: str) -> dict[str, dict[str, Any]]:
    lines = text.splitlines()
    out: dict[str, dict[str, Any]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r"\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*(.*)", line)
        if not match:
            i += 1
            continue
        name = match.group(1)
        body_parts = [match.group(3).rstrip("\\").rstrip()]
        start_line = i + 1
        while lines[i].rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            body_parts.append(lines[i].rstrip().rstrip("\\").rstrip())
        out[name] = {"body": "\n".join(body_parts), "line": start_line}
        i += 1
    return out


def _expanded_body(body: str, macros: dict[str, dict[str, Any]], *, max_depth: int = 3) -> str:
    expanded = body
    seen: set[str] = set()
    frontier = body
    for _ in range(max_depth):
        invoked: list[str] = []
        for name in macros:
            if name in seen:
                continue
            if re.search(rf"\b{re.escape(name)}\s*\(", frontier):
                invoked.append(name)
        if not invoked:
            break
        chunks = []
        for name in invoked:
            seen.add(name)
            chunks.append(str(macros[name].get("body") or ""))
        frontier = "\n".join(chunks)
        expanded += "\n" + frontier
    return expanded


def _kernel_types(text: str) -> list[str]:
    names = set(
        re.findall(
            r"\b([A-Za-z_][A-Za-z0-9_:]*(?:KernelDeter|Kernel))\s*<",
            text,
        )
    )
    return sorted(names)


def _called_names(text: str, names: set[str]) -> set[str]:
    return {
        name
        for name in names
        if re.search(rf"\b{re.escape(name)}\s*(?:<[^;{{}}]{{0,1800}}>)?\s*\(", text, re.DOTALL)
    }


def _path_parts(path: str) -> set[str]:
    return {part.casefold() for part in str(path or "").replace("\\", "/").split("/") if part}


def _demote_false_kernel_entries(nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    demotions: list[dict[str, Any]] = []
    for node in nodes.values():
        if node.get("role") != "public_kernel_entry":
            continue
        loc = node.get("locator") if isinstance(node.get("locator"), dict) else {}
        path = str(loc.get("file_path") or (node.get("symbol_ref") or {}).get("file_path") or "")
        parts = _path_parts(path)
        macro = str(node.get("macro") or "")
        role = ""
        reason = ""
        if "op_api" in parts:
            role = "public_api_wrapper"
            reason = "op_api_path"
        elif "ASCENDC_TPL_ARGS_DECL" in macro or "template_tiling_key" in path.casefold():
            role = "template_key_schema"
            reason = "tiling_key_schema_macro"
        if not role:
            continue
        node["role"] = role
        node["status"] = "verified"
        node["confidence"] = _VERIFIED
        node["verification_source"] = "kernel_dispatch_resolver"
        node["kernel_role_demoted_from"] = "public_kernel_entry"
        demotions.append({"id": node.get("id"), "role": role, "reason": reason})
    return demotions


def _node_for_function(fact: FunctionFact, *, role: str, architecture: str) -> dict[str, Any]:
    nid = _stable_id("EPKD", role, fact.file_path, fact.name, str(fact.start_line))
    return {
        "id": nid,
        "role": role,
        "architecture": architecture,
        "path_family": "kernel",
        "template_family": "kernel",
        "status": "verified",
        "name": fact.name,
        "qualified_name": f"{fact.file_path}::{fact.name}",
        "locator": {
            "file_path": fact.file_path,
            "start_line": fact.start_line,
            "end_line": fact.start_line,
            "text": fact.declaration,
        },
        "confidence": _VERIFIED,
        "verification_source": "kernel_dispatch_resolver",
        "syntax_fact": "__global__ __aicore__" if fact.is_global else "__aicore__",
    }


def _node_for_kernel_type(name: str, *, file_path: str, line: int, architecture: str) -> dict[str, Any]:
    nid = _stable_id("EPKD", "concrete_kernel_impl", file_path, name)
    return {
        "id": nid,
        "role": "concrete_kernel_impl",
        "architecture": architecture,
        "path_family": "kernel",
        "template_family": "kernel",
        "status": "verified",
        "name": name.split("::")[-1],
        "qualified_name": name,
        "locator": {"file_path": file_path, "start_line": line, "end_line": line, "text": name},
        "confidence": _VERIFIED,
        "verification_source": "kernel_dispatch_resolver",
        "syntax_fact": "template_instantiation",
    }


def _edge(edge_type: str, source: str, target: str, *, file_path: str, line: int, reason: str) -> dict[str, Any]:
    return {
        "id": _stable_id("E", edge_type, source, target, file_path, str(line), reason),
        "type": edge_type,
        "source": source,
        "target": target,
        "target_status": "resolved",
        "evidence": [{"file_path": file_path, "line": line, "reason": reason}],
        "confidence": _VERIFIED,
        "verification_source": "kernel_dispatch_resolver",
    }


def _merge_facts(entrypoint_graph: dict[str, Any], facts: dict[str, Any], *, architecture: str) -> dict[str, Any]:
    nodes = {
        str(node.get("id")): dict(node)
        for node in (entrypoint_graph.get("nodes") or [])
        if isinstance(node, dict) and node.get("id")
    }
    for demotion in facts.get("demotions") or []:
        nid = str(demotion.get("id") or "")
        if nid in nodes:
            nodes[nid]["role"] = demotion.get("role")
            nodes[nid]["status"] = "verified"
            nodes[nid]["confidence"] = _VERIFIED
            nodes[nid]["verification_source"] = "kernel_dispatch_resolver"
            nodes[nid]["kernel_role_demoted_from"] = "public_kernel_entry"
    for node in facts.get("nodes") or []:
        if isinstance(node, dict) and node.get("id"):
            nodes[str(node["id"])] = dict(node)

    edges = [dict(edge) for edge in (entrypoint_graph.get("edges") or []) if isinstance(edge, dict)]
    by_id = {str(edge.get("id")): edge for edge in edges if edge.get("id")}
    for edge in facts.get("edges") or []:
        if isinstance(edge, dict) and edge.get("id"):
            by_id[str(edge["id"])] = dict(edge)
    edges = list(by_id.values())

    _apply_link_status(nodes, edges)
    entrypoint_graph["nodes"] = sorted(nodes.values(), key=lambda n: (n.get("role") or "", n.get("id") or ""))
    entrypoint_graph["edges"] = edges
    entrypoint_graph["closure"] = _evaluate_closure(nodes, edges, architecture)
    entrypoint_graph["extraction_units"] = _build_extraction_units(nodes, edges, architecture)
    return entrypoint_graph


def apply_cached_kernel_dispatch_facts(
    entrypoint_graph: dict[str, Any], facts: dict[str, Any], *, architecture: str
) -> dict[str, Any]:
    """Reapply cached source-proven dispatch facts to a freshly rebuilt entrypoint graph."""
    return _merge_facts(entrypoint_graph, facts or {}, architecture=architecture)


def resolve_kernel_dispatch_semantics(
    entrypoint_graph: dict[str, Any],
    source_texts: dict[str, str],
    *,
    op_name: str,
    architecture: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve real kernel entry → dispatcher → concrete implementation chains."""
    nodes = {
        str(node.get("id")): dict(node)
        for node in (entrypoint_graph.get("nodes") or [])
        if isinstance(node, dict) and node.get("id")
    }
    demotions = _demote_false_kernel_entries(nodes)
    entrypoint_graph["nodes"] = list(nodes.values())

    all_functions: list[FunctionFact] = []
    macros_by_file: dict[str, dict[str, dict[str, Any]]] = {}
    for file_path, text in source_texts.items():
        if "op_kernel" not in _path_parts(file_path):
            continue
        all_functions.extend(_functions(file_path, text))
        macros_by_file[file_path] = _macro_definitions(text)

    op_norm = _norm(op_name)
    public_functions = [
        fact
        for fact in all_functions
        if fact.is_global and _norm(fact.name) == op_norm
    ]

    expanded_by_key: dict[tuple[str, str, int], str] = {}
    kernel_types_by_key: dict[tuple[str, str, int], list[str]] = {}
    dispatchers: list[FunctionFact] = []
    for fact in all_functions:
        key = (fact.file_path, fact.name, fact.start_line)
        expanded = _expanded_body(fact.body, macros_by_file.get(fact.file_path, {}))
        expanded_by_key[key] = expanded
        ktypes = _kernel_types(expanded)
        kernel_types_by_key[key] = ktypes
        if not fact.is_global and (ktypes or "INVOKE_" in fact.body):
            dispatchers.append(fact)

    fact_nodes: list[dict[str, Any]] = []
    fact_edges: list[dict[str, Any]] = []
    node_by_function: dict[tuple[str, str, int], dict[str, Any]] = {}
    dispatcher_names = {fact.name for fact in dispatchers}

    for fact in public_functions:
        node = _node_for_function(fact, role="public_kernel_entry", architecture=architecture)
        fact_nodes.append(node)
        node_by_function[(fact.file_path, fact.name, fact.start_line)] = node

    for fact in dispatchers:
        node = _node_for_function(fact, role="template_dispatcher", architecture=architecture)
        fact_nodes.append(node)
        node_by_function[(fact.file_path, fact.name, fact.start_line)] = node

    dispatchers_by_name: dict[str, list[FunctionFact]] = {}
    for fact in dispatchers:
        dispatchers_by_name.setdefault(fact.name, []).append(fact)

    concrete_nodes: dict[str, dict[str, Any]] = {}
    for fact in dispatchers:
        dispatcher_node = node_by_function[(fact.file_path, fact.name, fact.start_line)]
        key = (fact.file_path, fact.name, fact.start_line)
        for kernel_type in kernel_types_by_key.get(key, []):
            concrete = concrete_nodes.setdefault(
                kernel_type,
                _node_for_kernel_type(
                    kernel_type,
                    file_path=fact.file_path,
                    line=fact.start_line,
                    architecture=architecture,
                ),
            )
            fact_edges.append(
                _edge(
                    "instantiates",
                    dispatcher_node["id"],
                    concrete["id"],
                    file_path=fact.file_path,
                    line=fact.start_line,
                    reason="bounded_macro_template_instantiation",
                )
            )

    for fact in public_functions:
        public_node = node_by_function[(fact.file_path, fact.name, fact.start_line)]
        key = (fact.file_path, fact.name, fact.start_line)
        expanded = expanded_by_key.get(key, fact.body)
        called = _called_names(expanded, dispatcher_names)
        for name in sorted(called):
            candidates = dispatchers_by_name.get(name) or []
            if len(candidates) != 1:
                continue
            dispatcher = candidates[0]
            dispatcher_node = node_by_function[(dispatcher.file_path, dispatcher.name, dispatcher.start_line)]
            fact_edges.append(
                _edge(
                    "dispatches_to",
                    public_node["id"],
                    dispatcher_node["id"],
                    file_path=fact.file_path,
                    line=fact.start_line,
                    reason="direct_or_bounded_macro_dispatch_call",
                )
            )
        for kernel_type in _kernel_types(expanded):
            concrete = concrete_nodes.setdefault(
                kernel_type,
                _node_for_kernel_type(
                    kernel_type,
                    file_path=fact.file_path,
                    line=fact.start_line,
                    architecture=architecture,
                ),
            )
            fact_edges.append(
                _edge(
                    "instantiates",
                    public_node["id"],
                    concrete["id"],
                    file_path=fact.file_path,
                    line=fact.start_line,
                    reason="public_kernel_direct_template_instantiation",
                )
            )

    fact_nodes.extend(concrete_nodes.values())
    facts = {
        "version": 1,
        "nodes": fact_nodes,
        "edges": fact_edges,
        "demotions": demotions,
        "stats": {
            "source_file_count": len(source_texts),
            "aicore_function_count": len(all_functions),
            "public_kernel_count": len(public_functions),
            "dispatcher_count": len(dispatchers),
            "concrete_kernel_count": len(concrete_nodes),
            "dispatch_edge_count": sum(1 for edge in fact_edges if edge.get("type") == "dispatches_to"),
            "instantiation_edge_count": sum(1 for edge in fact_edges if edge.get("type") == "instantiates"),
            "demoted_false_public_count": len(demotions),
        },
    }
    entrypoint_graph = _merge_facts(entrypoint_graph, facts, architecture=architecture)
    return entrypoint_graph, facts
