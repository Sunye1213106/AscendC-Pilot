from __future__ import annotations

from uo.scripts.function_body import CallSite, FunctionDefinition, extract_call_sites
from uo.scripts.function_call_graph import (
    CallResolutionFacts,
    build_call_edges_for_functions,
    collect_call_resolution_facts,
    resolve_call_site,
)


def _fn(
    body: str = "void Run() {}",
    *,
    name: str = "Run",
    qualified_name: str = "Driver::Run",
    owner: str = "Driver",
    stable_id: str = "FN_CALLER",
) -> FunctionDefinition:
    return FunctionDefinition(
        name=name,
        qualified_name=qualified_name,
        class_or_namespace=owner,
        normalized_signature="()",
        template_arity_or_signature="",
        specialization_kind="none",
        file_path="op_kernel/test.cpp",
        start_line=1,
        end_line=max(1, body.count("\n") + 1),
        header_text=f"void {qualified_name}()",
        body_text=body,
        source_hash="s",
        snippet_hash="h",
        identity_key=f"IK_{stable_id}",
        stable_id=stable_id,
    )


def _site(name: str, *, receiver: str = "", hint: str = "", argc: int = 1) -> CallSite:
    return CallSite(
        caller_function_id="FN_CALLER",
        callee_name=name,
        callee_qualified_hint=hint or name,
        call_expression=f"{receiver}{name}",
        file_path="op_kernel/test.cpp",
        line=2,
        receiver_type_or_object=receiver,
        template_args="",
        argument_count=argc,
        ordinal_in_function=1,
        snippet_hash="x",
    )


def test_custom_call_noise_filters_constexpr_and_comments() -> None:
    fn = _fn(
        'void Run() { // dataSize(fp32)\n'
        '  const char *s = "matrixA(ky, kx)";\n'
        '  if constexpr (FLAG) { Helper(); }\n'
        '}'
    )
    sites = extract_call_sites(fn)
    names = {site.callee_name for site in sites}
    assert "constexpr" not in names
    assert "dataSize" not in names
    assert "matrixA" not in names
    assert "Helper" in names


def test_source_function_macro_becomes_macro_target() -> None:
    caller = _fn("void Run() { unlikely(flag); }")
    facts = collect_call_resolution_facts(
        [caller],
        source_texts={"op_kernel/test.cpp": "#define unlikely(x) __builtin_expect(!!(x), 0)\n" + caller.body_text},
    )
    edge, _node, unresolved = resolve_call_site(
        _site("unlikely"), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "macro"
    assert edge["verification_source"] == "source_function_macro"
    assert edge["_target_node"]["node_type"] == "CompileMacro"
    assert unresolved is None


def test_official_documented_interface_becomes_external() -> None:
    caller = _fn()
    facts = collect_call_resolution_facts(
        [caller],
        doc_evidence={
            "items": [
                {
                    "symbol_or_macro": "DataCopy",
                    "symbol_kind": "function",
                    "call_style": "free_function",
                    "qualified_names": ["AscendC::DataCopy"],
                    "argument_counts": [1],
                    "allow_unqualified": True,
                    "document_title": "CANN DataCopy API",
                    "document_url": "https://www.hiascend.com/document/detail/zh/canncommercial/900/API/ascendcopapi/atlasascendc_api_07_0103.html",
                    "cann_version": "9.1.0",
                    "semantic_summary": "Copies tensor data.",
                    "source_authority": "official_hiascend",
                    "confidence": 1.0,
                }
            ]
        },
    )
    edge, _node, unresolved = resolve_call_site(
        _site("DataCopy"), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "external"
    assert edge["verification_source"].startswith("official_contract:")
    assert edge["_target_node"]["official_contract"]["cann_version"] == "9.1.0"
    assert unresolved is None


def test_capitalized_unknown_without_evidence_stays_unresolved() -> None:
    caller = _fn()
    edge, _node, unresolved = resolve_call_site(
        _site("MissingHelper"), caller, by_name={}, by_qn={}, by_id={}
    )
    assert edge and edge["target_status"] == "missing"
    assert unresolved and unresolved["kind"] == "internal_definition_not_indexed"


def test_receiver_type_resolves_internal_member() -> None:
    caller = _fn("void Run() { Worker worker; worker.Process(1); }")
    callee = _fn(
        "void Process(int x) {}",
        name="Process",
        qualified_name="Worker::Process",
        owner="Worker",
        stable_id="FN_WORKER_PROCESS",
    )
    facts = collect_call_resolution_facts(
        [caller, callee], source_texts={"op_kernel/test.cpp": caller.body_text}
    )
    edge, _node, unresolved = resolve_call_site(
        _site("Process", receiver="worker."),
        caller,
        by_name={"Process": [callee]},
        by_qn={"Worker::Process": [callee]},
        by_id={callee.stable_id: callee},
        facts=facts,
    )
    assert edge and edge["target_status"] == "resolved"
    assert edge["target"] == callee.stable_id
    assert "receiver_type" in edge["verification_source"]
    assert unresolved is None


def test_packaged_contract_supports_unqualified_interface() -> None:
    caller = _fn("void Run() { DataCopy(a, b, 16); }")
    facts = collect_call_resolution_facts(
        [caller],
        source_texts={"op_kernel/test.cpp": "using namespace AscendC;\n" + caller.body_text},
    )
    edge, _node, unresolved = resolve_call_site(
        _site("DataCopy", argc=3), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "external"
    assert edge["verification_source"] == "official_contract:unqualified_free_function"
    assert edge["_target_node"]["official_contract"]["source_authority"] == "official_hiascend"
    assert unresolved is None


def test_using_namespace_does_not_prove_unknown_free_function() -> None:
    caller = _fn("void Run() { UnknownHelper(); }")
    facts = collect_call_resolution_facts(
        [caller],
        source_texts={"op_kernel/test.cpp": "using namespace AscendC;\n" + caller.body_text},
    )
    edge, _node, unresolved = resolve_call_site(
        _site("UnknownHelper", argc=0), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "missing"
    assert unresolved and unresolved["kind"] == "internal_definition_not_indexed"


def test_method_contract_requires_matching_receiver_type() -> None:
    caller = _fn("void Run() { Worker worker; worker.GetValue(0); }")
    facts = collect_call_resolution_facts(
        [caller], source_texts={"op_kernel/test.cpp": caller.body_text}
    )
    edge, _node, unresolved = resolve_call_site(
        _site("GetValue", receiver="worker.", argc=1),
        caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "missing"
    assert unresolved and unresolved["kind"] == "member_target_not_indexed"


def test_target_nodes_are_deduplicated() -> None:
    fn = _fn("void Run() { unlikely(a); unlikely(b); }")
    facts = CallResolutionFacts(source_macros={"unlikely"})
    nodes, edges = build_call_edges_for_functions([fn], unresolved=[], facts=facts)
    macros = [node for node in nodes if node.get("node_type") == "CompileMacro"]
    assert len(macros) == 1
    assert len([edge for edge in edges if edge.get("target_status") == "macro"]) == 2


def test_multiline_source_macro_keeps_compact_expansion_metadata() -> None:
    caller = _fn("void Run() { INVOKE_IMPL(float, true); }")
    source = """#define INVOKE_IMPL(T, FLAG) \\
    Kernel<T>(FLAG); \\
    SyncAll();
""" + caller.body_text
    facts = collect_call_resolution_facts(
        [caller], source_texts={"op_kernel/test.cpp": source}
    )
    edge, _node, unresolved = resolve_call_site(
        _site("INVOKE_IMPL", argc=2), caller, by_name={}, by_qn={}, by_id={}, facts=facts
    )
    assert edge and edge["target_status"] == "macro"
    definition = edge["_target_node"]["source_macro_definitions"][0]
    assert definition["end_line"] == 3
    assert definition["expands_to_symbols"] == ["Kernel", "SyncAll"]
    assert unresolved is None
