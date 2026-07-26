from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.fast_uo_engines import invoke_fast_uo_engine


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_zero_delta_rebuild_short_circuits_canonical_engine(tmp_path, monkeypatch) -> None:
    uo = tmp_path / ".ascendc-pilot" / "uo"
    _dump(uo / "manifest.yaml", {"op_name": "demo", "architecture": "arch35"})
    _dump(
        uo / "ir" / "entrypoint_graph.yaml",
        {"nodes": [], "edges": [], "closure": {"host_main_chain": "closed", "kernel_main_chain": "closed"}},
    )
    _dump(uo / "ir" / "operator_graph.yaml", {"nodes": [{"id": "n"}], "edges": []})

    import uo.scripts.evidence_score as evidence_score
    import uo.scripts.llm_tasks as llm_tasks
    import uo.scripts.semantic_resolution_ledger as ledger

    monkeypatch.setattr(evidence_score, "_source_snapshot_hash", lambda *_a, **_k: "snap")
    monkeypatch.setattr(
        ledger,
        "should_skip_layered_rebuild",
        lambda *_a, **_k: {
            "skip": True,
            "materializable_delta_count": 0,
            "rebuild_input_fingerprint": {"fingerprint": "fp"},
        },
    )
    monkeypatch.setattr(
        llm_tasks,
        "compute_semantic_stats",
        lambda *_a, **_k: {"blocking_gap_count": 0, "unconsumed_patch_count": 0},
    )

    called = False

    def fallback(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"ok": False}

    out = invoke_fast_uo_engine(
        tmp_path,
        "uo-init",
        "rebuild_from_ledger",
        ctx={"run_id": "RUN_TEST", "op_name": "demo", "architecture": "arch35"},
        fallback=fallback,
    )

    assert out["ok"] is True
    assert out["rebuild_skipped"] is True
    assert out["build_layered_kb_invoked"] is False
    assert out["large_yaml_reexported"] is False
    assert called is False
    assert (uo / "ir" / "rebuild_fastpath.yaml").is_file()


def test_recheck_uses_closure_only_and_caches_unchanged_success(tmp_path, monkeypatch) -> None:
    uo = tmp_path / ".ascendc-pilot" / "uo"
    _dump(uo / "manifest.yaml", {"op_name": "demo", "architecture": "arch35"})
    _dump(
        uo / "ir" / "entrypoint_graph.yaml",
        {"closure": {"host_main_chain": "closed", "kernel_main_chain": "closed"}},
    )
    _dump(uo / "ir" / "llm_tasks.yaml", {"tasks": []})
    _dump(uo / "ir" / "semantic_resolution_ledger.yaml", {"semantic_patches": []})
    _dump(uo / "ir" / "semantic_apply_report.yaml", {"unconsumed_patch_count": 0})
    _dump(
        uo / "ir" / "semantic_task_triage.yaml",
        {"stats": {"post_semantic_provisional_count": 0, "blocking_route_none_count": 0}},
    )

    import uo.scripts.llm_tasks as llm_tasks

    calls = 0

    def stats(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"blocking_gap_count": 0, "unconsumed_patch_count": 0}

    monkeypatch.setattr(llm_tasks, "compute_semantic_stats", stats)

    def fallback(*_args, **_kwargs):
        raise AssertionError("canonical recheck should not run")

    ctx = {"run_id": "RUN_TEST", "op_name": "demo", "architecture": "arch35"}
    first = invoke_fast_uo_engine(
        tmp_path, "uo-init", "recheck_closure", ctx=ctx, fallback=fallback
    )
    second = invoke_fast_uo_engine(
        tmp_path, "uo-init", "recheck_closure", ctx=ctx, fallback=fallback
    )

    assert first["ok"] is True
    assert first["integrity_recomputed"] is False
    assert first["fast_path"] == "closure_only"
    assert second["ok"] is True
    assert second["cache_hit"] is True
    assert calls == 1
