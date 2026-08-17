# -*- coding: utf-8 -*-
from uo_init.clang_walk import FieldDecl
from uo_init.host_ir import FuncSummary, HostIR, LocalDecl, WriteEvent
from uo_init.source_resolver import (
    LEGAL_ROOTS,
    REASON_FUNCTION_PARAMETER,
    REASON_NO_CONDITION,
    REASON_TILING_DATA_NO_WRITER,
    REASON_UNMAPPED_SYMBOL,
    SourceResolver,
    dotted_path,
    inferred_function_local_roots,
    inferred_parameter_roots,
)
from uo_init.cpp_expr import parse_expr


def test_accessor_calls_map_to_roots():
    r = SourceResolver()
    res = r.resolve("ctx->GetOptionalInputTensor(static_cast<size_t>(InputIndex::ACTUAL_SEQ_Q_LEN)) != nullptr")
    assert res.closed
    assert res.roots == ["OPTIONAL_INPUT_PRESENCE"]
    assert res.atoms[0].symbol == "actual_seq_q_len"


class _Model:
    """Just the two things `adopt` reads: constants and operand order."""

    def __init__(self, constants, operands):
        self.named_constants = dict(constants)
        self._operands = dict(operands)

    def operand_names(self):
        return {k: list(v) for k, v in self._operands.items()}


def _fag_like() -> SourceResolver:
    r = SourceResolver()
    r.adopt(
        _Model(
            {"QUERY_INPUT_INDEX": 0, "KEY_INPUT_INDEX": 1, "DIM_1": 1, "DIM_2": 2},
            {"input": ["query", "key", "value"], "output": ["dq", "dk", "dv"]},
        )
    )
    return r


def test_two_axes_of_one_tensor_are_two_variables():
    """`d` and `s1` are different numbers; sharing a variable invents UNSAT."""
    r = _fag_like()
    d = r.resolve("ctx->GetInputShape(QUERY_INPUT_INDEX)->GetStorageShape().GetDim(DIM_2)")
    s1 = r.resolve("ctx->GetInputShape(QUERY_INPUT_INDEX)->GetStorageShape().GetDim(DIM_1)")
    assert (d.atoms[0].symbol, d.atoms[0].index) == ("query", 2)
    assert (s1.atoms[0].symbol, s1.atoms[0].index) == ("query", 1)


def test_two_tensors_on_the_same_axis_are_two_variables():
    r = _fag_like()
    q = r.resolve("ctx->GetInputShape(QUERY_INPUT_INDEX)->GetStorageShape().GetDim(0)")
    k = r.resolve("ctx->GetInputShape(KEY_INPUT_INDEX)->GetStorageShape().GetDim(0)")
    assert q.atoms[0].symbol == "query"
    assert k.atoms[0].symbol == "key"


def test_a_local_alias_to_a_shape_keeps_the_tensor():
    """`auto &queryShape = ...->GetStorageShape();` then `queryShape.GetDim(2)`."""
    r = _fag_like().scoped(
        bindings={
            "queryShape": "ctx->GetInputShape(QUERY_INPUT_INDEX)->GetStorageShape()"
        }
    )
    res = r.resolve("queryShape.GetDim(DIM_2)")
    assert (res.atoms[0].symbol, res.atoms[0].index) == ("query", 2)


def test_a_shape_passed_into_a_helper_is_the_tensor_the_caller_passed():
    """`IsSameShape(dyShape, queryShape)` decides what `aShape` reads.

    Without chasing the formal, the accessor called on it had no operand and
    fell back to its own name, so every helper's tensors — and every caller's —
    shared one variable and were forced to agree.
    """
    r = _fag_like().scoped(
        parameters={"aShape"},
        param_actuals={"aShape": ["ctx->GetInputShape(KEY_INPUT_INDEX)"]},
    )
    res = r.resolve("aShape->GetStorageShape().GetDimNum() == 0")
    assert res.closed and res.atoms[0].symbol == "key"


def test_dtype_is_read_off_the_tensor_it_was_asked_about():
    """The outer accessor picks what is read; the receiver picks which tensor."""
    r = _fag_like()
    res = r.resolve("ctx->GetInputDesc(KEY_INPUT_INDEX)->GetDataType()")
    assert res.roots == ["INPUT_DTYPE"]
    assert res.atoms[0].symbol == "key"


def test_outputs_are_indexed_against_the_output_list():
    r = _fag_like()
    res = r.resolve("ctx->GetOutputShape(1)->GetStorageShape().GetDim(0)")
    assert res.atoms[0].symbol == "dk"


def test_without_a_model_the_accessor_name_still_stands_in():
    """No constants, no operand list: fall back rather than fail."""
    res = SourceResolver().resolve("ctx->GetInputShape(QUERY_INPUT_INDEX)->GetDim(DIM_2)")
    assert res.roots == ["INPUT_SHAPE"]


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


def test_a_local_that_picks_between_constants_is_not_one():
    """A ternary's arms are all constants, but the local is not a constant.

    Reading it as one keeps the first arm and silently deletes the branches
    that would have produced the others.
    """
    r = SourceResolver().scoped(
        bindings={"mode": "(cubebaseM == cubebaseN ? 0 : (cubebaseM > cubebaseN ? 2 : 1))"}
    )
    res = r.resolve("mode")
    assert res.roots != ["CONSTANT"]


def test_arithmetic_over_constants_is_still_one_constant():
    """`kBlockSize * 2` names two values but only ever produces one."""
    r = SourceResolver().scoped(bindings={"span": "16 * 2"})
    res = r.resolve("span")
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


def test_self_derived_counter_is_loop_derived_not_initial_constant():
    """`needCoreNum = 1; needCoreNum += 1` is host loop state, not literal 1."""
    ir = HostIR(
        summaries={
            "f": FuncSummary(
                name="f",
                locals={"needCoreNum": "1"},
                assign_lists={"needCoreNum": ["1", "needCoreNum + 1"]},
                assigns={"needCoreNum": "needCoreNum + 1"},
            )
        }
    )
    local_roots = inferred_function_local_roots(ir, "f")
    assert local_roots["needCoreNum"] == "LOOP_DERIVED"
    r = SourceResolver(host_ir=ir).scoped(
        bindings=ir.locals_by_function()["f"],
        def_lists=ir.defs_by_function()["f"],
        local_roots=local_roots,
    )
    res = r.resolve("needCoreNum > fBaseParams.aicNum")
    assert "LOOP_DERIVED" in res.roots
    assert "CONSTANT" not in res.roots
    assert any(
        a.symbol == "needCoreNum" and a.root == "LOOP_DERIVED" and not a.partial
        for a in res.atoms
    )
    # Params-shaped fields without a writer stay partial, not a closed root.
    assert any(
        a.reason == REASON_TILING_DATA_NO_WRITER for a in res.atoms
    )


def test_local_container_member_access_inherits_loop_derived_root():
    ir = HostIR(
        summaries={"f": FuncSummary(name="f")},
        local_decls=[
            LocalDecl(
                name="invalidS1Array",
                function="f",
                type_text="std::vector<bool>",
                init=None,
                file="f.cpp",
                line=1,
            )
        ],
    )
    local_roots = inferred_function_local_roots(ir, "f")
    assert local_roots["invalidS1Array"] == "LOOP_DERIVED"
    r = SourceResolver(host_ir=ir).scoped(local_roots=local_roots)
    assert r.resolve("invalidS1Array.size() > 0").roots == ["LOOP_DERIVED"]
    assert r.resolve("!invalidS1Array[j]").roots == ["LOOP_DERIVED"]


def test_caller_container_root_flows_to_same_named_formal():
    ir = HostIR(
        summaries={
            "caller": FuncSummary(name="caller", calls=[("callee", ("syncRounds",))]),
            "callee": FuncSummary(name="callee", params=["syncRounds"]),
        },
        local_decls=[
            LocalDecl(
                name="syncRounds",
                function="caller",
                type_text="std::vector<std::pair<uint64_t, uint64_t>>",
                init=None,
                file="f.cpp",
                line=1,
            )
        ],
    )
    assert inferred_parameter_roots(ir, "callee")["syncRounds"] == "LOOP_DERIVED"
    r = SourceResolver(host_ir=ir).scoped(
        parameters={"syncRounds"},
        local_roots=inferred_parameter_roots(ir, "callee"),
        param_actuals=ir.param_bindings()["callee"],
    )
    res = r.resolve("syncRounds.size() == 0")
    assert res.closed and res.roots == ["LOOP_DERIVED"]


def test_loop_derived_local_flows_through_local_expression_and_formal():
    ir = HostIR(
        summaries={
            "caller": FuncSummary(
                name="caller",
                locals={"left": "0", "right": "100", "mid": "0"},
                assign_lists={
                    "left": ["0", "mid + 1"],
                    "right": ["100", "mid"],
                    "mid": ["0", "(left + right) / 2"],
                },
                calls=[("callee", ("mid",))],
            ),
            "callee": FuncSummary(name="callee", params=["possibleMax"]),
        }
    )
    caller_roots = inferred_function_local_roots(ir, "caller")
    assert caller_roots["mid"] == "LOOP_DERIVED"
    assert inferred_parameter_roots(ir, "callee")["possibleMax"] == "LOOP_DERIVED"
    r = SourceResolver(host_ir=ir).scoped(
        parameters={"possibleMax"},
        local_roots=inferred_parameter_roots(ir, "callee"),
        param_actuals=ir.param_bindings()["callee"],
    )
    res = r.resolve("possibleMax > 0")
    assert res.closed and res.roots == ["LOOP_DERIVED"]


def test_loop_root_inside_actual_expression_flows_to_formal():
    from uo_init.clang_walk import CtrlNode

    ir = HostIR(
        summaries={
            "caller": FuncSummary(name="caller", calls=[("callee", ("coreId + 1",))]),
            "callee": FuncSummary(name="callee", params=["coreId"]),
        },
        controls=[
            CtrlNode(
                id="L1",
                kind="for",
                file="f.cpp",
                line=1,
                function="caller",
                condition="coreId < 4",
                induction_vars=("coreId",),
            )
        ],
    )
    assert inferred_parameter_roots(ir, "callee")["coreId"] == "LOOP_DERIVED"
    r = SourceResolver(host_ir=ir).scoped(
        parameters={"coreId"},
        local_roots=inferred_parameter_roots(ir, "callee"),
        param_actuals=ir.param_bindings()["callee"],
    )
    assert r.resolve("coreId > 0").roots == ["LOOP_DERIVED"]


def test_mixed_loop_roots_flow_to_formal_as_loop_derived():
    from uo_init.clang_walk import CtrlNode

    ir = HostIR(
        summaries={
            "caller_a": FuncSummary(name="caller_a", calls=[("callee", ("round",))]),
            "caller_b": FuncSummary(
                name="caller_b",
                assign_lists={"round": ["__tuple_elem(coordinateInfo, 8)"]},
                assigns={"round": "__tuple_elem(coordinateInfo, 8)"},
                calls=[("callee", ("round",))],
            ),
            "callee": FuncSummary(name="callee", params=["round"]),
        },
        controls=[
            CtrlNode(
                id="L1",
                kind="for",
                file="f.cpp",
                line=1,
                function="caller_a",
                condition="round > 0",
                induction_vars=("round",),
            )
        ],
    )
    assert inferred_parameter_roots(ir, "callee")["round"] == "LOOP_DERIVED"


def test_tuple_unpack_local_is_loop_derived():
    ir = HostIR(
        summaries={
            "f": FuncSummary(
                name="f",
                assign_lists={"x": ["__tuple_elem(coordinateInfo, 4)"]},
                assigns={"x": "__tuple_elem(coordinateInfo, 4)"},
            )
        }
    )
    roots = inferred_function_local_roots(ir, "f")
    assert roots["x"] == "LOOP_DERIVED"
    r = SourceResolver(host_ir=ir).scoped(
        bindings=ir.locals_by_function()["f"],
        def_lists=ir.defs_by_function()["f"],
        local_roots=roots,
    )
    assert r.resolve("x < 0").roots == ["LOOP_DERIVED"]


def test_generated_tiling_pointer_decl_does_not_close_without_writer():
    ir = HostIR(
        class_fields={"tndParam_"},
        field_decls={
            ("FlashAttentionScoreGradTilingNormalRegbase", "tndParam_"): FieldDecl(
                host="FlashAttentionScoreGradTilingNormalRegbase",
                name="tndParam_",
                init="nullptr",
                file="f.h",
                line=60,
            )
        },
    )
    res = SourceResolver(host_ir=ir).resolve("tndParam_ != nullptr")
    assert not res.closed
    assert res.partial
    assert REASON_TILING_DATA_NO_WRITER in res.reasons
    assert res.roots == ["TILING_DATA"]


def test_constant_ternary_value_uses_selector_provenance():
    """`cond ? 0 : 1` is a mode selected by `cond`, not an opaque constant."""
    r = SourceResolver().scoped(
        bindings={
            "cubebaseM": "fBaseParams.s1Inner * fBaseParams.s1CvRatio",
            "cubebaseN": "fBaseParams.s2Inner * fBaseParams.s2CvRatio",
            "mode": "(cubebaseM == cubebaseN ? 0 : (cubebaseM > cubebaseN ? 2 : 1))",
        },
        local_roots={"fBaseParams": "TILING_DATA"},
    )
    res = r.resolve("mode == 2")
    assert res.closed, res.reasons
    assert "TILING_DATA" in res.roots


def _filled_aggregate(name: str) -> HostIR:
    return HostIR(
        class_fields={name},
        writes=[
            WriteEvent(path=f"{name}.b", line=1, rhs="1", file="f.cpp", function="f")
        ],
    )


def test_an_aggregate_the_host_fills_closes_as_tiling_data():
    res = SourceResolver(host_ir=_filled_aggregate("fBaseParams")).resolve("fBaseParams")
    assert res.closed and res.roots == ["TILING_DATA"]


def test_an_aggregate_is_recognised_by_its_writes_not_its_name():
    """An operator that named its tiling struct something else still closes.

    The old test asserted the name pattern `*Params`; a struct called `cfg` was
    silently left unclassified, which is the whole failure this replaces.
    """
    res = SourceResolver(host_ir=_filled_aggregate("cfg")).resolve("cfg")
    assert res.closed and res.roots == ["TILING_DATA"]


def test_a_params_shaped_name_with_no_writes_is_not_assumed_to_be_tiling_data():
    """No write means no evidence. Reporting a root here would be a guess."""
    res = SourceResolver(host_ir=HostIR(class_fields={"fBaseParams"})).resolve(
        "fBaseParams"
    )
    assert not res.closed


def test_large_helper_body_is_not_chased():
    """Performance/tiling methods with many calls are not one-hop wrappers."""
    ir = HostIR(
        summaries={
            "MatmulTime": FuncSummary(
                name="MatmulTime",
                params=["m"],
                returns=["acc"],
                locals={"acc": "0"},
                calls=tuple((f"step{i}", ("m",)) for i in range(40)),
            )
        }
    )
    res = SourceResolver(host_ir=ir).resolve("MatmulTime(m)")
    assert not res.closed
    assert res.reasons == ["UNMAPPED_CALL"]


def test_resolve_step_budget_is_honored(monkeypatch):
    import uo_init.source_resolver as mod

    monkeypatch.setattr(mod, "RESOLVE_STEP_BUDGET", 0)
    res = SourceResolver().resolve("foo > 1")
    assert any(a.reason == mod.REASON_RESOLVE_BUDGET for a in res.atoms)
