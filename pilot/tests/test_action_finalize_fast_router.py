from __future__ import annotations

from pathlib import Path

import ascendc_pilot.actions as actions
from ascendc_pilot.actions import runtime


def test_finalize_scopes_fast_router_and_restores_engine(monkeypatch, tmp_path: Path) -> None:
    original_engine = runtime.invoke_engine
    seen = {}

    def fake_pipeline(root, workflow_id, action_id, *, ctx, fallback):
        seen["routed"] = (workflow_id, action_id)
        return {"ok": True, "engine": action_id}

    def fake_finalize(project_root, action_id, *, engine_result=None):
        del engine_result
        return runtime.invoke_engine(
            project_root,
            "uo-init",
            action_id,
            ctx={"run_id": "RUN"},
        )

    monkeypatch.setattr(actions, "invoke_fast_pipeline_engine", fake_pipeline)
    monkeypatch.setattr(runtime, "finalize_action", fake_finalize)

    result = actions.finalize_action(tmp_path, "extract_plan")
    assert result["ok"] is True
    assert seen["routed"] == ("uo-init", "extract_plan")
    assert runtime.invoke_engine is original_engine
