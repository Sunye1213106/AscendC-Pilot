# -*- coding: utf-8 -*-
"""include_heal locates missing headers and adds -I without editing yaml."""
from __future__ import annotations

from pathlib import Path

from uo_init.build_context import BuildContext
from uo_init.include_heal import (
    bootstrap_operator_includes,
    enrich_scope_with_heal,
    extras_summary_path,
    find_include_dir,
    header_resolves,
    heal_missing_includes,
    include_dir_for,
    is_forbidden_include_dir,
    missing_includes_from_probes,
    parse_missing_includes,
    reset_index_cache,
    MissingInclude,
)


def test_parse_missing_include_from_clang_spelling():
    names = parse_missing_includes("'hccl/hccl_types.h' file not found")
    assert names == ["hccl/hccl_types.h"]
    names = parse_missing_includes('fatal error: "util/math_util.h" file not found')
    assert names == ["util/math_util.h"]
    names = parse_missing_includes("use of undeclared identifier 'string'")
    assert names == []


def test_include_dir_for_strips_quoted_prefix(tmp_path: Path):
    found = tmp_path / "hcomm" / "hccl" / "hccl_types.h"
    found.parent.mkdir(parents=True)
    found.write_text("//\n", encoding="utf-8")
    assert include_dir_for(found, "hccl/hccl_types.h") == tmp_path / "hcomm"
    leaf = tmp_path / "include" / "base" / "alog_pub.h"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("//\n", encoding="utf-8")
    assert include_dir_for(leaf, "alog_pub.h") == tmp_path / "include" / "base"


def test_forbidden_ascendc_basic_api():
    assert is_forbidden_include_dir("/cann/cann-asc-devkit/x86_64-linux/ascendc/include/basic_api")
    assert not is_forbidden_include_dir("/cann/cann-asc-devkit/x86_64-linux/asc/include/basic_api")


def _ctx(tmp_path: Path, *, op_rel: str = "mc2/matmul_all_reduce") -> BuildContext:
    cann = tmp_path / "cann"
    ops = tmp_path / "ops"
    op = ops / op_rel
    op.mkdir(parents=True)
    (op / "op_host").mkdir()
    (op / "op_kernel").mkdir()
    (ops / "common" / "include").mkdir(parents=True)
    return BuildContext.load(
        cann_root=str(cann),
        ops_root=str(ops),
        op_dir=str(op),
        arch_dir="arch22",
        apply_saved_extras=False,
    )


def test_find_hccl_types_under_hcomm(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    found = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "asc"
        / "include"
        / "adv_api"
        / "hccl"
        / "internal"
        / "hcomm"
        / "hccl"
        / "hccl_types.h"
    )
    found.parent.mkdir(parents=True)
    found.write_text("// types\n", encoding="utf-8")
    hit = find_include_dir(ctx, "hccl/hccl_types.h", side="host")
    assert hit is not None
    assert hit.include_dir.replace("\\", "/").endswith("hccl/internal/hcomm")
    # yaml already lists this -I; heal should still identify the directory.
    assert header_resolves(ctx, "hccl/hccl_types.h", side="host")


def test_find_alog_pub_one_level_below_include(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path, op_rel="attention/flash_attention_score")
    leaf = (
        tmp_path
        / "cann"
        / "cann-npu-runtime"
        / "x86_64-linux"
        / "include"
        / "base"
        / "alog_pub.h"
    )
    leaf.parent.mkdir(parents=True)
    leaf.write_text("//\n", encoding="utf-8")
    hit = find_include_dir(ctx, "alog_pub.h", side="host")
    assert hit is not None
    assert hit.include_dir.replace("\\", "/").endswith("include/base")


def test_find_family_bare_header(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    leaf = tmp_path / "ops" / "mc2" / "common" / "utils" / "mc2_log.h"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("//\n", encoding="utf-8")
    hit = find_include_dir(ctx, "mc2_log.h", side="host")
    assert hit is not None
    assert "mc2/common/utils" in hit.include_dir.replace("\\", "/")


def test_heal_skips_ascendc_basic_api_kernel_trap(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    trap = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "ascendc"
        / "include"
        / "basic_api"
        / "tuple.h"
    )
    trap.parent.mkdir(parents=True)
    trap.write_text("// trap\n", encoding="utf-8")
    good = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "asc"
        / "include"
        / "utils"
        / "std"
        / "tuple.h"
    )
    good.parent.mkdir(parents=True)
    good.write_text("// good\n", encoding="utf-8")
    hit = find_include_dir(ctx, "tuple.h", side="kernel")
    assert hit is not None
    assert "ascendc/include/basic_api" not in hit.include_dir.replace("\\", "/")


def test_bootstrap_adds_missing_quoted_include(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    header = (
        tmp_path
        / "cann"
        / "cann-extra-sdk"
        / "x86_64-linux"
        / "include"
        / "secret"
        / "hidden_util.h"
    )
    header.parent.mkdir(parents=True)
    header.write_text("//\n", encoding="utf-8")
    tu = Path(ctx.op_dir) / "op_host" / "tiling.cpp"
    tu.write_text('#include "secret/hidden_util.h"\nvoid f() {}\n', encoding="utf-8")
    hits = bootstrap_operator_includes(ctx, [tu])
    assert hits
    assert any(h.include == "secret/hidden_util.h" for h in hits)
    assert header_resolves(ctx, "secret/hidden_util.h", side="host")


def test_enrich_retries_until_probes_clean(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    header = (
        tmp_path
        / "cann"
        / "cann-extra-sdk"
        / "x86_64-linux"
        / "include"
        / "secret"
        / "hidden_util.h"
    )
    header.parent.mkdir(parents=True)
    header.write_text("//\n", encoding="utf-8")
    calls = {"n": 0}

    class _Enr:
        def __init__(self, probes):
            self.probes = probes
            self.errors = []
            self.scope = None
            self.status = "incomplete" if probes and probes[0].get("samples") else "complete"
            self.tus_expected = 1
            self.tus_parsed = 1

    def _enrich():
        calls["n"] += 1
        if calls["n"] == 1:
            return _Enr(
                [
                    {
                        "side": "host",
                        "samples": ["'secret/hidden_util.h' file not found"],
                        "fatal_count": 1,
                    }
                ]
            )
        return _Enr([{"side": "host", "samples": [], "fatal_count": 0}])

    _enr, report = enrich_scope_with_heal(
        ctx=ctx,
        host_tus=[],
        kernel_tu=None,
        enrich_fn=_enrich,
    )
    assert calls["n"] >= 2
    assert report.unresolved == []
    assert report.added_host
    extras = extras_summary_path(ctx.op_dir, ctx.arch_dir)
    assert extras.is_file()
    assert header_resolves(ctx, "secret/hidden_util.h", side="host")


def test_build_context_load_applies_saved_extras(tmp_path: Path):
    ctx = _ctx(tmp_path)
    extra = tmp_path / "cann" / "extra_inc"
    extra.mkdir(parents=True)
    ctx.add_include(str(extra), side="host")
    from uo_init.include_heal import HealReport, save_extras

    save_extras(ctx, HealReport(rounds=1, added_host=[str(extra).replace("\\", "/")]))
    loaded = BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path / "ops"),
        op_dir=ctx.op_dir,
        arch_dir=ctx.arch_dir,
        apply_saved_extras=True,
    )
    assert any(str(extra).replace("\\", "/") in p.replace("\\", "/") for p in loaded.host_includes())


def test_missing_from_probe_rows_keeps_side():
    rows = missing_includes_from_probes(
        [
            {
                "side": "kernel",
                "samples": ["'kernel_inc.h' file not found"],
            }
        ]
    )
    assert rows == [MissingInclude(name="kernel_inc.h", side="kernel")]


def test_find_cross_family_bare_header(tmp_path: Path):
    """ffn TUs include headers that live under a sibling family (mc2/common)."""
    reset_index_cache()
    ctx = _ctx(tmp_path, op_rel="ffn/ffn_worker_batching")
    leaf = tmp_path / "ops" / "mc2" / "common" / "utils" / "context_util.h"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("//\n", encoding="utf-8")
    hit = find_include_dir(ctx, "context_util.h", side="host")
    assert hit is not None
    assert "mc2/common/utils" in hit.include_dir.replace("\\", "/")


def test_find_cross_family_header_when_checkout_folder_is_test(tmp_path: Path):
    """Absolute path contains /TEST/; that must not look like an operator tests/ dir."""
    reset_index_cache()
    ops = tmp_path / "TEST" / "ops-transformer"
    op = ops / "ffn" / "ffn_worker_batching"
    op.mkdir(parents=True)
    (op / "op_host").mkdir()
    (op / "op_kernel").mkdir()
    leaf = ops / "mc2" / "common" / "utils" / "context_util.h"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("//\n", encoding="utf-8")
    ctx = BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(ops),
        op_dir=str(op),
        arch_dir="arch35",
        apply_saved_extras=False,
    )
    hit = find_include_dir(ctx, "context_util.h", side="host")
    assert hit is not None
    assert "mc2/common/utils" in hit.include_dir.replace("\\", "/")


def test_heal_missing_is_noop_when_header_absent_from_tree(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    hits = heal_missing_includes(
        ctx, [MissingInclude(name="acl/acl_base_mdl.h", side="host")]
    )
    assert hits == []
    assert ctx.extra_host_includes == []


def test_heal_missing_is_noop_when_unresolved(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    hits = heal_missing_includes(ctx, [MissingInclude(name="no_such/header.h", side="host")])
    assert hits == []
    assert ctx.extra_host_includes == []


def test_to_dict_roundtrips_extras(tmp_path: Path):
    ctx = _ctx(tmp_path)
    extra = tmp_path / "unique_inc"
    extra.mkdir()
    assert ctx.add_include(str(extra), side="host")
    restored = BuildContext.from_dict(ctx.to_dict())
    assert restored.extra_host_includes == ctx.extra_host_includes
