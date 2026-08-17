# -*- coding: utf-8 -*-
from uo_init.harness import (
    build_harness_jobs,
    count_legal_instances,
    emit_instantiation,
    pairwise_coverage,
    parse_entry_signature,
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
