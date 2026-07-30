# -*- coding: utf-8 -*-
"""Clang-backed BranchInventory: the denominator the closure rate is computed on."""
import pytest

from uo_init.branch_inventory import (
    UNIVERSE,
    assert_no_sink_pruning,
    inventory_clang,
)
from uo_init.clang_walk import CtrlNode, PathCond, classify_universe

pytestmark = pytest.mark.requires_cann

# FAG arch35 host baselines — fixture-local, not product code.
GOLDEN_HOST_DENOMINATORS = {
    "flash_attention_score_grad_tiling.cpp": 136,
    "flash_attention_score_grad_tiling_normal_regbase.cpp": 324,
    "flash_attention_score_grad_tiling_common_regbase.cpp": 377,
}


def test_golden_denominators(host_walks):
    """Locked against the plan's baseline: 136 / 324 / 377 control nodes."""
    got = {
        name: sum(1 for n in inv.nodes if n.kind != "macro_dispatch")
        for name, inv in host_walks.items()
    }
    assert got == GOLDEN_HOST_DENOMINATORS


def test_macro_idiom_is_not_a_branch(host_walks):
    """`do {...} while (0)` from OP_LOG* macros must not inflate the denominator."""
    inv = host_walks["flash_attention_score_grad_tiling.cpp"]
    assert inv.macro_idioms > 0
    assert not any(n.kind == "do" for n in inv.nodes)


def test_nodes_carry_file_line_and_condition(host_walks):
    inv = host_walks["flash_attention_score_grad_tiling_normal_regbase.cpp"]
    named = [n for n in inv.nodes if n.condition]
    assert named
    n = named[0]
    assert n.line > 0 and n.file.endswith(".cpp") or n.file.endswith(".h")
    assert n.id.startswith(n.file)
    assert str(n.line) in n.id


def test_ids_are_stable_and_unique(host_walks):
    inv = host_walks["flash_attention_score_grad_tiling.cpp"]
    assert len(inv.ids()) == len(inv.nodes)


def test_universes_are_from_the_closed_set(host_walks):
    for inv in host_walks.values():
        assert {n.universe for n in inv.nodes} <= UNIVERSE


def test_production_is_a_strict_subset(host_walks):
    inv = host_walks["flash_attention_score_grad_tiling_common_regbase.cpp"]
    assert 0 < inv.denominator() < len(inv.nodes)
    assert inv.by_universe("VALIDATION_ONLY")
    assert inv.by_universe("LIBRARY_INTERNAL")


def test_path_conditions_are_recorded(host_walks):
    inv = host_walks["flash_attention_score_grad_tiling_normal_regbase.cpp"]
    nested = [n for n in inv.nodes if len(n.path_conditions) >= 2]
    assert nested
    assert any(not pc.is_opaque for n in nested for pc in n.path_conditions)


def test_loop_induction_variables_are_captured(host_walks):
    inv = host_walks["flash_attention_score_grad_tiling.cpp"]
    loops = [n for n in inv.nodes if n.kind == "for" and n.induction_vars]
    assert loops
    assert all("<" in n.condition or ">" in n.condition for n in loops[:3])


def test_text_backend_cannot_be_used_as_a_denominator():
    from uo_init.branch_inventory import BranchInventory

    with pytest.raises(ValueError):
        BranchInventory(nodes=[], backend="text").denominator()


def test_macro_dispatch_survives_sink_pruning(fag_dir, build_ctx):
    target = None
    for p in (fag_dir / "op_kernel" / "arch35").rglob("*.h"):
        if "INVOKE_FAG" in p.read_text(encoding="utf-8", errors="replace"):
            target = p
            break
    if target is None:
        pytest.skip("no INVOKE_FAG dispatch site in this operator")
    inv = inventory_clang(target, build_ctx, side="kernel")
    assert any(n.kind == "macro_dispatch" for n in inv.nodes)
    assert_no_sink_pruning(inv, target.read_text(encoding="utf-8", errors="replace"))


@pytest.mark.parametrize(
    "condition,expected",
    [
        ("CheckLogLevel(static_cast<int>(OP), DLOG_ERROR) == 1", "VALIDATION_ONLY"),
        ("ret != ge::GRAPH_SUCCESS", "VALIDATION_ONLY"),
        ("", "LIBRARY_INTERNAL"),
        ("x > 0", "PRODUCTION"),
    ],
)
def test_universe_classification_rules(condition, expected):
    node = CtrlNode(id="n", kind="if", file="f.cpp", line=1, condition=condition)
    assert classify_universe(node) == expected


def test_path_cond_pretty_marks_opaque_guards():
    assert PathCond("", False, "f", 1).pretty() == "<macro-expanded>"
    assert PathCond("a > 0", True, "f", 1).pretty() == "!(a > 0)"
