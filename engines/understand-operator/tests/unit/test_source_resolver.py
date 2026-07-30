# -*- coding: utf-8 -*-
from uo_init.host_ir import HostIR, WriteEvent
from uo_init.source_resolver import (
    LEGAL_ROOTS,
    REASON_FUNCTION_PARAMETER,
    REASON_NO_CONDITION,
    REASON_UNMAPPED_SYMBOL,
    SourceResolver,
    dotted_path,
)
from uo_init.cpp_expr import parse_expr


def test_accessor_calls_map_to_roots():
    r = SourceResolver()
    res = r.resolve("ctx->GetOptionalInputTensor(static_cast<size_t>(InputIndex::ACTUAL_SEQ_Q_LEN)) != nullptr")
    assert res.closed
    assert res.roots == ["OPTIONAL_INPUT_PRESENCE"]
    assert res.atoms[0].symbol == "actual_seq_q_len"


def test_platform_arch_symbol():
    res = SourceResolver().resolve("npuArch == NpuArch::DAV_3510")
    assert res.closed and res.roots == ["PLATFORM_ARCH"]


def test_empty_condition_has_its_own_reason():
    res = SourceResolver().resolve("")
    assert not res.closed
    assert res.reasons == [REASON_NO_CONDITION]


def test_unknown_symbol_is_reported_not_guessed():
    res = SourceResolver().resolve("mysteryFlag")
    assert not res.closed
    assert res.reasons == [REASON_UNMAPPED_SYMBOL]


def test_function_parameter_gets_a_distinct_reason():
    r = SourceResolver().scoped(parameters={"alignSize"})
    res = r.resolve("alignSize == 0")
    assert res.reasons == [REASON_FUNCTION_PARAMETER]


def test_loop_variable_resolves_to_induction_root():
    r = SourceResolver().scoped(local_roots={"i": "LOOP_INDUCTION"})
    res = r.resolve("i < 50")
    assert res.closed and res.roots == ["LOOP_INDUCTION"]


def test_local_binding_is_chased_to_the_accessor():
    r = SourceResolver().scoped(
        bindings={"layout": "ctx->GetAttrs()->GetAttrPointer<char>(AttrIndex::INPUT_LAYOUT)"}
    )
    res = r.resolve('strcmp(layout, "SBH") == 0')
    assert res.closed and res.roots == ["ATTRIBUTE"]
    assert res.atoms[0].via  # records how the local was derived


def test_dotted_field_path_is_reconstructed():
    assert dotted_path(parse_expr("fBaseParams.isNzOut")) == "fBaseParams.isNzOut"
    assert dotted_path(parse_expr("this->a.b.c")) == "this.a.b.c"
    assert dotted_path(parse_expr("f(x)")) is None


def test_field_is_chased_through_host_ir():
    ir = HostIR(
        writes=[
            WriteEvent(
                path="this.fBaseParams.isNzOut",
                line=10,
                rhs="ctx->GetAttrs()->GetAttrPointer<char>(AttrIndex::OUT_TYPE) != nullptr",
                file="f.cpp",
            )
        ]
    )
    res = SourceResolver(host_ir=ir).resolve("fBaseParams.isNzOut")
    assert res.closed and res.roots == ["ATTRIBUTE"]
    assert res.atoms[0].via[0].startswith("this.fBaseParams.isNzOut@0=")


def test_all_reported_roots_are_legal():
    r = SourceResolver()
    for cond in (
        "npuArch == NpuArch::DAV_3510",
        "ctx->GetInputShape(0)->GetDim(1) > 0",
        "ctx->GetAttrs()->GetAttrNum() > 3",
    ):
        for root in r.resolve(cond).roots:
            assert root in LEGAL_ROOTS


def test_parameters_win_over_class_fields():
    """A1: a formal must not be stolen by a same-named class field."""
    from uo_init.host_ir import FuncSummary

    ir = HostIR(
        class_fields={"isTnd"},
        summaries={
            "helper": FuncSummary(name="helper", params=["isTnd"]),
        },
    )
    r = SourceResolver(host_ir=ir).scoped(
        parameters={"isTnd"},
        param_actuals={"isTnd": ["ctx->GetInputShape(0)->GetDim(0) > 0"]},
    )
    res = r.resolve("isTnd")
    assert res.closed
    assert res.roots == ["INPUT_SHAPE"]


def test_binding_all_constant_still_closed():
    """A4: locals that expand only to CONSTANT remain closed."""
    r = SourceResolver().scoped(bindings={"flag": "true"})
    res = r.resolve("flag")
    assert res.closed and res.roots == ["CONSTANT"]


def test_assigns_last_write_wins_in_locals_map():
    """A4: later assignment overrides a declaration initialiser."""
    from uo_init.host_ir import FuncSummary

    ir = HostIR(
        summaries={
            "f": FuncSummary(
                name="f",
                locals={"m": "0"},
                assigns={"m": "ctx->GetInputShape(0)->GetDim(1)"},
            )
        }
    )
    assert ir.locals_by_function()["f"]["m"].startswith("ctx->GetInputShape")


def test_helper_body_chase_via_return():
    """A6: known FuncRecord return expression is chased generically."""
    from uo_init.host_ir import FuncSummary

    ir = HostIR(
        summaries={
            "IsDense": FuncSummary(
                name="IsDense",
                params=["layout"],
                returns=['strcmp(layout, "SBH") == 0'],
            )
        }
    )
    r = SourceResolver(host_ir=ir).scoped(
        bindings={"layout": "ctx->GetAttrs()->GetAttrPointer<char>(AttrIndex::INPUT_LAYOUT)"}
    )
    # Call with no CALL_ROOTS entry must still close through the body
    res = r.resolve("IsDense(layout)")
    assert res.closed
    assert "ATTRIBUTE" in res.roots


def test_subscript_stripped_for_field_chase():
    """A7: foo.bar[i] matches writes to foo.bar."""
    ir = HostIR(
        writes=[
            WriteEvent(
                path="this.fBaseParams.actualSeqQlen",
                line=10,
                rhs="ctx->GetData(InputIndex::ACTUAL_SEQ_Q_LEN)",
                file="f.cpp",
            )
        ]
    )
    res = SourceResolver(host_ir=ir).resolve("fBaseParams.actualSeqQlen[i]")
    assert res.closed
    assert res.roots[0] in ("INPUT_VALUE", "TILING_DATA")


def test_output_bindings_flow_to_caller():
    """A3: callee out-param assign becomes a binding in the caller."""
    from uo_init.host_ir import FuncSummary

    ir = HostIR(
        summaries={
            "fill": FuncSummary(
                name="fill",
                params=["out"],
                out_params=["out"],
                assigns={"out": "ctx->GetInputShape(0)->GetDim(0)"},
            ),
            "caller": FuncSummary(
                name="caller",
                calls=[("fill", ("&n",))],
            ),
        }
    )
    outs = ir.output_bindings_by_function()["caller"]
    assert outs["n"].startswith("ctx->GetInputShape")


def test_multi_def_prefers_independent_rhs():
    """Short locals like p=CeilDiv(...); p=p+q must chase CeilDiv, not the cycle."""
    from uo_init.host_ir import FuncSummary

    ir = HostIR(
        summaries={
            "f": FuncSummary(
                name="f",
                assign_lists={
                    "p": [
                        "CeilDivideBy(fBaseParams.s1, 16)",
                        "p + q",
                    ]
                },
                assigns={"p": "p + q"},
            )
        },
        class_fields={"fBaseParams"},
        writes=[
            WriteEvent(
                path="this.fBaseParams.s1",
                line=1,
                rhs="ctx->GetInputShape(0)->GetDim(0)",
                file="f.cpp",
            )
        ],
    )
    # primary def should be the independent CeilDivideBy
    assert "CeilDivideBy" in ir.locals_by_function()["f"]["p"]
    r = SourceResolver(host_ir=ir).scoped(
        bindings=ir.locals_by_function()["f"],
        def_lists=ir.defs_by_function()["f"],
    )
    res = r.resolve("p < 0")
    assert res.closed, res.reasons
    assert "INPUT_SHAPE" in res.roots or "TILING_DATA" in res.roots


def test_aggregate_params_close_as_tiling_data():
    ir = HostIR(class_fields={"fBaseParams", "deterPrefixData"})
    res = SourceResolver(host_ir=ir).resolve("fBaseParams")
    assert res.closed and res.roots == ["TILING_DATA"]
