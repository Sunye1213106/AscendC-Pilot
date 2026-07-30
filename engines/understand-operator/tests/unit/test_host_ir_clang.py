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
