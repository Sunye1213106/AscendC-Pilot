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
