# -*- coding: utf-8 -*-
"""Following one container object across the functions that mutate it.

A container is declared in one function, filled in a second through a
reference parameter, and read in a third. "Every change to this container" is
therefore not a question about a single function, and answering it
incompletely is worse than not answering: a partial event list is
indistinguishable from a container that is mutated less than it really is.

Built on real `HostIR` objects rather than mocks, so the tests break if the IR
shape changes under them.
"""
from __future__ import annotations

from uo_init.clang_walk import CallSite, LocalDecl
from uo_init.host_ir import FuncSummary, HostIR, WriteEvent
from uo_init.loop_summary import resolve_param_container

VEC = "std::vector<std::pair<unsigned long, unsigned long> >"


def _append(container: str, function: str, line: int, rhs: str = "x") -> WriteEvent:
    return WriteEvent(
        path=container,
        rhs=rhs,
        file="f.cpp",
        line=line,
        column=5,
        function=function,
        kind="append",
    )


def _ir(
    *,
    summaries: dict[str, list[str]],
    calls: list[CallSite],
    events: list[WriteEvent] = (),
    decls: list[LocalDecl] = (),
) -> HostIR:
    return HostIR(
        summaries={
            name: FuncSummary(name=name, params=list(params))
            for name, params in summaries.items()
        },
        call_sites=list(calls),
        local_writes=list(events),
        local_decls=list(decls),
    )


def _call(caller: str, callee: str, args: tuple[str, ...], line: int = 1, **kw) -> CallSite:
    return CallSite(
        caller=caller, callee=callee, file="f.cpp", line=line, args=args, **kw
    )


def _decl(name: str, function: str, line: int, init=None, type_text: str = VEC):
    return LocalDecl(
        name=name,
        function=function,
        type_text=type_text,
        init=init,
        file="f.cpp",
        line=line,
    )


def _fag_shaped():
    """The real arrangement: declare in one function, fill in another, read in a third.

        Owner:  vector<..> v;        // empty
                Fill(v);             // appends
                Read(v);             // reads v.size()
    """
    return _ir(
        summaries={"Owner": [], "Fill": ["out"], "Read": ["seen"]},
        calls=[
            _call("Owner", "Fill", ("v",), line=10),
            _call("Owner", "Read", ("v",), line=11),
        ],
        events=[_append("out", "Fill", 20)],
        decls=[_decl("v", "Owner", 9)],
    )


def test_a_containers_mutations_are_found_through_two_reference_parameters():
    got = resolve_param_container(_fag_shaped(), "Read", "seen")
    assert len(got) == 1
    inst = got[0]
    assert inst, inst.reason
    assert (inst.root_function, inst.name) == ("Owner", "v")
    assert [e.line for e in inst.events] == [20]
    assert inst.starts_empty
    # The reader is on the chain too: it holds the container by reference and
    # could mutate it, so it gets checked rather than assumed innocent.
    assert set(inst.functions) == {"Owner", "Fill", "Read"}


def test_a_default_constructed_vector_is_known_to_start_empty():
    inst = resolve_param_container(_fag_shaped(), "Read", "seen")[0]
    assert inst.starts_empty


def test_a_vector_given_an_initialiser_is_not_assumed_empty():
    ir = _fag_shaped()
    ir.local_decls = [_decl("v", "Owner", 9, init="other")]
    assert not resolve_param_container(ir, "Read", "seen")[0].starts_empty


def test_an_undeclared_container_is_not_assumed_empty():
    """A member, or a local from a function we did not walk."""
    ir = _fag_shaped()
    ir.local_decls = []
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert inst
    assert not inst.starts_empty


def test_a_non_container_type_is_not_assumed_empty():
    ir = _fag_shaped()
    ir.local_decls = [_decl("v", "Owner", 9, type_text="int64_t")]
    assert not resolve_param_container(ir, "Read", "seen")[0].starts_empty


def test_two_callers_yield_two_separate_objects():
    """Dense and Band each pass their own local vector; they are not one container."""
    ir = _ir(
        summaries={"Dense": [], "Band": [], "Read": ["seen"]},
        calls=[
            _call("Dense", "Read", ("a",), line=10),
            _call("Band", "Read", ("b",), line=20),
        ],
        events=[_append("a", "Dense", 5), _append("b", "Band", 15)],
        decls=[_decl("a", "Dense", 4), _decl("b", "Band", 14)],
    )
    got = resolve_param_container(ir, "Read", "seen")
    assert len(got) == 2
    assert {i.name for i in got} == {"a", "b"}
    # Each sees only its own append; merging them would attribute one caller's
    # mutations to the other's container.
    assert all(len(i.events) == 1 for i in got)


def test_a_call_we_cannot_follow_into_ends_the_trace():
    """An unknown callee may hold onto the container or mutate it unseen."""
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "std::copy", ("v", "dest"), line=12))
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert not inst
    assert inst.reason == "escapes_into:std::copy"


def test_a_method_with_no_rule_ends_the_trace():
    ir = _fag_shaped()
    ir.call_sites.append(
        _call("Owner", "shuffle", (), line=12, receiver="v")
    )
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert not inst
    assert inst.reason == "unmodelled_method:shuffle"


def test_a_read_only_method_does_not_end_the_trace():
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "size", (), line=12, receiver="v"))
    assert resolve_param_container(ir, "Read", "seen")[0]


def test_a_modelled_mutator_does_not_end_the_trace():
    """`clear()` is recorded as an event, so seeing the call is not a surprise."""
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "clear", (), line=12, receiver="v"))
    assert resolve_param_container(ir, "Read", "seen")[0]


def test_passing_a_part_of_the_container_does_not_end_the_trace():
    """An element is not the container: no callee can resize `v` through `v[0]`."""
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "Unknown", ("v[0]",), line=12))
    assert resolve_param_container(ir, "Read", "seen")[0]


def test_passing_an_iterator_does_not_end_the_trace():
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "Unknown", ("v.begin()", "v.end()"), line=12))
    assert resolve_param_container(ir, "Read", "seen")[0]


def test_moving_the_container_ends_the_trace():
    """A move leaves it empty, which no append event records."""
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "vector", ("std::move(v)",), line=12))
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert not inst
    assert inst.reason.startswith("used_in_expression")


def test_copy_constructing_from_the_container_does_not_end_the_trace():
    """`std::vector<T> copy(v)` builds a new object; `v` is untouched."""
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "vector", ("v",), line=12))
    assert resolve_param_container(ir, "Read", "seen")[0]


def test_subscripting_through_operator_call_does_not_end_the_trace():
    """The walk records `v[i]` as `operator[](v, i)`; it still only reads."""
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "operator[]", ("v", "i"), line=12))
    assert resolve_param_container(ir, "Read", "seen")[0]


def test_an_unknown_function_taking_the_whole_container_still_ends_the_trace():
    """The distinction that matters: the container itself, not a part of it."""
    ir = _fag_shaped()
    ir.call_sites.append(_call("Owner", "Unknown", ("v",), line=12))
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert not inst
    assert inst.reason == "escapes_into:Unknown"


def test_a_name_that_merely_appears_in_another_argument_is_ignored():
    """`vCount` contains `v` as a substring but is a different variable."""
    ir = _fag_shaped()
    ir.summaries["Other"] = FuncSummary(name="Other", params=["n"])
    ir.call_sites.append(_call("Owner", "Other", ("vCount",), line=12))
    assert resolve_param_container(ir, "Read", "seen")[0]


def test_mutations_from_several_functions_are_all_collected():
    ir = _ir(
        summaries={"Owner": [], "FillA": ["out"], "FillB": ["out"], "Read": ["seen"]},
        calls=[
            _call("Owner", "FillA", ("v",), line=10),
            _call("Owner", "FillB", ("v",), line=11),
            _call("Owner", "Read", ("v",), line=12),
        ],
        events=[
            _append("out", "FillA", 30),
            _append("out", "FillB", 40),
            _append("v", "Owner", 9),
        ],
        decls=[_decl("v", "Owner", 8)],
    )
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert inst, inst.reason
    assert [e.line for e in inst.events] == [9, 30, 40]


def test_a_cycle_in_the_call_graph_terminates():
    ir = _ir(
        summaries={"Owner": [], "A": ["p"], "B": ["q"], "Read": ["seen"]},
        calls=[
            _call("Owner", "A", ("v",), line=10),
            _call("A", "B", ("p",), line=11),
            _call("B", "A", ("q",), line=12),
            _call("Owner", "Read", ("v",), line=13),
        ],
        events=[_append("p", "A", 20)],
        decls=[_decl("v", "Owner", 9)],
    )
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert inst, inst.reason
    assert [e.line for e in inst.events] == [20]


def test_a_parameter_with_no_call_site_yields_nothing():
    """Not the same as a container with no mutations, and must not read as one."""
    ir = _ir(summaries={"Read": ["seen"]}, calls=[])
    assert resolve_param_container(ir, "Read", "seen") == []


def test_an_unknown_function_or_parameter_yields_nothing():
    ir = _fag_shaped()
    assert resolve_param_container(ir, "Nope", "seen") == []
    assert resolve_param_container(ir, "Read", "nope") == []


def test_an_argument_that_is_not_a_variable_is_refused():
    ir = _ir(
        summaries={"Owner": [], "Read": ["seen"]},
        calls=[_call("Owner", "Read", ("make_vec()",), line=10)],
    )
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert not inst
    assert inst.reason.startswith("argument_not_a_variable")


def test_a_call_site_missing_the_argument_is_refused():
    ir = _ir(
        summaries={"Owner": [], "Read": ["seen"]},
        calls=[_call("Owner", "Read", (), line=10)],
    )
    inst = resolve_param_container(ir, "Read", "seen")[0]
    assert not inst
    assert inst.reason == "call_site_missing_argument"
