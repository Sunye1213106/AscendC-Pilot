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
        "topic=<TOPIC> op=<OP_NAME> target=<TARGET_IDS_OR_FILES>"
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
        project_root="D:/ops/flash_attention_score_grad",
    )
    assert "USER QUESTION" in stub
    assert "SplitAxis=1" in stub
    assert "kb-answer-v1" in stub
    assert "Explore" in stub
    assert "native Task" in stub
    assert "uo/checks" in stub
    assert "Do NOT write uo/checks" in stub
    assert "Hard stop" in stub
    assert "do not stall on routing" in stub
    assert "evidence-window" in stub
    assert "--project D:/ops/flash_attention_score_grad" in stub
    write_line = next((ln for ln in stub.splitlines() if ln.startswith("write:")), "")
    assert write_line.startswith("write: (none")
    assert "runs/" not in write_line
    assert "pilot_run" in stub.lower()
    assert "acp run-action" not in stub.lower()


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
        action_id="extract",
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
    uo_prod = op / ".ascendc-pilot" / "arch35" / "uo"
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
    assert "Explore" in stub
    assert "native Task" in stub
    assert "SplitAxis=1" in stub
    assert "Do NOT write uo/checks" in stub
    assert "write: (none" in stub
    msg = str(result.get("message_zh") or "")
    assert "pilot_run" in msg
    assert "acp run-action" not in str(result.get("finalize_hint") or "")
    assert result.get("finalize_hint") == "pilot_run"
    session = Path(str(result["session_dir"]))
    method = (session / "method.md").read_text(encoding="utf-8")
    assert "Explore" in method or "file:line" in method
    assert "dim_coverage" in method
    assert "Dim=V" in method or "file:line" in method
    bundle = yaml.safe_load((session / "bundle.yaml").read_text(encoding="utf-8"))
    assert bundle.get("output_mode") == "return_value"
    writes = [str(p).replace("\\", "/") for p in (bundle.get("allowed_write_paths") or [])]
    assert not any("answer.yaml" in p for p in writes)
    prompt = Path(str(result["prompt_path"])).read_text(encoding="utf-8")
    assert "## User question" in prompt
    assert "SplitAxis=1" in prompt
    assert not result.get("dispatch_tasks")


def test_prepare_kb_lookup_does_not_fanout_on_keywords(tmp_path: Path) -> None:
    """Deep multi-domain question stays one Action; Primary LLM owns dispatch."""
    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    uo_prod = op / ".ascendc-pilot" / "arch35" / "uo"
    uo_prod.mkdir(parents=True, exist_ok=True)
    (uo_prod / "Demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    question = (
        "950 上一个 FP16 dropout 的 case，D=80，B=1 N=4 S=2048。"
        "host 算出 TilingKey 了，板上却报找不到 kernel。"
        "同一份 shape 打开确定性 TND 之后能编过、tiling 也成功，可是一进核 "
        "coreNum/s1/s2 就是垃圾。"
        "把确定性关掉又能跑完，但核占不满，只有四个 AIC 在动，"
        "msprof 里 AIC 堵着等 AIV 的 L1。"
    )
    start_workflow(op, "uo-query", architecture="arch35", intent=question)
    result = prepare_action(op, "kb_lookup")
    assert result.get("ok") is True, result
    assert not result.get("dispatch_tasks")
    session = Path(str(result["session_dir"]))
    assert not (session / "query_slices.yaml").is_file()
    stub = str(result.get("task_prompt_stub") or "")
    assert "FIRST_QUERY:" not in stub
    assert "SLICE_ID=" not in stub


def test_uo_query_agent_has_empty_write_scopes() -> None:
    """A2: Explorer does not Write; kb-answer-v1 is a dialogue contract."""
    from ascendc_pilot.agents_registry import agent_write_scopes

    root = Path(__file__).resolve().parents[2]
    scopes = agent_write_scopes("uo-query", root)
    assert scopes == []


def test_ce_reviewer_agent_has_empty_write_scopes() -> None:
    """code-review-v1 is a dialogue contract; reviewer must not persist yaml."""
    from ascendc_pilot.agents_registry import agent_write_scopes

    root = Path(__file__).resolve().parents[2]
    scopes = agent_write_scopes("ce-reviewer", root)
    assert scopes == []
