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

_TRACE_BUDGET_S = 32.0


@pytest.mark.requires_fag
def test_fag_arch35_kernel_root_trace_quality_and_timing(
    fag_dir: Path, arch_dir: str, tmp_path: Path
) -> None:
    """Root-trace on real FAG: AscendC roots reachable, no exec/pipeline."""
    semreg.load_registry.cache_clear()
    clear_source_text()
    try:
        from uo_init.source_index import reset_index_cache

        reset_index_cache()
    except Exception:
        pass

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
    assert meta.get("gated_fill_complete") is not False
    assert len(ops) >= 50, f"expected AscendC call sites on FAG, got {len(ops)}"
    assert "DataCopy" in callees
    assert "LoadAlign" in callees
    assert "CreateMask" in callees
    assert all(
        e.attrs.get("root_status") == "REACHED"
        for e in ops
        if e.name in {"LoadAlign", "CreateMask"}
    )
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

    # MutexBuffer identity is source composition: WRAPS LocalTensor + CALLS Lock.
    mutex_types = [e for e in cm.by_kind(EntityKind.TYPE) if e.name == "MutexBuffer"]
    assert mutex_types, "expected MutexBuffer TYPE from FAG source"
    assert any(t.attrs.get("wraps_storage") for t in mutex_types)
    assert any(t.attrs.get("wraps_lock") for t in mutex_types)
    assert any(
        "LocalTensor" in str(t.attrs.get("root") or "") or t.attrs.get("wraps_storage")
        for t in mutex_types
    )
    mutex_sites = [
        b
        for b in bufs
        if b.attrs.get("wrapper") == "MutexBuffer"
        or "MutexBuffer" in str(b.attrs.get("type_name") or "")
    ]
    if mutex_sites:
        assert any(b.attrs.get("root_status") == "REACHED" for b in mutex_sites)
        assert not any(str(b.attrs.get("root") or "").endswith("MutexBuffer") for b in mutex_sites)

    assert not any(
        e.name == "LockProd" and e.attrs.get("root_status") == "REACHED" for e in ops
    )
    assert any(n in callees for n in ("Lock", "Unlock", "AllocMutexID", "SetFlag", "WaitFlag"))
    pipes = [e for e in cm.by_kind(EntityKind.PIPE) if e.attrs.get("catalog") != "ascendc"]
    assert len(pipes) >= 3, f"expected >=3 TPipe instances, got {len(pipes)}"
    binds = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value
        and str(r.attrs.get("via") or "") == "InitBuffer"
    ]
    assert binds, "expected PIPE --BINDS--> buffer via InitBuffer"

    from uo_init.store.writer import write_codemap
    from uo_init.uo_query import open_query

    product = tmp_path / ".ascendc-pilot" / arch_dir / "uo" / f"{fag_dir.name}.{arch_dir}.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path, architecture=arch_dir)
    launch = q.aggregate_kernel_launch()
    assert int(launch.get("count") or 0) >= 3
    lock = q.aggregate_kernel_api("Lock")
    assert int(lock.get("count") or 0) >= 1
    lock_names = {str(row.get("name") or "") for row in lock.get("calls") or []}
    assert "LockProd" not in lock_names
    assert any(n in lock_names for n in ("Lock", "Unlock"))
    flags = q.aggregate_kernel_api("SetFlag")
    waits = q.aggregate_kernel_api("WaitFlag")
    assert int(flags.get("count") or 0) >= 1 or int(waits.get("count") or 0) >= 1
    prod = q.aggregate_kernel_api("LockProd")
    assert not any(str(row.get("name") or "") == "LockProd" for row in prod.get("calls") or [])

    print(
        f"\n[FAG root-trace] closure={closure_s:.2f}s trace={trace_s:.2f}s "
        f"ops={len(ops)} reached_ops={len(reached_ops)} buf={len(bufs)} "
        f"reached_buf={len(reached_bufs)} rooted={len(rooted)} "
        f"gaps={meta.get('gap_count')} gap_counts={meta.get('gap_counts')} "
        f"files={meta.get('selected_files')}"
    )

    from uo_init.store.writer import write_codemap
    from uo_init.uo_query import open_query

    product = tmp_path / ".ascendc-pilot" / arch_dir / "uo" / f"{fag_dir.name}.{arch_dir}.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path, architecture=arch_dir)
    launch = q.aggregate_kernel_launch()
    assert int(launch.get("count") or 0) >= 3
    lock = q.aggregate_kernel_api("Lock")
    assert int(lock.get("count") or 0) >= 1
    lock_names = {str(row.get("name") or "") for row in (lock.get("calls") or [])}
    assert "LockProd" not in lock_names
    flags = q.aggregate_kernel_api("SetFlag")
    waits = q.aggregate_kernel_api("WaitFlag")
    assert int(flags.get("count") or 0) >= 1 or int(waits.get("count") or 0) >= 1
    buf_hits = q.aggregate_buffer("MutexBuffer")
    assert int(buf_hits.get("count") or 0) >= 1
