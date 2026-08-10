# -*- coding: utf-8 -*-
"""Closure rate must be computed over the real inventory, with reasons for every gap."""
import pytest

from uo_init.branch_inventory import BranchInventory
from uo_init.clang_walk import CtrlNode
from uo_init.lineage import build_lineages, lineage_for_node, run_gates
from uo_init.source_resolver import SourceResolver


def _inv(nodes):
    return BranchInventory(nodes=nodes, backend="clang")


def test_every_node_produces_exactly_one_lineage():
    nodes = [
        CtrlNode(id=f"n{i}", kind="if", file="f.cpp", line=i, condition="npuArch == NpuArch::DAV_3510")
        for i in range(5)
    ]
    lins = build_lineages(_inv(nodes), SourceResolver())
    assert len(lins) == len(nodes)
    assert {l.node_id for l in lins} == {n.id for n in nodes}


def test_closure_rate_uses_the_inventory_denominator():
    nodes = [
        CtrlNode(id="closed", kind="if", file="f.cpp", line=1, condition="npuArch == NpuArch::DAV_3510"),
        CtrlNode(id="open", kind="if", file="f.cpp", line=2, condition="mysteryFlag"),
    ]
    rep = run_gates(
        lineages=build_lineages(_inv(nodes), SourceResolver()), template_ok=1, schema_ok=True
    )
    assert rep.total == 2
    assert rep.branch_closed == 1 and rep.branch_open == 1
    assert rep.deterministic_closure == 0.5


def test_open_nodes_carry_a_reason_code():
    nodes = [CtrlNode(id="open", kind="if", file="f.cpp", line=1, condition="mysteryFlag")]
    rep = run_gates(
        lineages=build_lineages(_inv(nodes), SourceResolver()), template_ok=0, schema_ok=True
    )
    assert rep.reason_histogram == {"UNMAPPED_SYMBOL": 1}
    assert rep.reasons == ["open:UNMAPPED_SYMBOL"]


def test_closed_nodes_are_counted_by_root():
    nodes = [
        CtrlNode(id="a", kind="if", file="f.cpp", line=1, condition="npuArch == NpuArch::DAV_3510"),
        CtrlNode(id="b", kind="if", file="f.cpp", line=2, condition="npuArch == NpuArch::DAV_2201"),
    ]
    rep = run_gates(
        lineages=build_lineages(_inv(nodes), SourceResolver()), template_ok=0, schema_ok=True
    )
    assert rep.root_histogram == {"PLATFORM_ARCH": 2}


def test_counted_loop_closes_on_its_induction_variable():
    node = CtrlNode(
        id="loop", kind="for", file="f.cpp", line=1, condition="i < 50", induction_vars=("i",)
    )
    lin = lineage_for_node(node, SourceResolver())
    assert lin.reason_code is None
    assert lin.root_kind == "LOOP_INDUCTION"


def test_lineage_records_enclosing_guards():
    from uo_init.clang_walk import PathCond

    node = CtrlNode(
        id="n",
        kind="if",
        file="f.cpp",
        line=9,
        condition="npuArch == NpuArch::DAV_3510",
        path_conditions=(PathCond('strcmp(layout, "SBH") == 0', False, "f.cpp", 3),),
    )
    lin = lineage_for_node(node, SourceResolver())
    assert lin.guards == ['strcmp(layout, "SBH") == 0']


def test_function_locals_and_params_are_scoped_per_node():
    nodes = [
        CtrlNode(id="a", kind="if", file="f.cpp", line=1, condition="layout", function="F"),
        CtrlNode(id="b", kind="if", file="f.cpp", line=2, condition="layout", function="G"),
    ]
    lins = build_lineages(
        _inv(nodes),
        SourceResolver(),
        func_locals={"F": {"layout": "ctx->GetAttrs()->GetAttrPointer<char>(AttrIndex::INPUT_LAYOUT)"}},
        func_params={"G": {"layout"}},
    )
    by_id = {l.node_id: l for l in lins}
    assert by_id["a"].root_kind == "ATTRIBUTE"
    assert by_id["b"].reason_code == "FUNCTION_PARAMETER"


@pytest.mark.requires_cann
def test_real_closure_is_measured_and_fully_attributed(host_walks, build_ctx, fag_dir):
    """No node is silently dropped: closed + open equals the PRODUCTION universe."""
    from uo_init.host_ir import build_host_ir

    targets = [
        fag_dir / "op_host" / "flash_attention_score_grad_tiling.cpp",
    ]
    ir = build_host_ir(targets, ctx=build_ctx)
    assert ir.backend == "clang"
    inv = host_walks["flash_attention_score_grad_tiling.cpp"]
    lins = build_lineages(
        inv,
        SourceResolver(host_ir=ir),
        func_locals=ir.locals_by_function(),
        func_params=ir.params_by_function(),
    )
    rep = run_gates(lineages=lins, template_ok=0, schema_ok=True)
    assert rep.total == inv.denominator()
    assert sum(rep.reason_histogram.values()) == rep.branch_open
    assert 0.3 < rep.deterministic_closure < 1.0
