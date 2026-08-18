# -*- coding: utf-8 -*-
"""ProcessPool multi-TU host_ir walks."""
from __future__ import annotations

from pathlib import Path

import pytest

from uo_init.build_context import BuildContext
from uo_init.clang_walk import WalkResult
from uo_init.host_ir import _host_ir_pool_kind, _walk_tu_payload, _walk_tu_worker, build_host_ir


def test_host_ir_pool_defaults_to_thread_on_windows(monkeypatch):
    monkeypatch.delenv("UO_HOST_IR_POOL", raising=False)
    monkeypatch.setattr("os.name", "nt")
    assert _host_ir_pool_kind() == "thread"
    monkeypatch.setenv("UO_HOST_IR_POOL", "process")
    assert _host_ir_pool_kind() == "process"
    monkeypatch.setenv("UO_HOST_IR_POOL", "thread")
    monkeypatch.setattr("os.name", "posix")
    assert _host_ir_pool_kind() == "thread"


def test_build_context_roundtrip_for_worker():
    ctx = BuildContext(
        raw={"base_flags": ["-std=c++17"], "std": "c++17", "target": "aarch64-linux-gnu"},
        cann_root="/cann",
        ops_root="/ops",
        compat_root="/compat",
        op_dir="/op",
        arch_dir="arch35",
        repo_root="/repo",
    )
    restored = BuildContext.from_dict(ctx.to_dict())
    assert restored.cann_root == ctx.cann_root
    assert restored.op_dir == ctx.op_dir
    assert restored.arch_dir == ctx.arch_dir


def test_walk_tu_payload_shape(tmp_path: Path):
    p = tmp_path / "a.cpp"
    p.write_text("void f() {}\n", encoding="utf-8")
    ctx = BuildContext.from_dict(
        {
            "raw": {},
            "cann_root": "/cann",
            "ops_root": "/ops",
            "compat_root": "/compat",
            "op_dir": str(tmp_path),
            "arch_dir": "arch35",
            "repo_root": "/repo",
        }
    )
    payload = _walk_tu_payload(
        p,
        ctx,
        side="host",
        op_needle="op",
        scope=None,
        logs_rejections=False,
    )
    assert payload["path"] == str(p)
    assert payload["ctx"]["op_dir"] == str(tmp_path)


def test_process_pool_falls_back_to_thread_pool(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UO_HOST_IR_POOL", "process")
    monkeypatch.setenv("UO_TU_CACHE", "0")

    p1 = tmp_path / "one.cpp"
    p2 = tmp_path / "two.cpp"
    p1.write_text("void one() {}\n", encoding="utf-8")
    p2.write_text("void two() {}\n", encoding="utf-8")

    def _fake(path, ctx, **kwargs):
        return WalkResult(path=str(path).replace("\\", "/"))

    monkeypatch.setattr("uo_init.clang_walk.walk_file", _fake)

    class _BrokenProcessPool:
        def __init__(self, *args, **kwargs):
            raise OSError("process pool unavailable in test")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, *args, **kwargs):
            raise OSError("process pool unavailable in test")

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _BrokenProcessPool)

    ctx = BuildContext.from_dict(
        {
            "raw": {},
            "cann_root": "/cann",
            "ops_root": "/ops",
            "compat_root": "/compat",
            "op_dir": str(tmp_path),
            "arch_dir": "arch35",
            "repo_root": "/repo",
        }
    )
    ir = build_host_ir([p1, p2], ctx=ctx, side="host")
    assert ir.backend == "clang"
    assert len(ir.summaries) >= 0


@pytest.mark.requires_cann
def test_process_pool_two_tus(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UO_HOST_IR_POOL", "process")
    monkeypatch.setenv("UO_TU_CACHE", "0")
    p1 = tmp_path / "one.cpp"
    p2 = tmp_path / "two.cpp"
    p1.write_text("void one() { int x = 1; }\n", encoding="utf-8")
    p2.write_text("void two() { int y = 2; }\n", encoding="utf-8")
    ctx = BuildContext.from_dict(
        {
            "raw": {"base_flags": ["-std=c++17"], "std": "c++17"},
            "cann_root": "/cann",
            "ops_root": "/ops",
            "compat_root": "/compat",
            "op_dir": str(tmp_path),
            "arch_dir": "arch35",
            "repo_root": str(tmp_path),
        }
    )
    ir = build_host_ir([p1, p2], ctx=ctx, side="host", op_needle="")
    assert ir.backend == "clang"


def test_walk_tu_worker_invokes_walk(monkeypatch, tmp_path: Path):
    p = tmp_path / "w.cpp"
    p.write_text("void w() {}\n", encoding="utf-8")
    seen = {}

    def _fake(path, ctx, **kwargs):
        seen["path"] = str(path)
        return WalkResult(path=str(path).replace("\\", "/"))

    monkeypatch.setattr("uo_init.clang_walk.walk_file", _fake)
    payload = _walk_tu_payload(
        p,
        BuildContext.from_dict(
            {
                "raw": {},
                "cann_root": "",
                "ops_root": "",
                "compat_root": "",
                "op_dir": str(tmp_path),
                "arch_dir": "arch35",
                "repo_root": "",
            }
        ),
        side="host",
        op_needle="",
        scope=None,
        logs_rejections=False,
    )
    res = _walk_tu_worker(payload)
    assert seen["path"] == str(p)
    assert res.path.replace("\\", "/").endswith("w.cpp")
