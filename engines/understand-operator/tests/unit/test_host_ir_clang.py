# -*- coding: utf-8 -*-
"""Host IR on the clang backend: SSA versions, guards and function summaries."""
import pytest

from uo_init.host_ir import (
    assert_no_flatten,
    build_host_ir,
    derivation_chain,
    extract_writes_text,
)

pytestmark = pytest.mark.requires_cann


@pytest.fixture(scope="module")
def normal_ir(request):
    from uo_init.build_context import BuildContext
    from tests.conftest import CANN, FAG, OPS  # type: ignore

    if not (FAG.exists() and CANN.exists()):
        pytest.skip("FAG/CANN not available")
    ctx = BuildContext.load(
        cann_root=str(CANN), ops_root=str(OPS), op_dir=str(FAG), arch_dir="arch35"
    )
    p = (
        FAG
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp"
    )
    return build_host_ir([p], ctx=ctx, template_precondition="Normal"), p


def test_clang_backend_finds_writes_the_regex_misses(normal_ir):
    ir, p = normal_ir
    assert ir.backend == "clang"
    text_writes = extract_writes_text(p)
    assert len(ir.writes) > len(text_writes)
    # the regex cannot attribute a write to a function or to its guards
    assert not any(w.function for w in text_writes)
    assert any(w.function and w.guards() for w in ir.writes)


def test_writes_keep_the_nested_field_path(normal_ir):
    ir, _ = normal_ir
    assert_no_flatten(ir.writes)
    assert any(w.path.count(".") >= 2 for w in ir.writes)


def test_ssa_versions_are_dense_and_ordered(normal_ir):
    ir, _ = normal_ir
    paths = {w.path for w in ir.writes}
    multi = next((p for p in paths if len([w for w in ir.writes if w.path == p]) > 1), None)
    assert multi, "expected at least one field written more than once"
    versions = [w.version for w in ir.writes if w.path == multi]
    assert versions == list(range(len(versions)))
    lines = [w.line for w in ir.writes if w.path == multi]
    assert lines == sorted(lines)


def test_writes_carry_line_function_and_guards(normal_ir):
    ir, _ = normal_ir
    guarded = [w for w in ir.writes if w.guards()]
    assert guarded
    w = guarded[0]
    assert w.line > 0 and w.file and w.function
    assert w.template_precondition == "Normal"


def test_isnzout_derivation_chain(normal_ir):
    ir, _ = normal_ir
    chain = derivation_chain(ir, "isNzOut")
    assert chain
    assert all("ssa" in step and "rhs" in step for step in chain)


def test_function_summaries_have_reads_writes_locals_params(normal_ir):
    ir, _ = normal_ir
    named = [s for s in ir.summaries.values() if s.writes and s.reads]
    assert named
    assert any(s.locals for s in ir.summaries.values())
    assert any(s.params for s in ir.summaries.values())


def test_locals_and_params_lookup_helpers(normal_ir):
    ir, _ = normal_ir
    assert any(ir.locals_by_function().values())
    assert any(ir.params_by_function().values())


# -- the control statements, not just the guards they put on writes --------
def test_the_control_statements_reach_the_ir(normal_ir):
    ir, _ = normal_ir
    assert ir.controls
    kinds = {n.kind for n in ir.controls}
    assert "if" in kinds and kinds & {"for", "while", "cxx_for_range"}


def test_a_loop_guard_finds_its_statement_and_induction_variable(normal_ir):
    """A write inside a loop carries the loop's file and line in its guard.
    That is what lets a loop be summarised instead of given up on — the guard
    text alone names no induction variable."""
    ir, _ = normal_ir
    loop_conds = [
        pc
        for w in list(ir.writes) + list(ir.local_writes)
        for pc in w.path_conditions
        if pc.kind in ("for", "while", "do", "cxx_for_range")
    ]
    assert loop_conds, "expected at least one write inside a loop"
    found = [ir.loop_at(pc.file, pc.line) for pc in loop_conds]
    assert all(n is not None for n in found)
    assert any(n.induction_vars for n in found)


def test_member_declarations_carry_their_in_class_initialiser(normal_ir):
    ir, _ = normal_ir
    assert ir.field_decls
    with_init = [d for d in ir.field_decls.values() if d.init is not None]
    without = [d for d in ir.field_decls.values() if d.init is None]
    assert with_init and without, "expected both kinds in a real header"
    assert all(d.host and d.name and d.line > 0 for d in ir.field_decls.values())


def test_a_member_declared_by_two_structs_is_not_resolved_by_name(normal_ir):
    """`field_decl` is keyed by member name and must give up on collisions. The
    table itself is keyed on the struct, so both declarations survive in it."""
    ir, _ = normal_ir
    by_name: dict[str, list] = {}
    for (_, name), decl in ir.field_decls.items():
        by_name.setdefault(name, []).append(decl)
    shared = [n for n, ds in by_name.items() if len(ds) > 1]
    for name in shared:
        assert ir.field_decl(name) is None
    unique = next(n for n, ds in by_name.items() if len(ds) == 1)
    assert ir.field_decl(unique) is not None
    assert ir.field_decl(f"this.fBaseParams.{unique}") is not None


def test_one_statement_is_not_counted_once_per_translation_unit(normal_ir):
    """Headers are walked once per TU. Deduplication is on position, because an
    id's ordinal is assigned in walk order and the TUs run in parallel."""
    ir, _ = normal_ir
    seen = [(n.file, n.line, n.column, n.kind) for n in ir.controls]
    assert len(seen) == len(set(seen))


# -- one line, several calls on different containers -----------------------
def test_two_calls_of_one_method_on_one_line_both_survive(normal_ir):
    """`a.size() + b.size()` agrees on caller, callee, file and line. Keying
    deduplication on those four made the second call look like a header arriving
    twice, and dropped a container's only read."""
    ir, _ = normal_ir
    by_pos: dict[tuple[str, int, str], set[str]] = {}
    for cs in ir.call_sites:
        if cs.receiver:
            by_pos.setdefault((cs.file, cs.line, cs.callee), set()).add(cs.receiver)
    shared = {k: v for k, v in by_pos.items() if len(v) > 1}
    assert shared, "expected a line calling one method on two different objects"


def test_a_call_knows_its_column(normal_ir):
    """A container read and a write to it can share a line, so ordering them
    needs the column."""
    ir, _ = normal_ir
    assert all(cs.column > 0 for cs in ir.call_sites)
    per_line: dict[tuple[str, int], set[int]] = {}
    for cs in ir.call_sites:
        per_line.setdefault((cs.file, cs.line), set()).add(cs.column)
    assert any(len(cols) > 1 for cols in per_line.values())


def test_the_same_call_is_still_not_recorded_twice(normal_ir):
    ir, _ = normal_ir
    keys = [
        (cs.caller, cs.callee, cs.file, cs.line, cs.column, cs.receiver)
        for cs in ir.call_sites
    ]
    assert len(keys) == len(set(keys))
