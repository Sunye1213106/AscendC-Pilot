# -*- coding: utf-8 -*-
import pytest

from uo_init.harness import (
    build_harness_jobs,
    count_legal_instances,
    emit_instantiation,
    pairwise_coverage,
    parse_entry_signature,
    parse_fold_dump,
    sample_instances,
    write_harness_dir,
)
from uo_init.tpl_dsl import parse_file


def _key(fag_dir):
    return fag_dir / "op_kernel" / "arch35" / "flash_attention_score_grad_template_tiling_key.h"


def _apt(fag_dir):
    return fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"


def test_sel_expands_to_65(fag_dir):
    sch = parse_file(_key(fag_dir))
    assert len(sch.selections) == 65


def test_entry_signature_parsed_from_source(fag_dir):
    sig = parse_entry_signature(_apt(fag_dir), "flash_attention_score_grad")
    assert sig.name == "flash_attention_score_grad"
    assert len(sig.template_params) == 19
    assert sig.arity == 36
    assert all("uint8_t" in t for t in sig.param_types)
    names = [n for _, n in sig.template_params]
    assert names[0] == "IsEmptyTensor" and names[-1] == "IsRegbase"


def test_instantiation_matches_real_arity(fag_dir):
    """The old harness emitted 2 parameters for a 36-parameter entry point."""
    sch = parse_file(_key(fag_dir))
    sig = parse_entry_signature(_apt(fag_dir), "flash_attention_score_grad")
    inst = sample_instances(sch, strategy="pairwise")[0]
    src = emit_instantiation(sch, inst, signature=sig, dtype="DT_FLOAT16")
    assert src.count("__gm__ uint8_t *") == sig.arity
    assert "template __global__ __aicore__ void flash_attention_score_grad<" in src
    assert f'#include "{sig.source}"' in src
    # bool NTTPs must be spelled as bools, not as 0/1 ints
    assert "true" in src or "false" in src


def test_pairwise_sample_is_small_and_complete(fag_dir):
    sch = parse_file(_key(fag_dir))
    total = count_legal_instances(sch)
    assert total == 8705  # full expansion is not a usable compile matrix
    chosen = sample_instances(sch, strategy="pairwise")
    assert len(chosen) < total / 100
    assert pairwise_coverage(sch, chosen) == 1.0


def test_sampling_is_deterministic(fag_dir):
    sch = parse_file(_key(fag_dir))
    a = sample_instances(sch, strategy="pairwise", seed=7)
    b = sample_instances(sch, strategy="pairwise", seed=7)
    assert a == b


def test_harness_source_emitted(fag_dir, tmp_path):
    jobs = build_harness_jobs(
        _key(fag_dir),
        limit=2,
        dtypes=["DT_FLOAT16"],
        entry_source=_apt(fag_dir),
        entry_name="flash_attention_score_grad",
    )
    assert jobs
    assert "template __global__ __aicore__ void flash_attention_score_grad<" in jobs[0].source
    paths = write_harness_dir(jobs, tmp_path)
    assert paths[0].read_text(encoding="utf-8").startswith("// dtype")


def test_dtype_orthogonal(fag_dir):
    jobs = build_harness_jobs(
        _key(fag_dir),
        limit=1,
        dtypes=["DT_FLOAT16", "DT_FLOAT", "DT_BF16"],
        entry_source=_apt(fag_dir),
        entry_name="flash_attention_score_grad",
    )
    assert {j.dtype for j in jobs} == {"DT_FLOAT16", "DT_FLOAT", "DT_BF16"}
    for j in jobs:
        assert f"ORIG_DTYPE_QUERY {j.dtype}" in j.source
        assert "flash_attention_score_grad<" in j.source


def test_parse_fold_controls_skips_null_arms():
    from uo_init.harness import parse_fold_controls, mint_kernel_branches

    dump = "\n".join(
        [
            "Dumping my_op:",
            "`-FunctionDecl 0x3 'my_op' 'void (unsigned char *)' explicit_instantiation_definition",
            "  |-TemplateArgument integral 1",
            "  `-CompoundStmt 0x4",
            "    |-IfStmt 0x5 <a.cpp:9:5> has_else constexpr",
            "    | |-BinaryOperator 0x6 'bool' '=='",
            "    | | |-DeclRefExpr 0x7 'int' lvalue Var 0x8 'flag' 'int'",
            "    | | `-IntegerLiteral 0x9 'int' 0",
            "    | `-<<<NULL>>>",
            "    `-IfStmt 0xa <a.cpp:12:5>",
            "      |-BinaryOperator 0xb 'bool' '>'",
            "      | |-DeclRefExpr 0xc 'int' lvalue Var 0xd 'n' 'int'",
            "      | `-IntegerLiteral 0xe 'int' 0",
            "      `-CompoundStmt 0xf",
        ]
    )
    ctrls = parse_fold_controls(dump, entry="my_op", file="a.cpp")
    # discarded constexpr arm skipped; live if kept
    assert len(ctrls) == 1
    assert ctrls[0].kind == "if"
    ids = mint_kernel_branches(ctrls, entry="my_op")
    assert ids and ids[0].id.startswith("KBR_")
    assert ids[0].file == "a.cpp"


def test_parse_fold_dump_reads_specialisation():
    dump = "\n".join(
        [
            "Dumping my_op:",
            "FunctionTemplateDecl 0x1 <a.cpp:1:1> my_op",
            "|-NonTypeTemplateParmDecl 0x2 <line:1:1> 'bool' depth 0 index 0",
            "`-FunctionDecl 0x3 'my_op' 'void (unsigned char *)' explicit_instantiation_definition",
            "  |-TemplateArgument integral 1",
            "  |-TemplateArgument integral 0",
            "  `-CompoundStmt 0x4",
            "    `-IfStmt 0x5 <line:9:5> has_else constexpr",
            "      |-ConstantExpr 0x6",
            "      `-<<<NULL>>>",
        ]
    )
    rep = parse_fold_dump(dump)
    assert rep.instantiated
    assert rep.template_args == ["1", "0"]
    assert rep.constexpr_ifs == 1
    assert rep.discarded_branches == 1


def test_parse_fold_dump_ignores_declref_function_noise():
    from uo_init.harness import parse_fold_controls

    dump = "\n".join(
        [
            "Dumping my_op:",
            "FunctionTemplateDecl 0x1 my_op",
            "|-FunctionDecl 0x2 'my_op' 'void ()'",
            "| `-CompoundStmt 0x3",
            "|   `-DeclRefExpr 0x4 'bool ()' lvalue Function 0x99 'HELPER' 'bool ()'",
            "`-FunctionDecl 0x5 'my_op' 'void ()' explicit_instantiation_definition",
            "  |-TemplateArgument integral 7",
            "  `-CompoundStmt 0x6",
            "    `-IfStmt 0x7 <line:3:1>",
            "      `-IntegerLiteral 0x8 'int' 1",
        ]
    )
    rep = parse_fold_dump(dump)
    assert rep.instantiated
    assert rep.template_args == ["7"]
    assert len(parse_fold_controls(dump, entry="my_op", file="a.cpp")) == 1


def test_parse_fold_dump_detects_missing_instantiation():
    rep = parse_fold_dump("Dumping x:\nFunctionTemplateDecl 0x1 x\n")
    assert not rep.instantiated
    assert rep.template_args == []


@pytest.mark.requires_cann
def test_instantiation_materialises_under_clang(fag_dir, build_ctx, clang_exe, tmp_path):
    """The emitted TU really instantiates: clang reports all 19 template args."""
    from uo_init.harness import fold_report

    sch = parse_file(_key(fag_dir))
    sig = parse_entry_signature(_apt(fag_dir), "flash_attention_score_grad")
    inst = sample_instances(sch, strategy="pairwise")[0]
    p = tmp_path / "h.cpp"
    p.write_text(emit_instantiation(sch, inst, signature=sig), encoding="utf-8")

    rep = fold_report(p, build_ctx, clang_exe=clang_exe, entry="flash_attention_score_grad")
    assert rep.instantiated
    assert len(rep.template_args) == 19
    assert rep.template_args[0] == str(int(inst["IsEmptyTensor"]))
