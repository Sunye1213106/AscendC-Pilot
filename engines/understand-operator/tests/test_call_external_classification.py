from __future__ import annotations

from uo.scripts.function_body import CallSite, FunctionDefinition, extract_call_sites
from uo.scripts.function_call_graph import build_call_edges_for_functions, resolve_call_site


def _fn(body: str = "void Run() {}") -> FunctionDefinition:
    return FunctionDefinition(
        name="Run",
        qualified_name="Driver::Run",
        class_or_namespace="Driver",
        normalized_signature="()",
        template_arity_or_signature="",
        specialization_kind="none",
        file_path="op_kernel/test.cpp",
        start_line=1,
        end_line=max(1, body.count("\n") + 1),
        header_text="void Run()",
        body_text=body,
        source_hash="s",
        snippet_hash="h",
        identity_key="IK_CALLER",
        stable_id="FN_CALLER",
    )


def _site(name: str, *, receiver: str = "", hint: str = "") -> CallSite:
    return CallSite(
        caller_function_id="FN_CALLER",
        callee_name=name,
        callee_qualified_hint=hint or name,
        call_expression=f"{receiver}{name}",
        file_path="op_kernel/test.cpp",
        line=2,
        receiver_type_or_object=receiver,
        template_args="",
        argument_count=1,
        ordinal_in_function=1,
        snippet_hash="x",
    )


def test_custom_call_noise_filters_constexpr() -> None:
    fn = _fn("void Run() { if constexpr (FLAG) { Helper(); } }")
    unresolved: list[dict] = []
    _nodes, edges = build_call_edges_for_functions([fn], unresolved=unresolved)
    assert all(edge.get("callee_name") != "constexpr" for edge in edges)
    assert all(item.get("callee_name") != "constexpr" for item in unresolved)


def test_object_receiver_without_internal_definition_becomes_external() -> None:
    caller = _fn()
    edge, _node, unresolved = resolve_call_site(
        _site("SetGlobalBuffer", receiver="tensor."),
        caller,
        by_name={},
        by_qn={},
        by_id={},
    )
    assert edge and edge["target_status"] == "external"
    assert edge["verification_source"] == "object_receiver_without_internal_definition"
    assert edge["_external_target_node"]["node_type"] == "ExternalFunction"
    assert unresolved is None


def test_api_style_symbol_without_internal_definition_becomes_external() -> None:
    caller = _fn()
    edge, _node, unresolved = resolve_call_site(
        _site("DataCopy"),
        caller,
        by_name={},
        by_qn={},
        by_id={},
    )
    assert edge and edge["target_status"] == "external"
    assert edge["verification_source"] == "api_style_symbol_without_internal_definition"
    assert unresolved is None


def test_lowercase_unqualified_missing_stays_auditable() -> None:
    caller = _fn()
    edge, _node, unresolved = resolve_call_site(
        _site("helper"),
        caller,
        by_name={},
        by_qn={},
        by_id={},
    )
    assert edge and edge["target_status"] == "missing"
    assert unresolved and unresolved["kind"] == "internal_definition_not_indexed"


def test_external_nodes_are_deduplicated() -> None:
    fn = _fn("void Run() { DataCopy(a); DataCopy(b); }")
    unresolved: list[dict] = []
    nodes, edges = build_call_edges_for_functions([fn], unresolved=unresolved)
    externals = [node for node in nodes if node.get("node_type") == "ExternalFunction"]
    assert len(externals) == 1
    assert len([edge for edge in edges if edge.get("target_status") == "external"]) == 2
    assert not unresolved
