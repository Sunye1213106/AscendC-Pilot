"""Pilot unit tests including ses_076d KEY gate fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_pilot.context import build_context_pack
from ascendc_pilot.gates import (
    gate_confidence_closed_high,
    gate_confidence_reason_review,
    gate_confidence_report_quality,
    gate_empty_only_producer,
    gate_key_triage_required,
    reject_key_patch_batch,
    run_key_gates,
)
from ascendc_pilot.memory import add_candidate, promote_stable, propose_global_promote, search_local
from ascendc_pilot.paths import tg_root, uo_root
from ascendc_pilot.router import route
from ascendc_pilot.state import (
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


def test_router_slash_only_no_nl_keywords():
    """Generic NL is not keyword-routed; caller uses the orchestration skill."""
    assert route("/uo-init foo").get("workflow_id") == "uo-init"
    assert route("/tg-plan").get("workflow_id") == "tg-plan"
    assert route("uo-init").get("workflow_id") == "uo-init"
    # Natural language must NOT be keyword-routed by the script
    nl = route("为 flash_attention_score_grad 算子建立本地知识库，只分析 arch35")
    assert nl.get("ok") is False
    assert nl.get("error") == "use_orchestration_skill"
    assert nl.get("workflow_id") in {None, ""}
    assert "uo-init" in (nl.get("candidates") or [])
    assert nl.get("message_zh")
    assert route("帮我建库初始化知识库").get("ok") is False
    assert route("完全无关的话").get("error") == "use_orchestration_skill"
    assert route("/uo-diff").get("ok") is False
    goal = route("建立 TilingKey 全覆盖测试")
    assert goal.get("ok") is False and goal.get("error") == "use_orchestration_skill"
    ce = route("验证这次改动")
    assert ce.get("ok") is False and not ce.get("workflow_id")
    op = route("/operator /uo-init")
    assert op.get("ok") is True and op.get("workflow_id") == "uo-init" and op.get("via") == "operator"
    assert route("/operator 帮我建库").get("ok") is False
    assert route("/operator").get("ok") is False


def test_state_machine_and_no_progress(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="analyze", force_phase=True, architecture="arch35")
    record_gate(tmp_path, "g1", ok=False)
    record_gate(tmp_path, "g1", ok=False)
    record_gate(tmp_path, "g1", ok=False)
    assert no_progress_exceeded(tmp_path, limit=3)
    st = load_state(tmp_path)
    assert st["workflow_id"] == "uo-init"
    assert st["status"] == "blocked"


def test_start_rejects_arbitrary_phase(tmp_path: Path):
    with pytest.raises(RuntimeError, match="entry_state"):
        start_workflow(tmp_path, "uo-init", phase="analyze", architecture="arch35")


def test_start_uses_entry_and_next(tmp_path: Path):
    from ascendc_pilot.state import describe_next

    st = start_workflow(tmp_path, "uo-init", architecture="arch35")
    assert st["phase"] == "prepare"
    assert st["phase_label_zh"] == "准备 BuildVariant / 范围"
    assert st["status"] == "running"
    nxt = describe_next(tmp_path)
    assert nxt["ok"] is True
    assert nxt["phase"] == "prepare"


def test_mark_terminal_pass_refused_without_complete(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="verify", force_phase=True, architecture="arch35")
    with pytest.raises(RuntimeError, match="complete_workflow"):
        mark_terminal(tmp_path, "pass")
    with pytest.raises(RuntimeError, match="complete_workflow"):
        mark_terminal(tmp_path, "passed")


def test_advance_gate_fail_keeps_phase_rework(tmp_path: Path):
    from ascendc_pilot.state import advance_phase
    from ascendc_pilot.runs import issue_receipt
    from ascendc_pilot.spec_hashes import workflow_spec_hash

    start_workflow(tmp_path, "uo-init", phase="analyze", force_phase=True, architecture="arch35")
    # Analyze pipeline must complete before advancing to commit.
    st = load_state(tmp_path)
    issue_receipt(
        tmp_path,
        actor_type="deterministic_engine",
        actor_id="deterministic-uo-engine",
        action_id="analyze",
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"f": "1"},
        output_hashes={"f": "1"},
        checker_result={"ok": True},
        nonce="analyze-n",
        _internal=True,
    )
    result = advance_phase(tmp_path, "commit")
    # analyze has no required phase gates; advance should succeed once receipt exists
    # or fail closed on pipeline — either way phase must not skip ahead silently.
    st = load_state(tmp_path)
    if result.get("ok"):
        assert st["phase"] == "commit"
    else:
        assert st["phase"] == "analyze"
        assert st["status"] in {"human_required", "rework_required", "running"}


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
    start_workflow(tmp_path, "uo-init", phase="verify", force_phase=True, architecture="arch35")
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
    assert load_state(tmp_path)["phase"] == "verify"


def test_plan_approved_reads_plan_md(tmp_path: Path):
    from ascendc_pilot.gates.tg_adapters import gate_plan_approved
    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(tmp_path, arch="arch35")
    tg = tg_root(tmp_path, arch="arch35")
    tg.mkdir(parents=True, exist_ok=True)
    (tg / "plan.md").write_text(
        "# plan\n\n```yaml\nschema: tg-plan/v1\napproved: true\ndecision: approve\n"
        "obligations:\n  - id: o1\n    why: x\n    class: replay\n"
        "    control:\n      columns: [B]\n      recipe: set\n"
        "    hit:\n      pred: key\n    uo:\n      query: q\n    cover: L0\n```\n",
        encoding="utf-8",
    )
    r = gate_plan_approved(tmp_path)
    assert r["ok"] is True


def test_spec_hashes_four_kinds():
    from ascendc_pilot.spec_hashes import all_spec_hashes

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
    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.state import start_workflow

    start_workflow(tmp_path, "tg-init", force_phase=True, architecture="arch35")
    r = run_named_gate(tmp_path, "kb_fingerprint_fresh")
    assert r.get("gate") == "kb_fingerprint_fresh"
    # Must not silently pass via uo_ready alias when TG/UO empty
    assert r.get("ok") is False


def test_e2e_cli_loop_prepare_to_extract_rework(tmp_path: Path):
    """CLI-shaped loop: start → receipt → advance → extract → SCOPE_REWORK → prepare."""
    from ascendc_pilot.state import advance_phase, describe_next, rework_phase, start_workflow
    from ascendc_pilot.runs import issue_receipt
    from ascendc_pilot.spec_hashes import workflow_spec_hash

    st = start_workflow(tmp_path, "uo-init", architecture="arch35")
    assert st["phase"] == "prepare"
    nxt = describe_next(tmp_path)
    assert nxt["status"] == "running"
    # prepare advance requires prepare receipt + layout gate (fail-closed)
    denied = advance_phase(tmp_path, "extract")
    assert denied["ok"] is False
    assert denied.get("error") == "PIPELINE_INCOMPLETE"
    issue_receipt(
        tmp_path,
        actor_type="controller",
        actor_id="ascendc-pilot",
        action_id="prepare",
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"f": "1"},
        output_hashes={"f": "1"},
        checker_result={"ok": True},
        nonce="prep-n",
        _internal=True,
    )
    # layout_receipt checks the products too, not just the receipt.
    from ascendc_pilot.paths import uo_root

    uo = uo_root(tmp_path)
    uo.mkdir(parents=True, exist_ok=True)
    (uo / "manifest.yaml").write_text("op_name: DemoOp\n", encoding="utf-8")
    (uo / "operator.yaml").write_text("scope: op\n", encoding="utf-8")
    st = load_state(tmp_path)
    run_id = str(st.get("run_id") or "")
    scope = uo / "runs" / run_id / "scope"
    scope.mkdir(parents=True, exist_ok=True)
    (scope / "scope_validated.yaml").write_text(
        "status: confirmed\n"
        f"run_id: {run_id}\n"
        "workflow_id: uo-init\n"
        "action_id: scope_validated\n"
        "source: machine\n"
        "auto: true\n",
        encoding="utf-8",
    )
    ok = advance_phase(tmp_path, "extract")
    assert ok["ok"] is True, ok
    assert load_state(tmp_path)["phase"] == "extract"
    # Force phase extract then rework to prepare (former scope)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True, architecture="arch35")
    rw = rework_phase(tmp_path, reason_code="SCOPE_REWORK")
    assert rw["ok"] is True
    assert load_state(tmp_path)["phase"] == "prepare"


def test_authorize_acp_only():
    from ascendc_pilot.authorize import authorize

    assert authorize(tool="bash", command="acp next --project .").get("ok") is True
    deny = authorize(tool="bash", command="python engines/understand-operator/uo/scripts/build_layered_kb.py")
    assert deny.get("ok") is False
    assert deny.get("decision") in {"deny", "ask"}
    write_deny = authorize(tool="write", path="/tmp/.ascendc-pilot/uo/ir/input_derivable.yaml")
    assert write_deny.get("decision") == "deny"


def test_compile_skills_smoke():
    import sys

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "scripts"))
    from compose_runtime import compose_all

    result = compose_all(repo, hosts=["opencode"])
    assert result["ok"]
    assert not (repo / "generated" / "opencode" / "skills" / "operator" / "SKILL.md").exists()
    assert (repo / "generated" / "opencode" / "agents" / "ascendc-pilot.md").is_file()
    text = (repo / "generated" / "opencode" / "skills" / "uo-init" / "SKILL.md").read_text(encoding="utf-8")
    assert "pilot-control" in text
    assert "Composition index" in text


def test_memory_and_context(tmp_path: Path):
    start_workflow(tmp_path, "uo-query", phase="answer", force_phase=True, architecture="arch35")
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
    from ascendc_pilot.state import describe_next
    from ascendc_pilot.workflows import actions_for_phase

    prepare = actions_for_phase("uo-init", "prepare")
    assert [a["id"] for a in prepare] == ["prepare"]
    extract = actions_for_phase("uo-init", "extract")
    assert [a["id"] for a in extract] == ["extract"]
    commit = actions_for_phase("uo-init", "commit")
    assert [a["id"] for a in commit] == ["commit"]
    verify = actions_for_phase("uo-init", "verify")
    assert [a["id"] for a in verify] == ["verify"]
    empty = actions_for_phase("uo-init", "nonexistent_phase")
    assert empty == []
    assert actions_for_phase("uo-init", "resolve") == []
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    nxt = describe_next(tmp_path)
    assert [a["id"] for a in nxt["allowed_actions"]] == ["prepare"]
    assert nxt["phase_label_zh"] == "准备 BuildVariant / 范围"


def test_complete_uo_query_no_implicit_key_gates(tmp_path: Path):
    """uo-query must not inherit uo-init KEY complete gates by prefix."""
    start_workflow(tmp_path, "uo-query", phase="answer", force_phase=True, architecture="arch35")
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
    start_workflow(tmp_path, "uo-query", phase="answer", force_phase=True, architecture="arch35")
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"op_name": "Demo"})
    _write(uo / "checks" / "integrity.yaml", {"status": "pass"})
    result = complete_workflow(tmp_path)
    if result.get("ok"):
        snap = result.get("state") or {}
        assert result["status"] == "passed"
        assert snap.get("open_items") == []
        assert not load_state(tmp_path)
        assert result.get("released_execution", {}).get("released") is True
    else:
        assert result["status"] in {"rework_required", "human_required", "blocked"}
        assert load_state(tmp_path)["status"] != "passed"


def test_authorize_action_and_role(tmp_path: Path):
    from ascendc_pilot.authorize import authorize

    start_workflow(tmp_path, "uo-update", phase="apply", force_phase=True, architecture="arch35")
    bad_action = authorize(
        tmp_path,
        tool="write",
        path=str(uo_root(tmp_path) / "ir" / "x.yaml"),
        agent="deterministic-uo-engine",
        action="prepare_layout",
    )
    assert bad_action.get("decision") == "deny"
    assert bad_action.get("reason_code") == "ACTION_NOT_ALLOWED"

    ok = authorize(
        tmp_path,
        tool="write",
        path=str(uo_root(tmp_path) / "diff" / "change_set.yaml"),
        agent="deterministic-uo-engine",
        action="apply_update",
    )
    assert ok.get("decision") == "allow"

    primary = authorize(
        tmp_path,
        tool="write",
        path=str(uo_root(tmp_path) / "ir" / "x.yaml"),
        agent="ascendc-pilot",
        action="apply_update",
    )
    assert primary.get("decision") == "deny"


def test_verify_receipt_strict(tmp_path: Path):
    from ascendc_pilot.runs import issue_receipt, verify_receipt
    from ascendc_pilot.spec_hashes import workflow_spec_hash

    start_workflow(tmp_path, "uo-update", phase="apply", force_phase=True, architecture="arch35")
    wf = workflow_spec_hash("uo-update")
    issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="deterministic-uo-engine",
        action_id="apply_update",
        workflow_spec_hash=wf,
        input_hashes={"plan": "abc"},
        output_hashes={"receipt": "def"},
        checker_result={"ok": True},
        _internal=True,
    )
    ok = verify_receipt(
        tmp_path,
        actor_id="deterministic-uo-engine",
        action_id="apply_update",
        require_hashes=True,
        require_action_id=True,
        require_spec_hash=True,
    )
    assert ok.get("ok") is True
    bad = verify_receipt(
        tmp_path,
        actor_id="deterministic-uo-engine",
        action_id="wrong_action",
        require_action_id=True,
    )
    assert bad.get("ok") is False


def test_spec_hashes_not_empty():
    from ascendc_pilot.spec_hashes import all_spec_hashes

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
    from ascendc_pilot.workflows import get_workflow

    meta = get_workflow("tg-init")
    assert "kb_fingerprint_fresh" not in (meta.get("phase_gates") or {}).get("kb_ready", [])
    assert "uo_ready" in (meta.get("phase_gates") or {}).get("kb_ready", [])
    assert "kb_fingerprint_fresh" in (meta.get("phase_gates") or {}).get("confirm", [])


def test_install_skill_lists_symmetric():
    repo = Path(__file__).resolve().parents[2]
    ps1 = (repo / "install.ps1").read_text(encoding="utf-8")
    sh = (repo / "install.sh").read_text(encoding="utf-8")
    workflow = (
        "uo-init",
        "uo-update",
        "uo-query",
        "uo-investigate",
        "ce-review",
        "ce-plan",
        "ce-apply",
        "handoff",
        "tg-init",
        "tg-plan",
        "tg-solve",
    )
    wf_ps1 = next(line for line in ps1.splitlines() if line.startswith("$workflowSkills"))
    wf_sh_start = sh.index("WORKFLOW_SKILLS=(")
    wf_sh = sh[wf_sh_start : sh.index(")", wf_sh_start) + 1]
    for name in workflow:
        assert name in wf_ps1, name
        assert name in wf_sh, name
        assert name in ps1 and name in sh
    for retired in (
        "operator",
        "uo-diff",
        "tg-domain-review",
        "tg-contract",
        "ce-intent",
        "ce-impact",
        "ce-verify",
        "ce-handoff",
    ):
        assert retired not in wf_ps1
        assert retired not in wf_sh
    cog_ps1 = next(line for line in ps1.splitlines() if line.startswith("$cognitiveSkills"))
    assert "code-engineering" in cog_ps1
    assert "_shared" not in cog_ps1
    assert "code-engineering" in sh
    assert "COGNITIVE_SKILLS=" in sh
    assert "ascendc-pilot" in ps1
    assert "ascendc-pilot.ts" in ps1
    assert "ascendc-pilot.ts" in sh
    assert "tg-analyst" in ps1
    assert "tg-analyst" in sh
    assert "uo-heal-analyst" in ps1
    assert "uo-heal-analyst" in sh
    assert "uo-gap-investigator" in ps1
    assert "uo-gap-investigator" in sh
    for extra in (
        "ce-plan",
        "ce-apply",
        "handoff",
        "ce-review",
        "tg-analyst",
        "ce-applier",
        "ce-analyst",
    ):
        assert extra in ps1 and extra in sh
    assert "ce-change-referee" not in wf_ps1
    assert "ce-change-referee" not in wf_sh
    assert "XDG_CONFIG_HOME" in ps1
    assert "XDG_CONFIG_HOME" in sh
    assert "Get-AcpExe" in ps1
    assert "resolve_acp_bin" in sh
    assert "python3" in sh


def test_python_module_entrypoint_help() -> None:
    import os
    import subprocess
    import sys

    pilot = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(pilot) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "ascendc_pilot", "--help"],
        cwd=str(pilot),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    blob = f"{proc.stdout or ''}{proc.stderr or ''}".lower()
    assert "usage" in blob or "acp" in blob or "ascendc" in blob