"""Macro region analysis + host/kernel dead-code / KEY binding."""

from __future__ import annotations

from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.extract_host_subgraph import extract_host_subgraph
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.macro_regions import (
    analyze_macros,
    classify_macro_condition,
    eval_pp_condition,
    valued_seed_defines,
)
from uo.scripts.provenance import load_key_dimension_index
from tests._entrypoint_fixtures import write_entrypoint_graph


def test_eval_if_zero_and_defined() -> None:
    assert eval_pp_condition("0", {}) is False
    assert eval_pp_condition("1", {}) is True
    assert eval_pp_condition("defined(FOO)", {}) is False
    assert eval_pp_condition("defined(FOO)", {"FOO": None}) is True
    assert eval_pp_condition("!defined(FOO)", {}) is True
    assert eval_pp_condition("FOO", {"FOO": "0"}) is False
    assert eval_pp_condition("FOO && BAR", {"FOO": "1", "BAR": "1"}) is True
    assert eval_pp_condition("UNKNOWN_MACRO", {}) is None


def test_analyze_if_zero_marks_dead_region() -> None:
    text = """
int live1 = 1;
#if 0
int dead = 1;
if (tilingData->x) { DoDead(); }
#endif
int live2 = 2;
#ifdef MISSING
int also_dead = 2;
#endif
#ifdef IS_FOO
int key_gated = 9;
#endif
#define FLAG 1
#if FLAG
int gated_live = 3;
#endif
"""
    info = analyze_macros(text, soft_undefined={"isfoo", "IS_FOO"})
    lines = text.splitlines()
    dead_line = next(i for i, l in enumerate(lines, 1) if "dead = 1" in l)
    also_dead = next(i for i, l in enumerate(lines, 1) if "also_dead" in l)
    key_gated = next(i for i, l in enumerate(lines, 1) if "key_gated" in l)
    live_line = next(i for i, l in enumerate(lines, 1) if "live2" in l)
    gated = next(i for i, l in enumerate(lines, 1) if "gated_live" in l)
    assert not info.is_active_line(dead_line)
    assert not info.is_active_line(also_dead)
    assert info.is_active_line(key_gated)  # soft KEY macro kept active
    assert info.is_active_line(live_line)
    assert info.is_active_line(gated)


def test_classify_macro_binds_tiling_key() -> None:
    index = load_key_dimension_index({"dimensions": [{"name": "IsNzOut", "values": [0, 1]}]})
    source, ref, domain = classify_macro_condition("IS_NZ_OUT", key_index=index)
    assert source == "TilingKey"
    assert ref == "IsNzOut"
    assert domain == [0, 1]


def test_valued_seed_skips_include_guards() -> None:
    seeded = valued_seed_defines(
        {
            "FOO_H": None,
            "FLASH_ATTENTION_SCORE_GRAD_KERNEL_H": None,
            "FEATURE_FLAG": "1",
            "VERSION": "9",
            "EMPTY": "",
        }
    )
    assert "FOO_H" not in seeded
    assert "FLASH_ATTENTION_SCORE_GRAD_KERNEL_H" not in seeded
    assert seeded["FEATURE_FLAG"] == "1"
    assert seeded["VERSION"] == "9"
    assert "EMPTY" not in seeded


def test_cross_file_guard_seed_does_not_kill_body() -> None:
    """Regression: seeding #define GUARD from file A must not deaden file B's #ifndef GUARD body."""
    text = """
#ifndef DEMO_KERNEL_H
#define DEMO_KERNEL_H
if constexpr (IS_FOO) { DoFoo(); }
if (tilingData->realField) { Live(); }
#endif
"""
    poisoned = {"DEMO_KERNEL_H": None, "FEATURE": "1"}
    bad = analyze_macros(text, seed_defines=poisoned)
    good = analyze_macros(text, seed_defines=valued_seed_defines(poisoned))
    live = next(i for i, l in enumerate(text.splitlines(), 1) if "realField" in l)
    assert not bad.is_active_line(live)
    assert good.is_active_line(live)


def test_kernel_skips_dead_runtime_and_binds_macro(tmp_path: Path) -> None:
    repo = tmp_path / "demo_op"
    arch = repo / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (arch / "demo_op_template_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(DemoOp, ASCENDC_TPL_BOOL_DECL(IsFoo, 0, 1),);\n",
        encoding="utf-8",
    )
    (arch / "demo_op_kernel.h").write_text(
        """
class DemoKernel {
  void Process() {
#if 0
    if (tilingData->ghostField) { Dead(); }
#endif
    if (tilingData->realField) { Live(); }
#ifdef IS_FOO
    DoCompile();
#endif
    if constexpr (IS_FOO) { DoFoo(); }
  }
};
""",
        encoding="utf-8",
    )
    (arch / "demo_op_entry.h").write_text("// entry\n", encoding="utf-8")
    root = operator_root(repo, "demo_op")
    init_operator_contract_layout(root, "demo_op", repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    write_entrypoint_graph(
        ir,
        op_name="demo_op",
        kernel_name="DemoKernel",
        kernel_file="op_kernel/arch35/demo_op_kernel.h",
        kernel_line=2,
    )
    write_yaml(ir / "tilingkey_space.yaml", {"dimensions": [{"name": "IsFoo", "values": [0, 1]}]})
    write_yaml(ir / "extract_plan.yaml", {"version": 1, "writers": [], "receivers": [], "aliases": []})

    payload = extract_kernel_subgraph(repo, "demo_op", architecture="arch35")
    conds = [str(b.get("condition") or "") for b in payload.get("branches") or []]
    assert not any("ghostField" in c for c in conds)
    assert any("realField" in c for c in conds)
    foo_macros = [
        b
        for b in payload.get("branches") or []
        if "IS_FOO" in str(b.get("condition") or "") or b.get("determinant_ref") == "IsFoo"
    ]
    assert foo_macros
    assert any(b.get("determinant_source") == "TilingKey" for b in foo_macros)


def test_host_emits_macro_branch_and_skips_dead_set(tmp_path: Path) -> None:
    op = "macro_host_op"
    repo = tmp_path / op
    host = repo / "op_host" / "arch35"
    host.mkdir(parents=True)
    (repo / "op_kernel" / "arch35").mkdir(parents=True)
    (host / "tiling.cpp").write_text(
        """
void FooTiling() {
  SaveStuff();
}

void SaveStuff() {
#if 0
  blob_->set_deadField(1);
#endif
#ifdef FEATURE_X
  blob_->set_feature(2);
#endif
  blob_->set_live(3);
}
""",
        encoding="utf-8",
    )
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    write_entrypoint_graph(
        ir,
        op_name=op,
        host_name="FooTiling",
        host_file="op_host/arch35/tiling.cpp",
        host_line=2,
    )
    write_yaml(
        ir / "extract_plan.yaml",
        {
            "version": 1,
            "confirmed_by": "test",
            "writers": [
                {"name": "SaveStuff", "file_path": "op_host/arch35/tiling.cpp", "start_line": 6, "role": "tiling_writer"},
                {"name": "FooTiling", "file_path": "op_host/arch35/tiling.cpp", "start_line": 2, "role": "ignore"},
            ],
            "receivers": [{"name": "blob_", "is_tiling_sink": True}],
            "aliases": [],
            "non_sink_roots": [],
            "extra_host_entries": [],
        },
    )
    # candidates for apply not needed when plan already written
    write_yaml(
        ir / "extract_plan_candidates.yaml",
        {
            "writer_candidates": [{"name": "SaveStuff"}, {"name": "FooTiling"}],
            "receiver_candidates": [{"name": "blob_"}],
            "alias_candidates": [],
            "non_sink_root_candidates": [],
            "extra_entry_candidates": [],
        },
    )

    payload = extract_host_subgraph(repo, op, architecture="arch35")
    tdf = {n["name"] for n in payload["nodes"] if n.get("node_type") == "TilingDataField"}
    assert "live" in tdf
    assert "deadField" not in tdf
    macros = [n for n in payload["nodes"] if n.get("node_type") == "HostMacroBranch"]
    assert macros
    assert any("FEATURE_X" in str(n.get("condition") or "") or "FEATURE_X" in str(n.get("determinant_ref") or "") for n in macros)

def test_function_like_macro_metadata_is_preserved() -> None:
    info = analyze_macros(
        "#define LIKELY(x) __builtin_expect(!!(x), 1)\n"
        "#define TRACE(fmt, ...) log(fmt, __VA_ARGS__)\n"
    )
    assert info.function_macros["LIKELY"]["parameters"] == ["x"]
    assert info.function_macros["LIKELY"]["body"].startswith("__builtin_expect")
    assert info.function_macros["TRACE"]["variadic"] is True
    directives = [d for d in info.directives if d.function_like]
    assert {d.name for d in directives} == {"LIKELY", "TRACE"}

