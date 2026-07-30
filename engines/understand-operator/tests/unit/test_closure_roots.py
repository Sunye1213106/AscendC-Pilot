# -*- coding: utf-8 -*-
"""Synthetic fixtures for residual closure root causes (no operator hardcoding)."""
from __future__ import annotations

from uo_init.host_ir import FuncSummary, HostIR, WriteEvent
from uo_init.source_resolver import SourceResolver
from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Call, Ref
from uo_init.source_resolver import dotted_path, _call_name


def test_field_accessor_on_call_base_inherits_root():
    """`helper().first` must not become UNMAPPED_CALL 'first'.

    Root cause: _call_name strips the `field:` prefix, so member access on a
    non-Ref base was looked up as a free function named `first`/`second`.
    """
    ir = HostIR(
        summaries={
            "helper": FuncSummary(
                name="helper",
                returns=["tileParams.s1"],
            )
        },
        class_fields={"tileParams"},
    )
    # parser shape: field:first(helper())
    res = SourceResolver(host_ir=ir).resolve("helper().first")
    assert res.closed, (res.reasons, [a.text for a in res.atoms])
    assert "TILING_DATA" in res.roots


def test_local_tuple_element_chases_binding_not_field_writer():
    """`best.first` where best is a local must chase the local, not `*.first` writes."""
    ir = HostIR(
        class_fields={"tileParams"},
        summaries={
            "f": FuncSummary(
                name="f",
                locals={"best": "tileParams"},
                assign_lists={"best": ["tileParams"]},
            )
        },
    )
    r = SourceResolver(host_ir=ir).scoped(
        bindings={"best": "tileParams"},
        def_lists={"best": ["tileParams"]},
    )
    res = r.resolve("best.first > 0")
    assert res.closed, res.reasons
    assert res.roots == ["TILING_DATA"]


def test_scratch_local_cycle_closes_via_params_derived_def():
    """`p = CeilDiv(params.x); p = p + q` must use the params-derived def."""
    ir = HostIR(
        class_fields={"tileParams"},
        summaries={
            "f": FuncSummary(
                name="f",
                assign_lists={
                    "p": [
                        "CeilDivideBy(tileParams.s1, 16)",
                        "p + q",
                    ],
                    "q": ["CeilDivideBy(tileParams.s2, 16)", "q + 1"],
                },
                assigns={"p": "p + q", "q": "q + 1"},
            )
        },
    )
    r = SourceResolver(host_ir=ir).scoped(
        bindings=ir.locals_by_function()["f"],
        def_lists=ir.defs_by_function()["f"],
    )
    for cond in ("p < 0", "q < 0", "p + q <= m"):
        # m may still be open in the third; just ensure p/q close
        pass
    assert r.resolve("p < 0").closed
    assert r.resolve("q < 0").closed
    assert "TILING_DATA" in r.resolve("p < 0").roots


def test_params_leaf_without_writer_is_tiling_data():
    """`tileParams.s1` is tiling state even when no write was recorded in-TU."""
    ir = HostIR(class_fields={"tileParams"})
    res = SourceResolver(host_ir=ir).resolve("tileParams.s1 > 0")
    assert res.closed
    assert res.roots == ["TILING_DATA"]


def test_zero_arg_method_body_chase_via_params():
    """0-arg helper returning locals derived from a params aggregate."""
    ir = HostIR(
        class_fields={"tileParams"},
        summaries={
            "BestSplit": FuncSummary(
                name="BestSplit",
                locals={
                    "s1Inner": "tileParams.s1 / 2",
                    "s2Inner": "tileParams.s2",
                },
                assign_lists={
                    "s1Inner": ["tileParams.s1 / 2"],
                    "s2Inner": ["tileParams.s2"],
                },
                returns=["std::tie(s1Inner, s2Inner)"],
            )
        },
    )
    res = SourceResolver(host_ir=ir).resolve("BestSplit()")
    assert res.closed, (res.reasons, [a.__dict__ for a in res.atoms])


def test_call_name_keeps_field_prefix_detectable():
    """Guard: field accessors must remain distinguishable from free calls."""
    e = Call("field:first", (Ref("best"),))
    # dotted path still works off raw func
    assert dotted_path(e) == "best.first"
    # stripped name is fine for display, but resolve_call must use e.func
    assert _call_name(e) == "first"


def test_tie_unpack_assigns_tuple_elements():
    """`std::tie(m, n) = coord` must define m/n from __tuple_elem(i, coord)."""
    from uo_init.host_ir import FuncSummary

    ir = HostIR(
        summaries={
            "caller": FuncSummary(
                name="caller",
                locals={"m": "tileParams.s1", "n": "tileParams.s2"},
                assign_lists={
                    "m": ["tileParams.s1"],
                    "n": ["tileParams.s2"],
                },
                calls=[("worker", ("std::make_tuple(m, n)",))],
            ),
            "worker": FuncSummary(
                name="worker",
                params=["coord"],
                assign_lists={
                    "m": ["__tuple_elem(0, coord)"],
                    "n": ["__tuple_elem(1, coord)"],
                },
                assigns={
                    "m": "__tuple_elem(0, coord)",
                    "n": "__tuple_elem(1, coord)",
                },
            ),
        },
        class_fields={"tileParams"},
    )
    r = SourceResolver(host_ir=ir).scoped(
        bindings=ir.locals_by_function()["worker"],
        def_lists=ir.defs_by_function()["worker"],
        parameters={"coord"},
        param_actuals=ir.param_bindings().get("worker", {}),
    )
    assert r.resolve("m < n").closed, r.resolve("m < n").reasons
    assert "TILING_DATA" in r.resolve("m < n").roots


def test_get_index_from_make_tuple_actual():
    """__tuple_elem(i, param) expands through make_tuple actuals at call sites."""
    ir = HostIR(
        summaries={
            "caller": FuncSummary(
                name="caller",
                calls=[("worker", ("std::make_tuple(tileParams.s1, tileParams.s2)",))],
            ),
            "worker": FuncSummary(name="worker", params=["coord"]),
        },
        class_fields={"tileParams"},
    )
    r = SourceResolver(host_ir=ir).scoped(
        parameters={"coord"},
        param_actuals=ir.param_bindings().get("worker", {}),
    )
    res = r.resolve("__tuple_elem(0, coord) > 0")
    assert res.closed, res.reasons


def test_keyword_condition_is_constant_noise():
    """Truncated macro text that is just `for` closes as CONSTANT, not a gap."""
    from uo_init.controllability import ControllabilityBuilder
    from uo_init.variable_model import VariableModel
    from types import SimpleNamespace

    model = VariableModel()
    builder = ControllabilityBuilder(SourceResolver(), model, side="host")
    node = SimpleNamespace(
        condition="for",
        file="f.cpp",
        line=1,
        function="f",
        kind="if",
        path_conditions=(),
        induction_vars=(),
        snippet="for",
    )
    a = builder.analyse(node)
    assert a.closed
    assert a.roots == ["CONSTANT"]
