# -*- coding: utf-8 -*-
"""Clang-backed BranchInventory: the denominator the closure rate is computed on."""
import pytest

import baselines
from uo_init.branch_inventory import (
    UNIVERSE,
    assert_no_sink_pruning,
    inventory_clang,
)
from uo_init.clang_walk import CtrlNode, PathCond, classify_universe

pytestmark = pytest.mark.requires_cann

def test_control_node_counts_match_baseline(
    host_walks, host_tus, op_name, update_baselines
):
    """The denominator the closure rate is computed on, per host TU.

    Recorded per source revision: see tests/baselines.py for why the file's
    digest is part of the comparison.
    """
    measured = {
        name: (host_tus[name], sum(1 for n in inv.nodes if n.kind != "macro_dispatch"))
        for name, inv in host_walks.items()
    }
    baselines.check(op_name, "host_control_nodes", measured, update=update_baselines)


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


def test_a_bail_out_that_forwards_its_status_is_still_an_error_exit():
    """`if (ret != GRAPH_SUCCESS) { return ret; }` names no failure code.

    The exit statement alone cannot show it is the failure path, so the
    condition has to. Reading it as normal flow hangs "every check so far
    passed" onto the rest of the function, and a value only ever assigned
    after such a check then looks like it might never be assigned.
    """
    from uo_init.clang_walk import _ERROR_EXIT_RE, _STATUS_FAILURE_RE

    assert not _ERROR_EXIT_RE.search("return ret ;")
    assert _STATUS_FAILURE_RE.search("ret != ge::GRAPH_SUCCESS")
    assert _STATUS_FAILURE_RE.search("ret!=GRAPH_SUCCESS")
    assert _STATUS_FAILURE_RE.search("GRAPH_SUCCESS != ret")


def test_merely_naming_the_success_code_is_not_a_failure_test():
    """The narrow reading is deliberate. Skipping a guard makes the writes
    behind it look unconditional, which is the direction that can decide a
    chain is exhaustive when it is not."""
    from uo_init.clang_walk import _STATUS_FAILURE_RE

    assert not _STATUS_FAILURE_RE.search("ret == ge::GRAPH_SUCCESS")
    assert not _STATUS_FAILURE_RE.search("status < GRAPH_SUCCESS")


def test_a_rejection_is_not_a_guard_on_what_follows():
    """`if (bad) return GRAPH_FAILED;` says what a legal input is, not when the
    next statement runs.

    Hung on the following writes it says the wrong thing twice: they look
    partial, so an initial value gets minted for a run that cannot happen, and
    the requirement itself ends up buried in one field instead of constraining
    the inputs everywhere. `is_bailout` keeps the two apart.
    """
    bail = PathCond("queryType == DT_HIFLOAT8", True, "f.cpp", 10, kind="bailout")
    plain = PathCond("d > 64", True, "f.cpp", 20, kind="if")

    assert bail.is_bailout and not plain.is_bailout
    # Not a decision: the other side does not reach here at all, so it cannot be
    # paired with its negation to prove a chain covers every path.
    assert not bail.is_decision and plain.is_decision


def test_writes_separate_their_guards_from_the_premises_they_ran_under():
    from uo_init.host_ir import WriteEvent

    w = WriteEvent(
        path="p.outDtype",
        line=30,
        rhs="p.inputDtype",
        path_conditions=(
            PathCond("queryType == DT_HIFLOAT8", True, "f.cpp", 10, kind="bailout"),
            PathCond("d > 64", False, "f.cpp", 20),
        ),
    )
    assert w.guards() == ["d > 64"]
    assert w.premises() == ["!(queryType == DT_HIFLOAT8)"]


def _write_under(*conds):
    from uo_init.host_ir import WriteEvent

    return WriteEvent(path="p.x", line=1, rhs="1", function="F", path_conditions=conds)


def test_a_rejection_at_the_top_of_a_function_asks_it_of_every_input():
    from uo_init.host_ir import HostIR

    ir = HostIR(
        writes=[
            _write_under(
                PathCond("queryType == DT_HIFLOAT8", True, "f.cpp", 10, kind="bailout")
            )
        ]
    )
    assert [p[0] for p in ir.legality_premises()] == ["!(queryType == DT_HIFLOAT8)"]


def test_a_rejection_inside_a_test_asks_it_only_of_the_inputs_that_reach_it():
    """FAG demands `keepProb < 1` only once a dropout mask has been passed.

    Read unconditionally it rejects every run without dropout, which is most of
    them, and the keys only those runs produce disappear. The premise has to
    carry the condition it was written under.
    """
    from uo_init.host_ir import HostIR

    ir = HostIR(
        writes=[
            _write_under(
                PathCond("dropMask != nullptr", False, "f.cpp", 5),
                PathCond("!hasDrop", True, "f.cpp", 6, kind="bailout"),
            )
        ]
    )
    assert [p[0] for p in ir.legality_premises()] == [
        "!((dropMask != nullptr)) || (!(!hasDrop))"
    ]


def test_a_rejection_reached_through_something_unreadable_is_dropped():
    """An opaque context cannot be stated, and stating the rejection without it
    would claim of every input what holds only of some."""
    from uo_init.host_ir import HostIR

    ir = HostIR(
        writes=[
            _write_under(
                PathCond("", False, "f.cpp", 5),
                PathCond("!hasDrop", True, "f.cpp", 6, kind="bailout"),
            )
        ]
    )
    assert ir.legality_premises() == []
