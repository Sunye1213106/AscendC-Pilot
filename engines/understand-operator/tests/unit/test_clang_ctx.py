# -*- coding: utf-8 -*-
import pytest

from uo_init.build_context import BuildContext


def test_host_args_contain_no_operator_impl():
    ctx = BuildContext.load(cann_root="D:/c", ops_root="D:/o", op_dir="D:/o/fag")
    args = " ".join(ctx.host_args())
    assert "NO_OPERATOR_IMPL" in args


def test_kernel_args_erase_aicore():
    ctx = BuildContext.load(cann_root="D:/c", ops_root="D:/o", op_dir="D:/o/fag")
    args = ctx.kernel_args()
    assert any(a == "-D__aicore__=" or a.startswith("-D__aicore__") for a in args)


def test_dtype_variant_injects_macro():
    ctx = BuildContext.load(cann_root="D:/c", ops_root="D:/o", op_dir="D:/o/fag")
    for dt in ("DT_FLOAT16", "DT_FLOAT", "DT_BF16"):
        joined = " ".join(ctx.kernel_args(dtype_variant=dt))
        assert f"ORIG_DTYPE_QUERY={dt}" in joined


@pytest.mark.requires_cann
def test_host_four_tus_zero_diag(fag_dir, cann_root, ops_root):
    from uo_init.clang_tu import parse_path

    ctx = BuildContext.load(
        cann_root=str(cann_root),
        ops_root=str(ops_root),
        op_dir=str(fag_dir),
        arch_dir="arch35",
    )
    files = [
        fag_dir / "op_host" / "flash_attention_score_grad_def.cpp",
        fag_dir / "op_host" / "flash_attention_score_grad_tiling.cpp",
        fag_dir / "op_host" / "arch35" / "flash_attention_score_grad_tiling_normal_regbase.cpp",
        fag_dir / "op_host" / "arch35" / "flash_attention_score_grad_tiling_common_regbase.cpp",
    ]
    for f in files:
        res = parse_path(str(f), ctx.host_args())
        assert res.error_count == 0, (f, res.diagnostics[:3])


@pytest.mark.requires_cann
def test_host_nested_writes_nonzero(fag_dir, cann_root, ops_root):
    from uo_init.clang_tu import analyze_host

    ctx = BuildContext.load(
        cann_root=str(cann_root),
        ops_root=str(ops_root),
        op_dir=str(fag_dir),
        arch_dir="arch35",
    )
    path = fag_dir / "op_host" / "arch35" / "flash_attention_score_grad_tiling_normal_regbase.cpp"
    res = analyze_host(str(path), ctx, "flash_attention")
    assert len(res.nested_writes) >= 1
    blob = " ".join(res.nested_writes)
    assert "isNzOut" in blob or "splitAxis" in blob


@pytest.mark.requires_cann
def test_kernel_fag_zero_diag(fag_dir, cann_root, ops_root):
    from uo_init.clang_tu import analyze_kernel

    ctx = BuildContext.load(
        cann_root=str(cann_root),
        ops_root=str(ops_root),
        op_dir=str(fag_dir),
        arch_dir="arch35",
    )
    apt = fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"
    res = analyze_kernel(str(apt), ctx, "flash_attention")
    # Residual errors live in CANN AscendC impl headers; FAG *sources* must be clean.
    fag_errs = [
        (sev, fn, sp)
        for sev, fn, sp in res.diagnostics
        if sev >= 3 and "flash_attention_score_grad" in fn.replace("\\", "/")
        and "/_cann/" not in fn.replace("\\", "/")
        and "cann-asc-devkit" not in fn.replace("\\", "/")
    ]
    assert fag_errs == []


@pytest.mark.requires_cann
def test_kernel_fag_ast_keeps_entry_templates_and_branches(
    fag_dir, cann_root, ops_root
):
    from clang import cindex

    from uo_init.clang_tu import analyze_kernel

    ctx = BuildContext.load(
        cann_root=str(cann_root),
        ops_root=str(ops_root),
        op_dir=str(fag_dir),
        arch_dir="arch35",
    )
    apt = fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"
    res = analyze_kernel(str(apt), ctx, "flash_attention")

    structural = []
    for node in res.tu.cursor.walk_preorder():
        source_file = node.location.file
        if source_file is None:
            continue
        source_path = source_file.name.replace("\\", "/")
        if "flash_attention_score_grad" not in source_path:
            continue
        if node.kind in {
            cindex.CursorKind.FUNCTION_TEMPLATE,
            cindex.CursorKind.CLASS_TEMPLATE,
        }:
            structural.append(
                (node.kind, node.spelling, source_path, node.location.line)
            )

    assert any(
        kind == cindex.CursorKind.FUNCTION_TEMPLATE
        and name == "flash_attention_score_grad"
        and path.endswith("/op_kernel/flash_attention_score_grad_apt.cpp")
        and line == 39
        for kind, name, path, line in structural
    )
    assert any(kind == cindex.CursorKind.CLASS_TEMPLATE for kind, *_ in structural)
    assert any(kind == cindex.CursorKind.FUNCTION_TEMPLATE for kind, *_ in structural)
    assert res.branches.get("IF_STMT", 0) > 0
