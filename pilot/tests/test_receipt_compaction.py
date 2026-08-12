"""Receipt compaction, filtering and pipeline-cache correctness."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.runs import issue_receipt, slim_checker_result_for_receipt, verify_receipt
from ascendc_pilot.spec_hashes import workflow_spec_hash
from ascendc_pilot.state import start_workflow


def test_slim_checker_result_drops_large_engine_blob() -> None:
    fat = {
        "ok": True,
        "gates": [{"id": "g1", "ok": True}],
        "output_contract": {"ok": True, "contract_id": "c1"},
        "engine": {
            "ok": True,
            "engine": "score",
            "checkpoint": "post",
            "report": {"items": [{"x": i} for i in range(500)]},
            "tasks": {"count": 262},
        },
        "apply": {"ok": True, "patches": list(range(200))},
    }
    slim = slim_checker_result_for_receipt(fat)
    assert slim["ok"] is True
    assert slim["schema"] == "receipt_checker_v1"
    assert "items" not in str(slim.get("engine") or {})
    assert "payload_sha256" in (slim.get("engine") or {})
    assert "report_sha256" in (slim.get("engine") or {})


def test_issue_receipt_stores_slim_checker(tmp_path: Path) -> None:
    import yaml

    start_workflow(tmp_path, "uo-investigate", phase="investigate", force_phase=True, architecture="arch35")
    path = issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="uo-gap-investigator",
        action_id="investigate",
        workflow_spec_hash=workflow_spec_hash("uo-investigate"),
        input_hashes={"a": "1"},
        output_hashes={"b": "2"},
        checker_result={"ok": True, "engine": {"report": {"huge": ["x" * 200] * 50}}},
        _internal=True,
    )
    checker = yaml.safe_load(path.read_text(encoding="utf-8"))["checker_result"]
    assert checker.get("schema") == "receipt_checker_v1"
    assert "huge" not in str(checker)
    assert verify_receipt(tmp_path, action_id="investigate").get("ok") is True


def test_verify_filters_by_requested_action_id(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-investigate", phase="investigate", force_phase=True, architecture="arch35")
    wf = workflow_spec_hash("uo-investigate")
    for i in range(4):
        issue_receipt(
            tmp_path,
            actor_type="deterministic_engine",
            actor_id="engine",
            action_id=f"other_action_{i}",
            workflow_spec_hash=wf,
            input_hashes={"k": str(i)},
            output_hashes={"o": str(i)},
            checker_result={"ok": True, "engine": {"blob": ["y" * 100] * 20}},
            _internal=True,
        )
    issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="uo-gap-investigator",
        action_id="investigate",
        workflow_spec_hash=wf,
        input_hashes={"k": "target"},
        output_hashes={"o": "target"},
        checker_result={"ok": True},
        _internal=True,
    )
    assert verify_receipt(tmp_path, action_id="investigate").get("ok") is True
    assert verify_receipt(tmp_path, action_id="missing_action").get("ok") is False


def test_recommend_next_uses_one_done_check_per_action(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.workflows import pipeline as pipe_mod

    start_workflow(tmp_path, "uo-init", phase="analyze", force_phase=True, architecture="arch35")
    calls: list[str] = []

    def fake_ok(project_root: Path, action_id: str) -> bool:
        del project_root
        calls.append(action_id)
        return False

    monkeypatch.setattr(pipe_mod, "action_receipt_ok", fake_ok)
    monkeypatch.setattr(pipe_mod, "preferred_pipeline", lambda *args, **kwargs: ["analyze", "commit"])
    monkeypatch.setattr(pipe_mod, "_not_applicable_proof", lambda *args, **kwargs: False)
    allowed = [
        {"id": "analyze", "label_zh": "Analyze"},
        {"id": "commit", "label_zh": "Commit"},
    ]
    rec = pipe_mod.recommend_next_action(
        tmp_path,
        workflow_id="uo-init",
        phase="analyze",
        allowed_actions=allowed,
    )
    assert rec and rec["id"] == "analyze"
    assert calls == ["analyze", "commit"]
    assert rec["missing_actions"] == ["analyze", "commit"]


def test_verify_compacts_legacy_fat_receipt_and_resigns(tmp_path: Path) -> None:
    import yaml

    from ascendc_pilot.runs import run_dir, sign_receipt_payload
    from ascendc_pilot.state import load_state

    start_workflow(tmp_path, "uo-investigate", phase="investigate", force_phase=True, architecture="arch35")
    state = load_state(tmp_path)
    run_id = str(state["run_id"])
    payload = {
        "identity": f"{run_id}:investigate:uo-gap-investigator",
        "run_id": run_id,
        "workflow_id": "uo-investigate",
        "phase": "investigate",
        "actor_type": "producer",
        "actor_id": "uo-gap-investigator",
        "action_id": "investigate",
        "workflow_spec_hash": workflow_spec_hash("uo-investigate"),
        "input_hashes": {"a": "1"},
        "output_hashes": {"b": "2"},
        "checker_result": {"ok": True, "engine": {"report": {"blob": ["z" * 500] * 40}}},
        "nonce": "n",
        "artifact": "",
        "issued_by": "pilot",
        "recorded_at": "2026-07-27T00:00:00Z",
    }
    payload["signature"] = sign_receipt_payload(tmp_path, payload)
    path = run_dir(tmp_path, run_id) / "subagents" / f"{run_id}_investigate_uo-gap-investigator.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    assert verify_receipt(tmp_path, action_id="investigate").get("ok") is True
    compacted = yaml.safe_load(path.read_text(encoding="utf-8"))["checker_result"]
    assert compacted.get("schema") == "receipt_checker_v1"
    assert "blob" not in str(compacted)
    assert verify_receipt(tmp_path, action_id="investigate").get("ok") is True
