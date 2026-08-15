# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import ascendc_pilot.actions as actions


def _answer() -> str:
    return """```yaml
schema: kb-answer-v1
status: PARTIAL
question: q
answer_zh: partial
adequacy: PARTIAL
```"""


def test_parse_host_action_result_from_fenced_yaml() -> None:
    payload = actions._parse_host_action_result(_answer())
    assert payload is not None
    assert payload["schema"] == "kb-answer-v1"
    assert payload["answer_zh"] == "partial"
    assert payload["_transport"] == "native_task"


def test_parse_host_action_result_keeps_native_prose() -> None:
    text = """三相是 PRE → CORE → POST。
证据：op_kernel/arch35/entry.h:12-40 的 pipeIn / pipeBase / pipePost。

```yaml
schema: kb-answer-v1
status: ANSWERED
question: q
answer_zh: 短摘要
adequacy: ANSWERED
```
"""
    payload = actions._parse_host_action_result(text)
    assert payload is not None
    assert "pipeIn" in payload["answer_zh"]
    assert "短摘要" not in payload["answer_zh"] or "三相" in payload["answer_zh"]
    assert payload["_transport"] == "native_task"
    assert payload["status"] == "ANSWERED"


def test_parse_host_action_result_plain_explore_message() -> None:
    payload = actions._parse_host_action_result("BN2 走 IS_BN2_MULTIBLK，见 kernel.h:88。")
    assert payload is not None
    assert payload["schema"] == "kb-answer-v1"
    assert "IS_BN2_MULTIBLK" in payload["answer_zh"]
    assert payload["_transport"] == "native_task"


def test_run_action_passes_result_file_through_facade(monkeypatch, tmp_path: Path) -> None:
    seen = {}

    def fake_finalize(project_root, action_id, **kwargs):
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(actions._runtime, "finalize_action", fake_finalize)
    result = actions.run_action(
        tmp_path,
        "kb_lookup",
        finalize=True,
        result_file=tmp_path / "answer.yaml",
    )
    assert result["ok"] is True
    assert seen["result_file"] == tmp_path / "answer.yaml"
    assert seen["action_result"] is None


def test_run_action_uses_ephemeral_env_task_return(monkeypatch, tmp_path: Path) -> None:
    seen = {}

    def fake_finalize(project_root, action_id, **kwargs):
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(actions._runtime, "finalize_action", fake_finalize)
    monkeypatch.setenv("ASCENDC_ACTION_RESULT", _answer())
    monkeypatch.setenv("ASCENDC_ACTION_RESULT_PROJECT", str(tmp_path.resolve()))
    monkeypatch.setenv("ASCENDC_ACTION_RESULT_ACTION", "kb_lookup")
    result = actions.run_action(tmp_path, "kb_lookup", finalize=True)
    assert result["ok"] is True
    assert seen["result_file"] is None
    assert seen["action_result"]["schema"] == "kb-answer-v1"
    assert seen["action_result"]["status"] == "PARTIAL"


def test_ephemeral_result_rejects_project_or_action_mismatch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ASCENDC_ACTION_RESULT", _answer())
    monkeypatch.setenv("ASCENDC_ACTION_RESULT_PROJECT", str((tmp_path / "other").resolve()))
    monkeypatch.setenv("ASCENDC_ACTION_RESULT_ACTION", "kb_lookup")
    assert actions._host_action_result_from_env(tmp_path, "kb_lookup") is None

    monkeypatch.setenv("ASCENDC_ACTION_RESULT_PROJECT", str(tmp_path.resolve()))
    monkeypatch.setenv("ASCENDC_ACTION_RESULT_ACTION", "other_action")
    assert actions._host_action_result_from_env(tmp_path, "kb_lookup") is None


def test_explicit_action_result_wins_over_env(monkeypatch, tmp_path: Path) -> None:
    seen = {}

    def fake_finalize(project_root, action_id, **kwargs):
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(actions._runtime, "finalize_action", fake_finalize)
    monkeypatch.setenv("ASCENDC_ACTION_RESULT", _answer())
    explicit = {
        "schema": "kb-answer-v1",
        "status": "ANSWERED",
        "question": "q",
        "answer_zh": "explicit",
        "adequacy": "ANSWERED",
    }
    result = actions.run_action(
        tmp_path,
        "kb_lookup",
        finalize=True,
        action_result=explicit,
    )
    assert result["ok"] is True
    assert seen["action_result"] == explicit
