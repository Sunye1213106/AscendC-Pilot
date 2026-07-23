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


def _init_corpus() -> str:
    parts = [
        _read("skills/uo-init/SKILL.md"),
        _read("prompts/init/workflow.md"),
        _read("prompts/init/dispatch.md"),
        _read("prompts/init/progress.md"),
        _read("prompts/init/scope_menu.md"),
        _read("prompts/init/macro_scope.md"),
    ]
    for path in sorted((ROOT / "skills/uo-init/references").glob("*.md")):
        parts.append(path.read_text(encoding="utf-8"))
    for path in sorted((ROOT / "prompts/init/references").glob("*.md")):
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


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
    corpus = _init_corpus()
    for title in (
        "创建知识库目录",
        "扫描并提案分析范围",
        "等待确认分析范围",
        "索引代码图并完成范围收尾",
        "分层抽取",
        "Resolve：按",
        "KB 产物审查",
    ):
        assert title in corpus
    assert "macro_scope" in corpus or "review_checkpoint.py" in corpus
    assert "check_kb_integrity" in corpus
    assert "uo-kb-review" in corpus
    assert "硬门禁" in corpus
    assert "export_human_views" in corpus or "export_human_views.py" in corpus
    assert "kb_query_export" in corpus
    assert "--profile lean" not in corpus
    assert "--replace-initial" in corpus


def test_orchestrator_matches_uo_init() -> None:
    corpus = _init_corpus()
    required = (
        "prepare_operator",
        "macro_scope_scan",
        "review_checkpoint",
        "finalize_phase0",
        "resolve_entrypoints",
        "propose_extract_plan",
        "apply_extract_plan",
        "build_layered_kb",
        "uo-semantic-resolve",
        "apply_resolution",
        "kb_query_export",
        "check_kb_integrity",
        "uo-kb-review",
    )
    missing = [item for item in required if item not in corpus]
    assert missing == []


def test_phase0_human_review_is_hard_gate() -> None:
    combined = _init_corpus()
    assert "macro_scope" in combined
    assert "AskQuestion" in combined or "question UI" in combined or "AskQuestion" in _read(
        "prompts/init/scope_menu.md"
    )
    assert "continue" in combined and "revise" in combined and "stop" in combined
    assert "禁止自动" in combined or "禁自动" in combined


def test_subagent_dispatch_reuses_stable_identity() -> None:
    dispatch = _read("prompts/init/dispatch.md")
    combined = _init_corpus()
    assert "<run_id>:<phase-or-step>:<owner>:<target-path-or-slice-id>" in dispatch
    assert "续跑" in dispatch
    assert "SUBAGENT_RESUME_UNAVAILABLE" in dispatch
    assert "uo-semantic-resolve" in combined


def test_residual_dispatch_locks_schema_and_sampling() -> None:
    residual = _read("prompts/init/references/tpl_residual.md")
    agent = _read("agents/uo-semantic-resolve.md")
    tasks = _read("agents/references/semantic-resolve-tasks.md")
    combined = "\n".join([residual, agent, tasks, _init_corpus()])
    assert "unresolved_resolutions" in residual or "unresolved_resolutions" in tasks
    assert "At most 12" in residual or "at most 12" in agent.lower() or "≤12" in combined
    assert "residuals:" in agent or "residuals:" in tasks
    assert "resolution: warning" in agent or "resolution: warning" in tasks
    assert "apply_resolution" in combined and "--check" in combined
    assert "hand-count" in residual.lower() or "hand-count" in agent.lower()


def test_all_subagents_resolve_prompts_from_prompt_dir() -> None:
    missing: list[str] = []
    for path in (ROOT / "agents").glob("uo-*.md"):
        text = path.read_text(encoding="utf-8")
        if "PROMPT_DIR" not in text or ("Do not resolve" not in text and "禁止" not in text):
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
    assert agents == [
        "uo-code-reviewer.md",
        "uo-kb-review.md",
        "uo-key-resolve.md",
        "uo-semantic-resolve.md",
    ]


def test_key_resolve_dispatch_and_templates_exist() -> None:
    dispatch = _read("prompts/init/dispatch.md")
    triage = _read("prompts/init/references/tpl_key_triage.md")
    resolve = _read("prompts/init/references/tpl_key_resolve.md")
    agent = _read("agents/uo-key-resolve.md")
    assert "uo-key-resolve" in dispatch
    assert "tpl_key_triage" in dispatch
    assert "key_triage.yaml" in triage
    assert "complexity: complex | simple" in triage or "complex|simple" in triage.replace(" ", "")
    assert "mode=single" in resolve or "`single`" in resolve
    assert "CBM" in resolve and "MAY" in resolve
    assert "PROMPT_DIR" in agent


def test_kb_review_dispatch_template_exists() -> None:
    tpl = _read("prompts/init/references/tpl_kb_review.md")
    assert "uo-kb-review" in tpl
    assert "rework_stage" in tpl
    assert "kb_product_review.yaml" in tpl


def test_prompt_layout_matches_skills() -> None:
    for rel in (
        "prompts/common/language.md",
        "prompts/init/workflow.md",
        "prompts/update/workflow.md",
        "prompts/query/README.md",
        "prompts/review/workflow.md",
    ):
        assert (ROOT / rel).is_file(), rel


def test_uo_query_skill_tg_isolation_and_csv_pointer() -> None:
    text = _read("skills/uo-query/SKILL.md")
    assert "OUT_ROOT" in text
    assert "tg-uo-query-escalation" in text or "testcase-agent" in text
    assert "建库期" in text or "uo-init" in text
    assert "key_shape_resolve" in text
    ownership = _read("spec/ownership.yaml")
    assert "must never write any file under `$UO_ROOT/**`" in ownership or "must never write any file under $UO_ROOT" in ownership
    assert "CSV↔HOST" in ownership or "CSV" in ownership
    esc = _read("skills/uo-query/references/complex-unresolved-escalation.md")
    assert "Mode A" in esc and "Mode B" in esc
    assert "tg-init --merge-uo-resolve" in esc
    assert "Never" in esc or "never" in esc

    over = []
    for path in (ROOT / "skills").rglob("SKILL.md"):
        n = len(path.read_text(encoding="utf-8").splitlines())
        if n > 200:
            over.append(f"{path.relative_to(ROOT).as_posix()}:{n}")
    assert over == []


def test_agent_prompt_files_under_200_lines() -> None:
    over = []
    for base in ("agents", "prompts"):
        for path in (ROOT / base).rglob("*.md"):
            n = len(path.read_text(encoding="utf-8").splitlines())
            if n > 200:
                over.append(f"{path.relative_to(ROOT).as_posix()}:{n}")
    assert over == []
