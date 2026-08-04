# -*- coding: utf-8 -*-
"""Exactness grading, and which guards may be softened.

`status` says whether a key field has an expression; `exactness` says whether
that expression still means what the source means. Grading them apart is what
stops the pipeline reporting 19/19 derived when most of those expressions have
had their guards replaced by free booleans.
"""
from __future__ import annotations

from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Bin, Call, Const, Ref
from uo_init.predicate import _leaf_text
from uo_init.derive_key_fields import (
    EX_CONSTANT,
    EX_EXACT,
    EX_OVERAPPROX,
    EX_PARTIAL,
    EX_UNRESOLVED,
    STATUS_DERIVED,
    STATUS_PARTIAL,
    STATUS_UNRESOLVED,
    _ValueNormalizer,
    classify_exactness,
    collapsed_leaf_values,
    is_overapprox_var,
    status_of_exactness,
)
from uo_init.source_resolver import SourceResolver
from uo_init.variable_model import VariableModel


# -- grading ---------------------------------------------------------------
def test_expression_over_real_inputs_is_exact():
    grade, free = classify_exactness(
        value_expr={"op": "eq", "var": "VAR_ATTR_KEEP_PROB", "value": 1},
        variables=["VAR_ATTR_KEEP_PROB"],
        unresolved=[],
    )
    assert (grade, free) == (EX_EXACT, [])


def test_expression_with_no_variables_is_constant():
    grade, free = classify_exactness(value_expr={"lit": 1}, variables=[], unresolved=[])
    assert (grade, free) == (EX_CONSTANT, [])


def test_a_single_softened_guard_makes_the_field_overapproximated():
    """The case that used to be reported as fully derived."""
    grade, free = classify_exactness(
        value_expr={"op": "if_then_else", "condition": {"op": "eq", "var": "VAR_SCHED_ABC", "value": True}},
        variables=["VAR_ATTR_KEEP_PROB", "VAR_SCHED_ABC"],
        unresolved=[],
    )
    assert grade == EX_OVERAPPROX
    assert free == ["VAR_SCHED_ABC"]


def test_unresolved_subterms_outrank_over_approximation():
    grade, free = classify_exactness(
        value_expr={"lit": 0},
        variables=["VAR_UNDECIDED_ABC"],
        unresolved=[{"text": "", "reason": "OPAQUE_EXPRESSION"}],
    )
    assert grade == EX_PARTIAL
    assert free == ["VAR_UNDECIDED_ABC"]


def test_no_expression_at_all_is_unresolved():
    assert classify_exactness(value_expr=None, variables=["X"], unresolved=[]) == (EX_UNRESOLVED, [])


# -- normalisation collapse detection --------------------------------------
def test_leaves_lost_between_expansion_and_normalisation_are_seen():
    """The DeterType shape: expansion reached 0..4, the SMT form only 0 and 2."""
    expr = {"op": "if_then_else", "condition": {"op": "eq", "var": "VAR_X", "value": True},
            "then": {"lit": 0}, "else": {"lit": 2}}
    assert collapsed_leaf_values(expr, ["0", "1", "2", "3", "4"]) == ["1", "3", "4"]


def test_leaves_the_expression_can_still_reach_are_not_a_collapse():
    expr = {"op": "if_then_else", "condition": {"op": "eq", "var": "VAR_X", "value": True},
            "then": {"lit": 0}, "else": {"lit": 1}}
    assert collapsed_leaf_values(expr, ["0", "1"]) == []


def test_non_numeric_spellings_are_not_treated_as_lost_values():
    """Enum spellings survive expansion without naming a reachable value."""
    expr = {"lit": 1}
    assert collapsed_leaf_values(expr, ["1", "DtypeEnum::FLOAT32"]) == []


def test_no_expression_means_no_collapse():
    assert collapsed_leaf_values(None, ["1", "2"]) == []


def test_every_over_approximation_prefix_is_recognized():
    for var in (
        "VAR_UNDECIDED_A",
        "VAR_SCHED_A",
        "VAR_REACHED_A",
        "VAR_INIT_A",
        "VAR_LOOPELEM_A",
    ):
        assert is_overapprox_var(var), var
    for var in ("VAR_ATTR_KEEP_PROB", "VAR_SHAPE_B", "VAR_ELEM_SIZE_Q"):
        assert not is_overapprox_var(var), var


def test_status_stays_a_projection_of_exactness():
    assert status_of_exactness(EX_EXACT) == STATUS_DERIVED
    assert status_of_exactness(EX_CONSTANT) == STATUS_DERIVED
    assert status_of_exactness(EX_OVERAPPROX) == STATUS_PARTIAL
    assert status_of_exactness(EX_PARTIAL) == STATUS_PARTIAL
    assert status_of_exactness(EX_UNRESOLVED) == STATUS_UNRESOLVED


# -- which guards may be softened -----------------------------------------
def _normalizer(**roots: str) -> _ValueNormalizer:
    """A normalizer whose leaves resolve to exactly the roots given."""
    return _ValueNormalizer(SourceResolver(local_roots=dict(roots)), VariableModel())


def _guard_of(norm: _ValueNormalizer, text: str) -> dict:
    return norm._guard(parse_expr(text))


def test_a_guard_on_traversal_position_is_softened():
    norm = _normalizer(coreIdx="LOOP_INDUCTION")
    out = _guard_of(norm, "coreIdx > 0")
    assert out["var"].startswith("VAR_SCHED_")
    assert norm.scheduling[out["var"]] == "SCHED_SOFT"


def test_next_fit_overflow_guard_folds_false_on_key_paths():
    """coreIdx >= CORE_LIST_NUM is a bailout, not a free schedule bit."""
    norm = _normalizer(coreIdx="LOOP_INDUCTION", CORE_LIST_NUM="CONSTANT")
    out = _guard_of(norm, "coreIdx >= CORE_LIST_NUM")
    assert out == {"op": "lit", "value": False, "origin": "bailout"}
    assert not norm.scheduling


def test_next_fit_overflow_against_aicNum_also_folds():
    norm = _normalizer(coreIdx="LOOP_INDUCTION", aicNum="CONSTANT")
    out = _guard_of(norm, "coreIdx >= aicNum")
    assert out.get("op") == "lit" and out.get("value") is False



def test_a_screaming_case_local_is_not_softened_as_schedule():
    """`N12` matches the SCREAMING_CASE constant regex and resolves to CONSTANT.

    That alone must not make `N12 > 0` a schedule guard — N12 is an
    input-derived local (`n2 % aicNum % 2`), and calling it SCHED_SOFT hid the
    real gap (the local was never inlined into an input root).
    """
    norm = _normalizer()
    out = _guard_of(norm, "N12 > 0")
    assert "VAR_SCHED_" not in str(out), out
    assert out["var"].startswith("VAR_UNDECIDED_")


def test_an_unmapped_local_plus_named_constant_is_not_schedule():
    """`bTail % MULT_BASE == 1`: MULT_BASE is CONSTANT, bTail resolves to nothing.

    The old rule saw only CONSTANT and softened; the honest outcome is UNDECIDED
    on the unmapped half.
    """
    norm = _normalizer()
    out = _guard_of(norm, "bTail % MULT_BASE == 1")
    assert "VAR_SCHED_" not in str(out), out
    assert out["var"].startswith("VAR_UNDECIDED_")


def test_a_guard_on_the_input_layout_is_not_softened():
    """The regression the old text-matching rule caused.

    `layoutType` resolves to INPUT_FORMAT, so this guard is a real constraint
    on the input; softening it lets a solver pick either branch and report
    unreachable keys as reachable.
    """
    norm = _normalizer(layoutType="INPUT_FORMAT")
    out = _guard_of(norm, "layoutType == 3")
    assert "VAR_SCHED_" not in str(out)
    assert "VAR_UNDECIDED_" not in str(out)
    assert norm.scheduling == {}


def test_scoped_layout_leaf_is_not_softened_by_encode_resolver():
    """Soft classification must use Ref.scope, not the encode-function resolver.

    Without that, a cross-function `inputLayout` leaf contributes no root, a
    sibling CONSTANT tips the guard into SCHED_SOFT, and a real layout
    constraint disappears.
    """
    norm = _two_scope_normalizer()
    # Force a CONSTANT sibling so the bug (ignore scope → empty constraining
    # roots → CONSTANT-only → SCHED) would have fired before the fix.
    cond = Bin(
        "&&",
        Bin("==", Ref("inputLayout", scope="GetShapeAttrsInfo"), Const("TND")),
        Bin("==", Ref("MULT_BASE"), Const(1)),
    )
    out = norm._guard(cond)
    assert "VAR_SCHED_" not in str(out), out
    assert norm.scheduling == {}


def test_one_input_leaf_protects_a_guard_that_also_mentions_the_schedule():
    """A mixed guard must keep its input half rather than collapse wholesale."""
    norm = _normalizer(coreIdx="LOOP_INDUCTION", layoutType="INPUT_FORMAT")
    out = _guard_of(norm, "coreIdx > 0 && layoutType == 3")
    rendered = str(out)
    assert "VAR_SCHED_" in rendered, "schedule half should still soften"
    assert "VAR_FORMAT" in rendered or "layoutType" in rendered.lower(), rendered


def test_cross_function_reachability_is_tracked_apart_from_scheduling():
    """`__reached_F` is a modelling gap call-graph slicing can close, not a
    schedule fact we soften on purpose; conflating them hides it."""
    norm = _normalizer()
    out = _guard_of(norm, "__reached_DoSparse")
    assert out["var"].startswith("VAR_REACHED_")
    assert norm.scheduling[out["var"]] == "REACHED_SOFT"


def test_an_unresolvable_guard_is_reported_not_quietly_softened():
    norm = _normalizer()
    out = _guard_of(norm, "MysteryHelper(a, b)")
    assert out["var"].startswith("VAR_UNDECIDED_")
    assert out["var"] in norm.undecided


def test_a_dropped_guard_names_the_symbol_it_stopped_on():
    """`undecided` holds the whole condition, which after expansion runs to
    hundreds of characters and gets truncated. Without the offending symbol
    recorded separately, the record says a guard failed but not on what."""
    norm = _normalizer(shape="INPUT_SHAPE")
    out = _guard_of(norm, "shape > 0 && mysteryAccumulator > 4")
    var = next(v for v in norm.undecided if v.startswith("VAR_UNDECIDED_"))
    assert "mysteryAccumulator" in norm.blocked_on[var]
    assert "VAR_SHAPE_SHAPE" in str(out), "the resolvable half must survive"


def test_softening_a_guard_records_it_for_escalation():
    """Anything that widens the condition must be visible to the gap machinery,
    otherwise it is an over-approximation nobody can ever close."""
    norm = _normalizer(coreIdx="LOOP_INDUCTION")
    out = _guard_of(norm, "coreIdx > 0")
    assert out["var"] in norm.undecided
    assert norm.model.get(out["var"]) is not None


# -- resolving a leaf in the function it was read in ------------------------
def _two_scope_normalizer() -> _ValueNormalizer:
    """`inputLayout` is a local of `GetShapeAttrsInfo`, absent from the encode
    function — the shape of every operator that reads an attribute into a local
    in one function and encodes the key in another."""
    encode = SourceResolver()
    shapes = SourceResolver(local_roots={"inputLayout": "ATTRIBUTE"})
    return _ValueNormalizer(
        encode, VariableModel(), scope_for=lambda fn: {"GetShapeAttrsInfo": shapes}.get(fn, encode)
    )


def test_a_leaf_is_resolved_in_the_function_it_came_from():
    """Expansion inlines across functions, so a leaf arriving here may be a
    local of somewhere else entirely. Resolved against the encode function it
    has no binding, and the guard silently widens to a free boolean."""
    norm = _two_scope_normalizer()
    out = norm._guard(Bin("==", Ref("inputLayout", scope="GetShapeAttrsInfo"), Const("SBH")))
    assert "VAR_UNDECIDED_" not in str(out), "should resolve, not soften"
    assert norm.undecided == {}


def _packing_normalizer() -> _ValueNormalizer:
    """Every function resolves `coreIdx` as a traversal position of its own."""
    packing = SourceResolver(local_roots={"coreIdx": "LOOP_INDUCTION"})
    return _ValueNormalizer(
        SourceResolver(), VariableModel(), scope_for=lambda fn: packing
    )


def test_counters_of_the_same_name_in_two_functions_are_two_variables():
    """Two functions pack blocks onto cores, each counting with a `coreIdx`.

    One variable for both asserts the two counts are equal, which shrinks the
    feasible set — the direction an over-approximation must never take, and on
    its own enough to rule out keys that are reachable.
    """
    norm = _packing_normalizer()
    one = norm._leaf(Ref("coreIdx", scope="FillBlockInfoLoadBalanceForBn2"))
    two = norm._leaf(Ref("coreIdx", scope="CaclePerCoreBlockInfo"))
    assert one["var"].startswith("VAR_SCHED_")
    assert one["var"] != two["var"]
    assert norm.var_scope[one["var"]] == "FillBlockInfoLoadBalanceForBn2"


def test_the_same_counter_read_twice_stays_one_variable():
    norm = _packing_normalizer()
    scope = "FillBlockInfoLoadBalanceForBn2"
    assert norm._leaf(Ref("coreIdx", scope=scope)) == norm._leaf(
        Ref("coreIdx", scope=scope)
    )


def test_a_leaf_that_folded_to_a_constant_carries_the_value_not_the_name():
    """A leaf reducible to a constant must emit the value it reduced to.

    Emitting the name instead spells the literal like an identifier, and every
    reader downstream then sees a symbol nobody modelled.
    """
    encode = SourceResolver().scoped(bindings={"blockSize": "128"})
    norm = _ValueNormalizer(encode, VariableModel(), scope_for=lambda fn: encode)
    out = norm._guard(Bin(">", Ref("blockSize"), Const(0)))
    assert "blockSize" not in str(out), out


def test_a_leaf_choosing_between_constants_is_not_folded_to_one():
    """The arms of a ternary are all constants; the local is not a constant.

    Folding it to the first arm deletes the branches that produce the others,
    which is the direction that invents false "unreachable" answers.
    """
    encode = SourceResolver().scoped(bindings={"mode": "(a == b ? 0 : (a > b ? 2 : 1))"})
    norm = _ValueNormalizer(encode, VariableModel(), scope_for=lambda fn: encode)
    out = norm._guard(Bin("==", Ref("mode"), Const(2)))
    assert "'lit': 0" not in str(out), out


def test_the_same_leaf_without_a_scope_still_fails():
    """Confirms the previous test passes because of the scope, not because the
    encode resolver happens to know the symbol."""
    norm = _two_scope_normalizer()
    out = norm._guard(Bin("==", Ref("inputLayout"), Const("SBH")))
    assert out["var"].startswith("VAR_UNDECIDED_")


def test_an_unexpanded_name_carries_the_scope_it_was_read_in():
    """`_expand_surface` keeps names as resolver leaves; dropping the scope
    there is what made them unresolvable later."""
    from uo_init.derive_key_fields import KeyFieldDeriver

    deriver = KeyFieldDeriver.__new__(KeyFieldDeriver)
    tagged = deriver._expand_surface(Ref("inputLayout"), "GetShapeAttrsInfo", 0)
    assert tagged == Ref("inputLayout", scope="GetShapeAttrsInfo")


def test_scope_is_metadata_and_does_not_change_the_rendered_name():
    assert _leaf_text(Ref("inputLayout", scope="F")) == _leaf_text(Ref("inputLayout"))


def test_container_element_uses_the_scope_on_the_array_ref():
    """`qValue[0]` is a local of GetShapeAttrsInfo. Resolved in the encode
    function it has no binding, so Select used to become array_subscript even
    though the same leaf is INPUT_VALUE in its defining scope."""
    from uo_init.expr_ir import Select

    encode = SourceResolver()
    shapes = SourceResolver(local_roots={"qValue": "INPUT_VALUE", "kvValue": "INPUT_VALUE"})
    norm = _ValueNormalizer(
        encode,
        VariableModel(),
        scope_for=lambda fn: {"GetShapeAttrsInfo": shapes}.get(fn, encode),
    )
    cond = Bin(
        "==",
        Select(Ref("qValue", scope="GetShapeAttrsInfo"), Const(0)),
        Const(0),
    )
    out = norm._guard(cond)
    assert "VAR_UNDECIDED_" not in str(out), out
    assert "array_subscript" not in norm.blocked_on.values()
    assert any(r == "INPUT_VALUE" for r in norm.roots.values()), norm.roots


# -- an accessor chain routed through a local ------------------------------
def _tagged(text: str, scope: str):
    """The expression as `_expand_surface` hands it on: names stamped with
    the function they were read in, accessor calls left for the resolver."""
    from uo_init.derive_key_fields import KeyFieldDeriver

    deriver = KeyFieldDeriver.__new__(KeyFieldDeriver)
    return deriver._expand_surface(parse_expr(text), scope, 0)


def _rope_like_normalizer() -> _ValueNormalizer:
    """Two optional tensors, each fetched into a local of the same helper.

    The ordinary shape of a rank test: a helper binds `<tensor>Shape` to an
    accessor and then asks that local for its rank, and the encode function
    never sees the local.
    """
    encode = SourceResolver()
    shapes = SourceResolver(
        bindings={
            "queryRopeShape": "ctx->GetOptionalInputShape("
            "static_cast<size_t>(InputIndex::QUERY_ROPE))",
            "keyRopeShape": "ctx->GetOptionalInputShape("
            "static_cast<size_t>(InputIndex::KEY_ROPE))",
        }
    )
    return _ValueNormalizer(
        encode,
        VariableModel(),
        scope_for=lambda fn: {"GetShapeAttrsInfo": shapes}.get(fn, encode),
    )


def test_a_call_is_resolved_in_the_scope_of_the_names_underneath_it():
    """Only `Ref` carries a scope, and a whole accessor chain arrives as a
    `Call`. Reading the stamp off that node alone found nothing, so the chain
    was resolved in the encode function, where the local naming the tensor
    does not exist."""
    norm = _rope_like_normalizer()
    out = norm._value(
        _tagged("queryRopeShape->GetStorageShape().GetDimNum()", "GetShapeAttrsInfo")
    )
    # A rank, not an element count: `GetDimNum()` answers how many axes there
    # are, and the host checks a rank of 4 against an extent of 0 on the same
    # tensor, so one variable cannot hold both.
    assert out["var"] == "VAR_RANK_QUERY_ROPE"


def test_two_tensors_read_through_locals_do_not_share_one_variable():
    """What the collapse cost: `rank(a) != 0 && rank(b) != 0` became
    `RANK != 0 && RANK != 0`, which asserts two unrelated tensors have equal
    rank — a constraint the source never states, and one that makes keys look
    unreachable."""
    norm = _rope_like_normalizer()
    q = norm._value(
        _tagged("queryRopeShape->GetStorageShape().GetDimNum()", "GetShapeAttrsInfo")
    )
    k = norm._value(
        _tagged("keyRopeShape->GetStorageShape().GetDimNum()", "GetShapeAttrsInfo")
    )
    assert q["var"] != k["var"]


def test_the_same_chain_with_no_scope_still_falls_back_to_the_accessor_name():
    """Confirms the two tests above pass because of the scope stamp, not
    because the encode resolver happened to know the local."""
    from uo_init.variable_model import names_an_accessor

    norm = _rope_like_normalizer()
    out = norm._value(parse_expr("queryRopeShape->GetStorageShape().GetDimNum()"))
    assert names_an_accessor(out["var"]), out


def test_a_chain_that_names_its_tensor_inline_never_needed_the_scope():
    """Why only the reads routed through a local were affected: an operand
    written into the expression is recognised from any scope."""
    norm = _rope_like_normalizer()
    out = norm._value(
        _tagged(
            "ctx->GetOptionalInputShape(static_cast<size_t>(InputIndex::KEY_ROPE))"
            "->GetStorageShape().GetDimNum()",
            "GetTilingKey",
        )
    )
    assert out["var"] == "VAR_RANK_KEY_ROPE"


def test_a_helper_call_is_classified_in_the_function_that_called_it():
    """Guard classification resolves the callee name on its own, and that name
    is looked up among the locals of the function that read it. Classified
    from the encode function instead, an input-backed helper standing beside a
    traversal position left the guard looking like a modelling gap."""
    encode = SourceResolver()
    helper = SourceResolver(
        local_roots={"IsHighPrecision": "ATTRIBUTE", "coreIdx": "LOOP_INDUCTION"}
    )
    norm = _ValueNormalizer(
        encode,
        VariableModel(),
        scope_for=lambda fn: {"F": helper}.get(fn, encode),
    )
    roots, _reached, unresolved = norm._guard_leaf_roots(
        Call("IsHighPrecision", (Ref("coreIdx", scope="F"),))
    )
    assert "ATTRIBUTE" in roots and not unresolved


# -- a container element nothing can resolve -------------------------------
def _loop_local_normalizer() -> _ValueNormalizer:
    """`invalidS1Array` is a `vector<bool>` filled inside a loop.

    No scope resolves it to an input, because no input decides it directly —
    what the loop establishes is a quantified statement over the elements.
    """
    encode = SourceResolver(local_roots={"layoutType": "INPUT_FORMAT"})
    return _ValueNormalizer(encode, VariableModel(), scope_for=lambda fn: encode)


def test_an_unresolvable_subscript_does_not_take_the_guard_down_with_it():
    """The whole point of cutting at the subscript.

    An expanded guard is the conjunction of every source guard on the path. If
    the `Select` raises, `_guard` replaces *the guard* with one free boolean and
    the layout constraint standing beside it is lost — the field then looks
    controllable by nothing, when in truth it is controllable by the layout.
    """
    from uo_init.expr_ir import Select

    norm = _loop_local_normalizer()
    cond = Bin(
        "&&",
        Bin("==", Ref("layoutType", scope="F"), Const(3)),
        Select(Ref("invalidS1Array", scope="F"), Ref("j", scope="F")),
    )
    out = norm._guard(cond)
    rendered = str(out)

    assert out.get("op") == "and", f"guard collapsed wholesale: {out}"
    assert "VAR_UNDECIDED_" not in rendered, rendered
    assert "VAR_LOOPELEM_" in rendered, rendered
    assert "VAR_FORMAT" in rendered or "layouttype" in rendered.lower(), rendered


def test_a_cut_subscript_is_registered_like_any_other_over_approximation():
    """An over-approximation nobody can see is one nobody can ever close."""
    from uo_init.expr_ir import Select

    norm = _loop_local_normalizer()
    norm._guard(Select(Ref("invalidS1Array", scope="F"), Ref("j", scope="F")))
    var = next(v for v in norm.undecided if v.startswith("VAR_LOOPELEM_"))
    assert norm.model.get(var) is not None, "must be in the variable model"
    assert "invalidS1Array" in norm.blocked_on[var], norm.blocked_on
    assert is_overapprox_var(var)


def test_the_same_element_read_twice_is_the_same_variable():
    """Two free booleans for one element would let a solver satisfy a guard and
    its negation at once, which is worse than an honest single unknown."""
    from uo_init.expr_ir import Select

    norm = _loop_local_normalizer()
    first = norm._guard(Select(Ref("invalidS1Array", scope="F"), Ref("j", scope="F")))
    second = norm._guard(Select(Ref("invalidS1Array", scope="F"), Ref("j", scope="F")))
    assert str(first) == str(second)
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 1


def test_same_named_containers_in_two_functions_are_not_equated():
    """`invalidS1Array` is a local of several functions. Treating them as one
    variable would constrain unrelated code to agree."""
    from uo_init.expr_ir import Select

    norm = _loop_local_normalizer()
    norm._guard(Select(Ref("invalidS1Array", scope="GetParseS1S2OuterInfo"), Ref("j")))
    norm._guard(Select(Ref("invalidS1Array", scope="FillBlockInfo"), Ref("j")))
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 2


def _nested(container: str, *subscripts, scope: str = "F"):
    """`container[s0][s1]…`, nested left to right as the parser builds it."""
    from uo_init.expr_ir import Select

    out = Ref(container, scope=scope)
    for sub in subscripts:
        out = Select(out, sub)
    return out


def test_a_subscript_is_not_expanded_through_its_definitions():
    """Nothing consumes a subscript's *value* — a `Select` is replaced wholesale
    by `_element_or_cut` — so expanding it buys nothing and costs identity.

    An expanded index picks up whatever guards its definition sat under
    (`SetSparseParams(...)`, `platformInfoPtr == None`), so one source read
    renders differently on different expansion paths: `parseInfo[i]` split into
    eleven variables the source had no counterpart for. Keeping it shallow also
    made the largest field's expansion less than half the size, because a
    subscript's definition chain is no longer inlined into it.
    """
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.expr_ir import Select

    deriver = KeyFieldDeriver.__new__(KeyFieldDeriver)
    deriver._nodes = 0
    out = deriver._expand_container_surface(
        Select(Ref("parseInfo"), Ref("i")), "GetSparseBlockInfo", 0
    )
    assert out == Select(
        Ref("parseInfo", scope="GetSparseBlockInfo"),
        Ref("i", scope="GetSparseBlockInfo"),
    ), out


def test_the_subscript_chain_is_outermost_first():
    """`a[b][0][SUM_ALL]` reads left to right; the surface has to as well."""
    from uo_init.derive_key_fields import _subscript_chain

    subs = (Ref("b"), Const(0), Ref("SUM_ALL"))
    assert _subscript_chain(_nested("a", *subs)) == list(subs)


def test_different_outer_subscripts_are_different_variables():
    """`a[b][0][SUM_ALL]` and `a[b-1][0][SUM_ALL]` are different values.

    Identity used to be keyed on the innermost subscript alone, because
    `_container_of` peels every subscript off to find the container's input
    root. Both surfaces then rendered as `a[SUM_ALL]` and collapsed into one
    variable. That is not a loose approximation but a false equality — and
    since these are prefix sums whose neighbours are never equal, it can rule
    out keys that are in fact legal.
    """
    norm = _loop_local_normalizer()
    here = _nested("calculatedBlockInfo", Ref("b"), Const(0), Ref("SUM_ALL"))
    prev = _nested(
        "calculatedBlockInfo", Bin("-", Ref("b"), Const(1)), Const(0), Ref("SUM_ALL")
    )
    norm._guard(Bin(">", here, Const(0)))
    norm._guard(Bin(">", prev, Const(0)))
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 2


def test_the_whole_subscript_chain_reaches_the_recorded_surface():
    """A reader has to be able to tell which element was cut."""
    norm = _loop_local_normalizer()
    expr = _nested("parseInfo", Ref("i"), Ref("LENGTH_IDX"))
    norm._guard(Bin(">", expr, Const(0)))
    var = next(v for v in norm.undecided if v.startswith("VAR_LOOPELEM_"))
    assert norm.model.get(var).name == "parseInfo[i][LENGTH_IDX]", norm.model.get(var).name


def test_the_same_nested_element_read_twice_is_still_one_variable():
    """Distinguishing more must not go so far as to split one value in two."""
    norm = _loop_local_normalizer()
    for _ in range(2):
        norm._guard(
            Bin(">", _nested("calculatedBlockInfo", Ref("b"), Const(0), Ref("SUM_ALL")), Const(0))
        )
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 1


def test_an_input_backed_container_still_becomes_an_element_variable():
    """The cut must be a last resort. `qValue[i]` is input data, and grading it
    as an over-approximation would hide a dimension the test generator drives."""
    from uo_init.expr_ir import Select

    encode = SourceResolver()
    shapes = SourceResolver(local_roots={"qValue": "INPUT_VALUE"})
    norm = _ValueNormalizer(
        encode,
        VariableModel(),
        scope_for=lambda fn: {"GetShapeAttrsInfo": shapes}.get(fn, encode),
    )
    out = norm._guard(
        Bin(
            "==",
            Select(Ref("qValue", scope="GetShapeAttrsInfo"), Ref("i")),
            Const(0),
        )
    )
    assert "VAR_LOOPELEM_" not in str(out), out
    assert "VAR_ELEM_" in str(out), out
    assert norm.undecided == {}


# -- a tuple slot of a container element -----------------------------------
def _slot(container: str, index: str, slot: str, scope: str = "F"):
    """`container[index].slot`, shaped as the C++ parser emits it."""
    from uo_init.expr_ir import Select

    return Call(
        f"field:{slot}", (Select(Ref(container, scope=scope), Ref(index, scope=scope)),)
    )


def test_a_slot_of_a_loop_local_element_is_cut_like_the_element():
    """`s1ValidIdx[i].second` is a `Call` wrapping a `Select`, so it reached
    none of the three `Select` cuts. It fell through to the text path, where
    `dotted_path` cannot render a subscript, arrived as `second(?)`, and was
    graded an unmapped call — taking the whole guard with it."""
    norm = _loop_local_normalizer()
    cond = Bin(
        "&&",
        Bin("==", Ref("layoutType", scope="F"), Const(3)),
        Bin(">", _slot("s1ValidIdx", "i", "second"), Const(0)),
    )
    out = norm._guard(cond)
    rendered = str(out)

    assert out.get("op") == "and", f"guard collapsed wholesale: {out}"
    assert "VAR_UNDECIDED_" not in rendered, rendered
    assert "VAR_LOOPELEM_" in rendered, rendered
    assert "VAR_FORMAT" in rendered or "layouttype" in rendered.lower(), rendered


def test_two_slots_of_one_element_are_different_variables():
    """The soundness case. `.first` is an index and `.second` a bound; sharing
    one variable would let the solver assert they are equal and satisfy guards
    that no input can."""
    norm = _loop_local_normalizer()
    first = norm._guard(Bin(">", _slot("s1ValidIdx", "i", "first"), Const(0)))
    second = norm._guard(Bin(">", _slot("s1ValidIdx", "i", "second"), Const(0)))
    assert str(first) != str(second), first
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 2


def test_the_same_slot_read_twice_is_the_same_variable():
    """The converse: one value must not become two free variables."""
    norm = _loop_local_normalizer()
    a = norm._guard(Bin(">", _slot("s1ValidIdx", "i", "second"), Const(0)))
    b = norm._guard(Bin(">", _slot("s1ValidIdx", "i", "second"), Const(0)))
    assert str(a) == str(b)
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 1


def test_a_slot_is_distinguished_from_the_bare_element():
    """`v[i]` and `v[i].second` are not the same value either."""
    from uo_init.expr_ir import Select

    norm = _loop_local_normalizer()
    norm._guard(Select(Ref("s1ValidIdx", scope="F"), Ref("i", scope="F")))
    norm._guard(Bin(">", _slot("s1ValidIdx", "i", "second"), Const(0)))
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 2


def test_a_std_get_slot_is_cut_the_same_way():
    """`std::get<1>(v[i])` is the same read spelled differently, and
    `_projection_index` already recognises both."""
    norm = _loop_local_normalizer()
    out = norm._guard(Bin(">", _slot("s1ValidIdx", "i", "get<1>"), Const(0)))
    assert "VAR_LOOPELEM_" in str(out), out
    assert "VAR_UNDECIDED_" not in str(out), out


def test_a_slot_of_an_input_backed_element_keeps_its_input_root():
    """The cut stays a last resort for slots too: a pair held by an
    input-backed container is still decided by that input, and grading it as an
    over-approximation would hide a dimension the test generator drives."""
    encode = SourceResolver()
    shapes = SourceResolver(local_roots={"seqLenPairs": "INPUT_VALUE"})
    norm = _ValueNormalizer(
        encode,
        VariableModel(),
        scope_for=lambda fn: {"GetShapeAttrsInfo": shapes}.get(fn, encode),
    )
    out = norm._guard(
        Bin(">", _slot("seqLenPairs", "i", "second", scope="GetShapeAttrsInfo"), Const(0))
    )
    assert "VAR_LOOPELEM_" not in str(out), out
    assert "VAR_ELEM_" in str(out), out
    assert norm.undecided == {}


def test_a_slot_on_something_other_than_a_subscript_is_left_alone():
    """`_expand_call` projects slots out of tuples it can see through. The cut
    must not intercept those, or a statically known component becomes a free
    variable."""
    norm = _loop_local_normalizer()
    pair = Call("make_pair", (Const(7), Const(9)))
    assert norm._element_member(Call("field:second", (pair,))) is None


# -- a summary of a loop-local container ------------------------------------
def test_a_size_of_a_loop_local_container_is_cut_not_collapsed():
    """`size(syncRounds) + size(syncRoundRanges) > CORE_LIST_NUM` used to take
    its whole guard down: `_container_reduction` can only name a summary after
    the input filling the container, and a vector built in a loop has no such
    root, so it returned `None` and the guard became one free boolean — losing
    the `CORE_LIST_NUM` comparison standing right beside it."""
    norm = _loop_local_normalizer()
    cond = Bin(
        "&&",
        Bin("==", Ref("layoutType", scope="F"), Const(3)),
        Bin(
            ">",
            Call("size", (Ref("syncRounds", scope="F"),)),
            Const(36),
        ),
    )
    out = norm._guard(cond)
    rendered = str(out)

    assert out.get("op") == "and", f"guard collapsed wholesale: {out}"
    assert "VAR_UNDECIDED_" not in rendered, rendered
    assert "VAR_LOOPELEM_" in rendered, rendered
    assert "36" in rendered, "the comparison beside it must survive"


def test_two_summaries_of_one_container_are_different_variables():
    """`size(v)` and `back(v)` are unrelated values."""
    norm = _loop_local_normalizer()
    norm._guard(Bin(">", Call("size", (Ref("v", scope="F"),)), Const(1)))
    norm._guard(Bin(">", Call("back", (Ref("v", scope="F"),)), Const(1)))
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 2


def test_the_same_summary_read_twice_is_one_variable():
    norm = _loop_local_normalizer()
    for _ in range(2):
        norm._guard(Bin(">", Call("size", (Ref("syncRounds", scope="F"),)), Const(1)))
    assert len([v for v in norm.undecided if v.startswith("VAR_LOOPELEM_")]) == 1


def test_an_input_backed_summary_keeps_its_input_root():
    """The cut is a last resort here too: `max_element(actualSeqQlen)` is
    decided by the sequence-length tensor, and grading it as an
    over-approximation would hide a dimension the generator drives."""
    encode = SourceResolver()
    shapes = SourceResolver(local_roots={"actualSeqQlen": "INPUT_VALUE"})
    norm = _ValueNormalizer(
        encode,
        VariableModel(),
        scope_for=lambda fn: {"GetShapeAttrsInfo": shapes}.get(fn, encode),
    )
    out = norm._guard(
        Bin(
            ">",
            Call("size", (Ref("actualSeqQlen", scope="GetShapeAttrsInfo"),)),
            Const(0),
        )
    )
    assert "VAR_LOOPELEM_" not in str(out), out
    assert norm.undecided == {}


# -- whether one variable may stand for a summary at every read point ------
class _Writers:
    """Stand-in for `HostIR.container_writers`."""

    def __init__(self, writers: dict[str, set[str]]) -> None:
        self._writers = writers

    def container_writers(self, path: str) -> set[str]:
        return set(self._writers.get(path.rsplit(".", 1)[-1], ()))


def _summary_normalizer(writers: dict[str, set[str]], root: str = "INPUT_VALUE"):
    encode = SourceResolver()
    scoped = SourceResolver(local_roots={"prefix1": root, "actualSeqQlen": root})
    return _ValueNormalizer(
        encode,
        VariableModel(),
        scope_for=lambda fn: scoped,
        host_ir=_Writers(writers),
    )


def test_a_summary_of_a_container_written_in_several_functions_is_isolated():
    """`prefix1.back()` is read both before and after the `push_back`s that
    six functions perform on it, and reads carry no line number, so program
    order cannot rule the interleaving out. One variable for all those reads
    asserts an equality the source never provides, and it fails by inventing
    an unsatisfiable key."""
    norm = _summary_normalizer({"prefix1": {"CalcleTNDDenseDeterParam", "GQA"}})
    out = norm._guard(
        Bin(">", Call("back", (Ref("prefix1", scope="Reader"),)), Const(0))
    )
    var = next(v for v in norm.model.variables if v.startswith("VAR_ELEM_BACK_"))
    assert norm.model.variables[var].identity_merged, out


def test_a_summary_of_a_container_filled_in_one_other_function_stays_shared():
    """`max(actualSeqQlen)` is the counterpart: filled once in
    `GetShapeAttrsInfo` and reduced later elsewhere, so all five dimensions
    that read it do mean the same value, and dropping that equality would
    only cost reachability verdicts."""
    norm = _summary_normalizer({"actualSeqQlen": {"GetShapeAttrsInfo"}})
    norm._guard(
        Bin(
            ">",
            Call("back", (Ref("actualSeqQlen", scope="CalcTiling"),)),
            Const(0),
        )
    )
    var = next(v for v in norm.model.variables if v.startswith("VAR_ELEM_BACK_"))
    assert not norm.model.variables[var].identity_merged


def test_a_summary_read_in_a_function_that_also_writes_it_is_isolated():
    """One writer is not enough when it is the reader: `+=` on a container in
    the same body puts a write between two reads."""
    norm = _summary_normalizer({"prefix1": {"Reader"}})
    norm._guard(Bin(">", Call("back", (Ref("prefix1", scope="Reader"),)), Const(0)))
    var = next(v for v in norm.model.variables if v.startswith("VAR_ELEM_BACK_"))
    assert norm.model.variables[var].identity_merged


def test_an_element_stays_index_free_whatever_the_writers_say():
    """`elem` names *some* element regardless of mutation, so the rule above
    must not be able to make it any less merged."""
    from uo_init.expr_ir import Select

    norm = _summary_normalizer({})
    norm._guard(
        Bin("==", Select(Ref("actualSeqQlen", scope="F"), Ref("i")), Const(0))
    )
    var = next(v for v in norm.model.variables if v.startswith("VAR_ELEM_ELEM_"))
    assert norm.model.variables[var].identity_merged


# -- the scope a container is read in --------------------------------------
def test_a_container_surface_carries_the_scope_it_was_read_in():
    """`Select.array` goes through `_expand_container_surface`, not
    `_expand_surface`. Only the latter used to tag the scope, so every
    cross-function container arrived untagged, resolved in the encode function,
    and lost its input root — `qValue[i]` is `GetData<int64_t>()` in
    `GetShapeAttrsInfo` and nothing at all anywhere else.
    """
    from uo_init.derive_key_fields import KeyFieldDeriver

    deriver = KeyFieldDeriver.__new__(KeyFieldDeriver)
    deriver._nodes = 0
    tagged = deriver._expand_container_surface(Ref("qValue"), "GetShapeAttrsInfo", 0)
    assert tagged == Ref("qValue", scope="GetShapeAttrsInfo")


def test_container_of_accepts_call_style_member_access():
    """Pretty-print drops `field:`; re-parsed `actualSeqQlen(base)[i]` must
    still name the same container as `base.actualSeqQlen[i]`."""
    from uo_init.derive_key_fields import _container_of
    from uo_init.expr_ir import Select

    dotted = parse_expr("fBaseParams.actualSeqQlen[i]")
    callish = parse_expr("actualSeqQlen(fBaseParams)[i]")
    assert _container_of(dotted) == "fBaseParams.actualSeqQlen"
    assert _container_of(callish) == "fBaseParams.actualSeqQlen"
    assert _container_of(parse_expr("begin(actualSeqQlen(fBaseParams))")) == (
        "fBaseParams.actualSeqQlen"
    )
    # Unary helpers must not be mistaken for members.
    assert _container_of(Select(parse_expr("CeilDiv(n)"), Const(0))) == ""


# -- how deep a field-vs-enum comparison is expanded -----------------------
def _classifier_deriver(writes, *, local_roots=None):
    """A deriver over one field's guarded writes, read from `Encode`."""
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent
    from uo_init.clang_walk import PathCond

    events = [
        WriteEvent(
            path="fBaseParams.opt",
            line=n,
            rhs=rhs,
            file="f.cpp",
            function="Writer",
            path_conditions=(PathCond(guard, negated, "f.cpp", n),),
        )
        for n, (rhs, guard, negated) in enumerate(writes, start=1)
    ]
    ir = HostIR(
        writes=events,
        class_fields={"fBaseParams", "opt"},
        summaries={"Writer": FuncSummary(name="Writer"), "Encode": FuncSummary(name="Encode")},
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(host_ir=ir, local_roots=local_roots or {}),
        var_model=VariableModel(),
    )


def test_a_classifier_field_is_expanded_into_the_input_condition_that_picks_it():
    """`pseOptional == NORMAL_TENSOR` says nothing a test can act on until the
    field's two guarded writes are substituted; then it is a test on the pse
    shape. Left shallow, the resolver calls the field host state and the
    dimension comes out `exact` yet undrivable."""
    deriver = _classifier_deriver(
        [("NORMAL_TENSOR", "pseShape == 0", True), ("EMPTY_TENSOR", "pseShape == 0", False)],
        local_roots={"pseShape": "INPUT_SHAPE"},
    )
    out = deriver._expand_operand(parse_expr("fBaseParams.opt"), "Encode", 0)
    assert "pseShape" in _pretty(out), out


def test_a_field_its_own_writes_read_back_is_left_shallow():
    """`layoutType = isAllSame ? TND : layoutType` is a field the host routes:
    set from the inputs, then rewritten on some paths. Chaining a prefix of
    those writes would report a value the later ones contradict."""
    deriver = _classifier_deriver(
        [("TND", "isAllSame", False), ("isAllSame ? TND : opt", "bn2Limit", False)],
        local_roots={"isAllSame": "INPUT_SHAPE", "bn2Limit": "INPUT_SHAPE"},
    )
    out = deriver._expand_operand(parse_expr("fBaseParams.opt"), "Encode", 0)
    assert _pretty(out) == "opt(fBaseParams)", out


def test_an_expansion_that_does_not_reach_inputs_is_thrown_away():
    """Expanding is only worth it if it *reduces*. When the writes are guarded
    by other host state, substitution drags in its chains too and the operand
    comes back no better driven than the leaf it replaced — two orders of
    magnitude larger, and still rooted in TILING_DATA."""
    deriver = _classifier_deriver(
        [("NORMAL_TENSOR", "someHostField != 0", False)],
        local_roots={"someHostField": "TILING_DATA"},
    )
    out = deriver._expand_operand(parse_expr("fBaseParams.opt"), "Encode", 0)
    assert _pretty(out) == "opt(fBaseParams)", out


def test_a_rejected_expansion_gives_back_the_node_budget_it_spent():
    """The global budget pays for the tree that is kept, not for attempts that
    were discarded. Leaving probes charged to it exhausted the budget on the
    largest field and turned one that derives fine into `unresolved`."""
    deriver = _classifier_deriver(
        [("NORMAL_TENSOR", "someHostField != 0", False)],
        local_roots={"someHostField": "TILING_DATA"},
    )
    before = deriver._nodes
    deriver._expand_operand(parse_expr("fBaseParams.opt"), "Encode", 0)
    assert deriver._nodes == before


# -- what a chain falls through to ----------------------------------------
def _fallthrough_deriver(writes, decls):
    """A deriver over one guarded write, with a member-declaration table."""
    from uo_init.clang_walk import FieldDecl, PathCond
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    events = [
        WriteEvent(
            path="fBaseParams.opt",
            line=n,
            rhs=rhs,
            file="f.cpp",
            function="Writer",
            path_conditions=(PathCond(guard, negated, "f.cpp", n),),
        )
        for n, (rhs, guard, negated) in enumerate(writes, start=1)
    ]
    ir = HostIR(
        writes=events,
        class_fields={"fBaseParams", "opt"},
        summaries={"Writer": FuncSummary(name="Writer")},
        field_decls={
            (host, name): FieldDecl(host, name, init, "h.h", 1)
            for host, name, init in decls
        },
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(host_ir=ir, local_roots={"cond": "INPUT_SHAPE"}),
        var_model=VariableModel(),
    )


def test_a_chain_falls_through_to_what_the_declaration_says():
    """`Const(0)` asserts a default nobody read. `dTemplateType` is declared
    `NUM64` and `s1TemplateType` `NUM128`, so the assertion was not merely
    unproven — it was false, and let a solver accept keys where the field is 0."""
    deriver = _fallthrough_deriver(
        [("7", "cond", False)], [("Params", "opt", "192")]
    )
    out = deriver._expand_text("fBaseParams.opt", "Writer", 0)
    assert "192" in _pretty(out), out
    assert deriver.implicit_zero == []


def test_a_member_declaring_no_initialiser_keeps_its_assumption():
    """No in-class initialiser means the value before the first write really is
    indeterminate. That is a stronger statement than "we did not look", and
    neither one is an excuse to invent a default."""
    deriver = _fallthrough_deriver([("7", "cond", False)], [("Params", "opt", None)])
    deriver._expand_text("fBaseParams.opt", "Writer", 0)
    assert len(deriver.implicit_zero) == 1


def test_a_member_name_two_structs_declare_is_not_resolved():
    """A write path names a variable, not a struct, so the member name has to
    identify the declaration alone. The generated tiling-data structs declare
    many of the same names `= 0`; picking one would turn "cannot prove" into
    "proved to be zero"."""
    deriver = _fallthrough_deriver(
        [("7", "cond", False)],
        [("Params", "opt", "192"), ("OtherTilingData", "opt", "0")],
    )
    out = deriver._expand_text("fBaseParams.opt", "Writer", 0)
    assert "192" not in _pretty(out), out
    assert len(deriver.implicit_zero) == 1


def test_a_non_constant_initialiser_is_not_used_as_a_default():
    """`= other * 2` is a value, but not one this chain can state without
    chasing `other` too — and `other`'s own value at that point is a different
    question from what the declaration says."""
    deriver = _fallthrough_deriver(
        [("7", "cond", False)], [("Params", "opt", "someOther * 2")]
    )
    deriver._expand_text("fBaseParams.opt", "Writer", 0)
    assert len(deriver.implicit_zero) == 1


def test_an_unread_default_becomes_a_free_variable_rather_than_zero():
    """Recording the assumption was never enough on its own: the expression
    still said the field is 0 there, so a solver would rule out every key where
    it is not — the very keys the assumption cannot speak for."""
    deriver = _fallthrough_deriver([("7", "cond", False)], [("Params", "opt", None)])
    out = deriver._expand_text("fBaseParams.opt", "Writer", 0)
    text = _pretty(out)
    [record] = deriver.implicit_zero
    assert record["variable"].startswith("VAR_INIT_")
    assert record["variable"] in text, text
    assert record["field"] == "fBaseParams.opt"


def test_the_variable_standing_in_for_a_default_is_declared_to_the_model():
    """K6 compiles a bare symbol it cannot find into `unmodelled_variable` and
    drops the whole dimension. A variable this analysis mints has to be
    declared, or making the derivation honest would make the solver blinder."""
    deriver = _fallthrough_deriver([("7", "cond", False)], [("Params", "opt", None)])
    deriver._expand_text("fBaseParams.opt", "Writer", 0)
    [record] = deriver.implicit_zero
    spec = deriver.model.get(record["variable"])
    assert spec is not None
    assert spec.value_type == "int"
    assert spec.domain.completeness == "open"


def test_the_same_site_mints_one_variable_however_often_it_is_chained():
    deriver = _fallthrough_deriver([("7", "cond", False)], [("Params", "opt", None)])
    first = _pretty(deriver._expand_text("fBaseParams.opt", "Writer", 0))
    deriver._implicit_seen.clear()
    deriver.implicit_zero.clear()
    deriver._cache.clear()
    second = _pretty(deriver._expand_text("fBaseParams.opt", "Writer", 0))
    assert first == second


def _member_chain_deriver(writes):
    """A deriver over writes to one member: (line, rhs, [(cond, negated)], function)."""
    from uo_init.clang_walk import PathCond
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    events = [
        WriteEvent(
            path="fBaseParams.b",
            line=line,
            rhs=rhs,
            file="f.cpp",
            function=function,
            path_conditions=tuple(
                PathCond(text, neg, "f.cpp", 1) for text, neg in conds
            ),
        )
        for line, rhs, conds, function in writes
    ]
    ir = HostIR(
        writes=events,
        class_fields={"fBaseParams", "b"},
        summaries={fn: FuncSummary(name=fn) for _, _, _, fn in writes},
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(host_ir=ir, local_roots={"layout": "ATTRIBUTE"}),
        var_model=VariableModel(),
    )


def test_a_write_elsewhere_does_not_unmake_coverage_here():
    """`fBaseParams.b` is assigned on every layout branch of `GetShapeAttrsInfo`
    — the last a plain `else` — and once more in `DoOpTiling`. Letting that
    sixth write veto the judgement minted a free variable for a path the five
    branches leave no room for, and it blocked five dimensions."""
    deriver = _member_chain_deriver(
        [
            (1, "10", [("layout == SBH", False)], "Shapes"),
            (2, "20", [("layout == SBH", True)], "Shapes"),
            (3, "30", [], "Later"),
        ]
    )
    deriver._expand_text("fBaseParams.b", "Shapes", 0)
    assert deriver.implicit_zero == [], deriver.implicit_zero


def test_two_functions_each_writing_one_side_are_still_not_exhaustive():
    """The rule that survives: either function can be called without the other,
    so together they promise nothing about any single run."""
    deriver = _member_chain_deriver(
        [
            (1, "10", [("layout == SBH", False)], "Shapes"),
            (2, "20", [("layout == SBH", True)], "Other"),
        ]
    )
    deriver._expand_text("fBaseParams.b", "Shapes", 0)
    assert len(deriver.implicit_zero) == 1


def _reached_symbols(expr):
    """Names of the `__reached_` placeholders anywhere in an expansion."""
    from uo_init.derive_key_fields import REACHED_PREFIX, Ref, _walk_dag

    return {
        n.symbol
        for n in _walk_dag(expr)
        if isinstance(n, Ref) and n.symbol.startswith(REACHED_PREFIX)
    }


def test_a_function_nobody_calls_does_not_get_to_overwrite():
    """`Later` writes with no guard, and no call of it was recorded. Reading
    that as "always runs" makes its write the answer outright, erasing what
    `Shapes` put there — a claim about control flow with nothing behind it,
    and erasing a value is what makes a satisfiable key look unreachable."""
    deriver = _member_chain_deriver(
        [
            (1, "10", [("layout == SBH", False)], "Shapes"),
            (2, "20", [("layout == SBH", True)], "Shapes"),
            (3, "30", [], "Later"),
        ]
    )
    out = deriver._expand_text("fBaseParams.b", "Shapes", 0)
    assert _reached_symbols(out) == {"__reached_Later"}


def test_the_function_the_question_is_asked_in_is_known_to_run():
    """The other side of it: a read inside `Shapes` is a run that got to
    `Shapes`, so nothing there needs a placeholder."""
    deriver = _member_chain_deriver(
        [(1, "10", [("layout == SBH", False)], "Shapes")]
    )
    deriver._expand_text("fBaseParams.b", "Shapes", 0)
    assert deriver._always_runs("Shapes", 0)


def test_a_sole_caller_of_the_asking_function_also_ran():
    """Called from exactly one place, `Entry` had to run for `Helper` to. Two
    call sites and the climb has to stop: either could have been the way in."""
    deriver = _conditional_call_deriver(path="fBaseParams.b")
    deriver._expand_text("fBaseParams.b", "Helper", 0)
    assert deriver._encode_path() == {"Helper", "Entry"}
    assert deriver._always_runs("Entry", 0)


def test_a_guard_nobody_could_read_is_not_no_guard():
    """The call of `Helper` sits under a macro-expanded condition. Dropping it
    leaves the call looking unguarded, which says `Helper` always runs."""
    deriver = _conditional_call_deriver(path="fBaseParams.b", opaque=True)
    reached = deriver._reached("Helper", 0)
    assert not deriver._always_runs("Helper", 0)
    assert _reached_symbols(reached)


def _conditional_call_deriver(*, path, decl=None, opaque=False):
    """Writes covering both sides of one condition, inside a helper that is
    itself only called under a guard."""
    from uo_init.clang_walk import CallSite, PathCond
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    events = [
        WriteEvent(
            path=path,
            line=line,
            rhs=rhs,
            file="f.cpp",
            function="Helper",
            path_conditions=(PathCond("mode == 1", neg, "f.cpp", 1),),
        )
        for line, rhs, neg in ((2, "10", False), (3, "20", True))
    ]
    member = "." in path
    ir = HostIR(
        writes=events if member else [],
        local_writes=[] if member else events,
        class_fields={"fBaseParams", "b"} if member else set(),
        summaries={
            "Entry": FuncSummary(name="Entry"),
            "Helper": FuncSummary(name="Helper"),
        },
        call_sites=[
            CallSite(
                caller="Entry",
                callee="Helper",
                file="f.cpp",
                line=1,
                args=(),
                path_conditions=(
                    PathCond("", False, "f.cpp", 1)
                    if opaque
                    else PathCond("wanted", False, "f.cpp", 1),
                ),
            )
        ],
        local_decls=[decl] if decl is not None else [],
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(
            host_ir=ir,
            local_roots={"mode": "ATTRIBUTE", "wanted": "ATTRIBUTE"},
        ),
        var_model=VariableModel(),
    )


def test_a_member_covered_only_inside_a_conditional_helper_keeps_its_assumption():
    """Coverage inside the helper says nothing about a run that never calls it,
    and a member outlives the call: such a run reads whatever it held before."""
    deriver = _conditional_call_deriver(path="fBaseParams.b")
    deriver._expand_text("fBaseParams.b", "Helper", 0)
    assert len(deriver.implicit_zero) == 1


def test_a_local_covered_inside_a_conditional_helper_needs_no_assumption():
    """Same shape, but a local does not outlive the call. A run that skips the
    helper has nowhere to read it from, so there is no earlier value to name."""
    from uo_init.clang_walk import LocalDecl

    deriver = _conditional_call_deriver(
        path="tmp", decl=LocalDecl("tmp", "Helper", "int64_t", None, "f.cpp", 1)
    )
    deriver._expand_text("tmp", "Helper", 0)
    assert deriver.implicit_zero == [], deriver.implicit_zero


def _local_decl_deriver(*, init, decl_line=1, write_line=1):
    """A deriver over one guarded write to a local, with a declaration table.

    Shaped like `seqQShapeSize`: declared with an initialiser inside the branch
    that is the only place it can be read.
    """
    from uo_init.clang_walk import LocalDecl, PathCond
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    events = [
        WriteEvent(
            path="seqSize",
            line=write_line,
            rhs="GetShapeSize()",
            file="f.cpp",
            function="Reader",
            path_conditions=(PathCond("layoutType == TND", False, "f.cpp", 1),),
        )
    ]
    ir = HostIR(
        summaries={
            "Reader": FuncSummary(name="Reader", locals={"seqSize": "GetShapeSize()"})
        },
        local_writes=events,
        local_decls=[
            LocalDecl("seqSize", "Reader", "size_t", init, "f.cpp", decl_line)
        ],
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(
            host_ir=ir, local_roots={"layoutType": "ATTRIBUTE"}
        ),
        var_model=VariableModel(),
    )


def test_a_local_declared_in_a_branch_needs_no_value_for_the_other_side():
    """`const size_t seqQShapeSize = ...;` inside the TND branch. Asking what
    it holds when the layout is not TND asks about a block it is not declared
    in, where no read of it exists — and the free variable minted to answer
    kept five dimensions off `exact`."""
    deriver = _local_decl_deriver(init="GetShapeSize()")
    out = _pretty(deriver._expand_text("seqSize", "Reader", 0))
    assert deriver.implicit_zero == [], deriver.implicit_zero
    assert "VAR_INIT_" not in out, out


def test_a_later_assignment_to_that_local_is_not_its_declaration():
    """Only the declaration carries the scoping argument. A guarded write
    further down really can be skipped with the variable already readable."""
    deriver = _local_decl_deriver(init="0", write_line=9)
    deriver._expand_text("seqSize", "Reader", 0)
    assert len(deriver.implicit_zero) == 1


def test_a_local_declared_without_a_value_keeps_its_assumption():
    """`size_t seqSize;` and a guarded write: the read really can come first,
    and what it sees is indeterminate rather than anything worth naming."""
    deriver = _local_decl_deriver(init=None)
    deriver._expand_text("seqSize", "Reader", 0)
    assert len(deriver.implicit_zero) == 1


def test_an_assumed_default_costs_the_field_its_exact_grade():
    """The record and the grade must agree. A field graded `exact` while
    resting on an assumption is the combination that makes the assumption
    invisible to everyone downstream."""
    grade, _ = classify_exactness(
        value_expr={"op": "eq", "var": "VAR_ATTR_KEEP_PROB", "value": 1},
        variables=["VAR_ATTR_KEEP_PROB"],
        unresolved=[],
        implicit_defaults=[{"function": "Writer", "file": "f.cpp", "line": 1}],
    )
    assert grade == EX_OVERAPPROX


def test_a_field_with_no_assumptions_is_still_gradeable_as_exact():
    grade, _ = classify_exactness(
        value_expr={"op": "eq", "var": "VAR_ATTR_KEEP_PROB", "value": 1},
        variables=["VAR_ATTR_KEEP_PROB"],
        unresolved=[],
        implicit_defaults=[],
    )
    assert grade == EX_EXACT


# -- writes reaching a member through a reference parameter ----------------
def _alias_deriver(calls, *, param="fBaseParams", helper="Helper"):
    """`this.fBaseParams.opt` written once directly and once through `helper`.

    `calls` lists what each caller passes in the parameter's position, so a test
    can hand the helper the member, something else, or nothing at all.
    """
    from uo_init.clang_walk import PathCond
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    events = [
        WriteEvent(
            path="this.fBaseParams.opt",
            line=1,
            rhs="1",
            file="f.cpp",
            function="Owner",
            path_conditions=(PathCond("cond", False, "f.cpp", 1),),
        ),
        WriteEvent(
            path=f"{param}.opt",
            line=2,
            rhs="2",
            file="f.cpp",
            function=helper,
            path_conditions=(PathCond("cond", True, "f.cpp", 2),),
        ),
    ]
    summaries = {
        "Owner": FuncSummary(
            name="Owner", calls=[(helper, tuple(a)) for a in calls]
        ),
        helper: FuncSummary(name=helper, params=["ctx", param]),
    }
    ir = HostIR(
        writes=events,
        class_fields={"fBaseParams", "other"},
        summaries=summaries,
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(host_ir=ir, local_roots={"cond": "INPUT_SHAPE"}),
        var_model=VariableModel(),
    )


def test_a_helper_handed_the_member_defines_it():
    """`SetSplitAxis(ctx, fBaseParams)` writes `fBaseParams.splitAxis`, named
    after its parameter. Without the binding the suffix match cannot relate that
    to `this.fBaseParams.splitAxis`, and the field looks like it has one write
    when it has four."""
    deriver = _alias_deriver([("ctx", "fBaseParams")])
    assert len(deriver._field_defs("this.fBaseParams.opt")) == 2


def test_the_two_spellings_of_one_member_agree():
    """Asking for `fBaseParams.opt` and for `this.fBaseParams.opt` is asking
    about the same storage. Two answers would make exhaustiveness — which reads
    this pool — depend on how the caller happened to spell it."""
    deriver = _alias_deriver([("ctx", "fBaseParams")])
    a = deriver._field_defs("this.fBaseParams.opt")
    b = deriver._field_defs("fBaseParams.opt")
    assert [(d.file, d.line) for d in a] == [(d.file, d.line) for d in b]


def test_a_helper_that_two_callers_hand_different_objects_defines_neither():
    """Two objects of one type reach the same parameter, so a write through it
    cannot be attributed to either. `CalcleTNDBandDeterPrefix` is really called
    this way, and merging its 10 writes into a member would invent branches."""
    deriver = _alias_deriver([("ctx", "fBaseParams"), ("ctx", "other")])
    assert len(deriver._field_defs("this.fBaseParams.opt")) == 1


def test_a_parameter_holding_something_that_is_not_a_member_is_not_bound():
    """A local `FuzzyBaseInfoParamsRegbase` passed by reference is a different
    object from the class member of the same type."""
    deriver = _alias_deriver([("ctx", "scratch")])
    assert len(deriver._field_defs("this.fBaseParams.opt")) == 1


def test_a_helper_nobody_calls_is_not_bound():
    """No call site is no evidence. Attributing the write to `this` would let an
    unreferenced helper contribute branches the operator never takes."""
    deriver = _alias_deriver([])
    assert len(deriver._field_defs("this.fBaseParams.opt")) == 1


def test_a_bare_member_name_does_not_bind_through_a_parameter():
    """`this.b` and `this.fBaseParams.b` are two fields sharing a tail. A
    one-segment path has no member prefix to bind against, so the parameter name
    would be matched against the field name itself."""
    deriver = _alias_deriver([("ctx", "fBaseParams")], param="b", helper="Take")
    assert len(deriver._field_defs("this.b")) == 0


# -- `push_back(x); back()` is `x` -----------------------------------------
def _back_deriver(
    events,
    reads,
    *,
    calls=(),
    local_defs=None,
):
    """A function that appends to a local container and reads `back()`.

    `events` are `(line, column, kind, rhs, conds)` mutations of `v`; `reads`
    are `(line, column)` of `v.back()` calls, and `calls` are extra
    `(callee, line, column, receiver, args)` sites in the window between them.
    """
    from uo_init.clang_walk import CallSite
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    writes = [
        WriteEvent(
            path="v",
            line=line,
            column=col,
            rhs=rhs,
            file="f.cpp",
            function="Fn",
            kind=kind,
            path_conditions=tuple(conds),
        )
        for line, col, kind, rhs, conds in events
    ]
    sites = [
        CallSite(
            caller="Fn",
            callee="back",
            file="f.cpp",
            line=r[0],
            column=r[1],
            receiver="v",
            path_conditions=tuple(r[2]) if len(r) > 2 else (),
        )
        for r in reads
    ] + [
        CallSite(
            caller="Fn",
            callee=callee,
            file="f.cpp",
            line=l,
            column=c,
            receiver=recv,
            args=tuple(args),
        )
        for callee, l, c, recv, args in calls
    ]
    ir = HostIR(
        local_writes=writes,
        call_sites=sites,
        summaries={
            "Fn": FuncSummary(name="Fn", locals=dict(local_defs or {})),
        },
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(host_ir=ir, local_roots={"R1": "INPUT_SHAPE"}),
        var_model=VariableModel(),
    )


def _back_of_v(deriver):
    from uo_init.cpp_expr import parse_expr

    return deriver._last_push_dominates_back(parse_expr("v.back()"), "Fn")


def test_the_last_push_before_a_back_read_is_its_value():
    """`slicePrefix1.push_back(R1); … slicePrefix1.back()` — the source states
    the value outright, and calling it unknown loses it for no reason."""
    deriver = _back_deriver([(2, 5, "append", "R1", ())], [(4, 9)])
    assert _pretty(_back_of_v(deriver)) == "R1"


def test_a_push_after_the_read_is_not_its_value():
    """Program order decides, not the presence of a push somewhere in the
    function."""
    deriver = _back_deriver([(9, 5, "append", "R1", ())], [(4, 9)])
    assert _back_of_v(deriver) is None


def test_a_clear_between_the_push_and_the_read_blocks_the_rewrite():
    """The event that makes the answer `no` carries an empty RHS, which is why
    this rule reads raw events instead of the filtered write index."""
    deriver = _back_deriver(
        [(2, 5, "append", "R1", ()), (3, 5, "shrink", "", ())], [(4, 9)]
    )
    assert _back_of_v(deriver) is None


def test_a_whole_container_assignment_after_the_push_blocks_the_rewrite():
    deriver = _back_deriver(
        [(2, 5, "append", "R1", ()), (3, 5, "replace", "other", ())], [(4, 9)]
    )
    assert _back_of_v(deriver) is None


def test_two_reads_of_back_in_one_function_block_the_rewrite():
    """The expression IR carries no position, so with two reads there is no way
    to tell which one is being expanded. Pinning the push's value to the wrong
    read would assert an equality the source does not make."""
    deriver = _back_deriver([(2, 5, "append", "R1", ())], [(4, 9), (7, 3)])
    assert _back_of_v(deriver) is None


def test_a_conditional_push_is_not_the_value_on_every_path():
    """Reached only under a guard, so on the other path `back()` is whatever
    was there before."""
    from uo_init.clang_walk import PathCond

    deriver = _back_deriver(
        [(2, 5, "append", "R1", (PathCond("cond", False, "f.cpp", 1),))], [(4, 9)]
    )
    assert _back_of_v(deriver) is None


def test_a_push_and_read_under_the_same_guard_still_rewrites():
    """The real case: both sit inside the same `deterSparseType == DETER_BAND`
    block. Demanding the push be unconditional would reject exactly the shape
    this rule exists for."""
    from uo_init.clang_walk import PathCond

    guard = PathCond("sparse != BAND", True, "f.cpp", 1)
    deriver = _back_deriver(
        [(2, 5, "append", "R1", (guard,))], [(4, 9, (guard,))]
    )
    assert _pretty(_back_of_v(deriver)) == "R1"


def test_a_push_guarded_more_tightly_than_the_read_does_not_rewrite():
    """The push runs under an extra condition the read does not carry, so on
    the other side of it `back()` is whatever was there before."""
    from uo_init.clang_walk import PathCond

    outer = PathCond("sparse != BAND", True, "f.cpp", 1)
    inner = PathCond("g == 1", False, "f.cpp", 2)
    deriver = _back_deriver(
        [(3, 5, "append", "R1", (outer, inner))], [(5, 9, (outer,))]
    )
    assert _back_of_v(deriver) is None


def test_a_push_behind_an_incompletely_recorded_guard_does_not_rewrite():
    """`guard_clause` records less than the truth, so the guard comparison
    cannot see every condition the push really runs under."""
    from uo_init.clang_walk import PathCond

    guard = PathCond("ptr == nullptr", True, "f.cpp", 1, kind="guard_clause")
    deriver = _back_deriver(
        [(2, 5, "append", "R1", (guard,))], [(4, 9, (guard,))]
    )
    assert _back_of_v(deriver) is None


def test_a_push_inside_a_loop_is_not_a_known_last_element():
    """Which element is last depends on the trip count, and textual order is
    not program order across a back edge."""
    from uo_init.clang_walk import PathCond

    deriver = _back_deriver(
        [(2, 5, "append", "R1", (PathCond("i < n", False, "f.cpp", 1, kind="for"),))],
        [(4, 9)],
    )
    assert _back_of_v(deriver) is None


def test_handing_the_container_to_a_callee_blocks_the_rewrite():
    """A by-reference parameter can change the last element without leaving any
    write event, so the absence of an event is not evidence here."""
    deriver = _back_deriver(
        [(2, 5, "append", "R1", ())],
        [(4, 9)],
        calls=[("Mutate", 3, 5, "", ("v",))],
    )
    assert _back_of_v(deriver) is None


def test_an_unmodelled_method_call_on_the_container_blocks_the_rewrite():
    deriver = _back_deriver(
        [(2, 5, "append", "R1", ())],
        [(4, 9)],
        calls=[("shrink_to_fit", 3, 5, "v", ())],
    )
    assert _back_of_v(deriver) is None


def test_a_read_only_method_call_on_the_container_still_allows_it():
    """`v.size()` between the two does not change the last element."""
    deriver = _back_deriver(
        [(2, 5, "append", "R1", ())],
        [(4, 9)],
        calls=[("size", 3, 5, "v", ())],
    )
    assert _pretty(_back_of_v(deriver)) == "R1"


def test_a_push_on_the_same_line_before_the_read_still_counts():
    """`prefix0.push_back(x); … prefix0.back()` share a line in FAG, so the
    column is what orders them."""
    deriver = _back_deriver([(4, 5, "append", "R1", ())], [(4, 30)])
    assert _pretty(_back_of_v(deriver)) == "R1"


def test_a_push_later_on_the_same_line_is_not_the_read_value():
    deriver = _back_deriver([(4, 30, "append", "R1", ())], [(4, 5)])
    assert _back_of_v(deriver) is None


def test_a_member_container_is_never_rewritten_this_way():
    """`deterPrefixData.prefix1` is appended to in six functions and any callee
    reaches it through `this`, so one function's events cannot show that
    nothing intervened."""
    from uo_init.cpp_expr import parse_expr

    deriver = _back_deriver([(2, 5, "append", "R1", ())], [(4, 9)])
    out = deriver._last_push_dominates_back(
        parse_expr("deterPrefixData.prefix1.back()"), "Fn"
    )
    assert out is None


def _pretty(e):
    from uo_init.derive_key_fields import _pretty_dag

    return _pretty_dag(e)


# -- program order: what a name held where it was read ----------------------
def _save_restore_deriver():
    """A member stashed in a local, changed under a condition, restored after.

    The shape `fBaseParams.s2Inner` has: saved into a same-named local above
    the change, doubled if the split mode says so, put back from the local at
    the end. Expanding the local reads the member, whose last write reads the
    local — round it goes, though the source has no cycle in it.
    """
    from uo_init.clang_walk import PathCond
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    member = [
        WriteEvent(
            path="fBaseParams.s2Inner", line=505, rhs="bestSplit",
            file="a.cpp", function="Setup",
        ),
        WriteEvent(
            path="fBaseParams.s2Inner", line=907, rhs="fBaseParams.s2Inner * 2",
            file="b.cpp", function="Adjust",
            path_conditions=(PathCond("mode == 2", False, "b.cpp", 900),),
        ),
        WriteEvent(
            path="fBaseParams.s2Inner", line=929, rhs="s2Inner",
            file="b.cpp", function="Adjust",
            path_conditions=(PathCond("changed", False, "b.cpp", 925),),
        ),
    ]
    saved = [
        WriteEvent(
            path="s2Inner", line=898, rhs="fBaseParams.s2Inner",
            file="b.cpp", function="Adjust",
        )
    ]
    ir = HostIR(
        writes=member,
        local_writes=saved,
        class_fields={"fBaseParams", "s2Inner"},
        summaries={
            "Setup": FuncSummary(name="Setup"),
            "Adjust": FuncSummary(name="Adjust"),
        },
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(
            host_ir=ir,
            local_roots={
                "bestSplit": "ATTRIBUTE",
                "mode": "ATTRIBUTE",
                "changed": "ATTRIBUTE",
            },
        ),
        var_model=VariableModel(),
    )


def test_a_value_stashed_and_restored_is_not_a_cycle():
    """At line 898 neither the doubling nor the restore has run, so what the
    local saves is just the earlier value. Reading the writes without regard
    to position made this a cycle, and that verdict cost five dimensions."""
    deriver = _save_restore_deriver()
    out = _pretty(deriver._expand_text("fBaseParams.s2Inner", "Adjust", 0))
    assert deriver.cycles == set(), deriver.cycles
    assert "bestSplit" in out, out


def test_a_definition_that_really_is_circular_still_says_so():
    """Position has to earn the verdict. Here every write could have run
    before the read, so nothing explains the recursion away."""
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    ir = HostIR(
        writes=[
            WriteEvent(path="fBaseParams.x", line=10, rhs="y", file="f.cpp", function="F")
        ],
        local_writes=[
            WriteEvent(path="y", line=20, rhs="fBaseParams.x", file="f.cpp", function="F")
        ],
        class_fields={"fBaseParams", "x"},
        summaries={"F": FuncSummary(name="F")},
    )
    deriver = KeyFieldDeriver(
        host_ir=ir, resolver=SourceResolver(host_ir=ir), var_model=VariableModel()
    )
    deriver._expand_text("fBaseParams.x", "F", 0)
    assert deriver.cycles == {"fBaseParams.x"}, deriver.cycles


# -- the read's own condition ----------------------------------------------
def _guarded_pair_deriver(read_guard: str | None):
    """`b` is written only under one condition; `a` reads it under another.

    Shaped like `fBaseParams.bandIdx`: written only where an attention mask is
    present, and read only under the same test. `read_guard` of `None` puts
    the read on an unguarded write, where nothing rules the fall-through out.
    """
    from uo_init.clang_walk import PathCond
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    conds = (
        () if read_guard is None else (PathCond(read_guard, False, "f.cpp", 1),)
    )
    ir = HostIR(
        writes=[
            WriteEvent(
                path="fBaseParams.b", line=2, rhs="10", file="f.cpp", function="F",
                path_conditions=(PathCond("mask != 0", False, "f.cpp", 1),),
            ),
            WriteEvent(
                path="fBaseParams.a", line=3, rhs="fBaseParams.b + 1",
                file="f.cpp", function="F", path_conditions=conds,
            ),
        ],
        class_fields={"fBaseParams", "a", "b"},
        summaries={"F": FuncSummary(name="F")},
    )
    return KeyFieldDeriver(
        host_ir=ir,
        resolver=SourceResolver(
            host_ir=ir, local_roots={"mask": "ATTRIBUTE", "other": "ATTRIBUTE"}
        ),
        var_model=VariableModel(),
    )


def _assumed_fields(deriver) -> list[str]:
    """Which names the derivation had to assume an initial value for.

    `fBaseParams.a` is always among them: it is read at the top, where there
    is no condition to rule its fall-through out. The question these tests ask
    is about `b`, which is only ever read from inside `a`'s write.
    """
    deriver._expand_text("fBaseParams.a", "F", 0)
    return [row["field"] for row in deriver.implicit_zero]


def test_a_read_under_the_same_condition_as_the_write_assumes_nothing():
    """One write does not cover both sides of its own condition, but the only
    place the value is read is inside that condition — so no run reads it
    unwritten, and there is no initial value to assume."""
    assumed = _assumed_fields(_guarded_pair_deriver("mask != 0"))
    assert "fBaseParams.b" not in assumed, assumed


def test_a_read_under_an_unrelated_condition_still_assumes_one():
    assumed = _assumed_fields(_guarded_pair_deriver("other != 0"))
    assert "fBaseParams.b" in assumed, assumed


def test_a_read_with_no_condition_of_its_own_still_assumes_one():
    assumed = _assumed_fields(_guarded_pair_deriver(None))
    assert "fBaseParams.b" in assumed, assumed


def _same_name_locals_deriver():
    """Two functions, each with a local called `s1Inner`, holding different
    values. FAG spells 183 local names in more than one function, `s1Inner`
    and `blockOuter` among them.
    """
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_ir import FuncSummary, HostIR, WriteEvent

    ir = HostIR(
        writes=[
            WriteEvent(path="fBaseParams.x", line=3, rhs="s1Inner", file="f.cpp", function="F"),
            WriteEvent(path="fBaseParams.y", line=13, rhs="s1Inner", file="f.cpp", function="G"),
        ],
        local_writes=[
            WriteEvent(path="s1Inner", line=2, rhs="7", file="f.cpp", function="F"),
            WriteEvent(path="s1Inner", line=12, rhs="9", file="f.cpp", function="G"),
        ],
        class_fields={"fBaseParams", "x", "y"},
        summaries={"F": FuncSummary(name="F"), "G": FuncSummary(name="G")},
    )
    return KeyFieldDeriver(
        host_ir=ir, resolver=SourceResolver(host_ir=ir), var_model=VariableModel()
    )


def test_two_functions_with_the_same_local_name_hold_two_variables():
    """Reading one must not answer with the other's value, whichever is
    expanded first: the cache is shared across scopes and a stale entry here
    would put `7` where `9` belongs — a wrong equality, not a loose one."""
    deriver = _same_name_locals_deriver()
    first = _pretty(deriver._expand_text("fBaseParams.x", "F", 0))
    second = _pretty(deriver._expand_text("fBaseParams.y", "G", 0))
    assert "7" in first and "9" not in first, first
    assert "9" in second and "7" not in second, second


def test_the_same_local_name_in_another_function_is_not_recursion():
    """`G`'s `s1Inner` expanded while `F`'s is still on the stack is a second
    variable, not a cycle, and must expand rather than give up."""
    deriver = _same_name_locals_deriver()
    deriver._active.add(deriver._ident("s1Inner", "F"))
    assert "9" in _pretty(deriver._expand_text("fBaseParams.y", "G", 0))
    assert "s1Inner" not in deriver.cycles, deriver.cycles


def test_what_counts_as_running_before_a_read():
    from uo_init.derive_key_fields import DefSite

    deriver = _save_restore_deriver()
    loop = (("f.cpp", 5),)
    read = DefSite(rhs="", file="f.cpp", line=10, function="F", loops=loop)

    # Below the read but inside the same loop: it runs before it, one pass on.
    assert deriver._runs_before(
        DefSite(rhs="", file="f.cpp", line=20, function="F", loops=loop), read
    )
    # Below the read and outside the loop: the loop has finished by then.
    assert not deriver._runs_before(
        DefSite(rhs="", file="f.cpp", line=20, function="F"), read
    )
    # Another function, or no position at all: call order is not line order.
    assert deriver._runs_before(
        DefSite(rhs="", file="f.cpp", line=20, function="G"), read
    )
    assert deriver._runs_before(DefSite(rhs="", function="F"), read)
    # Above the read, plainly.
    assert deriver._runs_before(
        DefSite(rhs="", file="f.cpp", line=3, function="F"), read
    )
