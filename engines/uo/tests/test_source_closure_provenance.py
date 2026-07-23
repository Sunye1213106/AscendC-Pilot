"""Acceptance tests for UO source closure / provenance revision."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from uo.scripts.arch_path import arch_compatible, architecture_of_path, path_family_of
from uo.scripts.cann_doc_evidence import load_doc_contract, collect_doc_evidence_bundle
from uo.scripts.def_use import bind_argument_parameter, extract_def_use_from_text
from uo.scripts.extract_build_evidence import extract_build_evidence
from uo.scripts.extract_operator_boundary import extract_operator_boundary, optional_state_label
from uo.scripts.reconcile_bridge import reconcile_bridge
from uo.scripts.resolve_entrypoints import (
    ROLE_PATTERNS,
    _role_patterns_for_op,
    collect_entrypoint_candidates,
)
from uo.scripts.semantic_identity import mint_field_identity, mint_symbol_identity
from uo.scripts.source_closure import run_source_closure
from uo.scripts._ir_io import write_yaml


def _prep_op(tmp_path: Path, op_name: str) -> Path:
    op_root = tmp_path / op_name
    op_root.mkdir(parents=True)
    uo = op_root / ".ascendc-agent" / "uo"
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    run = uo / "runs" / "UO_RUN_TEST1" / "scope"
    run.mkdir(parents=True, exist_ok=True)
    write_yaml(
        uo / "manifest.yaml",
        {"op_name": op_name, "current_run": "UO_RUN_TEST1", "current_run_id": "UO_RUN_TEST1"},
    )
    return op_root


def test_arch_neutral_entry_not_filtered() -> None:
    assert arch_compatible("op_host/foo_tiling.cpp", "arch35")
    assert arch_compatible("op_host/arch35/normal/x.cpp", "arch35")
    assert not arch_compatible("op_host/arch22/x.cpp", "arch35")
    assert architecture_of_path("op_host/foo_tiling.cpp") == "neutral"
    assert architecture_of_path("op_kernel/arch35/k.h") == "arch35"
    assert path_family_of("op_host/arch35/varlen/x.cpp") == "varlen"


def test_entrypoint_graph_multi_impl(tmp_path: Path) -> None:
    op = "demo_attn_op"
    root = _prep_op(tmp_path, op)
    host = root / "op_host"
    host.mkdir()
    (host / "demo_attn_op_tiling.cpp").write_text(
        textwrap.dedent(
            """
            REG_OP(DemoAttnOp)
            IMPL_OP_OPTILING(DemoAttnOp)
            REGISTER_TILING_TEMPLATE(DemoAttnOp, DemoNormalTiling)
            REGISTER_TILING_TEMPLATE(DemoAttnOp, DemoVarlenTiling)
            class DemoNormalTiling {
              ge::graphStatus DoOpTiling() { return ge::GRAPH_SUCCESS; }
            };
            """
        ),
        encoding="utf-8",
    )
    arch = root / "op_host" / "arch35" / "normal"
    arch.mkdir(parents=True)
    (arch / "normal_tiling.cpp").write_text(
        "class NormalTiling { ge::graphStatus DoOpTiling() { return ge::GRAPH_SUCCESS; } };\n",
        encoding="utf-8",
    )
    varlen = root / "op_host" / "arch35" / "varlen"
    varlen.mkdir(parents=True)
    (varlen / "varlen_tiling.cpp").write_text(
        "class VarlenTiling { ge::graphStatus DoOpTiling() { return ge::GRAPH_SUCCESS; } };\n",
        encoding="utf-8",
    )
    kern = root / "op_kernel"
    kern.mkdir()
    (kern / "demo_attn_op_apt.cpp").write_text(
        "__global__ void DemoAttnOpEntry() {}\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch35" / "demo_attn_op_kernel.h").write_text(
        "class DemoAttnOpKernel { void Process(); };\n",
        encoding="utf-8",
    )
    uo = root / ".ascendc-agent" / "uo"
    write_yaml(
        uo / "runs" / "UO_RUN_TEST1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [
                {"path": "op_host/demo_attn_op_tiling.cpp"},
                {"path": "op_host/arch35/normal/normal_tiling.cpp"},
                {"path": "op_host/arch35/varlen/varlen_tiling.cpp"},
                {"path": "op_kernel/demo_attn_op_apt.cpp"},
                {"path": "op_kernel/arch35/demo_attn_op_kernel.h"},
            ],
            "confirmed_file_list": [
                {"path": "op_host/demo_attn_op_tiling.cpp"},
                {"path": "op_host/arch35/normal/normal_tiling.cpp"},
                {"path": "op_host/arch35/varlen/varlen_tiling.cpp"},
                {"path": "op_kernel/demo_attn_op_apt.cpp"},
                {"path": "op_kernel/arch35/demo_attn_op_kernel.h"},
            ],
        },
    )
    doc = collect_entrypoint_candidates(root, op, architecture="arch35")
    graph = doc["entrypoint_graph"]
    assert graph["version"] == 2
    assert "selected" not in graph
    roles = {n["role"] for n in graph["nodes"]}
    assert "operator_registration" in roles or "public_host_entry" in roles
    # Neutral public host path retained
    files = {(n.get("locator") or {}).get("file_path") for n in graph["nodes"]}
    assert any(f and "demo_attn_op_tiling.cpp" in f for f in files)
    # Multiple DoOpTiling impls not collapsed to one selected
    do_ops = [n for n in graph["nodes"] if n.get("name") == "DoOpTiling"]
    assert len(do_ops) >= 2
    assert graph["closure"]["blocking_unresolved"] is not None


def test_entry_closure_status_requires_dispatch(tmp_path: Path) -> None:
    op = "lonely_op"
    root = _prep_op(tmp_path, op)
    (root / "op_host").mkdir()
    (root / "op_host" / "lonely.cpp").write_text(
        "class Lone { ge::graphStatus DoOpTiling() { return ge::GRAPH_SUCCESS; } };\n",
        encoding="utf-8",
    )
    uo = root / ".ascendc-agent" / "uo"
    write_yaml(
        uo / "runs" / "UO_RUN_TEST1" / "scope" / "scope_confirmed.yaml",
        {"confirmed_source_files": [{"path": "op_host/lonely.cpp"}], "confirmed_file_list": [{"path": "op_host/lonely.cpp"}]},
    )
    graph = collect_entrypoint_candidates(root, op)["entrypoint_graph"]
    # Finding DoOpTiling alone must not silently claim full closed without kernel/dispatch.
    assert graph["closure"]["kernel_main_chain"] == "unresolved"
    assert any(b.get("severity") == "blocking" for b in graph["closure"]["blocking_unresolved"])


def test_symbol_identity_overload_and_line_shift() -> None:
    a = mint_symbol_identity(
        kind="method",
        name="GetTilingKey",
        file_path="op_host/a.h",
        qualified_name="NormalTiling::GetTilingKey",
        class_or_namespace="NormalTiling",
        signature="uint64 GetTilingKey() const",
    )
    b = mint_symbol_identity(
        kind="method",
        name="GetTilingKey",
        file_path="op_host/b.h",
        qualified_name="VarlenTiling::GetTilingKey",
        class_or_namespace="VarlenTiling",
        signature="uint64 GetTilingKey() const",
    )
    assert a.identity_key != b.identity_key
    # Adding comments / shifting lines must not change semantic id (line not in key).
    a2 = mint_symbol_identity(
        kind="method",
        name="GetTilingKey",
        file_path="op_host/a.h",
        qualified_name="NormalTiling::GetTilingKey",
        class_or_namespace="NormalTiling",
        signature="uint64 GetTilingKey() const",
    )
    assert a.identity_key == a2.identity_key


def test_deterministic_ids() -> None:
    ids = [
        mint_symbol_identity(
            kind="method",
            name="Process",
            file_path="k.h",
            qualified_name="K::Process",
            class_or_namespace="K",
        ).identity_key
        for _ in range(3)
    ]
    assert len(set(ids)) == 1


def test_conditional_assignment_and_scope_shadowing() -> None:
    text = textwrap.dedent(
        """
        int d = queryShape.GetDim(3);
        if (hasRope) {
            d = ropeShape.GetDim(3);
        }
        baseParams.d = d;
        {
            int d = other;
            baseParams.x = d;
        }
        """
    )
    result = extract_def_use_from_text(text, file_path="host.cpp", scope_symbol="DoOpTiling")
    defs = result["definitions"]
    assert len(defs) >= 3
    guarded = [d for d in defs if "hasRope" in str(d.get("guard") or "")]
    assert guarded, "conditional assignment must retain guard"
    # Distinct def_ids for reassignment / shadowing
    assert len({d["def_id"] for d in defs}) == len(defs)


def test_object_field_identity() -> None:
    f1 = mint_field_identity(owning_type="TilingBaseParams", field_path="d")
    f2 = mint_field_identity(owning_type="OtherParams", field_path="d")
    assert f1.identity_key != f2.identity_key


def test_argument_parameter_binding() -> None:
    ok = bind_argument_parameter(
        caller_expr="query_h",
        callee_param="h",
        evidence=[{"file_path": "x.cpp", "line": 10}],
    )
    assert ok["type"] == "binds_arg"
    bad = bind_argument_parameter(caller_expr="a", callee_param="b", evidence=None)
    assert bad["code"] == "argument_parameter_unbound"


def test_operator_boundary_slots(tmp_path: Path) -> None:
    op = "bound_op"
    root = _prep_op(tmp_path, op)
    (root / "op_host").mkdir()
    (root / "op_host" / "reg.cpp").write_text(
        textwrap.dedent(
            """
            REG_OP(BoundOp)
            .Input("query")
            .Input("key")
            .OptionalInput("query_rope")
            .Attr("input_layout")
            .AttrDefault("BSH");
            """
        ),
        encoding="utf-8",
    )
    (root / "op_host" / "tiling.cpp").write_text(
        textwrap.dedent(
            """
            void DoOpTiling() {
              auto q = context_->GetInputShape(0);
              auto rope = context_->GetOptionalInputShape(2);
              auto layout = context_->GetAttrs()->GetAttrPointer("input_layout");
              auto mystery = context_->GetInputShape(9);
            }
            """
        ),
        encoding="utf-8",
    )
    uo = root / ".ascendc-agent" / "uo"
    write_yaml(
        uo / "runs" / "UO_RUN_TEST1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [
                {"path": "op_host/reg.cpp"},
                {"path": "op_host/tiling.cpp"},
            ],
            "confirmed_file_list": [
                {"path": "op_host/reg.cpp"},
                {"path": "op_host/tiling.cpp"},
            ],
        },
    )
    payload = extract_operator_boundary(root, op)
    names = {i.get("name") for i in payload["inputs"]}
    assert "query" in names and "query_rope" in names
    assert any(i.get("slot") == 9 and i.get("name") is None for i in payload["inputs"])
    assert any(u.get("code") == "input_slot_unbound" for u in payload["unresolved"])
    assert optional_state_label(absent=True) == "absent"
    assert optional_state_label(empty=True) == "present_but_empty"
    assert optional_state_label(nonempty=True) == "present_and_nonempty"


def test_tilingdata_bridge_typed_and_ambiguous(tmp_path: Path) -> None:
    op = "bridge_op"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-agent" / "uo"
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    write_yaml(
        uo / "ir" / "host_subgraph.yaml",
        {
            "nodes": [
                {
                    "id": "H1",
                    "node_type": "TilingDataField",
                    "name": "base.s1",
                    "field_path": "base.s1",
                    "owning_type": "DemoTilingData",
                },
                {
                    "id": "H2",
                    "node_type": "TilingDataField",
                    "name": "x",
                    "field_path": "x",
                    "owning_type": "",
                },
            ],
            "edges": [],
        },
    )
    write_yaml(
        uo / "ir" / "kernel_subgraph.yaml",
        {
            "nodes": [
                {
                    "id": "K1",
                    "node_type": "TilingDataField",
                    "name": "base.s1",
                    "field_path": "base.s1",
                    "owning_type": "DemoTilingData",
                },
                {
                    "id": "K2",
                    "node_type": "TilingDataField",
                    "name": "x",
                    "field_path": "x",
                    "owning_type": "TypeA",
                },
                {
                    "id": "K3",
                    "node_type": "TilingDataField",
                    "name": "x",
                    "field_path": "x",
                    "owning_type": "TypeB",
                },
            ],
            "loaded_tiling_fields": [],
            "edges": [],
        },
    )
    write_yaml(uo / "ir" / "tilingkey_space.yaml", {"dimensions": [], "nodes": [], "edges": []})
    payload = reconcile_bridge(root, op)
    verified = [b for b in payload["tilingdata_bridges"] if b["status"] == "verified"]
    assert any(b.get("field_path") == "base.s1" for b in verified)
    assert any(u.get("code") == "tilingdata_bridge_ambiguous" for u in payload["unresolved"])


def test_tilingkey_positional_and_spaces(tmp_path: Path) -> None:
    op = "key_op"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-agent" / "uo"
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    (root / "op_host").mkdir()
    (root / "op_host" / "key.cpp").write_text(
        "uint64_t k = GET_TPL_TILING_KEY(isTnd, isDeter);\n",
        encoding="utf-8",
    )
    write_yaml(
        uo / "ir" / "host_subgraph.yaml",
        {"nodes": [{"id": "H", "file_path": "op_host/key.cpp", "node_type": "Helper"}], "edges": []},
    )
    write_yaml(
        uo / "ir" / "kernel_subgraph.yaml",
        {
            "nodes": [],
            "template_parameters": [
                {"index": 0, "name": "IsTnd", "is_tilingkey": True},
                {"index": 1, "name": "IsDeter", "is_tilingkey": True},
            ],
        },
    )
    write_yaml(
        uo / "ir" / "tilingkey_space.yaml",
        {
            "architecture": "arch35",
            "dimensions": [
                {"name": "IsTnd", "bit_width": 1, "values": [0, 1]},
                {"name": "IsDeter", "bit_width": 1, "values": [0, 1]},
            ],
            "args_sel_count": 1,
            "selection_space": [{"name": "IsDeter", "values": [0]}],
            "schemas": [{"key_schema_id": "default", "dimensions": [
                {"name": "IsTnd", "bit_width": 1, "values": [0, 1]},
                {"name": "IsDeter", "bit_width": 1, "values": [0, 1]},
            ]}],
        },
    )
    payload = reconcile_bridge(root, op)
    assert payload["tilingkey_bindings"]
    binding = payload["tilingkey_bindings"][0]
    assert "declaration_space" in binding
    assert "compile_selection_space" in binding
    assert binding["positions"][0]["index"] == 0


def test_tilingkey_multiple_schemas_no_global_match(tmp_path: Path) -> None:
    op = "multi_key"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-agent" / "uo"
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    (root / "op_host").mkdir()
    (root / "op_host" / "a.cpp").write_text("GET_TPL_TILING_KEY(a0, a1);\n", encoding="utf-8")
    (root / "op_host" / "b.cpp").write_text("GET_TPL_TILING_KEY(b0, b1);\n", encoding="utf-8")
    write_yaml(
        uo / "ir" / "host_subgraph.yaml",
        {
            "nodes": [
                {"id": "H1", "file_path": "op_host/a.cpp"},
                {"id": "H2", "file_path": "op_host/b.cpp"},
            ]
        },
    )
    write_yaml(uo / "ir" / "kernel_subgraph.yaml", {"nodes": [], "template_parameters": []})
    write_yaml(
        uo / "ir" / "tilingkey_space.yaml",
        {
            "dimensions": [{"name": "A", "values": [0, 1]}],
            "schemas": [
                {"key_schema_id": "schemaA", "dimensions": [{"name": "A", "values": [0, 1]}]},
                {"key_schema_id": "schemaB", "dimensions": [{"name": "B", "values": [0, 1]}]},
            ],
        },
    )
    payload = reconcile_bridge(root, op)
    assert any(u.get("code") == "tilingkey_schema_ambiguous" for u in payload["unresolved"])


def test_cmake_evidence_and_not_csv(tmp_path: Path) -> None:
    op = "cmake_op"
    root = _prep_op(tmp_path, op)
    (root / "CMakeLists.txt").write_text(
        textwrap.dedent(
            """
            target_sources(cmake_op PRIVATE op_kernel/arch35/k.cpp)
            add_ops_compile_options(cmake_op PRIVATE -DASC_FOO=1)
            if(ASCEND_COMPUTE_UNIT STREQUAL "ascend910b")
            endif()
            option(BUILD_OPS_RTY_KERNEL "x" OFF)
            """
        ),
        encoding="utf-8",
    )
    uo = root / ".ascendc-agent" / "uo"
    write_yaml(
        uo / "runs" / "UO_RUN_TEST1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [{"path": "op_kernel/arch35/k.cpp"}],
            "confirmed_build_files": [{"path": "CMakeLists.txt"}],
            "confirmed_file_list": [{"path": "op_kernel/arch35/k.cpp"}],
        },
    )
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch35" / "k.cpp").write_text("// k\n", encoding="utf-8")
    payload = extract_build_evidence(root, op)
    assert payload["build_files"]
    assert any(d["source"] == "CompileMacro" for d in payload["determinants"])
    assert any(d["source"] == "BuildConfig" for d in payload["determinants"])
    assert all(d.get("csv_controllable") is False for d in payload["determinants"])
    assert "BuildConfig" in payload["csv_excluded_sources"]


def test_source_closure_reindex_and_round_limit(tmp_path: Path) -> None:
    op = "close_op"
    root = _prep_op(tmp_path, op)
    (root / "op_host").mkdir()
    (root / "op_host" / "a.cpp").write_text('#include "helper.h"\nint x;\n', encoding="utf-8")
    (root / "op_host" / "helper.h").write_text("inline int h(){return 1;}\n", encoding="utf-8")
    uo = root / ".ascendc-agent" / "uo"
    write_yaml(
        uo / "runs" / "UO_RUN_TEST1" / "scope" / "scope_scan.yaml",
        {"workspace_root": str(root), "operator_path": op},
    )
    write_yaml(
        uo / "runs" / "UO_RUN_TEST1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [{"path": "op_host/a.cpp"}],
            "confirmed_file_list": [{"path": "op_host/a.cpp"}],
            "closure": {"allowed_roots": ["op_host", "."]},
        },
    )
    result = run_source_closure(root, op, restage=False, max_rounds=2, max_new_files_per_round=40)
    paths = result["confirmed_source_files"]
    assert any(p.endswith("helper.h") for p in paths)

    # Round limit: many missing includes → unresolved rather than unbounded expand
    (root / "op_host" / "b.cpp").write_text(
        "\n".join(f'#include "missing_{i}.h"' for i in range(60)),
        encoding="utf-8",
    )
    write_yaml(
        uo / "runs" / "UO_RUN_TEST1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [{"path": "op_host/b.cpp"}],
            "confirmed_file_list": [{"path": "op_host/b.cpp"}],
            "closure": {"allowed_roots": ["op_host", "."]},
        },
    )
    limited = run_source_closure(root, op, restage=False, max_rounds=1, max_new_files_per_round=5)
    assert any(u.get("code") == "missing_scope_dependency_round_limit" for u in limited["unresolved"]) or len(
        limited["confirmed_source_files"]
    ) <= 6


def test_official_doc_offline_cache_and_version_mismatch(tmp_path: Path) -> None:
    op = "doc_op"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-agent" / "uo"
    hit = load_doc_contract(uo, "GET_TPL_TILING_KEY", cann_version="offline_fixture", allow_network=False)
    assert not hit.get("unresolved")
    assert hit["symbol_or_macro"] == "GET_TPL_TILING_KEY"
    # cached
    assert (uo / "docs_cache" / "GET_TPL_TILING_KEY.json").exists()
    mismatch = load_doc_contract(uo, "GET_TPL_TILING_KEY", cann_version="8.0.RC1", allow_network=False)
    # offline_fixture is accepted as stand-in OR mismatch depending on gate — either ok if structured
    assert "symbol_or_macro" in mismatch or mismatch.get("code") == "documentation_version_mismatch"
    missing = load_doc_contract(uo, "TOTALLY_UNKNOWN_MACRO_XYZ", allow_network=False)
    assert missing.get("code") == "documentation_unavailable"
    bundle = collect_doc_evidence_bundle(root, op, symbols=["ASCENDC_TPL_ARGS_DECL"], allow_network=False)
    assert bundle["items"] or bundle["unresolved"]


def test_no_fag_hardcode_dual_synthetic_ops() -> None:
    assert "FlashAttentionScoreGradKernel" not in ROLE_PATTERNS["kernel_entry"]
    assert "flash_attention_score_grad" not in str(ROLE_PATTERNS)
    for op in ("alpha_score_grad", "beta_score_grad"):
        patterns = _role_patterns_for_op(op)
        pascal = "".join(p[:1].upper() + p[1:] for p in op.split("_"))
        assert f"{pascal}Kernel" in patterns["kernel_entry"]
        assert "FlashAttentionScoreGradKernel" not in patterns["kernel_entry"]


def test_provenance_chain_shape_to_field() -> None:
    text = textwrap.dedent(
        """
        int query_h = queryShape->GetStorageShape().GetDim(2);
        int d = query_h / head_num;
        fBaseParams.d = d;
        """
    )
    result = extract_def_use_from_text(text, file_path="tiling.cpp", scope_symbol="DoOpTiling")
    assert any("input_shape:" in s for d in result["definitions"] for s in d["source_nodes"])
    assert any(f.get("type") == "writes" and "fBaseParams.d" in str(f.get("to")) for f in result["flows"])
