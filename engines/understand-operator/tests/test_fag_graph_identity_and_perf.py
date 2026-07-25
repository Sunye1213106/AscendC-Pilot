from __future__ import annotations

from pathlib import Path

from uo.scripts.extract_host_subgraph import _chain_item_key, _writer_role_indexes
from uo.scripts.resolve_entrypoints import collect_entrypoint_candidates
from uo.scripts.propose_extract_plan import MAX_NON_SINK
from uo.scripts.function_body import (
    CallSite,
    FunctionDefinition,
    iter_function_definitions,
)
from uo.scripts.function_call_graph import resolve_call_site
from uo.scripts.extract_kernel_subgraph import (
    parse_constexpr_block_domains,
    parse_enum_class_domains,
)


def _fn(name: str, cls: str, sig: str, stable_id: str) -> FunctionDefinition:
    return FunctionDefinition(
        name=name, qualified_name=f"{cls}::{name}", class_or_namespace=cls,
        normalized_signature=sig, template_arity_or_signature="",
        specialization_kind="none", file_path="op_kernel/test.cpp",
        start_line=1, end_line=3, header_text=f"void {name}{sig}",
        body_text=f"void {name}{sig} {{}}", source_hash="s", snippet_hash="h",
        identity_key=f"IK_{stable_id}", stable_id=stable_id,
    )


def test_host_writer_roles_preserve_same_name_identity() -> None:
    normal = {
        "name": "SetTilingData", "qualified_name": "NormalTiling::SetTilingData",
        "class_or_namespace": "NormalTiling", "file_path": "normal.cpp",
        "start_line": 10, "role": "tiling_writer",
    }
    varlen = {
        "name": "SetTilingData", "qualified_name": "VarlenTiling::SetTilingData",
        "class_or_namespace": "VarlenTiling", "file_path": "varlen.cpp",
        "start_line": 20, "role": "workspace_writer",
    }
    by_identity, by_name, incomplete = _writer_role_indexes({"writers": [normal, varlen]})
    assert by_identity[_chain_item_key(normal)] == "tiling_writer"
    assert by_identity[_chain_item_key(varlen)] == "workspace_writer"
    assert "settilingdata" not in by_name
    assert not incomplete


def test_incomplete_duplicate_writer_fails_closed() -> None:
    a = {"name": "SetTilingData", "role": "tiling_writer"}
    b = {"name": "SetTilingData", "role": "workspace_writer"}
    _by_identity, by_name, incomplete = _writer_role_indexes({"writers": [a, b]})
    assert "settilingdata" not in by_name
    assert "settilingdata" in incomplete


def test_unknown_object_receiver_keeps_cross_class_candidates() -> None:
    caller = _fn("Run", "Driver", "()", "CALLER")
    a = _fn("Process", "NormalKernel", "(int)", "A")
    b = _fn("Process", "VarlenKernel", "(int)", "B")
    site = CallSite(
        caller_function_id=caller.stable_id, callee_name="Process",
        callee_qualified_hint="obj->Process", call_expression="obj->Process",
        file_path=caller.file_path, line=2, receiver_type_or_object="obj->",
        template_args="", argument_count=1, ordinal_in_function=1, snippet_hash="x",
    )
    edge, _node, unresolved = resolve_call_site(
        site, caller, by_name={"Process": [a, b]},
        by_qn={a.qualified_name: [a], b.qualified_name: [b]},
        by_id={a.stable_id: a, b.stable_id: b},
    )
    assert edge and edge["target_status"] == "candidate_set"
    assert set(edge["candidate_ids"]) == {"A", "B"}
    assert unresolved and unresolved["kind"] == "call_target_ambiguous"


def test_function_definition_cache_avoids_second_read(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "sample.cpp"
    source.write_text("class A { public: void Run() { Helper(); } void Helper() {} };", encoding="utf-8")
    reads = 0
    original = Path.read_text

    def counted(self: Path, *args, **kwargs):
        nonlocal reads
        if self == source:
            reads += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    first = iter_function_definitions(tmp_path, "sample.cpp", architecture="arch35")
    second = iter_function_definitions(tmp_path, "sample.cpp", architecture="arch35")
    assert first and second
    assert reads == 1


def test_declared_domain_parsers_compute_lines_without_external_state() -> None:
    enum_text = """// header
enum class Mode { A = 0, B = 1 };
"""
    enum_domains = parse_enum_class_domains(enum_text, "mode.h")
    assert enum_domains and enum_domains[0].start_line == 2

    constexpr_text = """// header
constexpr int MODE_A = 0;
constexpr int MODE_B = 1;
"""
    constexpr_domains = parse_constexpr_block_domains(constexpr_text, "mode.h")
    assert constexpr_domains and constexpr_domains[0].start_line == 2


def test_host_tdf_writes_do_not_use_short_name_fallback() -> None:
    from inspect import getsource
    from uo.scripts.extract_host_subgraph import extract_host_subgraph

    source = getsource(extract_host_subgraph)
    assert "name_l in tiling_writers" not in source



def test_fresh_repo_scans_neutral_host_registration_without_scope(tmp_path: Path) -> None:
    host = tmp_path / "op_host" / "flash_attention_score_grad_tiling.cpp"
    host.parent.mkdir(parents=True)
    host.write_text(
        """ge::graphStatus TilingFlashAttentionGradScore(gert::TilingContext *context) {
    return ge::GRAPH_SUCCESS;
}
IMPL_OP_OPTILING(FlashAttentionScoreGrad)
    .Tiling(TilingFlashAttentionGradScore);
""",
        encoding="utf-8",
    )
    doc = collect_entrypoint_candidates(
        tmp_path, "flash_attention_score_grad", architecture="arch35"
    )
    graph = doc["entrypoint_graph"]
    roles = {str(node.get("role")) for node in graph.get("nodes") or []}
    names = {str(node.get("name")) for node in graph.get("nodes") or []}
    assert "public_host_entry" in roles
    assert "FlashAttentionScoreGrad" in names
    assert "TilingFlashAttentionGradScore" in names
    assert any(
        edge.get("type") == "dispatches_to"
        and edge.get("confidence") == "source_verified"
        for edge in graph.get("edges") or []
    )


def test_default_non_sink_budget_covers_real_fag_candidate_volume() -> None:
    assert MAX_NON_SINK >= 177
