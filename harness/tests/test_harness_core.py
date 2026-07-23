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
    assert route("/uo-diff").get("ok") is False
    op = route("/operator 帮我建库")
    assert op.get("ok") is True and op.get("workflow_id") == "uo-init" and op.get("via") == "operator"
    assert route("/operator").get("ok") is False


def test_state_machine_and_no_progress(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    record_gate(tmp_path, "g1", ok=False)
    record_gate(tmp_path, "g1", ok=False)
    record_gate(tmp_path, "g1", ok=False)
    assert no_progress_exceeded(tmp_path, limit=3)
    st = load_state(tmp_path)
    assert st["workflow_id"] == "uo-init"
    assert st["status"] == "blocked"


def test_start_rejects_arbitrary_phase(tmp_path: Path):
    with pytest.raises(RuntimeError, match="entry_state"):
        start_workflow(tmp_path, "uo-init", phase="resolve")


def test_start_uses_entry_and_next(tmp_path: Path):
    from ascendc_harness.state import describe_next

    st = start_workflow(tmp_path, "uo-init")
    assert st["phase"] == "prepare"
    assert st["phase_label_zh"] == "环境准备"
    assert st["status"] == "running"
    nxt = describe_next(tmp_path)
    assert nxt["ok"] is True
    assert nxt["phase"] == "prepare"


def test_mark_terminal_pass_refused_without_complete(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="review", force_phase=True)
    with pytest.raises(RuntimeError, match="complete_workflow"):
        mark_terminal(tmp_path, "pass")
    with pytest.raises(RuntimeError, match="complete_workflow"):
        mark_terminal(tmp_path, "passed")


def test_advance_gate_fail_keeps_phase_rework(tmp_path: Path):
    from ascendc_harness.state import advance_phase

    start_workflow(tmp_path, "uo-init")
    # prepare → scope has empty phase_gates; skip to scope then fail scope gate
    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    result = advance_phase(tmp_path, "extract")
    assert result["ok"] is False
    st = load_state(tmp_path)
    assert st["phase"] == "scope"
    assert st["status"] in {"human_required", "rework_required"}


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


def test_complete_workflow_rework_on_key_gates(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="review", force_phase=True)
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
    assert result["status"] == "rework_required"
    assert load_state(tmp_path)["status"] == "rework_required"
    assert load_state(tmp_path)["phase"] == "review"


def test_plan_approved_reads_human_supplement(tmp_path: Path):
    from ascendc_harness.gates.tg_adapters import gate_plan_approved
    from ascendc_harness.paths import tg_root

    tg = tg_root(tmp_path)
    level = tg / "plan" / "levels" / "L0"
    level.mkdir(parents=True)
    _write(tg / "plan" / "latest_level.yaml", {"level": "L0"})
    _write(level / "coverage_obligations.yaml", {"obligations": []})
    _write(level / "plan.yaml", {"snapshot_hash": "abc", "plan_hash": "def"})
    _write(
        level / "human_supplement.yaml",
        {
            "status": "approved",
            "decision": "approve",
            "approved_snapshot_hash": "abc",
            "approved_plan_hash": "def",
            "approved_at": "2026-01-01T00:00:00Z",
            "supplements": [],
            "notes": "ok",
        },
    )
    _write(
        level / "unresolved.yaml",
        {
            "status": "ready_for_manual_review",
            "allow_solve": True,
            "allow_solve_reason": "ok",
            "blocking_hard_obligations": [],
            "contract_gaps": [],
        },
    )
    r = gate_plan_approved(tmp_path)
    assert r["ok"] is True


def test_spec_hashes_four_kinds():
    from ascendc_harness.spec_hashes import all_spec_hashes

    repo = Path(__file__).resolve().parents[2]
    hashes = all_spec_hashes(repo, workflow_id="uo-init")
    assert set(hashes) == {
        "kb_schema_hash",
        "workflow_spec_hash",
        "agent_contract_hash",
        "tg_contract_hash",
    }
    assert all(isinstance(v, str) and len(v) == 64 for v in hashes.values())
    # Chinese label change must not be required to recompute kb hash content here —
    # workflow_spec_hash excludes label_zh by construction.
    assert hashes["workflow_spec_hash"] != hashes["kb_schema_hash"]


def test_kb_fingerprint_not_uo_ready_alias(tmp_path: Path):
    from ascendc_harness.gates import run_named_gate

    r = run_named_gate(tmp_path, "kb_fingerprint")
    assert r.get("gate") == "kb_fingerprint"
    # Must not silently pass via uo_ready alias when TG/UO empty
    assert r.get("ok") is False


def test_e2e_cli_loop_prepare_to_scope_rework(tmp_path: Path):
    """CLI-shaped loop: start → next → advance fail → rework_required (not blocked)."""
    from ascendc_harness.state import advance_phase, describe_next, rework_phase, start_workflow
    from ascendc_harness.paths import uo_root

    st = start_workflow(tmp_path, "uo-init")
    assert st["phase"] == "prepare"
    nxt = describe_next(tmp_path)
    assert nxt["status"] == "running"
    # prepare has empty gates → can advance to scope
    ok = advance_phase(tmp_path, "scope")
    assert ok["ok"] is True
    assert load_state(tmp_path)["phase"] == "scope"
    # scope gate fails without confirmation
    fail = advance_phase(tmp_path, "extract")
    assert fail["ok"] is False
    assert load_state(tmp_path)["phase"] == "scope"
    assert load_state(tmp_path)["status"] in {"human_required", "rework_required"}
    assert load_state(tmp_path)["status"] != "blocked"
    # Force phase extract then rework to scope
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    rw = rework_phase(tmp_path, reason_code="SCOPE_REWORK")
    assert rw["ok"] is True
    assert load_state(tmp_path)["phase"] == "scope"


def test_authorize_harness_only():
    from ascendc_harness.authorize import authorize

    assert authorize(tool="bash", command="harness next --project .").get("ok") is True
    deny = authorize(tool="bash", command="python engines/uo/uo/scripts/build_layered_kb.py")
    assert deny.get("ok") is False
    assert deny.get("decision") in {"deny", "ask"}
    write_deny = authorize(tool="write", path="/tmp/.ascendc-agent/uo/ir/input_derivable.yaml")
    assert write_deny.get("decision") == "deny"


def test_compile_skills_smoke():
    import sys

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "scripts"))
    from compose_runtime import compose_all

    result = compose_all(repo, hosts=["opencode"])
    assert result["ok"]
    assert (repo / "generated" / "opencode" / "skills" / "operator" / "SKILL.md").is_file()
    assert (repo / "generated" / "opencode" / "agents" / "ascendc-agent.md").is_file()
    text = (repo / "generated" / "opencode" / "skills" / "uo-init" / "SKILL.md").read_text(encoding="utf-8")
    assert "harness-control" in text
    assert "Composition index" in text


def test_memory_and_context(tmp_path: Path):
    start_workflow(tmp_path, "uo-query", phase="answer", force_phase=True)
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


def test_actions_for_phase_strict_binding(tmp_path: Path):
    from ascendc_harness.state import describe_next
    from ascendc_harness.workflows import actions_for_phase

    prepare = actions_for_phase("uo-init", "prepare")
    assert [a["id"] for a in prepare] == ["prepare_layout"]
    scope = actions_for_phase("uo-init", "scope")
    assert [a["id"] for a in scope] == ["scope_confirmation"]
    empty = actions_for_phase("uo-init", "nonexistent_phase")
    assert empty == []
    start_workflow(tmp_path, "uo-init")
    nxt = describe_next(tmp_path)
    assert [a["id"] for a in nxt["allowed_actions"]] == ["prepare_layout"]
    assert nxt["phase_label_zh"] == "环境准备"


def test_complete_uo_query_no_implicit_key_gates(tmp_path: Path):
    """uo-query must not inherit uo-init KEY complete gates by prefix."""
    start_workflow(tmp_path, "uo-query", phase="answer", force_phase=True)
    record_gate(tmp_path, "kb_ready", ok=True)
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"op_name": "Demo"})
    _write(uo / "checks" / "integrity.yaml", {"status": "pass"})
    result = complete_workflow(tmp_path)
    if not result.get("ok"):
        lf = load_state(tmp_path).get("last_failure") or {}
        assert lf.get("reason_code") != "KEY_GATES_FAILED"
        assert "key_gates" not in result


def test_complete_rejects_open_obligations(tmp_path: Path):
    start_workflow(tmp_path, "uo-query", phase="answer", force_phase=True)
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"op_name": "Demo"})
    _write(uo / "checks" / "integrity.yaml", {"status": "pass"})
    result = complete_workflow(tmp_path)
    if result.get("ok"):
        assert load_state(tmp_path)["status"] == "passed"
        assert load_state(tmp_path).get("open_items") == []
    else:
        assert result["status"] in {"rework_required", "human_required", "blocked"}
        assert load_state(tmp_path)["status"] != "passed"


def test_authorize_action_and_role(tmp_path: Path):
    from ascendc_harness.authorize import authorize

    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    bad_action = authorize(
        tmp_path,
        tool="write",
        path=str(tmp_path / ".ascendc-agent" / "uo" / "ir" / "x.yaml"),
        agent="uo-key-resolve",
        action="prepare_layout",
    )
    assert bad_action.get("decision") == "deny"
    assert bad_action.get("reason_code") == "ACTION_NOT_ALLOWED"

    ok = authorize(
        tmp_path,
        tool="write",
        path=str(tmp_path / ".ascendc-agent" / "uo" / "ir" / "input_derivable_patch.yaml"),
        agent="uo-key-resolve",
        action="key_resolution",
    )
    assert ok.get("decision") == "allow"

    primary = authorize(
        tmp_path,
        tool="write",
        path=str(tmp_path / ".ascendc-agent" / "uo" / "ir" / "x.yaml"),
        agent="ascendc-agent",
        action="key_resolution",
    )
    assert primary.get("decision") == "deny"


def test_verify_receipt_strict(tmp_path: Path):
    from ascendc_harness.runs import issue_receipt, verify_receipt
    from ascendc_harness.spec_hashes import workflow_spec_hash

    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    wf = workflow_spec_hash("uo-init")
    issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="uo-key-resolve",
        action_id="key_resolution",
        workflow_spec_hash=wf,
        input_hashes={"triage": "abc"},
        output_hashes={"patch": "def"},
        checker_result={"ok": True},
        _internal=True,
    )
    ok = verify_receipt(
        tmp_path,
        actor_id="uo-key-resolve",
        action_id="key_resolution",
        require_hashes=True,
        require_action_id=True,
        require_spec_hash=True,
    )
    assert ok.get("ok") is True
    bad = verify_receipt(
        tmp_path,
        actor_id="uo-key-resolve",
        action_id="wrong_action",
        require_action_id=True,
    )
    assert bad.get("ok") is False


def test_spec_hashes_not_empty():
    from ascendc_harness.spec_hashes import all_spec_hashes

    repo = Path(__file__).resolve().parents[2]
    hashes = all_spec_hashes(repo)
    assert "empty" not in hashes["kb_schema_hash"]
    assert "empty" not in hashes["agent_contract_hash"]
    assert "empty" not in hashes["tg_contract_hash"]


def test_uo_diff_route_removed():
    r = route("/uo-diff")
    assert r.get("ok") is False
    assert r.get("workflow_id") is None


def test_tg_kb_ready_no_fingerprint_gate():
    from ascendc_harness.workflows import get_workflow

    meta = get_workflow("tg-init")
    assert "kb_fingerprint_fresh" not in (meta.get("phase_gates") or {}).get("kb_ready", [])
    assert "uo_ready" in (meta.get("phase_gates") or {}).get("kb_ready", [])
    assert "kb_fingerprint_fresh" in (meta.get("phase_gates") or {}).get("confirm", [])


def test_install_skill_lists_symmetric():
    repo = Path(__file__).resolve().parents[2]
    ps1 = (repo / "install.ps1").read_text(encoding="utf-8")
    sh = (repo / "install.sh").read_text(encoding="utf-8")
    assert 'foreach ($name in @("uo-init","uo-update","uo-query","uo-code-review","tg-init","tg-plan","tg-solve","operator"))' in ps1
    assert "for name in uo-init uo-update uo-query uo-code-review tg-init tg-plan tg-solve operator; do" in sh
    for retired in ("uo-diff", "tg-domain-review", "tg-contract"):
        assert retired not in ps1
        assert retired not in sh
    assert "ascendc-agent" in ps1
    assert "ascendc-harness.ts" in ps1
    assert "ascendc-harness.ts" in sh
    assert "tg-semantic-bind" in ps1
    assert "tg-semantic-bind" in sh
