# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from uo_init.build_context import BuildContext
from uo_init.kernel_ir import (
    KernelIR,
    _kernel_ir_worker,
    kernel_ir_isolate,
    kernel_ir_payload,
)


def test_kernel_ir_isolate_defaults_to_process_on_windows(monkeypatch):
    monkeypatch.delenv("UO_KERNEL_IR_ISOLATE", raising=False)
    monkeypatch.setattr("os.name", "nt")
    assert kernel_ir_isolate() is True
    monkeypatch.setenv("UO_KERNEL_IR_ISOLATE", "thread")
    assert kernel_ir_isolate() is False
    monkeypatch.setenv("UO_KERNEL_IR_ISOLATE", "process")
    monkeypatch.setattr("os.name", "posix")
    assert kernel_ir_isolate() is True


def test_kernel_ir_isolate_defaults_to_thread_on_posix(monkeypatch):
    monkeypatch.delenv("UO_KERNEL_IR_ISOLATE", raising=False)
    monkeypatch.setattr("os.name", "posix")
    assert kernel_ir_isolate() is False


def test_kernel_ir_payload_and_worker_roundtrip(monkeypatch, tmp_path: Path):
    ctx = BuildContext.from_dict(
        {
            "raw": {},
            "cann_root": "/cann",
            "ops_root": "/ops",
            "compat_root": "/compat",
            "op_dir": str(tmp_path),
            "arch_dir": "arch35",
            "repo_root": str(tmp_path),
        }
    )
    spec = SimpleNamespace(
        kernel_targets=[tmp_path / "k.cpp"],
        kernel_entry=tmp_path / "k.cpp",
        op_needle="flash_attention_score",
        scope=None,
        op_dir=tmp_path,
        arch_dir="arch35",
    )
    payload = kernel_ir_payload(spec, ctx, dimensions=["D0"], max_variants=1)
    assert payload["spec"]["op_needle"] == "flash_attention_score"
    assert payload["dimensions"] == ["D0"]

    seen = {}

    def _fake(spec_obj, ctx_obj, *, dimensions=None, max_variants=None):
        seen["needle"] = spec_obj.op_needle
        seen["dims"] = list(dimensions or [])
        seen["max"] = max_variants
        seen["op_dir"] = str(ctx_obj.op_dir)
        return KernelIR(notes=["fake"])

    monkeypatch.setattr("uo_init.kernel_ir.build_kernel_ir", _fake)
    ir = _kernel_ir_worker(payload)
    assert ir.notes == ["fake"]
    assert seen["needle"] == "flash_attention_score"
    assert seen["dims"] == ["D0"]
    assert seen["max"] == 1
    assert seen["op_dir"] == str(tmp_path)


def test_kernel_ir_job_subprocess_unpickles_as_package_class(tmp_path: Path):
    """Child must pickle KernelIR as uo_init.kernel_ir.KernelIR, not __main__."""
    from uo_init.kernel_ir import finish_kernel_ir_job, start_kernel_ir_job

    src = tmp_path / "k.cpp"
    src.write_text("void f() {}\n", encoding="utf-8")
    ctx = BuildContext.from_dict(
        {
            "raw": {"base_flags": ["-std=c++17"], "std": "c++17"},
            "cann_root": "",
            "ops_root": "",
            "compat_root": "",
            "op_dir": str(tmp_path),
            "arch_dir": "arch35",
            "repo_root": str(tmp_path),
        }
    )
    spec = SimpleNamespace(
        kernel_targets=[src],
        kernel_entry=src,
        op_needle="",
        scope=None,
        op_dir=tmp_path,
        arch_dir="arch35",
    )
    payload = kernel_ir_payload(spec, ctx, dimensions=[], max_variants=1)
    job = start_kernel_ir_job(payload)
    ir = finish_kernel_ir_job(*job)
    assert isinstance(ir, KernelIR)
    assert ir.__class__.__module__ == "uo_init.kernel_ir"
