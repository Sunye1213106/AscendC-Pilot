from __future__ import annotations

from uo.scripts.function_body import CallSite, FunctionDefinition
from uo.scripts.function_call_graph import build_call_edges_for_functions, collect_call_resolution_facts


def _fn(
    *,
    name: str,
    owner: str,
    header: str,
    body: str,
    signature: str,
    stable_id: str,
    line: int = 1,
) -> FunctionDefinition:
    return FunctionDefinition(
        name=name,
        qualified_name=f"{owner}::{name}" if owner else name,
        class_or_namespace=owner,
        normalized_signature=signature,
        template_arity_or_signature="",
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
    return next(item for item in edges if item.get("source") == caller and item.get("callee_name") == callee)


def test_parameter_parser_handles_multiple_template_parameters() -> None:
    caller = _fn(
        name="Run",
        owner="Driver",
        header="void Driver::Run(TBuf<> &first, TBuf<> &second) {",
        body="void Driver::Run(TBuf<> &first, TBuf<> &second) { second.Get<int>(); }",
        signature="(TBuf<>&first,TBuf<>&second)",
        stable_id="FN_RUN",
    )
    get_fn = _fn(
        name="Get",
        owner="TBuf",
        header="template <typename T> LocalTensor<T> TBuf::Get() {",
        body="template <typename T> LocalTensor<T> TBuf::Get() { return {}; }",
        signature="()",
        stable_id="FN_GET",
    )
    unresolved: list[dict] = []
    nodes, edges = build_call_edges_for_functions(
        [caller, get_fn],
        unresolved=unresolved,
        source_texts={"op_kernel/test.h": caller.body_text + "\n" + get_fn.body_text},
    )
    call = _edge(edges, caller.stable_id, "Get")
    site = next(node for node in nodes if node.get("id") == call.get("call_site_id"))
    assert call["target_status"] == "resolved"
    assert site["receiver_type"] == "TBuf<>"


def test_class_member_type_resolves_member_call() -> None:
    source = """
class Buffer { public: void Init() {} };
class Policy {
public:
  void Run() { buffer_.Init(); }
private:
  Buffer buffer_;
};
"""
    caller = _fn(
        name="Run", owner="Policy", header="void Policy::Run() {",
        body="void Policy::Run() { buffer_.Init(); }", signature="()", stable_id="FN_RUN",
    )
    init_fn = _fn(
        name="Init", owner="Buffer", header="void Buffer::Init() {",
        body="void Buffer::Init() {}", signature="()", stable_id="FN_INIT",
    )
    unresolved: list[dict] = []
    nodes, edges = build_call_edges_for_functions(
        [caller, init_fn], unresolved=unresolved, source_texts={"op_kernel/test.h": source}
    )
    call = _edge(edges, caller.stable_id, "Init")
    site = next(node for node in nodes if node.get("id") == call.get("call_site_id"))
    assert call["target_status"] == "resolved"
    assert site["receiver_type"] == "Buffer"


def test_one_hop_auto_return_type_resolves_following_member() -> None:
    source = """
template <typename T> class Buffer {
public:
  template <typename U> LocalTensor<U> GetTensor() { return {}; }
};
template <typename T> class Policy {
public:
  Buffer<T> &Get() { return buffer_; }
private:
  Buffer<T> buffer_;
};
class Driver {
public:
  void Run(Policy<int> &policy) {
    auto &buffer = policy.Get();
    buffer.GetTensor<float>();
  }
};
"""
    caller = _fn(
        name="Run", owner="Driver", header="void Driver::Run(Policy<int> &policy) {",
        body="void Driver::Run(Policy<int> &policy) {\n auto &buffer = policy.Get();\n buffer.GetTensor<float>();\n}",
        signature="(Policy<int>&policy)", stable_id="FN_RUN",
    )
    get_fn = _fn(
        name="Get", owner="Policy", header="Buffer<T> &Policy::Get() {",
        body="Buffer<T> &Policy::Get() { return buffer_; }", signature="()", stable_id="FN_POLICY_GET",
    )
    tensor_fn = _fn(
        name="GetTensor", owner="Buffer", header="template <typename U> LocalTensor<U> Buffer::GetTensor() {",
        body="template <typename U> LocalTensor<U> Buffer::GetTensor() { return {}; }",
        signature="()", stable_id="FN_GET_TENSOR",
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, get_fn, tensor_fn], source_texts={"op_kernel/test.h": source}
    )
    nodes, edges = build_call_edges_for_functions(
        [caller, get_fn, tensor_fn], unresolved=unresolved, facts=facts
    )
    first = _edge(edges, caller.stable_id, "Get")
    second = _edge(edges, caller.stable_id, "GetTensor")
    second_site = next(node for node in nodes if node.get("id") == second.get("call_site_id"))
    assert first["target_status"] == "resolved"
    assert second["target_status"] == "resolved"
    assert second_site["receiver_type"].startswith("Buffer<")
    assert not any(item.get("callee_name") == "GetTensor" for item in unresolved)



def test_official_receiver_method_precedes_unrelated_short_name_candidate() -> None:
    caller = _fn(
        name="Run", owner="Driver", header="void Driver::Run(TBuf<> &buffer) {",
        body="void Driver::Run(TBuf<> &buffer) { buffer.Get<int>(); }",
        signature="(TBuf<>&buffer)", stable_id="FN_RUN",
    )
    unrelated = _fn(
        name="Get", owner="Policy", header="Buffer<int> &Policy::Get() {",
        body="Buffer<int> &Policy::Get() { return buffer_; }",
        signature="()", stable_id="FN_POLICY_GET",
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, unrelated],
        source_texts={"op_kernel/test.h": caller.body_text + "\n" + unrelated.body_text},
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, unrelated], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Get")
    assert call["target_status"] == "external"
    assert call["verification_source"] == "official_contract:receiver_type"
    assert not any(item.get("callee_name") == "Get" for item in unresolved)
