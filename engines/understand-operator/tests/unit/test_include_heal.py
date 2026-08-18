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
    aliased_include_name,
    MissingInclude,
    search_roots,
    clear_saved_extras,
    load_extras_payload,
    promote_include_dirs,
    SOURCE_HEAL_PROMOTE,
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


def test_search_roots_follow_aarch64_and_install_layout(tmp_path: Path):
    reset_index_cache()
    cann = tmp_path / "cann"
    (cann / "cann-asc-devkit" / "aarch64-linux" / "asc" / "include").mkdir(parents=True)
    (cann / "cann-asc-devkit" / "aarch64-linux" / "asc" / "impl").mkdir(parents=True)
    ctx = _ctx(tmp_path)
    ctx.cann_root = str(cann)
    roots = [str(p).replace("\\", "/") for p in search_roots(ctx)]
    assert any("/aarch64-linux/" in r for r in roots)
    assert not any("/x86_64-linux/" in r for r in roots)

    installed = tmp_path / "latest"
    (installed / "x86_64-linux" / "asc" / "include").mkdir(parents=True)
    ctx.cann_root = str(installed)
    roots = [str(p).replace("\\", "/") for p in search_roots(ctx)]
    assert any(r.endswith("/x86_64-linux/asc/include") for r in roots)


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


def test_missing_from_heal_hints_when_samples_are_unrelated():
    rows = missing_includes_from_probes(
        [
            {
                "side": "kernel",
                "samples": ["unknown type name 'T'"] * 5,
                "heal_hints": ["'op_kernel/platform_util.h' file not found"],
            }
        ]
    )
    assert rows == [MissingInclude(name="op_kernel/platform_util.h", side="kernel")]


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


def test_find_nlohmann_json_under_3rdparty(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    leaf = tmp_path / "ops" / "3rdparty" / "include" / "nlohmann" / "json.hpp"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("// real json\n", encoding="utf-8")
    hit = find_include_dir(ctx, "nlohmann/json.hpp", side="host")
    assert hit is not None
    assert hit.include_dir.replace("\\", "/").endswith("3rdparty/include")


def test_parse_unknown_type_from_clang_spelling():
    from uo_init.include_heal import parse_unknown_types, SKIP_UNKNOWN_TYPES

    assert parse_unknown_types("unknown type name 'TCubeTiling'") == ["TCubeTiling"]
    assert parse_unknown_types("unknown type name 'SoftMaxTiling'") == ["SoftMaxTiling"]
    assert parse_unknown_types("unknown type name 'Dim3'") == []
    assert parse_unknown_types("unknown type name 'cce'") == []
    assert "Dim3" in SKIP_UNKNOWN_TYPES


def test_find_type_header_kernel_tiling(tmp_path: Path):
    from uo_init.include_heal import find_type_header

    reset_index_cache()
    ctx = _ctx(tmp_path)
    header = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "ascendc"
        / "include"
        / "highlevel_api"
        / "kernel_tiling"
        / "kernel_tiling.h"
    )
    header.parent.mkdir(parents=True)
    header.write_text(
        "namespace AscendC { namespace tiling { struct TCubeTiling { uint32_t M; }; } }\n"
        "using AscendC::tiling::TCubeTiling;\n"
        "using AscendC::tiling::SoftMaxTiling;\n"
        "struct SoftMaxTiling { uint32_t srcM; };\n",
        encoding="utf-8",
    )
    hit = find_type_header(ctx, "TCubeTiling", side="kernel")
    assert hit is not None
    assert hit.found.replace("\\", "/").endswith("kernel_tiling/kernel_tiling.h")
    # yaml already force-includes this path when the file exists.
    assert any(
        hit.found.replace("\\", "/").lower() in p.replace("\\", "/").lower()
        for p in ctx.kernel_force_includes()
    ) or ctx.add_force_include(hit.found, side="kernel")


def test_enrich_retries_unknown_cann_type(tmp_path: Path):
    from uo_init.include_heal import find_type_header

    reset_index_cache()
    ctx = _ctx(tmp_path)
    header = (
        tmp_path
        / "cann"
        / "cann-extra-sdk"
        / "x86_64-linux"
        / "include"
        / "extra_softmax_tiling.h"
    )
    header.parent.mkdir(parents=True)
    header.write_text(
        "struct SoftMaxTiling { uint32_t srcM = 0; };\n",
        encoding="utf-8",
    )
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
                        "side": "kernel",
                        "samples": ["unknown type name 'SoftMaxTiling'"],
                        "fatal_count": 0,
                    }
                ]
            )
        return _Enr([{"side": "kernel", "samples": [], "fatal_count": 0}])

    _enr, report = enrich_scope_with_heal(
        ctx=ctx,
        host_tus=[],
        kernel_tu=None,
        enrich_fn=_enrich,
    )
    assert calls["n"] >= 2
    assert report.unresolved == []
    extras = extras_summary_path(ctx.op_dir, ctx.arch_dir)
    assert extras.is_file()
    assert any(
        str(header).replace("\\", "/") in str(p).replace("\\", "/")
        for p in (ctx.extra_kernel_force_includes or [])
    )
    assert find_type_header(ctx, "SoftMaxTiling", side="kernel") is not None


def test_type_header_ambiguous_does_not_score_pick(tmp_path: Path):
    from uo_init.include_heal import INCLUDE_AMBIGUOUS, find_type_header, last_include_resolution

    reset_index_cache()
    ctx = _ctx(tmp_path, op_rel="attention/block_toy")
    cann = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "asc"
        / "impl"
        / "basic_api"
        / "utils"
        / "kernel_utils_ceil_oom_que.h"
    )
    cann.parent.mkdir(parents=True)
    cann.write_text("struct Tuple { int x; };\n", encoding="utf-8")
    local = tmp_path / "ops" / "attention" / "block_toy" / "op_kernel" / "tla" / "tuple.hpp"
    local.parent.mkdir(parents=True)
    local.write_text("namespace tla { struct Tuple {}; }\n", encoding="utf-8")
    hit = find_type_header(ctx, "Tuple", side="kernel")
    assert hit is None
    status, cands = last_include_resolution()
    assert status == INCLUDE_AMBIGUOUS
    assert len(cands) >= 2


def test_basename_ambiguous_does_not_score_pick(tmp_path: Path):
    reset_index_cache()
    ctx = _ctx(tmp_path)
    left = tmp_path / "ops" / "mc2" / "common" / "utils" / "shared.h"
    right = tmp_path / "ops" / "attention" / "common" / "utils" / "shared.h"
    left.parent.mkdir(parents=True)
    right.parent.mkdir(parents=True)
    left.write_text("// left\n", encoding="utf-8")
    right.write_text("// right\n", encoding="utf-8")
    hit = find_include_dir(ctx, "shared.h", side="host")
    assert hit is None
    from uo_init.include_heal import INCLUDE_AMBIGUOUS, last_include_resolution

    status, cands = last_include_resolution()
    assert status == INCLUDE_AMBIGUOUS
    assert len(cands) >= 2


def test_hcom_header_aliases_to_hccl_h():
    assert aliased_include_name("hccl/hcom.h") == "hccl/hccl.h"
    assert aliased_include_name("lib/matrix/matmul/foo.h") == "lib/matmul/foo.h"


def test_heal_promote_writes_extras_and_survives_clear(tmp_path: Path):
    ctx = _ctx(tmp_path)
    extra = tmp_path / "cann" / "extra_inc"
    extra.mkdir(parents=True)
    posix = str(extra).replace("\\", "/")
    out = promote_include_dirs(ctx, {"host": [posix], "kernel": []})
    assert out.get("ok") is True
    payload = load_extras_payload(ctx.op_dir, ctx.arch_dir)
    assert posix in [str(x).replace("\\", "/") for x in (payload.get("promoted_host") or [])]
    assert payload.get("source") == SOURCE_HEAL_PROMOTE

    script_dir = tmp_path / "cann" / "script_inc"
    script_dir.mkdir()
    ctx.add_include(str(script_dir), side="host")
    from uo_init.include_heal import HealReport, save_extras

    save_extras(ctx, HealReport(enabled=True))
    clear_saved_extras(ctx.op_dir, ctx.arch_dir, run_id="r1")
    kept = load_extras_payload(ctx.op_dir, ctx.arch_dir)
    promoted = [str(x).replace("\\", "/") for x in (kept.get("promoted_host") or kept.get("host") or [])]
    assert posix in promoted
    assert str(script_dir).replace("\\", "/") not in promoted

    loaded = BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path / "ops"),
        op_dir=ctx.op_dir,
        arch_dir=ctx.arch_dir,
        apply_saved_extras=True,
    )
    args = " ".join(loaded.host_args())
    assert posix in args.replace("\\", "/")


def test_heal_promote_rejects_outside_tree(tmp_path: Path):
    ctx = _ctx(tmp_path)
    outside = tmp_path / "not_cann"
    outside.mkdir()
    out = promote_include_dirs(ctx, {"host": [str(outside)]})
    assert out.get("ok") is False
    assert out.get("error") == "INCLUDE_HEAL_PROMOTE_REJECTED"
    assert not extras_summary_path(ctx.op_dir, ctx.arch_dir).is_file()


