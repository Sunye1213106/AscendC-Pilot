"""Receipt verify performance + slim checker_result for HMAC receipts."""

from __future__ import annotations

import time
from pathlib import Path

from ascendc_pilot.runs import (
    issue_receipt,
    slim_checker_result_for_receipt,
    verify_receipt,
)
from ascendc_pilot.spec_hashes import workflow_spec_hash
from ascendc_pilot.state import start_workflow


def test_slim_checker_result_drops_engine_blob():
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
        "producer_identity": {"ok": True},
        "identity_injection": {"ok": True, "skipped": True},
        "target_violation": {},
    }
    slim = slim_checker_result_for_receipt(fat)
    assert slim["ok"] is True
    assert slim["schema"] == "receipt_checker_v1"
    assert "items" not in str(slim.get("engine") or {})
    assert "payload_sha256" in (slim.get("engine") or {})
    assert "report_sha256" in (slim.get("engine") or {})
    assert len(str(slim)) < len(str(fat)) // 5


def test_issue_receipt_stores_slim_checker(tmp_path: Path):
    import yaml

    start_workflow(tmp_path, "uo-init", phase="normalize", force_phase=True)
    wf = workflow_spec_hash("uo-init")
    fat_engine = {"ok": True, "report": {"huge": ["x" * 200] * 50}}
    path = issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="agent-a",
        action_id="detect_score_post",
        workflow_spec_hash=wf,
        input_hashes={"a": "1"},
        output_hashes={"b": "2"},
        checker_result={"ok": True, "engine": fat_engine},
        _internal=True,
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    checker = data["checker_result"]
    assert checker.get("schema") == "receipt_checker_v1"
    assert "huge" not in str(checker)
    assert verify_receipt(tmp_path, action_id="detect_score_post").get("ok") is True


def test_verify_receipt_filters_by_action_id_before_scanning_others(tmp_path: Path):
    """With many fat unrelated receipts, action_id verify must stay cheap."""
    start_workflow(tmp_path, "uo-init", phase="normalize", force_phase=True)
    wf = workflow_spec_hash("uo-init")
    fat = {"ok": True, "engine": {"report": {"blob": ["y" * 1000] * 80}}}
    for i in range(6):
        issue_receipt(
            tmp_path,
            actor_type="producer",
            actor_id=f"agent-{i}",
            action_id=f"other_action_{i}",
            workflow_spec_hash=wf,
            input_hashes={"k": str(i)},
            output_hashes={"o": str(i)},
            checker_result=fat,
            _internal=True,
        )
    issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="target-agent",
        action_id="adjudicate_llm_tasks",
        workflow_spec_hash=wf,
        input_hashes={"k": "t"},
        output_hashes={"o": "t"},
        checker_result={"ok": True},
        _internal=True,
    )
    t0 = time.perf_counter()
    ok = verify_receipt(tmp_path, action_id="adjudicate_llm_tasks")
    elapsed = time.perf_counter() - t0
    assert ok.get("ok") is True
    assert elapsed < 1.5


def test_verify_receipt_missing_action_does_not_scan_siblings(tmp_path: Path):
    """Incomplete action_id must not HMAC every unrelated fat receipt."""
    start_workflow(tmp_path, "uo-init", phase="normalize", force_phase=True)
    wf = workflow_spec_hash("uo-init")
    fat = {"ok": True, "engine": {"report": {"blob": ["y" * 2000] * 100}}}
    for i in range(4):
        issue_receipt(
            tmp_path,
            actor_type="producer",
            actor_id=f"agent-{i}",
            action_id=f"done_action_{i}",
            workflow_spec_hash=wf,
            input_hashes={"k": str(i)},
            output_hashes={"o": str(i)},
            checker_result=fat,
            _internal=True,
        )
    t0 = time.perf_counter()
    bad = verify_receipt(tmp_path, action_id="not_yet_done_action")
    elapsed = time.perf_counter() - t0
    assert bad.get("ok") is False
    assert elapsed < 0.5


def test_recommend_next_uses_single_pass_cache(tmp_path: Path, monkeypatch):
    from ascendc_pilot.workflows import pipeline as pipe_mod

    start_workflow(tmp_path, "uo-init", phase="normalize", force_phase=True)
    calls: list[str] = []

    def fake_ok(project_root: Path, action_id: str) -> bool:
        calls.append(action_id)
        return False

    monkeypatch.setattr(pipe_mod, "action_receipt_ok", fake_ok)
    monkeypatch.setattr(pipe_mod, "preferred_pipeline", lambda *a, **k: ["a", "b", "c"])
    monkeypatch.setattr(pipe_mod, "_not_applicable_proof", lambda *a, **k: False)

    allowed = [
        {"id": "a", "label_zh": "A"},
        {"id": "b", "label_zh": "B"},
        {"id": "c", "label_zh": "C"},
    ]
    rec = pipe_mod.recommend_next_action(
        tmp_path, workflow_id="uo-init", phase="normalize", allowed_actions=allowed
    )
    assert rec and rec["id"] == "a"
    assert calls == ["a", "b", "c"]
    assert rec["missing_actions"] == ["a", "b", "c"]


def test_verify_compacts_bloated_legacy_receipt(tmp_path: Path):
    """Successful verify rewrites legacy fat checker_result and re-signs."""
    import yaml

    from ascendc_pilot.runs import run_dir, sign_receipt_payload
    from ascendc_pilot.state import load_state

    start_workflow(tmp_path, "uo-init", phase="normalize", force_phase=True)
    state = load_state(tmp_path)
    run_id = str(state["run_id"])
    wf = workflow_spec_hash("uo-init")
    fat_checker = {
        "ok": True,
        "engine": {"ok": True, "report": {"blob": ["z" * 500] * 40}},
    }
    payload = {
        "identity": f"{run_id}:detect_score_post:agent-x",
        "run_id": run_id,
        "workflow_id": "uo-init",
        "phase": "extract",
        "actor_type": "producer",
        "actor_id": "agent-x",
        "action_id": "detect_score_post",
        "workflow_spec_hash": wf,
        "input_hashes": {"a": "1"},
        "output_hashes": {"b": "2"},
        "checker_result": fat_checker,
        "nonce": "n",
        "artifact": "",
        "issued_by": "pilot",
        "recorded_at": "2026-07-27T00:00:00Z",
    }
    payload["signature"] = sign_receipt_payload(tmp_path, payload)
    path = run_dir(tmp_path, run_id) / "subagents" / f"{run_id}_detect_score_post_agent-x.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    before = path.stat().st_size
    assert verify_receipt(tmp_path, action_id="detect_score_post").get("ok") is True
    after_data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert after_data["checker_result"].get("schema") == "receipt_checker_v1"
    assert "blob" not in str(after_data["checker_result"])
    assert path.stat().st_size < before // 2
    # Second verify still ok (re-signed)
    assert verify_receipt(tmp_path, action_id="detect_score_post").get("ok") is True
