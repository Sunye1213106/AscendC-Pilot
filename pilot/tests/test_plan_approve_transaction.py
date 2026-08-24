"""plan_approve must consume a decision receipt and stay on one request_id."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_pilot.human_confirm import (
    hosted_confirm_should_ask,
    materialize_primary_decision,
)
from ascendc_pilot.human_interaction import (
    issue_interaction_request,
    record_answer,
    require_decision_receipt,
)
from ascendc_pilot.paths import ensure_agent_layout, runs_root, tg_root
from ascendc_pilot.state import load_state, start_workflow
from testcase_agent.products import is_plan_approved, parse_plan_fence


@pytest.fixture(autouse=True)
def _isolate_uo_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UO_ARCH", raising=False)


_ARCH = "arch35"

_PLAN_MD = """## 测什么

测 dtype 分发。

## 覆盖什么

L0 两个 partition。

## 怎么判定

看 Replay tiling_key。

```yaml
schema: tg-plan/v3
requirement: {id: R-dtype, text: dtype}
targets:
- id: T-dispatch
  evidence: {kind: replay_field, field: tiling_key, expected: 1}
guards: []
dimensions:
- id: D-dtype
  target: T-dispatch
  controls: [B]
  partitions:
  - {id: fp16, predicate: {op: eq, field: case.B, value: 1}}
  - {id: bf16, predicate: {op: eq, field: case.B, value: 2}}
coverage:
  L0: {dimensions: [D-dtype]}
  L1: {combinations: []}
  L2: []
  L3: {guards: []}
oracle: []
```
"""


def _ask() -> dict:
    return {
        "header": "规划已就绪，是否开始求解？",
        "question": "是否批准规划并进入求解？",
        "options": [
            {"label": "批准并开始求解", "value": "approve"},
            {"label": "返工规划", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    }


def _write_session(root: Path, action_id: str = "plan_approve") -> None:
    state = load_state(root) or {}
    run_id = str(state.get("run_id") or "")
    assert run_id
    sdir = runs_root(root) / run_id / "actions" / action_id
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "session.yaml").write_text(
        yaml.safe_dump(
            {
                "action_id": action_id,
                "run_id": run_id,
                "workflow_id": "tg-plan",
                "phase": "approve",
                "actor_id": "ascendc-pilot",
                "role_id": "primary_interactive",
                "action_session_id": f"{run_id}:{action_id}",
                "lease_id": "lease-test",
                "prepare_nonce": "nonce-test",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _seed_plan_products(root: Path) -> Path:
    ensure_agent_layout(root, arch=_ARCH)
    tg = tg_root(root, arch=_ARCH)
    tg.mkdir(parents=True, exist_ok=True)
    (tg / "init.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "tg-init/v1",
                "columns": [{"name": "B"}],
                "mapping": {
                    "B": {
                        "control": {"status": "active"},
                        "relation": "direct",
                        "confidence": "confirmed",
                        "uo": {"id": "b", "candidate": ""},
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    path = tg / "plan.md"
    path.write_text(_PLAN_MD, encoding="utf-8")
    return path


def _prepare_approve(tmp_path: Path) -> Path:
    start_workflow(
        tmp_path, "tg-plan", phase="approve", force_phase=True, architecture=_ARCH
    )
    _write_session(tmp_path)
    return _seed_plan_products(tmp_path)


def test_issue_reuses_request_id_while_waiting(tmp_path: Path) -> None:
    start_workflow(
        tmp_path, "tg-plan", phase="approve", force_phase=True, architecture=_ARCH
    )
    first = issue_interaction_request(
        tmp_path,
        kind="primary_approve",
        ask_question=_ask(),
        action_id="plan_approve",
        decision_kind="primary_approve",
        allowed_values=["approve", "rework", "stop"],
    )
    second = issue_interaction_request(
        tmp_path,
        kind="primary_approve",
        ask_question=_ask(),
        action_id="plan_approve",
        decision_kind="primary_approve",
        allowed_values=["approve", "rework", "stop"],
    )
    assert first["request_id"]
    assert second["request_id"] == first["request_id"]


def test_issue_reuses_request_id_after_answer_before_consume(tmp_path: Path) -> None:
    start_workflow(
        tmp_path, "tg-plan", phase="approve", force_phase=True, architecture=_ARCH
    )
    env = issue_interaction_request(
        tmp_path,
        kind="primary_approve",
        ask_question=_ask(),
        action_id="plan_approve",
        decision_kind="primary_approve",
        allowed_values=["approve", "rework", "stop"],
    )
    answered = record_answer(tmp_path, request_id=env["request_id"], value="approve")
    assert answered.get("ok") is True
    again = issue_interaction_request(
        tmp_path,
        kind="primary_approve",
        ask_question=_ask(),
        action_id="plan_approve",
        decision_kind="primary_approve",
        allowed_values=["approve", "rework", "stop"],
    )
    assert again["request_id"] == env["request_id"]


def test_approve_receipt_materializes_plan_md(tmp_path: Path) -> None:
    plan_path = _prepare_approve(tmp_path)
    state = load_state(tmp_path) or {}
    assert hosted_confirm_should_ask(tmp_path, state, action_id="plan_approve") is False
    env = issue_interaction_request(
        tmp_path,
        kind="primary_approve",
        ask_question=_ask(),
        action_id="plan_approve",
        decision_kind="primary_approve",
        allowed_values=["approve", "rework", "stop"],
    )
    assert record_answer(tmp_path, request_id=env["request_id"], value="approve").get("ok")
    out = materialize_primary_decision(tmp_path, "plan_approve")
    assert out.get("ok") is True, out
    text = plan_path.read_text(encoding="utf-8")
    fence = parse_plan_fence(text)
    assert is_plan_approved(fence) is True
    assert fence.get("approved") is True
    assert fence.get("decision") == "approve"


def test_already_approved_is_idempotent(tmp_path: Path) -> None:
    _prepare_approve(tmp_path)
    env = issue_interaction_request(
        tmp_path,
        kind="primary_approve",
        ask_question=_ask(),
        action_id="plan_approve",
        decision_kind="primary_approve",
        allowed_values=["approve", "rework", "stop"],
    )
    assert record_answer(tmp_path, request_id=env["request_id"], value="approve").get("ok")
    first = materialize_primary_decision(tmp_path, "plan_approve")
    assert first.get("ok") is True, first
    require_decision_receipt(
        tmp_path,
        expected_values=["approve"],
        expected_action_id="plan_approve",
        expected_kind="primary_approve",
        consume=True,
    )
    second = materialize_primary_decision(tmp_path, "plan_approve")
    assert second.get("ok") is True, second
    assert second.get("already_approved") is True


def test_attach_host_step_does_not_rewrite_plan_approve_as_intake(tmp_path: Path) -> None:
    """ses_fccf: dispatch_legacy must not overlay intake/test_script_root on plan_approve."""
    from ascendc_pilot.actions.dispatch import attach_host_step
    from ascendc_pilot.human_interaction import pending_path

    _prepare_approve(tmp_path)
    env = issue_interaction_request(
        tmp_path,
        kind="primary_approve",
        ask_question=_ask(),
        action_id="plan_approve",
        decision_kind="primary_approve",
        allowed_values=["approve", "rework", "stop"],
    )
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "status": "running",
            "next": {
                "execution_kind": "primary_interactive",
                "action_id": "plan_approve",
                "actor_id": "ascendc-pilot",
            },
            "ask_question": _ask(),
            "needs_human_decision": True,
            "prepare": {
                "ok": True,
                "needs_human_decision": True,
                "ask_question": _ask(),
                "human_interaction_request": env,
                "actor_id": "ascendc-pilot",
                "action_id": "plan_approve",
            },
        },
        reenter_drive=False,
    )
    step = out.get("host_step") or {}
    assert step.get("kind") == "ask_human"
    pending = yaml.safe_load(pending_path(tmp_path).read_text(encoding="utf-8"))
    assert pending.get("kind") == "primary_approve"
    assert pending.get("decision_kind") == "primary_approve"
    assert pending.get("request_id") == env["request_id"]
    assert pending.get("action_id") == "plan_approve"
    assert (step.get("ask_question") or {}).get("request_id") == env["request_id"]
    receipt = require_decision_receipt(
        tmp_path,
        expected_values=["approve"],
        expected_action_id="plan_approve",
        expected_kind="primary_approve",
        consume=False,
    )
    assert receipt.get("ok") is False
    assert receipt.get("error") == "HUMAN_DECISION_RECEIPT_REQUIRED"
    answered = record_answer(tmp_path, request_id=env["request_id"], value="approve")
    assert answered.get("ok") is True, answered
    got = require_decision_receipt(
        tmp_path,
        expected_values=["approve"],
        expected_action_id="plan_approve",
        expected_kind="primary_approve",
        consume=False,
    )
    assert got.get("ok") is True, got
    assert got.get("value") == "approve"


def test_stale_intake_receipt_does_not_block_reissue(tmp_path: Path) -> None:
    """ses_fccf recovery: intake overlay must not freeze plan_approve on KIND_MISMATCH."""
    from ascendc_pilot.actions.runtime import prepare_action
    from ascendc_pilot.human_interaction import pending_path

    _prepare_approve(tmp_path)
    stale = issue_interaction_request(
        tmp_path,
        kind="intake",
        ask_question=_ask(),
        action_id="plan_approve",
        decision_kind="test_script_root",
        allowed_values=["approve", "rework", "stop"],
    )
    assert record_answer(tmp_path, request_id=stale["request_id"], value="approve").get("ok")
    mismatch = require_decision_receipt(
        tmp_path,
        expected_values=["approve"],
        expected_action_id="plan_approve",
        expected_kind="primary_approve",
        consume=False,
    )
    assert mismatch.get("error") == "HUMAN_DECISION_RECEIPT_KIND_MISMATCH"
    prep = prepare_action(tmp_path, "plan_approve")
    assert prep.get("ok") is not False or prep.get("error") != "HUMAN_DECISION_RECEIPT_KIND_MISMATCH", prep
    assert prep.get("needs_human_decision") is True, prep
    pending = yaml.safe_load(pending_path(tmp_path).read_text(encoding="utf-8"))
    assert pending.get("kind") == "primary_approve"
    assert pending.get("decision_kind") == "primary_approve"
    assert pending.get("request_id") != stale["request_id"]
