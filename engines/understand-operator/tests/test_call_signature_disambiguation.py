"""Focused tests for deterministic call-signature disambiguation."""
from __future__ import annotations

from uo.scripts.function_body import FunctionDefinition, extract_call_sites
from uo.scripts.function_call_graph import build_call_edges_for_functions, collect_call_resolution_facts


def _fn(
    *,
    name: str,
    owner: str,
    header: str,
    body: str,
    signature: str,
    stable_id: str,
    template: str = "",
    line: int = 1,
) -> FunctionDefinition:
    return FunctionDefinition(
        name=name,
        qualified_name=f"{owner}::{name}" if owner else name,
        class_or_namespace=owner,
        normalized_signature=signature,
        template_arity_or_signature=template,
        specialization_kind="none",
        file_path="op_kernel/test.h",
        start_line=line,
        end_line=line + body.count("\n"),
        header_text=header,
        body_text=body,
        source_hash="s",
        snippet_hash=stable_id,
        identity_key=f"IK_{stable_id}",
        stable_id=stable_id,
    )


def _edge(edges: list[dict], caller: str, callee: str) -> dict:
    return next(
        item
        for item in edges
        if item.get("source") == caller and item.get("callee_name") == callee
    )


def test_explicit_template_args_disambiguate_local_vs_global_tensor() -> None:
    source = """
template <typename T> void Run(LocalTensor<T> x) {}
template <typename T> void Run(GlobalTensor<T> x) {}
void Driver() {
  LocalTensor<float> x;
  Run<float>(x);
}
"""
    local = _fn(
        name="Run", owner="", header="template <typename T> void Run(LocalTensor<T> x) {",
        body="template <typename T> void Run(LocalTensor<T> x) {}",
        signature="(LocalTensor<T>x)", stable_id="FN_LOCAL", template="typename T",
    )
    global_fn = _fn(
        name="Run", owner="", header="template <typename T> void Run(GlobalTensor<T> x) {",
        body="template <typename T> void Run(GlobalTensor<T> x) {}",
        signature="(GlobalTensor<T>x)", stable_id="FN_GLOBAL", template="typename T", line=2,
    )
    caller = _fn(
        name="Driver", owner="", header="void Driver() {",
        body="void Driver() {\n  LocalTensor<float> x;\n  Run<float>(x);\n}",
        signature="()", stable_id="FN_DRIVER", line=3,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, local, global_fn], source_texts={"op_kernel/test.h": source}
    )
    nodes, edges = build_call_edges_for_functions(
        [caller, local, global_fn], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Run")
    site = next(node for node in nodes if node.get("id") == call.get("call_site_id"))
    assert call["target_status"] == "resolved"
    assert call["target"] == local.stable_id
    assert site["explicit_template_arguments"] == ["float"]
    assert site["argument_expressions"] == ["x"]
    assert site["argument_type_candidates"] == [["LocalTensor<float>"]]


def test_argument_type_disambiguates_local_vs_global_process() -> None:
    source = """
void Process(LocalTensor<float> x) {}
void Process(GlobalTensor<float> x) {}
void Driver() {
  LocalTensor<float> x;
  Process(x);
}
"""
    local = _fn(
        name="Process", owner="", header="void Process(LocalTensor<float> x) {",
        body="void Process(LocalTensor<float> x) {}",
        signature="(LocalTensor<float>x)", stable_id="FN_LOCAL",
    )
    global_fn = _fn(
        name="Process", owner="", header="void Process(GlobalTensor<float> x) {",
        body="void Process(GlobalTensor<float> x) {}",
        signature="(GlobalTensor<float>x)", stable_id="FN_GLOBAL", line=2,
    )
    caller = _fn(
        name="Driver", owner="", header="void Driver() {",
        body="void Driver() {\n  LocalTensor<float> x;\n  Process(x);\n}",
        signature="()", stable_id="FN_DRIVER", line=3,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, local, global_fn], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, local, global_fn], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Process")
    assert call["target_status"] == "resolved"
    assert call["target"] == local.stable_id


def test_argument_count_filters_init_overloads() -> None:
    source = """
class Obj {
public:
  void Init(int x) {}
  void Init(int x, int y) {}
  void Run() { Init(1); }
};
"""
    one = _fn(
        name="Init", owner="Obj", header="void Init(int x) {",
        body="void Init(int x) {}", signature="(int x)", stable_id="FN_INIT1",
    )
    two = _fn(
        name="Init", owner="Obj", header="void Init(int x, int y) {",
        body="void Init(int x, int y) {}", signature="(int x,int y)", stable_id="FN_INIT2", line=2,
    )
    caller = _fn(
        name="Run", owner="Obj", header="void Run() {",
        body="void Run() { Init(1); }", signature="()", stable_id="FN_RUN", line=3,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, one, two], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, one, two], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Init")
    assert call["target_status"] == "resolved"
    assert call["target"] == one.stable_id


def test_true_template_ambiguity_is_preserved() -> None:
    source = """
template <typename T> void Run(T x) {}
template <typename U> void Run(U x) {}
void Driver() {
  int x;
  Run(x);
}
"""
    first = _fn(
        name="Run", owner="", header="template <typename T> void Run(T x) {",
        body="template <typename T> void Run(T x) {}",
        signature="(T x)", stable_id="FN_T", template="typename T",
    )
    second = _fn(
        name="Run", owner="", header="template <typename U> void Run(U x) {",
        body="template <typename U> void Run(U x) {}",
        signature="(U x)", stable_id="FN_U", template="typename U", line=2,
    )
    caller = _fn(
        name="Driver", owner="", header="void Driver() {",
        body="void Driver() {\n  int x;\n  Run(x);\n}",
        signature="()", stable_id="FN_DRIVER", line=3,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, first, second], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, first, second], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Run")
    assert call["target_status"] == "candidate_set"
    assert set(call["candidate_ids"]) == {first.stable_id, second.stable_id}


def test_official_tbuf_get_not_regressed_by_project_short_name() -> None:
    source = """
class Policy { public: int Get() { return 0; } };
void Driver(TBuf<> &buf) {
  buf.Get<float>();
}
"""
    unrelated = _fn(
        name="Get", owner="Policy", header="int Policy::Get() {",
        body="int Policy::Get() { return 0; }", signature="()", stable_id="FN_POLICY_GET",
    )
    caller = _fn(
        name="Driver", owner="", header="void Driver(TBuf<> &buf) {",
        body="void Driver(TBuf<> &buf) {\n  buf.Get<float>();\n}",
        signature="(TBuf<>&buf)", stable_id="FN_DRIVER", line=2,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, unrelated], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, unrelated], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Get")
    assert call["target_status"] == "external"
    assert "official_contract" in call["verification_source"]
    assert not any(item.get("callee_name") == "Get" for item in unresolved)


def test_unknown_argument_expression_does_not_force_choice() -> None:
    source = """
void Run(LocalTensor<float> x) {}
void Run(GlobalTensor<float> x) {}
void Driver(LocalTensor<float> a, LocalTensor<float> b) {
  Run(a + b);
}
"""
    local = _fn(
        name="Run", owner="", header="void Run(LocalTensor<float> x) {",
        body="void Run(LocalTensor<float> x) {}",
        signature="(LocalTensor<float>x)", stable_id="FN_LOCAL",
    )
    global_fn = _fn(
        name="Run", owner="", header="void Run(GlobalTensor<float> x) {",
        body="void Run(GlobalTensor<float> x) {}",
        signature="(GlobalTensor<float>x)", stable_id="FN_GLOBAL", line=2,
    )
    caller = _fn(
        name="Driver", owner="",
        header="void Driver(LocalTensor<float> a, LocalTensor<float> b) {",
        body=(
            "void Driver(LocalTensor<float> a, LocalTensor<float> b) {\n"
            "  Run(a + b);\n"
            "}"
        ),
        signature="(LocalTensor<float>a,LocalTensor<float>b)",
        stable_id="FN_DRIVER",
        line=3,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, local, global_fn], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, local, global_fn], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Run")
    assert call["target_status"] == "candidate_set"
    assert set(call["candidate_ids"]) == {local.stable_id, global_fn.stable_id}


def test_call_site_keeps_raw_argument_expressions_and_template_args() -> None:
    body = (
        "void Driver() {\n"
        "  obj.GetTensor<float>();\n"
        "  Func<int32_t>(x);\n"
        "  Func(a, static_cast<uint32_t>(b));\n"
        "  Func(a[i], ptr->field);\n"
        "}"
    )
    caller = _fn(
        name="Driver", owner="", header="void Driver() {", body=body,
        signature="()", stable_id="FN_DRIVER",
    )
    sites = {site.callee_name + str(site.ordinal_in_function): site for site in extract_call_sites(caller)}
    get_tensor = next(site for site in extract_call_sites(caller) if site.callee_name == "GetTensor")
    assert get_tensor.explicit_template_arguments == ("float",)
    cast_site = next(
        site
        for site in extract_call_sites(caller)
        if site.callee_name == "Func" and site.argument_count == 2 and "static_cast" in ",".join(site.argument_expressions)
    )
    assert cast_site.argument_expressions[1].startswith("static_cast<uint32_t>")
    indexed = next(
        site
        for site in extract_call_sites(caller)
        if site.callee_name == "Func" and any("->" in expr for expr in site.argument_expressions)
    )
    assert indexed.argument_expressions == ("a[i]", "ptr->field")
    del sites
