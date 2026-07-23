"""Harness unit tests including ses_076d KEY gate fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_harness.context import build_context_pack
from ascendc_harness.gates import (
    gate_confidence_closed_high,
    gate_confidence_reason_review,
    gate_confidence_report_quality,
    gate_empty_only_producer,
    gate_key_triage_required,
    reject_key_patch_batch,
    run_key_gates,
)
from ascendc_harness.memory import add_candidate, promote_stable, propose_global_promote, search_local
from ascendc_harness.migrate import migrate_legacy
from ascendc_harness.paths import tg_root, uo_root
from ascendc_harness.router import route
from ascendc_harness.state import (
    complete_workflow,
    load_state,
    mark_terminal,
    no_progress_exceeded,
    record_gate,
    start_workflow,
)


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_router_slash_and_keyword():
    assert route("/uo-init foo").get("workflow_id") == "uo-init"
    assert route("帮我建库初始化知识库").get("workflow_id") == "uo-init"
    assert route("/tg-plan").get("workflow_id") == "tg-plan"
    assert route("完全无关的话").get("ok") is False


def test_state_machine_and_no_progress(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="resolve")
    record_gate(tmp_path, "g1", ok=False)
    record_gate(tmp_path, "g1", ok=False)
    record_gate(tmp_path, "g1", ok=False)
    assert no_progress_exceeded(tmp_path, limit=3)
    st = load_state(tmp_path)
    assert st["workflow_id"] == "uo-init"


def test_mark_terminal_pass_refused_without_complete(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="review")
    with pytest.raises(RuntimeError, match="complete_workflow"):
        mark_terminal(tmp_path, "pass")


def test_migrate_legacy(tmp_path: Path):
    legacy_uo = tmp_path / ".understand-operator" / "DemoOp"
    _write(legacy_uo / "manifest.yaml", {"op_name": "DemoOp", "version": 1})
    _write(legacy_uo / "ir" / "x.yaml", {"ok": True})
    legacy_tg = tmp_path / ".testcase-generator" / "DemoOp"
    _write(legacy_tg / "init" / "status.yaml", {"status": "confirmed"})
    result = migrate_legacy(tmp_path, op_name="DemoOp")
    assert result["ok"]
    assert (uo_root(tmp_path) / "manifest.yaml").is_file()
    assert (tg_root(tmp_path) / "init" / "status.yaml").is_file()


def test_key_triage_required_fails_without_triage(tmp_path: Path):
    uo = uo_root(tmp_path)
    _write(
        uo / "ir" / "input_derivable_gaps.yaml",
        {"gaps": [{"id": "KEY_ISNZOUT", "status": "open"}]},
    )
    r = gate_key_triage_required(uo)
    assert r["ok"] is False
    _write(uo / "ir" / "key_triage.yaml", {"keys": [{"id": "KEY_ISNZOUT", "complexity": "complex"}]})
    r2 = gate_key_triage_required(uo)
    assert r2["ok"] is True


def test_empty_only_producer_rejected(tmp_path: Path):
    uo = uo_root(tmp_path)
    _write(
        uo / "ir" / "resolution_patch.yaml",
        {
            "items": [
                {
                    "id": "KEY_FOO",
                    "status": "accepted",
                    "evidence": "producer only in RunEmptyTiling Regbase",
                }
            ]
        },
    )
    r = gate_empty_only_producer(uo)
    assert r["ok"] is False


def test_reject_key_patch_batch_empty_and_receipt(tmp_path: Path):
    uo = uo_root(tmp_path)
    _write(
        uo / "ir" / "input_derivable_gaps.yaml",
        {"gaps": [{"id": "KEY_FOO", "status": "open"}]},
    )
    items = [
        {
            "id": "KEY_FOO",
            "status": "accepted",
            "confidence": "high",
            "evidence": "RunEmptyTiling empty_tensor only",
        }
    ]
    rejected = reject_key_patch_batch(tmp_path, uo, items)
    assert rejected
    assert any("empty_only" in r["reason"] for r in rejected)


def test_report_quality_rejects_boilerplate(tmp_path: Path):
    uo = uo_root(tmp_path)
    lines = ["# report", ""]
    excuse = "跨编译边界 bit-pack 无法回溯，Host/Kernel 不可解"
    for i in range(8):
        lines.extend([f"### KEY_X{i}", f"- 原因：{excuse}", ""])
    _write(uo / "summary" / "confidence_report.md", "\n".join(lines))
    r = gate_confidence_report_quality(uo, min_dup=5)
    assert r["ok"] is False


def test_closed_high_zero_fails_even_if_status_pass(tmp_path: Path):
    uo = uo_root(tmp_path)
    _write(
        uo / "ir" / "input_derivable.yaml",
        {"keys": {f"KEY_{i}": {"input_derivable": "unsolved", "confidence": "low"} for i in range(3)}},
    )
    _write(
        uo / "checks" / "confidence_gate.yaml",
        {"status": "pass", "closed_high_count": 0, "need_llm_count": 0},
    )
    r = gate_confidence_closed_high(uo)
    assert r["ok"] is False
    _write(uo / "checks" / "human_accept_reported.yaml", {"accepted": True})
    r2 = gate_confidence_closed_high(uo)
    assert r2["ok"] is True


def test_confidence_reason_review_requires_referee(tmp_path: Path):
    uo = uo_root(tmp_path)
    _write(
        uo / "ir" / "input_derivable.yaml",
        {"keys": {"KEY_X": {"input_derivable": "unsolved", "confidence": "low"}}},
    )
    _write(
        uo / "summary" / "confidence_report.md",
        "### KEY_X\n- 原因：Host optional 未实例化，暂无法 high\n",
    )
    r = gate_confidence_reason_review(uo)
    assert r["ok"] is False
    _write(
        uo / "review" / "confidence_reason_review.yaml",
        {
            "agent": "uo-confidence-review",
            "verdict": "pass",
            "summary": "原因充分",
            "need_llm_count": 1,
            "checked_ids": ["KEY_X"],
        },
    )
    r2 = gate_confidence_reason_review(uo)
    assert r2["ok"] is True


def test_ses076d_fixture_full_gate_fail(tmp_path: Path):
    """Regression: missing triage + boilerplate report + review pass must fail."""
    uo = uo_root(tmp_path)
    keys = {f"KEY_{i}": {"input_derivable": "unsolved", "confidence": "low"} for i in range(20)}
    _write(uo / "ir" / "input_derivable.yaml", {"keys": keys})
    _write(
        uo / "ir" / "input_derivable_gaps.yaml",
        {"gaps": [{"id": k, "status": "open"} for k in keys]},
    )
    lines = ["# 置信度", ""]
    for k in keys:
        lines.extend(
            [
                f"### {k}",
                "- 原因：跨编译边界 bit-pack 无法回溯",
                "",
            ]
        )
    _write(uo / "summary" / "confidence_report.md", "\n".join(lines))
    _write(
        uo / "checks" / "confidence_gate.yaml",
        {"status": "reported", "closed_high_count": 0, "need_llm_count": 20},
    )
    _write(uo / "review" / "kb_product_review.yaml", {"verdict": "pass", "closed_high_count": 0, "need_llm_count": 20})
    payload = run_key_gates(tmp_path)
    assert payload["ok"] is False
    failed = {g["gate"] for g in payload["gates"] if not g.get("ok")}
    assert "key_triage_required" in failed
    assert "confidence_closed_high" in failed or "key_report_quality" in failed
    assert "confidence_reason_review" in failed


def test_complete_workflow_blocked_on_key_gates(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="review")
    uo = uo_root(tmp_path)
    _write(
        uo / "ir" / "input_derivable.yaml",
        {"keys": {"KEY_A": {"input_derivable": "unsolved", "confidence": "low"}}},
    )
    _write(
        uo / "ir" / "input_derivable_gaps.yaml",
        {"gaps": [{"id": "KEY_A", "status": "open"}]},
    )
    result = complete_workflow(tmp_path)
    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert load_state(tmp_path)["status"] == "blocked"


def test_memory_and_context(tmp_path: Path):
    start_workflow(tmp_path, "uo-query", phase="answer")
    e = add_candidate(tmp_path, topic="tilingkey", kind="fact", content="Host GetTilingKey has IsNzOut predicate")
    promote_stable(tmp_path, e["id"], verified_by="test")
    hits = search_local(tmp_path, topic="tilingkey", limit=3)
    assert hits
    pack = build_context_pack(tmp_path, intent="uo-query", topic="tilingkey")
    assert pack["memory"]
    # private source blocked from global promote
    bad = add_candidate(
        tmp_path,
        topic="src",
        kind="fact",
        content="```\n" + ("int x;\n" * 80) + "```\nD:\\code\\op.cpp",
    )
    promote_stable(tmp_path, bad["id"], verified_by="test")
    prop = propose_global_promote(tmp_path, bad["id"])
    assert prop.get("ok") is False
