"""uo-update detect must pin architecture and pass it into detect_kb_changes."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "engines" / "understand-operator" / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "engines" / "understand-operator" / "src"))
if str(REPO / "pilot") not in sys.path:
    sys.path.insert(0, str(REPO / "pilot"))


def test_run_detect_changes_passes_architecture(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions.engines import _run_detect_changes
    from ascendc_pilot.paths import ensure_agent_layout, uo_root

    ensure_agent_layout(tmp_path, arch="arch35")
    uo = uo_root(tmp_path, arch="arch35")
    (uo / "manifest.yaml").write_text(
        yaml.safe_dump({"op_name": "Toy", "architecture": "arch35"}),
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    def fake_detect(project_root, op_name, **kwargs):
        seen["op_name"] = op_name
        seen["kwargs"] = kwargs
        out = uo / "diff" / "change_set.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("files: []\n", encoding="utf-8")
        return {"scoped_change_count": 2, "detection": "git", "worktree_dirty": True}

    monkeypatch.setattr("uo_init.update.detect_kb_changes", fake_detect)
    result = _run_detect_changes(
        tmp_path,
        {"architecture": "arch35", "op_name": "Toy"},
    )
    assert result["ok"] is True
    assert result["scoped_change_count"] == 2
    assert seen["op_name"] == "Toy"
    assert seen["kwargs"]["architecture"] == "arch35"
    assert seen["kwargs"]["write"] is True


def test_uo_op_ctx_uses_ctx_architecture(tmp_path: Path) -> None:
    from ascendc_pilot.actions.engines import _uo_op_ctx
    from ascendc_pilot.paths import ensure_agent_layout, uo_root

    ensure_agent_layout(tmp_path, arch="arch35")
    uo, op_name, arch = _uo_op_ctx(
        tmp_path,
        {"architecture": "arch35", "op_name": "Toy"},
    )
    assert arch == "arch35"
    assert op_name == "Toy"
    assert uo == uo_root(tmp_path, arch="arch35")


def test_run_apply_update_returns_cann_message(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import engines as eng_mod

    monkeypatch.setattr(
        eng_mod,
        "_cann_not_ready",
        lambda engine, ctx: {
            "ok": False,
            "engine": engine,
            "error": "CANN_ENV_NOT_READY",
            "message_zh": "UO 解析前 CANN 环境未就绪。请设置 UO_CANN_ROOT。",
            "issues": ["CANN packages not found"],
        },
    )
    out = eng_mod._run_apply_update(
        tmp_path,
        {"architecture": "arch35", "op_name": "Toy", "run_id": "r1"},
    )
    assert out["ok"] is False
    assert out["error"] == "CANN_ENV_NOT_READY"
    assert "UO_CANN_ROOT" in str(out.get("message_zh") or "")


def test_rebuild_failure_from_update_copies_nested_cann() -> None:
    from ascendc_pilot.actions.engines import _rebuild_failure_from_update

    nested = _rebuild_failure_from_update(
        {
            "status": "fail",
            "action_results": [
                {
                    "action": "prepare_layout",
                    "ok": False,
                    "result": {
                        "ok": False,
                        "error": "CANN_ENV_NOT_READY",
                        "message_zh": "UO 解析前 CANN 环境未就绪。请设置 UO_CANN_ROOT。",
                        "issues": ["CANN packages not found"],
                    },
                }
            ],
        }
    )
    assert nested["error"] == "CANN_ENV_NOT_READY"
    assert "UO_CANN_ROOT" in str(nested.get("message_zh") or "")
    assert nested["failed_rebuild_action"] == "prepare_layout"
