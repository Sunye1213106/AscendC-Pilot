# -*- coding: utf-8 -*-
from pathlib import Path

from uo_init.bisheng_attrs import (
    has_bisheng_bracket_attrs,
    kernel_unsaved_files,
    reset_unsaved_cache,
    strip_bisheng_bracket_attrs,
)


def test_strip_spaced_host_aicore_brackets():
    src = "#define HOST_DEVICE __forceinline__ [host, aicore]\n"
    out = strip_bisheng_bracket_attrs(src)
    assert "[host" not in out
    assert "aicore]" not in out
    assert "__forceinline__" in out
    assert not has_bisheng_bracket_attrs(out)


def test_strip_attached_aicore_brackets():
    src = "#define HOST_DEVICE __forceinline__[aicore]\n"
    out = strip_bisheng_bracket_attrs(src)
    assert "[aicore]" not in out
    assert "__forceinline__" in out


def test_kernel_unsaved_files_rewrites_operator_macro(tmp_path: Path):
    reset_unsaved_cache()
    header = tmp_path / "op_kernel" / "attn_infra" / "detail" / "macros.hpp"
    header.parent.mkdir(parents=True)
    header.write_text(
        "#define HOST_DEVICE __forceinline__ [host, aicore]\n",
        encoding="utf-8",
    )
    (tmp_path / "op_kernel" / "clean.h").write_text("struct Clean {};\n", encoding="utf-8")
    pairs = kernel_unsaved_files(tmp_path)
    assert pairs
    assert any("HOST_DEVICE" in body and "[host" not in body for _path, body in pairs)
    assert not any("clean.h" in path.replace("\\", "/") for path, _body in pairs)
    reset_unsaved_cache()
