"""Closure fast path reads closure_summary and defers integrity."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.fast_uo_engines import _fast_recheck_closure


def test_closure_fast_path_uses_summary(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "op"
    project.mkdir()
    uo = project / ".ascendc-pilot" / "uo"
    ir = uo / "ir"
    ir.mkdir(parents=True)
    (uo / "manifest.yaml").write_text("op_name: DemoOp\ncurrent_run_id: run-1\n", encoding="utf-8")
    (ir / "entrypoint_graph.yaml").write_text(
        "closure:\n  host_main_chain: closed\n  kernel_main_chain: closed\n",
        encoding="utf-8",
    )
    (ir / "llm_tasks.yaml").write_text("tasks: []\n", encoding="utf-8")
    (ir / "semantic_resolution_ledger.yaml").write_text("semantic_patches: []\n", encoding="utf-8")
    (ir / "semantic_apply_report.yaml").write_text("applied: []\n", encoding="utf-8")
    (ir / "semantic_task_triage.yaml").write_text("stats: {}\n", encoding="utf-8")

    # seed summary cache
    from uo.scripts._ir_io import write_yaml

    write_yaml(
        ir / "closure_summary.yaml",
        {
            "version": 1,
            "input_fingerprint": "fp",
            "result": {
                "ok": True,
                "engine": "recheck_closure",
                "closure": {"host_main_chain": "closed", "kernel_main_chain": "closed"},
                "blocking_gap_count": 0,
                "unconsumed_patch_count": 0,
            },
        },
    )

    calls: list[str] = []

    def fail_integrity(*a, **k):  # type: ignore[no-untyped-def]
        calls.append("integrity")
        raise AssertionError("integrity should not run in fast path cache hit")

    monkeypatch.setattr("uo.scripts.llm_tasks.compute_semantic_stats", lambda *a, **k: {"blocking_gap_count": 0, "unconsumed_patch_count": 0})

    def fallback(*a, **k):  # type: ignore[no-untyped-def]
        calls.append("fallback")
        return {"ok": False, "engine": "recheck_closure"}

    # Force fingerprint match by patching _stat_fingerprint
    monkeypatch.setattr("ascendc_pilot.actions.fast_uo_engines._stat_fingerprint", lambda *a, **k: "fp")

    out = _fast_recheck_closure(
        project,
        {"run_id": "run-1"},
        fallback=fallback,
        workflow_id="uo-init",
        action_id="recheck_closure",
    )
    assert out.get("cache_hit") is True
    assert out.get("ok") is True
    assert "integrity" not in calls
