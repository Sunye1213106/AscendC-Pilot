"""Prepare fills prompt placeholders and emits a short task_prompt_stub."""

from __future__ import annotations

from pathlib import Path

import pytest

from ascendc_pilot.actions.runtime import (
    _build_task_prompt_stub,
    _render_placeholders,
    prepare_action,
)
from ascendc_pilot.paths import ensure_agent_layout, uo_root
from ascendc_pilot.state import start_workflow


def test_render_placeholders_fills_roots() -> None:
    text = (
        "run=<RUN_ID> root=<PROJECT_ROOT> uo=<UO_ROOT> tg=<TG_ROOT> "
        "topic=<TOPIC> pack=<CONTEXT_PACK_PATH> op=<OP_NAME> target=<TARGET_IDS_OR_FILES>"
    )
    out = _render_placeholders(
        text,
        run_id="RUN_1",
        action_id="extract_plan",
        workflow_id="uo-init",
        actor_id="uo-semantic-resolve",
        project_root="D:/op",
        uo_root="D:/op/.ascendc-pilot/uo",
        tg_root_path="D:/op/.ascendc-pilot/tg",
        topic="extract_plan",
        context_pack_path="D:/op/.ascendc-pilot/context/context_pack.yaml",
        op_name="demo",
        target="candidates only",
    )
    assert "RUN_1" in out
    assert "D:/op/.ascendc-pilot/uo" in out
    assert "UNRESOLVED" not in out
    assert "candidates only" in out


def test_task_prompt_stub_is_pointer_only() -> None:
    stub = _build_task_prompt_stub(
        actor_id="uo-semantic-resolve",
        action_id="extract_plan",
        run_id="RUN_1",
        session_dir="/s",
        prompt_path="/s/prompt.md",
        method_path="/s/method.md",
        bundle_path="/s/bundle.yaml",
        dispatch_targets={
            "read": ["uo/ir/extract_plan_candidates.yaml"],
            "write": ["uo/ir/extract_plan.yaml"],
            "forbid_read": ["uo/ir/llm_tasks.yaml"],
        },
    )
    assert "prompt.md" in stub
    assert "forbid_read" in stub
    assert "llm_tasks" in stub
    assert "METHOD" not in stub or "Do NOT" in stub
    # No *.summary.yaml in read → public MUST_READ_ORDER not injected.
    assert "MUST_READ_ORDER" not in stub


def test_kb_lookup_stub_requires_answer_yaml_not_integrity() -> None:
    stub = _build_task_prompt_stub(
        actor_id="uo-query",
        action_id="kb_lookup",
        run_id="RUN_Q",
        session_dir="/s",
        prompt_path="/s/prompt.md",
        method_path="/s/method.md",
        bundle_path="/s/bundle.yaml",
        write_paths=[
            "runs/RUN_Q/actions/kb_lookup/answer.yaml",
            "runs/RUN_Q/actions/kb_lookup/scratch/**",
        ],
        user_question="TND 下 SplitAxis=1 是否合法？",
    )
    assert "USER QUESTION" in stub
    assert "SplitAxis=1" in stub
    assert "kb-answer-v1" in stub
    assert "return_value" in stub
    assert "uo/checks" in stub
    assert "Do NOT write uo/checks" in stub
    assert "Hard stop" in stub
    assert "uo-query≤12" in stub
    assert "evidence-window" in stub
    write_line = next((ln for ln in stub.splitlines() if ln.startswith("write:")), "")
    assert write_line.startswith("write: (none")
    assert "runs/" not in write_line
    assert "fallback" in stub.lower()


def test_task_prompt_stub_injects_must_read_order_for_summary() -> None:
    stub = _build_task_prompt_stub(
        actor_id="uo-semantic-resolve",
        action_id="extract_plan",
        run_id="RUN_1",
        session_dir="/s",
        prompt_path="/s/prompt.md",
        method_path="/s/method.md",
        bundle_path="/s/bundle.yaml",
        dispatch_targets={
            "read": [
                "uo/ir/extract_plan_candidates.summary.yaml",
                "uo/ir/extract_plan.rework_hints.yaml",
                "uo/ir/extract_plan_candidates.yaml",
            ],
            "write": ["uo/ir/extract_plan.yaml"],
        },
    )
    assert "MUST_READ_ORDER" in stub
    assert "extract_plan_candidates.summary.yaml" in stub
    # SHA / evidence / neighbor rules are action-specific; MUST_READ_ORDER is the contract.


def test_task_prompt_stub_must_read_order_is_action_agnostic() -> None:
    stub = _build_task_prompt_stub(
        actor_id="uo-semantic-resolve",
        action_id="adjudicate_llm_tasks",
        run_id="RUN_1",
        session_dir="/s",
        prompt_path="/s/prompt.md",
        method_path="/s/method.md",
        bundle_path="/s/bundle.yaml",
        dispatch_targets={
            "read": ["uo/ir/llm_tasks.summary.yaml", "uo/ir/llm_tasks.yaml"],
            "write": ["uo/ir/semantic_patches.yaml"],
        },
    )
    assert "MUST_READ_ORDER" in stub
    assert "llm_tasks.summary.yaml" in stub
    assert "evidence_tools:" not in stub  # extract_plan-only contract


@pytest.mark.skip(reason="extract_plan removed; extract pipeline starts at extract_host")
def test_prepare_extract_plan_writes_filled_prompt(tmp_path: Path, monkeypatch) -> None:
    """Integration-ish: prepare on extract phase fills UO_ROOT and stub file."""
    from ascendc_pilot.runs import issue_receipt
    from ascendc_pilot.spec_hashes import workflow_spec_hash

    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-init", phase="extract", force_phase=True, architecture="arch35")
    # Minimal entrypoint graph so propose may still run / or we stub engine
    uo = uo_root(op)
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    (uo / "ir" / "entrypoint_graph.yaml").write_text(
        "version: 1\nnodes: []\nedges: []\n",
        encoding="utf-8",
    )
    # Satisfy extract pipeline progress so recommended_next is extract_plan
    (uo / "ir" / "score_report_pre.yaml").write_text("version: 1\nok: true\n", encoding="utf-8")
    (uo / "ir" / "llm_tasks.yaml").write_text("version: 1\ntasks: []\n", encoding="utf-8")
    issue_receipt(
        op,
        actor_type="deterministic_engine",
        actor_id="deterministic-uo-engine",
        action_id="detect_score_pre",
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"f": "1"},
        output_hashes={"f": "1"},
        checker_result={"ok": True},
        nonce="pre",
        _internal=True,
    )

    # Avoid heavy propose: patch invoke_engine for extract_plan propose
    from ascendc_pilot.actions import runtime as rt

    def fake_invoke(project_root, wid, action_id, ctx=None):
        cand = uo_root(project_root) / "ir" / "extract_plan_candidates.yaml"
        cand.write_text("version: 1\nwriter_candidates: []\n", encoding="utf-8")
        return {
            "ok": True,
            "phase": "propose",
            "candidates_path": cand.as_posix(),
        }

    monkeypatch.setattr(rt, "invoke_engine", fake_invoke)
    # Also patch module-level import path used inside prepare
    import ascendc_pilot.actions.engines as eng

    monkeypatch.setattr(eng, "invoke_engine", fake_invoke)

    result = prepare_action(op, "extract_plan")
    assert result.get("ok") is True, result
    prompt_path = Path(str(result["prompt_path"]))
    text = prompt_path.read_text(encoding="utf-8")
    assert "UNRESOLVED" not in text
    assert str(op.resolve().as_posix()) in text or op.name in text
    assert ".ascendc-pilot/uo" in text.replace("\\", "/")
    stub = str(result.get("task_prompt_stub") or "")
    assert "prompt.md" in stub
    assert (Path(str(result["session_dir"])) / "task_prompt_stub.md").is_file()
    assert "llm_tasks" in stub


def test_prepare_kb_lookup_writes_method_and_return_value_hint(tmp_path: Path) -> None:
    """kb_lookup prepare: METHOD playbook + return_value finalize hint."""
    import yaml

    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    uo_prod = op / ".ascendc-pilot" / "uo"
    uo_prod.mkdir(parents=True, exist_ok=True)
    (uo_prod / "Demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    start_workflow(
        op,
        "uo-query",
        architecture="arch35",
        intent="TND 布局下 SplitAxis=1 是否合法？",
    )
    result = prepare_action(op, "kb_lookup")
    assert result.get("ok") is True, result
    stub = str(result.get("task_prompt_stub") or "")
    assert "kb-answer-v1" in stub
    assert "return_value" in stub
    assert "SplitAxis=1" in stub
    assert "Do NOT write uo/checks" in stub
    assert "write: (none" in stub
    msg = str(result.get("message_zh") or "")
    assert "finalize" in msg
    assert result.get("finalize_hint") == "acp run-action kb_lookup --finalize"
    assert "result-file" in str(result.get("finalize_hint_fallback") or "")
    session = Path(str(result["session_dir"]))
    method = (session / "method.md").read_text(encoding="utf-8")
    assert "claim" in method.lower() or "Claim" in method
    assert "12" in method
    assert "22" in method
    bundle = yaml.safe_load((session / "bundle.yaml").read_text(encoding="utf-8"))
    assert bundle.get("output_mode") == "return_value"
    writes = [str(p).replace("\\", "/") for p in (bundle.get("allowed_write_paths") or [])]
    assert any(p.endswith("kb_lookup/answer.yaml") for p in writes)
    prompt = Path(str(result["prompt_path"])).read_text(encoding="utf-8")
    assert "## User question" in prompt
    assert "SplitAxis=1" in prompt


def test_uo_query_agent_has_empty_write_scopes() -> None:
    """A2: Explorer does not Write; Runtime materializes kb-answer."""
    from ascendc_pilot.agents_registry import agent_write_scopes

    root = Path(__file__).resolve().parents[2]
    scopes = agent_write_scopes("uo-query", root)
    assert scopes == []


def test_finalize_kb_lookup_from_result_file(tmp_path: Path) -> None:
    """return_value: finalize materializes answer.yaml from --result-file."""
    import yaml

    from ascendc_pilot.actions.runtime import finalize_action
    from ascendc_pilot.paths import agent_root

    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    uo_prod = op / ".ascendc-pilot" / "uo"
    uo_prod.mkdir(parents=True, exist_ok=True)
    (uo_prod / "Demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    start_workflow(op, "uo-query", architecture="arch35", intent="q?")
    prep = prepare_action(op, "kb_lookup")
    assert prep.get("ok"), prep
    result_path = tmp_path / "kb-answer.yaml"
    result_path.write_text(
        yaml.safe_dump(
            {
                "schema": "kb-answer-v1",
                "status": "ANSWERED",
                "question": "q?",
                "answer_zh": "合法（有条件）。",
                "citations": [{"path": "op_host/x.cpp", "lines": "1-2"}],
                "adequacy": "ANSWERED",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    fin = finalize_action(op, "kb_lookup", result_file=result_path)
    assert fin.get("ok") is True, fin
    answer = (
        agent_root(op, "arch35")
        / f"runs/{prep['run_id']}/actions/kb_lookup/answer.yaml"
    )
    assert answer.is_file()
    body = yaml.safe_load(answer.read_text(encoding="utf-8"))
    assert body.get("schema") == "kb-answer-v1"
    assert "合法" in str(body.get("answer_zh") or "")
    assert body.get("_transport") == "return_value"
    # Trusted stamp is injected by finalize after contract check.
    assert (body.get("artifact_identity") or {}).get("produced_by") == "pilot-finalizer"
