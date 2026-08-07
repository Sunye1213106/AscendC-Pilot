# -*- coding: utf-8 -*-
"""Small synthetic tests for KB assemble + KBR union (no operator hardcoding)."""
from __future__ import annotations

from pathlib import Path

import yaml

from uo_init.assemble_kb import assemble_kb, export_operator_kb
from uo_init.clang_walk import CtrlNode
from uo_init.controllability import ClosureMetrics
from uo_init.gaps import GapReport
from uo_init.harness import (
    MintedKernelBranch,
    mint_kernel_branches,
    union_mint_kernel_branches,
)
from uo_init.host_derivation import (
    EX_CONSTANT,
    FieldDerivation,
    HostDerivation,
    host_derivation_from_dict,
)
from uo_init.kb_model import Blocker, Evidence
from uo_init.tpl_dsl import TplDim, TplSchema


def _ctrl(cond: str, line: int = 1) -> CtrlNode:
    return CtrlNode(
        id=f"k.cpp:{line}:0:if:0",
        kind="if",
        file="k.cpp",
        line=line,
        snippet=cond,
        condition=cond,
        function="my_op",
        universe="PRODUCTION",
    )


def test_union_mint_dedups_identical_controls_across_batches():
    n = _ctrl("x > 0")
    a = mint_kernel_branches([n], entry="my_op")
    b = mint_kernel_branches([n], entry="my_op")
    assert [x.id for x in a] == [x.id for x in b]
    assert a[0].id.startswith("KBR_")
    assert a[0].line == 1
    assert a[0].condition == "x > 0"
    unioned = union_mint_kernel_branches([[n], [n]], entry="my_op")
    assert [x.id for x in unioned] == [x.id for x in a]


def test_union_mint_same_logical_file_collapses_harness_paths():
    """Ephemeral harness paths must not inflate the KBR set."""
    a = _ctrl("flag")
    b = CtrlNode(
        id="other:1:0:if:0",
        kind="if",
        file="k.cpp",  # same logical file
        line=1,
        snippet="flag",
        condition="flag",
        function="my_op",
        universe="PRODUCTION",
    )
    ids = union_mint_kernel_branches([[a], [b]], entry="my_op")
    assert len(ids) == 1


def test_union_mint_keeps_distinct_guards():
    batches = [[_ctrl("a")], [_ctrl("b")], [_ctrl("a")]]
    ids = union_mint_kernel_branches(batches, entry="my_op")
    assert len(ids) == 2
    assert all(i.id.startswith("KBR_") for i in ids)


def test_assemble_kb_exports_blockers_under_20(tmp_path: Path):
    gap = GapReport(
        blockers=[
            Blocker(
                id="BLK_1",
                text="scratch",
                reason_code="UNMAPPED_SYMBOL",
                affected_nodes=["HBR_1"],
                evidence=[Evidence.at("h.cpp", 1, snippet="scratch")],
            )
        ],
        open_node_count=1,
    )
    metrics = ClosureMetrics(total_nodes=100, closed_nodes=96, open_nodes=1)
    kbr = union_mint_kernel_branches([[_ctrl("flag")]], entry="my_op")
    kb = assemble_kb(
        op_name="MyOp",
        architecture="arch35",
        analyses=[],
        records=[],
        metrics=metrics,
        gap=gap,
        kernel_branches=kbr,
    )
    assert kb.by_kind("KernelBranch")
    for node in kb.by_kind("KernelBranch"):
        assert node.evidence
        assert node.status == "extracted"
    receipt = export_operator_kb(kb, tmp_path)
    unresolved = yaml.safe_load(
        (tmp_path / ".ascendc-pilot" / "uo" / "ir" / "unresolved.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert unresolved["blocker_count"] == 1
    assert unresolved["blocker_count"] < 20
    assert receipt["ok"]
    assert receipt["blocker_count"] == 1
    assert receipt["artifact_count"] > 0
    assert (tmp_path / ".ascendc-pilot" / "uo" / "indexes" / "kb_graph.sqlite").is_file()
    assert (tmp_path / ".ascendc-pilot" / "uo" / "checks" / "integrity.yaml").is_file()
    branches = yaml.safe_load(
        (tmp_path / ".ascendc-pilot" / "uo" / "kernel" / "branches.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert branches["nodes"][0]["evidence_refs"]


def test_export_operator_kb_accepts_arch_scoped_uo_root(tmp_path: Path):
    kb = assemble_kb(
        op_name="MyOp",
        architecture="arch35",
        analyses=[],
        records=[],
        metrics=ClosureMetrics(total_nodes=1, closed_nodes=1, open_nodes=0),
        gap=GapReport(),
        kernel_branches=union_mint_kernel_branches([[_ctrl("flag")]], entry="my_op"),
    )
    uo_root = tmp_path / ".ascendc-pilot" / "arch35" / "uo"

    receipt = export_operator_kb(kb, tmp_path, uo_root_override=uo_root)

    assert receipt["ok"]
    assert (uo_root / "ir" / "operator_graph.yaml").is_file()
    assert (uo_root / "quality.yaml").is_file()
    assert (uo_root / "indexes" / "kb_graph.sqlite").is_file()
    assert not (tmp_path / ".ascendc-pilot" / "uo" / "ir" / "operator_graph.yaml").exists()


def test_host_derivation_rehydrates_persisted_fields():
    doc = HostDerivation(
        op_name="MyOp",
        architecture="arch35",
        fields=[
            FieldDerivation(
                name="BlockM",
                index=0,
                status="derived",
                exactness=EX_CONSTANT,
                host_expr="tilingKey",
                domain=["0", "1"],
                value_leaves=["1"],
                root_vars=["CONSTANT"],
            )
        ],
    )

    restored = host_derivation_from_dict(doc.to_dict())

    field = restored.by_name()["BlockM"]
    assert restored.op_name == "MyOp"
    assert restored.architecture == "arch35"
    assert field.status == "derived"
    assert field.input_derivable is True
    assert field.value_leaves == ["1"]


def test_recovered_kernel_branch_keeps_dimension_edges():
    kb = assemble_kb(
        op_name="MyOp",
        architecture="arch35",
        analyses=[],
        records=[],
        metrics=ClosureMetrics(total_nodes=1, closed_nodes=1, open_nodes=0),
        gap=GapReport(),
        kernel_branches=[
            MintedKernelBranch(
                id="KBR_DIM",
                file="k.cpp",
                line=10,
                snippet="if constexpr (IS_MASK)",
                condition="IS_MASK",
                function="Kernel",
                kind="if_constexpr",
                dimensions=("IsMask",),
                symbols=("IS_MASK",),
                dtype_variants=("DT_FLOAT16",),
                stage="constexpr",
            )
        ],
        tpl_schema=TplSchema(
            op_tag="MyOp",
            dims=[TplDim("IsMask", "BOOL", 1, ["0", "1"], bit_lo=0, bit_hi=0)],
            selections=[],
        ),
    )

    edges = list(kb.iter_edges())
    assert any(e.src == "KEY_ISMASK" and e.dst == "KBR_DIM" for e in edges)
    assert kb.nodes["KBR_DIM"].data["dimensions"] == ["IsMask"]
