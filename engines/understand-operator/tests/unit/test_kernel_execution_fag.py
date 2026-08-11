# -*- coding: utf-8 -*-
"""FAG arch35 Kernel Execution acceptance + timing gate."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_data_deps import finalize_kernel_data_deps
from uo_init.passes.kernel_execution import finalize_kernel_execution
from uo_init.passes.kernel_pipeline import finalize_kernel_pipeline
from uo_init.passes.kernel_tiling_closure import finalize_kernel_tiling_closure
from uo_init.passes.source_text_cache import clear as clear_source_text
from uo_init.query.engine import CodeMapQuery
from uo_init.semantics import registry as semreg

# Hard gate from product requirement: Kernel Execution addition < 30s.
_EXEC_BUDGET_S = 30.0


@pytest.mark.requires_fag
def test_fag_arch35_kernel_execution_quality_and_timing(fag_dir: Path, arch_dir: str) -> None:
    """Run closure + execution on real FAG arch35; assert coverage and budget."""
    semreg.load_registry.cache_clear()
    clear_source_text()

    cm = CodeMap(op_name=fag_dir.name, architecture=arch_dir)
    # Minimal KERNEL seed so closure can attach selected-arch scopes.
    cm.upsert(
        EntityKind.KERNEL,
        "flash_attention_score_grad",
        attrs={"source_signature": True, "source_definition": True},
        file=f"op_kernel/{arch_dir}/flash_attention_score_grad_kernel.h",
    )

    t_closure = time.perf_counter()
    finalize_kernel_tiling_closure(cm, fag_dir, architecture=arch_dir)
    closure_s = time.perf_counter() - t_closure

    t_exec = time.perf_counter()
    finalize_kernel_execution(cm, fag_dir, architecture=arch_dir)
    finalize_kernel_data_deps(cm)
    exec_s = time.perf_counter() - t_exec
    finalize_kernel_pipeline(cm)

    meta = cm.meta.get("kernel_execution") or {}
    quality = meta.get("quality") or {}
    ops = cm.by_kind(EntityKind.OPERATION)
    syncs = cm.by_kind(EntityKind.SYNC_EVENT)
    bufs = cm.by_kind(EntityKind.BUFFER)
    callees = {e.name for e in ops}

    assert exec_s < _EXEC_BUDGET_S, (
        f"kernel_execution took {exec_s:.2f}s (budget {_EXEC_BUDGET_S}s); "
        f"meta={meta}"
    )
    assert float(meta.get("elapsed_s") or exec_s) < _EXEC_BUDGET_S
    assert len(ops) >= 50, f"expected rich operation set on FAG, got {len(ops)}"
    assert "DataCopy" in callees, f"missing DataCopy in {sorted(callees)[:20]}"
    assert any(n in callees for n in ("SetFlag", "WaitFlag", "CrossCoreSetFlag", "CrossCoreWaitFlag")), (
        f"missing sync primitives in {sorted(callees)[:30]}"
    )
    assert syncs, "expected SYNC_EVENT entities on FAG"
    assert bufs, "expected BUFFER entities on FAG"

    # Quality report fields must exist and be positive.
    assert isinstance(quality, dict) and quality, f"missing quality report: {meta}"
    assert int(quality.get("ops") or 0) > 0
    assert int(quality.get("buffers") or 0) > 0
    assert int(quality.get("sync_events") or 0) > 0
    assert int(meta.get("data_deps_total") or quality.get("data_deps_total") or 0) >= 0

    precedes = [r for r in cm.relations.values() if r.kind_name() == RelationKind.PRECEDES.value]
    assert precedes, "program-order PRECEDES required"
    emits = [r for r in cm.relations.values() if r.kind_name() == RelationKind.EMITS_SYNC.value]
    assert emits, "EMITS_SYNC links required when sync events exist"

    pipe = cm.meta.get("kernel_execution_pipeline") or {}
    assert int(pipe.get("operation_count") or 0) >= 50
    assert pipe.get("authority") == "derived"

    q = CodeMapQuery(codemap=cm)
    overview = q.kernel_overview()
    assert overview["operations"] == len(ops)
    assert isinstance(q.kernel_pipeline(), dict)

    # Timing print for manual inspection (pytest -s). Do not commit FAG logs.
    print(
        f"\n[FAG arch35] closure={closure_s:.2f}s exec={exec_s:.2f}s "
        f"ops={len(ops)} sync={len(syncs)} buf={len(bufs)} "
        f"paired={meta.get('sync_paired')} deps={meta.get('data_deps_total')} "
        f"quality={quality} files={meta.get('selected_files')}"
    )


@pytest.mark.requires_fag
def test_fag_arch35_kernel_execution_delta_vs_disabled(fag_dir: Path, arch_dir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabling Kernel Execution must not add more than 30s over disabled path."""
    semreg.load_registry.cache_clear()
    clear_source_text()

    def _seed() -> CodeMap:
        cm = CodeMap(op_name=fag_dir.name, architecture=arch_dir)
        cm.upsert(
            EntityKind.KERNEL,
            "flash_attention_score_grad",
            attrs={"source_signature": True, "source_definition": True},
        )
        finalize_kernel_tiling_closure(cm, fag_dir, architecture=arch_dir)
        return cm

    cm0 = _seed()
    monkeypatch.setenv("UO_KERNEL_EXEC", "0")
    t0 = time.perf_counter()
    finalize_kernel_execution(cm0, fag_dir, architecture=arch_dir)
    off_s = time.perf_counter() - t0
    assert cm0.meta.get("kernel_execution", {}).get("skipped") is True

    clear_source_text()
    cm1 = _seed()
    monkeypatch.setenv("UO_KERNEL_EXEC", "1")
    monkeypatch.setenv("UO_KERNEL_EXEC_BUDGET_S", "25")
    t1 = time.perf_counter()
    finalize_kernel_execution(cm1, fag_dir, architecture=arch_dir)
    on_s = time.perf_counter() - t1
    delta = on_s - off_s
    assert delta < _EXEC_BUDGET_S, f"delta {delta:.2f}s exceeds {_EXEC_BUDGET_S}s (on={on_s:.2f} off={off_s:.2f})"
    assert len(cm1.by_kind(EntityKind.OPERATION)) >= 50
    print(f"\n[FAG timing delta] off={off_s:.3f}s on={on_s:.3f}s delta={delta:.3f}s")
