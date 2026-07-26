"""Prepare fills prompt placeholders and emits a short task_prompt_stub."""

from __future__ import annotations

from pathlib import Path

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
    assert "section_lines" in stub
    assert "readonly_search" in stub
    assert "extract_plan_candidates.summary.yaml" in stub


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


def test_prepare_extract_plan_writes_filled_prompt(tmp_path: Path, monkeypatch) -> None:
    """Integration-ish: prepare on extract phase fills UO_ROOT and stub file."""
    from ascendc_pilot.runs import issue_receipt
    from ascendc_pilot.spec_hashes import workflow_spec_hash

    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "uo-init", phase="extract", force_phase=True)
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
