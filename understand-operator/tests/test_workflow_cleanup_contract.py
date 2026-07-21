from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ACTIVE_TEXT_DIRS = ("agents", "prompts", "skills/uo-init")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _active_text() -> dict[str, str]:
    result: dict[str, str] = {}
    for dirname in ACTIVE_TEXT_DIRS:
        for path in (ROOT / dirname).rglob("*.md"):
            result[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return result


def test_no_active_prompt_mentions_yaml_batch() -> None:
    forbidden = ("write YAML batch", "temporary YAML", "YAML batch")
    hits = [
        f"{rel}: {term}"
        for rel, text in _active_text().items()
        for term in forbidden
        if term.lower() in text.lower()
    ]
    assert hits == []


def test_no_active_prompt_mentions_merge_fact_entries() -> None:
    assert all("merge_fact_entries" not in text for text in _active_text().values())


def test_no_active_prompt_tells_model_to_write_ids_or_hashes() -> None:
    forbidden = (
        "provide IDs",
        "embed source anchors",
        "compute source_text",
        "compute code_hash",
        "compute file_hash",
        "replace entries by ID",
        "write five files",
        "nine files together",
    )
    hits = [
        f"{rel}: {term}"
        for rel, text in _active_text().items()
        for term in forbidden
        if term.lower() in text.lower()
    ]
    assert hits == []


def test_layered_milestones_exist() -> None:
    workflow = _read("skills/uo-init/SKILL.md")
    for title in (
        "创建知识库目录",
        "扫描并提案分析范围",
        "等待确认分析范围",
        "窄索引代码图并完成范围收尾",
        "抽取 Host/Kernel/桥接（含入口确认 + extract_plan）",
        "有界语义补全（残留 unresolved）",
        "KB 产物审查（uo-kb-review）",
    ):
        assert title in workflow
    assert "macro_scope" in workflow or "review_checkpoint.py" in workflow
    assert "check_kb_integrity" in workflow
    assert "uo-kb-review" in workflow
    assert "HARD STOP" in workflow or "硬门禁" in workflow
    assert "export_human_views.py" in workflow
    assert "--profile lean" in workflow
    assert "--replace-initial" in workflow


def test_orchestrator_matches_uo_init() -> None:
    source = _read("skills/uo-init/SKILL.md")
    orchestrator = _read("prompts/01_workflow_orchestrator.md")
    required = (
        "prepare_operator.py",
        "macro_scope_scan.py",
        "review_checkpoint.py",
        "finalize_phase0.py",
        "resolve_entrypoints.py",
        "propose_extract_plan.py",
        "apply_extract_plan.py",
        "build_layered_kb.py",
        "uo-semantic-resolve",
        "apply_resolution.py",
        "kb_query_export.py",
        "check_kb_integrity",
        "uo-kb-review",
    )
    missing = [item for item in required if item not in source or item not in orchestrator]
    assert missing == []


def test_phase0_human_review_is_hard_gate() -> None:
    combined = "\n".join(
        [
            _read("skills/uo-init/SKILL.md"),
            _read("prompts/01_workflow_orchestrator.md"),
            _read("prompts/00_review_menu.md"),
            _read("prompts/01a_macro_scope_human_review.md"),
        ]
    )
    assert "macro_scope" in combined
    assert "AskQuestion" in combined or "question UI" in combined
    assert "continue" in combined and "revise" in combined and "stop" in combined
    assert "never auto" in combined.lower() or "must not be skipped" in combined.lower() or "Never invent a silent" in combined


def test_subagent_dispatch_reuses_stable_identity() -> None:
    dispatch = _read("prompts/00_subagent_dispatch.md")
    orchestrator = _read("prompts/01_workflow_orchestrator.md")
    workflow = _read("skills/uo-init/SKILL.md")
    combined = "\n".join([dispatch, orchestrator, workflow])

    assert "<run_id>:<phase-or-step>:<owner>:<target-path-or-slice-id>" in dispatch
    assert "Resume that same\nsubagent context" in dispatch
    assert "Do not open another task window for the same identity" in dispatch
    assert "SUBAGENT_RESUME_UNAVAILABLE" in combined
    assert "uo-semantic-resolve" in combined


def test_residual_dispatch_locks_schema_and_sampling() -> None:
    dispatch = _read("prompts/00_subagent_dispatch.md")
    agent = _read("agents/uo-semantic-resolve.md")
    workflow = _read("skills/uo-init/SKILL.md")
    orchestrator = _read("prompts/01_workflow_orchestrator.md")
    combined = "\n".join([dispatch, agent, workflow, orchestrator])

    assert "mandatory residual dispatch template" in dispatch.lower() or "Residual resolve dispatch" in dispatch
    assert "unresolved_resolutions" in agent
    assert "At most 12" in agent or "at most 12" in agent.lower()
    assert "residuals:" in agent  # forbidden list mentions it
    assert "resolution: warning" in agent
    assert "apply_resolution.py" in combined and "--check" in combined
    assert "Do NOT hand-count" in dispatch or "hand-count" in agent
    # Parent must not invent alternate top-level schemas in resolve prompts.
    assert "Do not invent" in workflow or "do not invent" in workflow.lower()


def test_all_subagents_resolve_prompts_from_prompt_dir() -> None:
    missing: list[str] = []
    for path in (ROOT / "agents").glob("uo-*.md"):
        text = path.read_text(encoding="utf-8")
        if "PROMPT_DIR" not in text or "Do not resolve" not in text:
            missing.append(path.relative_to(ROOT).as_posix())
    assert missing == []


def test_no_phase35_or_phase4_workflow() -> None:
    text = "\n".join(_active_text().values())
    assert "Phase 3.5" not in text
    assert "Phase 4" not in text


def test_retired_phase_agents_absent() -> None:
    retired = (
        "agents/uo-boundary-agent.md",
        "agents/uo-host-extraction.md",
        "agents/uo-flow-extraction.md",
        "agents/uo-kernel-slice-agent.md",
        "prompts/02a_boundary_human_review.md",
        "prompts/02_macro_boundary_agent.md",
        "prompts/common/11_phase1_candidate_authoring.md",
    )
    assert [rel for rel in retired if (ROOT / rel).exists()] == []


def test_active_agents_include_kb_review() -> None:
    agents = sorted(p.name for p in (ROOT / "agents").glob("uo-*.md"))
    assert agents == ["uo-code-reviewer.md", "uo-kb-review.md", "uo-semantic-resolve.md"]


def test_kb_review_dispatch_template_exists() -> None:
    dispatch = _read("prompts/00_subagent_dispatch.md")
    assert "KB product review dispatch" in dispatch
    assert "uo-kb-review" in dispatch
    assert "rework_stage" in dispatch
    assert "kb_product_review.yaml" in dispatch
