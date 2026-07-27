from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.fast_pipeline_engines import invoke_fast_pipeline_engine


def test_structural_action_defers_publish_products(monkeypatch, tmp_path: Path) -> None:
    import uo.scripts.export_human_views as human
    import uo.scripts.export_kb_graph as sqlite_export

    originals = (
        sqlite_export.export_kb_graph,
        human.export_human_views,
    )

    def fallback(root, workflow_id, action_id, *, ctx=None):
        assert sqlite_export.export_kb_graph(tmp_path, "op")["status"] == "deferred"
        assert human.export_human_views(tmp_path)["status"] == "deferred"
        return {"ok": True, "engine": action_id}

    result = invoke_fast_pipeline_engine(
        tmp_path,
        "uo-init",
        "extract_plan",
        ctx={"run_id": "RUN"},
        fallback=fallback,
    )

    assert result["ok"] is True
    assert result["build_mode"] == "structural"
    assert result["publish_deferred"] is True
    assert set(result["deferred_products"]) == {"kb_graph.sqlite", "human_views"}
    assert sqlite_export.export_kb_graph is originals[0]
    assert human.export_human_views is originals[1]


def test_non_structural_action_delegates_unchanged(tmp_path: Path) -> None:
    calls = []

    def fallback(root, workflow_id, action_id, *, ctx=None):
        calls.append((workflow_id, action_id, ctx))
        return {"ok": True}

    out = invoke_fast_pipeline_engine(
        tmp_path,
        "uo-init",
        "detect_score_post",
        ctx={"x": 1},
        fallback=fallback,
    )
    assert out == {"ok": True}
    assert calls == [("uo-init", "detect_score_post", {"x": 1})]
