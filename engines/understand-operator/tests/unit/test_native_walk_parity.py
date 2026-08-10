# -*- coding: utf-8 -*-
"""Native uo_walk vs Python walk_file parity (optional binary)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from uo_init.build_context import BuildContext
from uo_init.clang_walk import _native_walk_bin, walk_file


class _FakeCtx:
    cann_root = "D:/cann"
    ops_root = "D:/ops"
    compat_root = "D:/compat"
    op_dir = ""
    arch_dir = "arch35"

    def host_args(self):
        return ["-std=c++17", "-I", "D:/cann/include"]

    def kernel_args(self, dtype_variant=None):
        return ["-std=c++17"]


@pytest.fixture
def toy_source(tmp_path: Path) -> Path:
    src = tmp_path / "toy.cpp"
    src.write_text(
        "\n".join(
            [
                "struct C {",
                "  int f(int x) {",
                "    if (x > 0) { g(x); }",
                "    return x;",
                "  }",
                "  void g(int y) { y = y + 1; }",
                "};",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return src


def test_native_walk_bin_missing_is_none():
    old = os.environ.pop("UO_WALK_BIN", None)
    try:
        os.environ["UO_WALK_BIN"] = str(Path("/nonexistent/uo_walk"))
        assert _native_walk_bin() is None
    finally:
        if old is None:
            os.environ.pop("UO_WALK_BIN", None)
        else:
            os.environ["UO_WALK_BIN"] = old


@pytest.mark.requires_cann
def test_uo_native_walk_zero_uses_python(toy_source: Path, monkeypatch):
    monkeypatch.setenv("UO_NATIVE_WALK", "0")
    ctx = _FakeCtx()
    ctx.op_dir = str(toy_source.parent)
    py = walk_file(toy_source, ctx, side="host", op_needle="toy")
    assert py.path.replace("\\", "/").endswith("toy.cpp")
    assert isinstance(py.functions, dict)


@pytest.mark.requires_cann
def test_native_vs_python_parity_when_binary_present(toy_source: Path, monkeypatch):
    exe = _native_walk_bin()
    if exe is None:
        pytest.skip("uo_walk binary not built")
    monkeypatch.setenv("UO_NATIVE_WALK", "1")
    monkeypatch.setenv("UO_WALK_BIN", str(exe))
    ctx = _FakeCtx()
    ctx.op_dir = str(toy_source.parent)
    native = walk_file(toy_source, ctx, side="host", op_needle="toy")
    monkeypatch.setenv("UO_NATIVE_WALK", "0")
    python = walk_file(toy_source, ctx, side="host", op_needle="toy")
    assert native.path == python.path
    native_fn = set(native.functions.keys())
    python_fn = set(python.functions.keys())
    overlap = native_fn & python_fn
    assert overlap, "expected overlapping function names"
    assert len(overlap) >= max(1, int(0.5 * len(python_fn)))
    assert abs(len(native.call_sites) - len(python.call_sites)) <= max(
        2, int(0.25 * max(len(python.call_sites), 1))
    )
