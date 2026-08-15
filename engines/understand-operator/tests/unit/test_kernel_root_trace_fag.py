# -*- coding: utf-8 -*-
"""FAG arch35 Kernel Root Trace acceptance + timing gate."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_root_trace import finalize_kernel_root_trace
from uo_init.passes.kernel_tiling_closure import finalize_kernel_tiling_closure
from uo_init.passes.source_text_cache import clear as clear_source_text
from uo_init.semantics import registry as semreg

_TRACE_BUDGET_S = 45.0


@pytest.mark.requires_fag
def test_fag_arch35_kernel_root_trace_quality_and_timing(fag_dir: Path, arch_dir: str) -> None:
    """Root-trace on real FAG: AscendC roots reachable, no exec/pipeline."""
    semreg.load_registry.cache_clear()
    clear_source_text()

    cm = CodeMap(op_name=fag_dir.name, architecture=arch_dir)
    cm.upsert(
        EntityKind.KERNEL,
        "flash_attention_score_grad",
        attrs={"source_signature": True, "source_definition": True},
        file=f"op_kernel/{arch_dir}/flash_attention_score_grad_kernel.h",
    )

    t_closure = time.perf_counter()
    finalize_kernel_tiling_closure(cm, fag_dir, architecture=arch_dir)
    closure_s = time.perf_counter() - t_closure

    t_trace = time.perf_counter()
    finalize_kernel_root_trace(cm, fag_dir, architecture=arch_dir)
    trace_s = time.perf_counter() - t_trace

    meta = cm.meta.get("kernel_root_trace") or {}
    quality = meta.get("quality") or {}
    ops = cm.by_kind(EntityKind.OPERATION)
    bufs = cm.by_kind(EntityKind.BUFFER)
    callees = {e.name for e in ops}

    assert trace_s < _TRACE_BUDGET_S, f"kernel_root_trace took {trace_s:.2f}s meta={meta}"
    assert float(meta.get("elapsed_s") or trace_s) < _TRACE_BUDGET_S
    assert len(ops) >= 50, f"expected AscendC call sites on FAG, got {len(ops)}"
    assert "DataCopy" in callees
    assert any(n in callees for n in ("SetFlag", "WaitFlag", "CrossCoreSetFlag", "CrossCoreWaitFlag"))
    assert bufs, "expected BUFFER entities"

    reached_ops = [e for e in ops if e.attrs.get("root_status") == "REACHED"]
    reached_bufs = [e for e in bufs if e.attrs.get("root_status") == "REACHED"]
    assert reached_ops, "expected REACHED operations"
    assert reached_bufs, "expected REACHED buffers"

    rooted = [r for r in cm.relations.values() if r.kind_name() == RelationKind.ROOTED_AT.value]
    assert rooted, "expected ROOTED_AT edges to AscendC catalog"

    # Must NOT ship execution-analysis artifacts by default.
    assert "kernel_execution_pipeline" not in cm.meta
    forbidden = {
        "HAPPENS_BEFORE",
        "DATA_DEPENDS_ON",
        "READS_BUFFER",
        "WRITES_BUFFER",
        "WAITS_ON",
        "SYNCHRONIZES_WITH",
        "EXECUTES_ON",
        "EMITS_SYNC",
    }
    assert not any(r.kind_name() in forbidden for r in cm.relations.values())

    assert isinstance(quality, dict) and int(quality.get("operations") or 0) > 0
    assert "gap_count" in meta

    # MutexBuffer is a wrapper TYPE → AscendC::LocalTensor (+ sync ops), not a BUFFER kind.
    mutex_types = [
        e
        for e in cm.by_kind(EntityKind.TYPE)
        if e.name == "MutexBuffer" and e.attrs.get("role") == "storage_wrapper_type"
    ]
    if mutex_types:
        assert any(t.attrs.get("root_status") == "REACHED" for t in mutex_types)
        assert any("LocalTensor" in str(t.attrs.get("root") or "") for t in mutex_types)
    mutex_sites = [
        b
        for b in bufs
        if b.attrs.get("wrapper") == "MutexBuffer"
        or ("MutexBuffer" in str(b.attrs.get("trace") or []) and b.attrs.get("role") == "storage_wrapper")
    ]
    if mutex_sites:
        assert any(b.attrs.get("root_status") == "REACHED" for b in mutex_sites)
        assert all("LocalTensor" in str(b.attrs.get("root") or "") for b in mutex_sites if b.attrs.get("root_status") == "REACHED")
        assert not any(b.attrs.get("root", "").endswith("MutexBuffer") for b in mutex_sites)

    print(
        f"\n[FAG root-trace] closure={closure_s:.2f}s trace={trace_s:.2f}s "
        f"ops={len(ops)} reached_ops={len(reached_ops)} buf={len(bufs)} "
        f"reached_buf={len(reached_bufs)} rooted={len(rooted)} "
        f"gaps={meta.get('gap_count')} gap_counts={meta.get('gap_counts')} "
        f"files={meta.get('selected_files')}"
    )


@pytest.mark.requires_fag
def test_fag_arch35_kernel_root_trace_delta_vs_disabled(
    fag_dir: Path, arch_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    semreg.load_registry.cache_clear()
    clear_source_text()

    def _seed() -> CodeMap:
        cm = CodeMap(op_name=fag_dir.name, architecture=arch_dir)
        cm.upsert(
            EntityKind.KERNEL,
            "flash_attention_score_grad",
            attrs={"source_signature": True, "source_definition": True},
            file=f"op_kernel/{arch_dir}/flash_attention_score_grad_kernel.h",
        )
        finalize_kernel_tiling_closure(cm, fag_dir, architecture=arch_dir)
        return cm

    monkeypatch.setenv("UO_KERNEL_ROOT_TRACE", "0")
    cm0 = _seed()
    t0 = time.perf_counter()
    finalize_kernel_root_trace(cm0, fag_dir, architecture=arch_dir)
    off_s = time.perf_counter() - t0

    monkeypatch.setenv("UO_KERNEL_ROOT_TRACE", "1")
    monkeypatch.setenv("UO_KERNEL_ROOT_TRACE_BUDGET_S", "25")
    cm1 = _seed()
    t1 = time.perf_counter()
    finalize_kernel_root_trace(cm1, fag_dir, architecture=arch_dir)
    on_s = time.perf_counter() - t1
    delta = on_s - off_s
    assert delta < _TRACE_BUDGET_S, f"root-trace delta {delta:.2f}s exceeds budget"
    print(f"\n[FAG root-trace delta] off={off_s:.3f}s on={on_s:.3f}s delta={delta:.3f}s")
