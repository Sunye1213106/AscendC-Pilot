from __future__ import annotations

from uo.scripts.function_body import FunctionDefinition, extract_call_sites


def _fn(body: str) -> FunctionDefinition:
    return FunctionDefinition(
        name="Run",
        qualified_name="K::Run",
        class_or_namespace="K",
        normalized_signature="()",
        template_arity_or_signature="",
        specialization_kind="none",
        file_path="k.h",
        start_line=1,
        end_line=max(1, body.count("\n") + 1),
        header_text="void K::Run()",
        body_text=body,
        source_hash="s",
        snippet_hash="h",
        identity_key="IK",
        stable_id="FN",
    )


def _names(body: str) -> list[str]:
    return [site.callee_name for site in extract_call_sites(_fn(body))]


def test_masks_comments_strings_and_preprocessor_directives() -> None:
    names = _names(
        'void Run() {\n'
        '  // dataSize(fp32), matrixA(ky,kx)\n'
        '  /* dimD(K) */\n'
        '  const char *s = "singleN(8)";\n'
        '#define LOCAL(x) (x)\n'
        '  RealCall();\n'
        '}'
    )
    assert names == ["RealCall"]


def test_comparison_is_not_template_call_but_nested_template_call_is() -> None:
    names = _names(
        "void Run() { for (uint16_t m = 0; m < static_cast<uint16_t>(srcM); ++m) { Foo<Bar<Baz>>(m); } }"
    )
    assert "m" not in names
    assert "static_cast" not in names
    assert names.count("Foo") == 1


def test_direct_initialization_and_builtin_casts_are_not_calls() -> None:
    names = _names(
        "void Run() { FixpipeParams<float> params(1); int64_t x = int64_t(v); bool ok = bool(flag); Execute(params); }"
    )
    assert "params" not in names
    assert "int64_t" not in names
    assert "bool" not in names
    assert names == ["Execute"]


def test_template_member_call_preserves_receiver() -> None:
    sites = extract_call_sites(_fn("void Run() { obj.template Get<int>(0); }"))
    assert len(sites) == 1
    assert sites[0].callee_name == "Get"
    assert sites[0].receiver_type_or_object == "obj."
    assert sites[0].template_args


def test_indexed_member_call_preserves_base_receiver() -> None:
    sites = extract_call_sites(_fn("void Run() { queues[idx].template AllocTensor<float>(); }"))
    assert len(sites) == 1
    assert sites[0].callee_name == "AllocTensor"
    assert sites[0].receiver_type_or_object == "queues[]."


def test_chained_accessor_call_preserves_receiver() -> None:
    sites = extract_call_sites(_fn("void Run() { GetTPipePtr()->FetchEventID(HardEvent::S_V); }"))
    names = {site.callee_name: site for site in sites}
    assert names["FetchEventID"].receiver_type_or_object == "GetTPipePtr()->"
