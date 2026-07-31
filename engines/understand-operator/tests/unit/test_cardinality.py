# -*- coding: utf-8 -*-
"""How many elements two containers can hold between them.

The bound is on the *sum*, because that is the question the code asks:
`syncRounds.size() + syncRoundRanges.size() > CORE_LIST_NUM`. Bounding each
container separately gives 36 + 36 = 72 and settles nothing. Bounding the sum
needs the appends to be seen as competing for the same loop iterations.

Everything has to line up — container traced to its declaration, provably
empty to begin with, every change an append, every enclosing loop counted —
and a gap in any of them yields no number at all. A bound from an incomplete
picture is not a loose bound, it is a wrong one, and it gets used to delete a
branch.
"""
from __future__ import annotations

from uo_init.clang_walk import CallSite, CtrlNode, LocalDecl, PathCond
from uo_init.host_ir import FuncSummary, HostIR, WriteEvent
from uo_init.loop_summary import GuardTruth, cardinality_bound, guard_truth

VEC = "std::vector<std::pair<unsigned long, unsigned long> >"
LOOP_LINE = 411
CORE_LIST_NUM = 36


def _loop(
    line: int = LOOP_LINE,
    cond: str = "coreId < CORE_LIST_NUM",
    var: str = "coreId",
    **kw,
) -> CtrlNode:
    kw.setdefault("init_value", 0)
    kw.setdefault("step", 1)
    return CtrlNode(
        id=f"L{line}",
        kind="for",
        file="f.cpp",
        line=line,
        condition=cond,
        function="Fill",
        induction_vars=(var,),
        **kw,
    )


def _in_loop(line: int = LOOP_LINE) -> PathCond:
    return PathCond("coreId < CORE_LIST_NUM", False, "f.cpp", line, kind="for")


def _append(container: str, line: int, conds: tuple[PathCond, ...], fn="Fill") -> WriteEvent:
    return WriteEvent(
        path=container,
        rhs="elem",
        file="f.cpp",
        line=line,
        column=5,
        function=fn,
        kind="append",
        path_conditions=conds,
    )


def _ir(events, *, controls=None, extra_calls=(), decls=None) -> HostIR:
    return HostIR(
        summaries={
            "Owner": FuncSummary(name="Owner", params=[]),
            "Fill": FuncSummary(name="Fill", params=["a", "b"]),
            "Read": FuncSummary(name="Read", params=["seenA", "seenB"]),
        },
        call_sites=[
            CallSite(caller="Owner", callee="Fill", file="f.cpp", line=10,
                     args=("rounds", "ranges")),
            CallSite(caller="Owner", callee="Read", file="f.cpp", line=11,
                     args=("rounds", "ranges")),
            *extra_calls,
        ],
        local_writes=list(events),
        controls=list(controls if controls is not None else [_loop()]),
        local_decls=list(
            decls
            if decls is not None
            else [
                LocalDecl("rounds", "Owner", VEC, None, "f.cpp", 8),
                LocalDecl("ranges", "Owner", VEC, None, "f.cpp", 9),
            ]
        ),
    )


def _exclusive_pair():
    """The real shape: one `if/else` inside one loop, one append on each side."""
    branch = PathCond("startSyncRound > endSyncRound", False, "f.cpp", 439, kind="if")
    other = PathCond("startSyncRound > endSyncRound", True, "f.cpp", 439, kind="if")
    return [
        _append("a", 440, (_in_loop(), branch)),
        _append("b", 442, (_in_loop(), other)),
    ]


def _bound(ir):
    return cardinality_bound(ir, "Read", ["seenA", "seenB"], constants={"CORE_LIST_NUM": 36})


def test_exclusive_appends_in_one_loop_share_its_iterations():
    got = _bound(_ir(_exclusive_pair()))
    assert got, got.reason
    assert got.bound == 36
    assert got.loops == (("f.cpp", LOOP_LINE, 36),)


def test_appends_that_can_both_run_are_counted_separately():
    """No `if/else` between them, so an iteration can produce two elements."""
    both = [
        _append("a", 440, (_in_loop(),)),
        _append("b", 442, (_in_loop(),)),
    ]
    assert _bound(_ir(both)).bound == 72


def test_a_single_append_needs_no_exclusion_argument():
    assert _bound(_ir([_append("a", 440, (_in_loop(),))])).bound == 36


def test_an_append_outside_any_loop_counts_once():
    assert _bound(_ir([_append("a", 440, ())])).bound == 1


def test_appends_in_different_loops_add_up():
    second = _loop(line=500, cond="i < 4", var="i")
    events = [
        _append("a", 440, (_in_loop(),)),
        _append("b", 502, (_in_loop(500),)),
    ]
    assert _bound(_ir(events, controls=[_loop(), second])).bound == 40


def test_nested_loops_multiply():
    inner = _loop(line=420, cond="j < 4", var="j")
    ev = [_append("a", 425, (_in_loop(), _in_loop(420)))]
    assert _bound(_ir(ev, controls=[_loop(), inner])).bound == 144


def test_a_loop_we_cannot_count_yields_no_bound():
    open_ended = _loop(cond="coreId < n")
    got = _bound(_ir(_exclusive_pair(), controls=[open_ended]))
    assert not got
    assert got.reason.startswith("loop_not_counted")


def test_a_missing_loop_statement_yields_no_bound():
    got = _bound(_ir(_exclusive_pair(), controls=[]))
    assert not got
    assert got.reason.startswith("loop_statement_not_found")


def test_a_container_not_known_to_start_empty_yields_no_bound():
    ir = _ir(_exclusive_pair())
    ir.local_decls = [LocalDecl("rounds", "Owner", VEC, None, "f.cpp", 8)]
    got = _bound(ir)
    assert not got
    assert got.reason.endswith("not_known_to_start_empty")


def test_a_non_append_mutation_yields_no_bound():
    """`resize` can grow the container past anything the appends account for."""
    events = _exclusive_pair()
    events.append(
        WriteEvent(path="a", rhs="", file="f.cpp", line=450, column=3,
                   function="Fill", kind="opaque", path_conditions=())
    )
    got = _bound(_ir(events))
    assert not got
    assert "non_append_mutation" in got.reason


def test_a_container_escaping_into_an_unknown_call_yields_no_bound():
    extra = (CallSite(caller="Fill", callee="std::sort", file="f.cpp", line=444,
                      args=("a", "b")),)
    got = _bound(_ir(_exclusive_pair(), extra_calls=extra))
    assert not got
    assert "escapes_into" in got.reason


def test_two_callers_are_maximised_not_added():
    """Dense and Band each fill their own vectors; the bound holds for each."""
    ir = _ir(_exclusive_pair())
    ir.call_sites.append(
        CallSite(caller="Other", callee="Read", file="f.cpp", line=99,
                 args=("p", "q"))
    )
    ir.summaries["Other"] = FuncSummary(name="Other", params=[])
    ir.local_decls += [
        LocalDecl("p", "Other", VEC, None, "f.cpp", 97),
        LocalDecl("q", "Other", VEC, None, "f.cpp", 98),
    ]
    got = _bound(ir)
    assert got, got.reason
    # The second caller appends nothing, so its own total is 0; the answer is
    # the worst case across callers, not their sum.
    assert got.bound == 36


def test_a_consumer_with_no_call_site_yields_no_bound():
    ir = _ir(_exclusive_pair())
    ir.call_sites = [c for c in ir.call_sites if c.callee != "Read"]
    got = _bound(ir)
    assert not got
    assert got.reason.startswith("no_call_site_for")


# --- using the bound to settle a guard -------------------------------------
#
# The point of the bound: `a.size() + b.size() > CORE_LIST_NUM` is false on
# every run, so the branch behind it is dead and both `size()` reads stop being
# free variables. Nothing else in the pipeline can reach that conclusion.

CONSTS = {"CORE_LIST_NUM": CORE_LIST_NUM}


def _truth(text: str, ir=None) -> GuardTruth:
    return guard_truth(ir or _ir(_exclusive_pair()), text, "Read", constants=CONSTS)


def test_a_guard_the_bound_rules_out_is_always_false():
    got = _truth("seenA.size() + seenB.size() > CORE_LIST_NUM")
    assert got.always_false
    assert not got.always_true
    assert got.detail == "CARD_seenA+CARD_seenB<=36"


def test_the_negation_of_that_guard_is_always_true():
    assert _truth("!(seenA.size() + seenB.size() > CORE_LIST_NUM)").always_true


def test_the_bound_is_not_read_as_one_lower_than_it_is():
    """36 elements are reachable, so `> 35` is not ruled out."""
    assert not _truth("seenA.size() + seenB.size() > 35").settled


def test_a_guard_at_the_bound_is_always_true():
    assert _truth("seenA.size() + seenB.size() <= CORE_LIST_NUM").always_true


def test_a_guard_within_the_bound_stays_open():
    assert not _truth("seenA.size() + seenB.size() > 10").settled


def test_a_single_container_is_bounded_by_the_sum_too():
    assert _truth("seenA.size() > CORE_LIST_NUM").always_false


def test_sizes_are_known_not_to_be_negative():
    assert _truth("seenA.size() >= 0").always_true


def test_a_guard_with_no_size_read_is_left_alone():
    assert not _truth("coreId != 0").settled


def test_a_named_constant_left_unresolved_settles_nothing():
    """Without the constant, `> CORE_LIST_NUM` compares against anything."""
    ir = _ir(_exclusive_pair())
    assert not guard_truth(
        ir, "seenA.size() + seenB.size() > CORE_LIST_NUM", "Read", constants={}
    ).settled


def test_a_guard_is_left_alone_when_the_bound_cannot_be_established():
    ir = _ir(_exclusive_pair(), controls=[_loop(cond="coreId < n")])
    assert not _truth("seenA.size() + seenB.size() > CORE_LIST_NUM", ir).settled


def test_a_name_that_is_not_a_parameter_of_this_function_is_ignored():
    assert not _truth("somethingElse.size() > CORE_LIST_NUM").settled
