from __future__ import annotations

from ascendc_pilot.actions import _prepare_with_fast_uo_engine
from ascendc_pilot.actions import runtime as runtime_module


def test_prepare_router_restores_runtime_engine(monkeypatch, tmp_path) -> None:
    original = runtime_module.invoke_engine
    seen = {}

    def fake_prepare(_root, _action_id, **_kwargs):
        seen["during"] = runtime_module.invoke_engine is not original
        return {"ok": True, "action_id": _action_id}

    monkeypatch.setattr(runtime_module, "prepare_action", fake_prepare)

    result = _prepare_with_fast_uo_engine(tmp_path, "recheck_closure")

    assert result["ok"] is True
    assert seen["during"] is True
    assert runtime_module.invoke_engine is original
