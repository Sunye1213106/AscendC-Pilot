"""Tests for general unresolved-hardening helpers (no FAG-specific names)."""
from __future__ import annotations

from uo.scripts.function_body import FunctionDefinition
from uo.scripts.function_call_graph import build_call_edges_for_functions, collect_call_resolution_facts
from uo.scripts.type_normalizer import narrow_receiver_for_method_call


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


def test_nullptr_conditional_receiver_narrows_to_object_type() -> None:
    narrowed = narrow_receiver_for_method_call(
        "std::conditional<FLAG,MutexBuffersPolicyDB<BufferType::L1>,std::nullptr_t>::type"
    )
    assert "MutexBuffersPolicyDB" in narrowed
    assert "nullptr" not in narrowed


def test_conditional_t_receiver_methods_resolve() -> None:
    source = """
using PolicyType = std::conditional_t<FLAG, RealPolicy, DummyPolicy>;
class RealPolicy { public: void *Get() { return nullptr; } };
class DummyPolicy { public: void *Get() { return nullptr; } };
class Driver {
public:
  PolicyType policy;
  void Run() { auto *p = policy.Get(); }
};
"""
    caller = _fn(
        name="Run", owner="Driver", header="void Driver::Run() {",
        body="void Driver::Run() { auto *p = policy.Get(); }",
        signature="()", stable_id="FN_RUN",
    )
    real = _fn(
        name="Get", owner="RealPolicy", header="void *RealPolicy::Get() {",
        body="void *RealPolicy::Get() { return nullptr; }",
        signature="()", stable_id="FN_REAL", line=2,
    )
    dummy = _fn(
        name="Get", owner="DummyPolicy", header="void *DummyPolicy::Get() {",
        body="void *DummyPolicy::Get() { return nullptr; }",
        signature="()", stable_id="FN_DUMMY", line=3,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, real, dummy], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, real, dummy], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Get")
    assert call["target_status"] == "resolved"


def test_out_of_line_destructor_binds_member_receiver() -> None:
    source = """
class BufferPolicy { public: void Uninit(int x) {} };
class Kernel {
public:
  BufferPolicy buf;
  ~Kernel();
};
Kernel::~Kernel() { buf.Uninit(1); }
"""
    caller = FunctionDefinition(
        name="Kernel",
        qualified_name="Kernel::~Kernel",
        class_or_namespace="Kernel",
        normalized_signature="()",
        template_arity_or_signature="",
        specialization_kind="none",
        file_path="op_kernel/test.h",
        start_line=6,
        end_line=6,
        header_text="Kernel::~Kernel() {",
        body_text="Kernel::~Kernel() { buf.Uninit(1); }",
        source_hash="s",
        snippet_hash="dtor",
        identity_key="IK_DTOR",
        stable_id="FN_DTOR",
    )
    uninit = _fn(
        name="Uninit", owner="BufferPolicy",
        header="void BufferPolicy::Uninit(int x) {",
        body="void BufferPolicy::Uninit(int x) {}",
        signature="(int x)", stable_id="FN_UNINIT", line=2,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, uninit], source_texts={"op_kernel/test.h": source}
    )
    nodes, edges = build_call_edges_for_functions(
        [caller, uninit], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Uninit")
    site = next(node for node in nodes if node.get("id") == call.get("call_site_id"))
    assert call["target_status"] == "resolved"
    assert site["receiver_type"] == "BufferPolicy"


def test_non_function_template_args_do_not_block_equivalence() -> None:
    source = """
using BlockType = std::conditional<FLAG, RealBlock, DummyBlock>::type;
class RealBlock { public: void InitUbBuffer() {} };
class DummyBlock { public: void InitUbBuffer() {} };
class Driver {
public:
  BlockType block;
  void Run() { block.InitUbBuffer(); }
};
"""
    caller = _fn(
        name="Run", owner="Driver", header="void Driver::Run() {",
        body="void Driver::Run() { block.InitUbBuffer(); }",
        signature="()", stable_id="FN_RUN",
    )
    real = FunctionDefinition(
        name="InitUbBuffer",
        qualified_name="RealBlock::InitUbBuffer",
        class_or_namespace="RealBlock",
        normalized_signature="()",
        template_arity_or_signature="TEMPLATE_ARGS",
        specialization_kind="none",
        file_path="op_kernel/test.h",
        start_line=2,
        end_line=2,
        header_text="void RealBlock<TEMPLATE_ARGS>::InitUbBuffer() {",
        body_text="void RealBlock<TEMPLATE_ARGS>::InitUbBuffer() {}",
        source_hash="s",
        snippet_hash="real",
        identity_key="IK_REAL",
        stable_id="FN_REAL",
    )
    dummy = FunctionDefinition(
        name="InitUbBuffer",
        qualified_name="DummyBlock::InitUbBuffer",
        class_or_namespace="DummyBlock",
        normalized_signature="()",
        template_arity_or_signature="HardEvent::MTE3_S",
        specialization_kind="none",
        file_path="op_kernel/test.h",
        start_line=3,
        end_line=3,
        header_text="void InitUbBuffer(){};",
        body_text="void InitUbBuffer(){};",
        source_hash="s",
        snippet_hash="dummy",
        identity_key="IK_DUMMY",
        stable_id="FN_DUMMY",
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, real, dummy], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, real, dummy], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "InitUbBuffer")
    assert call["target_status"] == "resolved"


def test_multi_declarator_members_resolve_official_method() -> None:
    source = """
class Kernel {
public:
  void Init() {
    keyGm.SetGlobalBuffer((__gm__ float *)ptr);
  }
  GlobalTensor<float> queryGm, keyGm, valueGm;
};
"""
    caller = _fn(
        name="Init", owner="Kernel", header="void Kernel::Init() {",
        body="void Kernel::Init() {\n  keyGm.SetGlobalBuffer((__gm__ float *)ptr);\n}",
        signature="()", stable_id="FN_INIT",
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "SetGlobalBuffer")
    assert call["target_status"] == "external"
    assert "official_contract" in call["verification_source"]


def test_inherited_member_type_resolves_receiver() -> None:
    source = """
class Base {
public:
  BufferPolicy policy;
};
class Child : public Base {
public:
  void Run() { policy.Init(1); }
};
class BufferPolicy {
public:
  void Init(int x) {}
};
"""
    caller = _fn(
        name="Run", owner="Child", header="void Child::Run() {",
        body="void Child::Run() { policy.Init(1); }",
        signature="()", stable_id="FN_RUN",
    )
    init_fn = _fn(
        name="Init", owner="BufferPolicy", header="void BufferPolicy::Init(int x) {",
        body="void BufferPolicy::Init(int x) {}",
        signature="(int x)", stable_id="FN_INIT", line=2,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, init_fn], source_texts={"op_kernel/test.h": source}
    )
    nodes, edges = build_call_edges_for_functions(
        [caller, init_fn], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Init")
    site = next(node for node in nodes if node.get("id") == call.get("call_site_id"))
    assert call["target_status"] == "resolved"
    assert site["receiver_type"] == "BufferPolicy"


def test_signature_equivalent_conditional_owners_resolve() -> None:
    source = """
using BlockType = std::conditional<FLAG, RealBlock, DummyBlock>::type;
class RealBlock { public: void Process(int x) {} };
class DummyBlock { public: void Process(int x) {} };
class Driver {
public:
  BlockType block;
  void Run() { block.Process(1); }
};
"""
    caller = _fn(
        name="Run", owner="Driver", header="void Driver::Run() {",
        body="void Driver::Run() { block.Process(1); }",
        signature="()", stable_id="FN_RUN",
    )
    real = _fn(
        name="Process", owner="RealBlock", header="void RealBlock::Process(int x) {",
        body="void RealBlock::Process(int x) {}",
        signature="(int x)", stable_id="FN_REAL", line=2,
    )
    dummy = _fn(
        name="Process", owner="DummyBlock", header="void DummyBlock::Process(int x) {",
        body="void DummyBlock::Process(int x) {}",
        signature="(int x)", stable_id="FN_DUMMY", line=3,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, real, dummy], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, real, dummy], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Process")
    assert call["target_status"] == "resolved"
    assert "signature_equivalent" in call["verification_source"]
    assert set(call["candidate_ids"]) == {real.stable_id, dummy.stable_id}


def test_same_file_identical_signature_duplicates_resolve() -> None:
    source = """
#ifndef TEST_MODE
void Helper(int x) {}
#else
void Helper(int x) {}
#endif
void Driver() { Helper(1); }
"""
    first = _fn(
        name="Helper", owner="", header="void Helper(int x) {",
        body="void Helper(int x) {}",
        signature="(int x)", stable_id="FN_A",
    )
    second = _fn(
        name="Helper", owner="", header="void Helper(int x) {",
        body="void Helper(int x) {}",
        signature="(int x)", stable_id="FN_B", line=4,
    )
    caller = _fn(
        name="Driver", owner="", header="void Driver() {",
        body="void Driver() { Helper(1); }",
        signature="()", stable_id="FN_DRIVER", line=6,
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller, first, second], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller, first, second], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "Helper")
    assert call["target_status"] == "resolved"


def test_aliased_tensor_receiver_matches_official_method_contract() -> None:
    source = """
class MutexBuffer {
public:
  using TensorType = LocalTensor<uint8_t>;
  TensorType tensor_;
  void Run() { tensor_.ReinterpretCast<float>(); }
};
"""
    caller = _fn(
        name="Run", owner="MutexBuffer", header="void MutexBuffer::Run() {",
        body="void MutexBuffer::Run() { tensor_.ReinterpretCast<float>(); }",
        signature="()", stable_id="FN_RUN",
    )
    unresolved: list[dict] = []
    facts = collect_call_resolution_facts(
        [caller], source_texts={"op_kernel/test.h": source}
    )
    _nodes, edges = build_call_edges_for_functions(
        [caller], unresolved=unresolved, facts=facts
    )
    call = _edge(edges, caller.stable_id, "ReinterpretCast")
    assert call["target_status"] == "external"
    assert "official_contract" in call["verification_source"]


def test_type_like_construction_is_external() -> None:
    caller = _fn(
        name="Run", owner="Driver", header="void Driver::Run() {",
        body="void Driver::Run() { AxisType(value); }",
        signature="()", stable_id="FN_RUN",
    )
    unresolved: list[dict] = []
    _nodes, edges = build_call_edges_for_functions([caller], unresolved=unresolved)
    call = _edge(edges, caller.stable_id, "AxisType")
    assert call["target_status"] == "external"
    assert call["verification_source"] == "type_like_construction"
