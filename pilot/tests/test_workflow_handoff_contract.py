# -*- coding: utf-8 -*-
"""Runtime handoff: produce → finalize → receipt → advance (not just artifact DAG)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from synthetic_uo import write_synthetic_uo

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "engines" / "understand-operator" / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "engines" / "understand-operator" / "src"))
if str(REPO / "engines" / "code-engineering") not in sys.path:
    sys.path.insert(0, str(REPO / "engines" / "code-engineering"))
if str(REPO / "engines" / "testcase-generation") not in sys.path:
    sys.path.insert(0, str(REPO / "engines" / "testcase-generation"))


def _receipts(project: Path) -> list[Path]:
    from ascendc_pilot.paths import runs_root
    from ascendc_pilot.state import load_state

    state = load_state(project)
    run_id = str(state.get("run_id") or "")
    root = runs_root(project) / run_id / "subagents"
    if not root.is_dir():
        return []
    return sorted(root.glob("*.yaml"))


def _setup_op(tmp_path: Path, monkeypatch, *, arch: str = "arch0", op: str = "_synthetic_toy") -> Path:
    monkeypatch.setenv("UO_OPERATOR", op)
    monkeypatch.setenv("UO_ARCH", arch)
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))
    from ascendc_pilot.paths import ensure_agent_layout

    ensure_agent_layout(tmp_path, arch=arch)
    write_synthetic_uo(tmp_path, op_name=op, architecture=arch)
    return tmp_path


def test_named_gate_uo_ready_resolves_identity_from_run_state(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.state import start_workflow

    root = _setup_op(tmp_path, monkeypatch)
    start_workflow(
        root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
    )
    explicit = run_named_gate(
        root, "uo_ready", op_name="_synthetic_toy", architecture="arch0"
    )
    bare = run_named_gate(root, "uo_ready")
    assert explicit.get("ok") is True, explicit
    assert bare.get("ok") is True, bare
    assert int((bare.get("checks") or {}).get("legal_key_count") or 0) == 4


def test_named_gate_without_state_stays_fail_closed(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.gates import run_named_gate

    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    result = run_named_gate(tmp_path, "uo_ready")
    assert result.get("ok") is False, result
    text = str(result.get("message") or "") + str(result.get("error") or "")
    assert "ARCHITECTURE" in text or int(result.get("legal_key_count") or 0) == 0


def test_tg_kb_check_finalize_issues_receipt_and_advance(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.state import advance_phase, load_state, start_workflow
    from ascendc_pilot.workflows.pipeline import action_receipt_ok

    root = _setup_op(tmp_path, monkeypatch)
    start_workflow(
        root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
    )
    intent = prepare_action(root, "init_intent")
    assert intent.get("ok") is True, intent
    assert intent.get("auto_finalize") is True
    assert action_receipt_ok(root, "init_intent") is True

    advanced = advance_phase(root, "kb_ready")
    assert advanced.get("ok") is True, advanced
    assert load_state(root)["phase"] == "kb_ready"

    kb = prepare_action(root, "kb_check")
    assert kb.get("ok") is True, kb
    fin = kb.get("finalize") or {}
    assert fin.get("ok") is True, fin
    ready = Path(kb.get("receipt_path") or (kb.get("engine") or {}).get("receipt_path") or "")
    assert ready.is_file(), kb
    assert ready.name == "uo_ready.yaml"
    assert "receipts" in ready.as_posix()
    doc = yaml.safe_load(ready.read_text(encoding="utf-8")) or {}
    assert int(doc.get("legal_key_count") or 0) == 4
    assert str(doc.get("run_id") or "") == str(load_state(root).get("run_id") or "")
    assert action_receipt_ok(root, "kb_check") is True
    assert _receipts(root), "expected completed Action receipt after kb_check finalize"

    nxt = advance_phase(root, "contract")
    assert nxt.get("ok") is True, nxt
    assert nxt.get("error") != "PIPELINE_INCOMPLETE"
    assert load_state(root)["phase"] == "contract"


def test_ce_intent_capture_reads_run_state_intent(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.paths import agent_root
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.workflows.pipeline import action_receipt_ok

    root = _setup_op(tmp_path, monkeypatch)
    start_workflow(
        root,
        "ce-intent",
        architecture="arch0",
        op_name="_synthetic_toy",
        intent="audit change",
    )
    captured = prepare_action(root, "intent_capture")
    assert captured.get("ok") is True, captured
    fin = captured.get("finalize") or {}
    assert fin.get("ok") is True, fin
    path = agent_root(root, "arch0") / "ce" / "intent" / "intent.yaml"
    assert path.is_file(), path
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert doc.get("intent") == "audit change"
    assert action_receipt_ok(root, "intent_capture") is True


def test_ce_intent_capture_fails_closed_without_intent(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.state import start_workflow

    root = _setup_op(tmp_path, monkeypatch)
    start_workflow(
        root,
        "ce-intent",
        architecture="arch0",
        op_name="_synthetic_toy",
        intent="",
    )
    captured = prepare_action(root, "intent_capture")
    assert captured.get("ok") is False, captured
    blob = str(captured.get("reason_code") or "") + str(captured.get("error") or "")
    assert "INTENT_MISSING_IN_RUN_STATE" in blob
