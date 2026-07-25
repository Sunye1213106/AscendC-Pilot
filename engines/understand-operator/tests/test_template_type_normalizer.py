from uo.scripts.type_normalizer import collect_type_aliases, expand_type_candidates
from uo.scripts.receiver_type_facts import build_receiver_type_facts
from uo.scripts.function_body import FunctionDefinition


def _fn(name: str, owner: str, header: str, body: str, stable_id: str) -> FunctionDefinition:
    return FunctionDefinition(
        name=name, qualified_name=f"{owner}::{name}", class_or_namespace=owner,
        normalized_signature="()", template_arity_or_signature="", specialization_kind="none",
        file_path="op_kernel/test.h", start_line=1, end_line=body.count("\n") + 1,
        header_text=header, body_text=body, source_hash="s", snippet_hash="h",
        identity_key=f"IK_{stable_id}", stable_id=stable_id,
    )


def test_alias_and_conditional_expansion_is_bounded() -> None:
    source = "using Chosen = std::conditional<FLAG, Buffer<int>, std::nullptr_t>::type;"
    aliases = collect_type_aliases({"x.h": source})
    assert expand_type_candidates("Chosen", aliases, max_depth=2) == {"Buffer<int>", "std::nullptr_t"}


def test_conditional_t_and_nested_type_alias_expand() -> None:
    source = """
struct BuffSelector {
  using TYPE = std::conditional_t<FLAG, MutexBuffersPolicyDB<BufferType::L1>, MutexBuffersPolicySingleBuffer<BufferType::L1>>;
};
using Chosen = std::conditional_t<REUSE, BuffSelector<FLAG>::TYPE, std::nullptr_t>;
"""
    aliases = collect_type_aliases({"x.h": source})
    expanded = expand_type_candidates("Chosen", aliases, max_depth=4)
    assert "std::nullptr_t" in expanded
    assert any("MutexBuffersPolicyDB" in item for item in expanded)
    assert any("MutexBuffersPolicySingleBuffer" in item for item in expanded)
    from uo.scripts.type_normalizer import narrow_receiver_for_method_call

    # Unique object branch after dropping nullptr_t.
    narrowed = narrow_receiver_for_method_call(
        "std::conditional_t<REUSE,MutexBuffersPolicyDB<BufferType::L1>,std::nullptr_t>",
        aliases,
    )
    assert "MutexBuffersPolicyDB" in narrowed
    assert "nullptr" not in narrowed


def test_bounded_return_propagation_binds_dependent_auto() -> None:
    source = """
class Leaf { public: void Run() {} };
class Mid { public: Leaf &GetLeaf() { return leaf_; } private: Leaf leaf_; };
class Root { public: Mid &GetMid() { return mid_; } private: Mid mid_; };
class Driver { public: void Go(Root &root) {
  auto &mid = root.GetMid();
  auto &leaf = mid.GetLeaf();
  leaf.Run();
}};
"""
    go = _fn("Go", "Driver", "void Driver::Go(Root &root) {", "void Driver::Go(Root &root) {\n auto &mid=root.GetMid();\n auto &leaf=mid.GetLeaf();\n leaf.Run();\n}", "GO")
    get_mid = _fn("GetMid", "Root", "Mid &Root::GetMid() {", "Mid &Root::GetMid() { return mid_; }", "GM")
    get_leaf = _fn("GetLeaf", "Mid", "Leaf &Mid::GetLeaf() {", "Leaf &Mid::GetLeaf() { return leaf_; }", "GL")
    run = _fn("Run", "Leaf", "void Leaf::Run() {", "void Leaf::Run() {}", "RUN")
    facts = build_receiver_type_facts([go, get_mid, get_leaf, run], {"op_kernel/test.h": source})
    bindings = {item.name: item for item in facts.bindings_by_function[go.stable_id]}
    assert bindings["mid"].type_name == "Mid"
    assert bindings["leaf"].type_name == "Leaf"
    assert bindings["leaf"].source in {"one_hop_return", "two_hop_return"}
