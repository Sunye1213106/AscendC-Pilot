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


def test_only_phase0_phase1_phase2_phase3_final_exist() -> None:
    workflow = _read("skills/uo-init/SKILL.md")
    assert "Phase 0" in workflow
    assert "Phase 1" in workflow
    assert "Phase 2" in workflow
    assert "Phase 3" in workflow
    assert "Final" in workflow
    assert "After the final gate passes, stop." in workflow


def test_orchestrator_matches_uo_init() -> None:
    source = _read("skills/uo-init/SKILL.md")
    orchestrator = _read("prompts/01_workflow_orchestrator.md")
    required = (
        "prepare_operator.py",
        "macro_scope_scan.py",
        "uo-boundary-agent",
        "validate_candidate_batch.py",
        "compile_candidate_facts.py",
        "validate_fact_stage.py",
        "uo-host-extraction",
        "uo-flow-extraction",
        "uo-kernel-overview-agent",
        "evaluate_review_trigger.py",
        "uo-kernel-slice-planner",
        "uo-kernel-slice-agent",
        "build_compile_gate.py",
        "source_graph_compiler.py",
        "materialize_derived_graph.py",
        "quality_gate.py",
    )
    missing = [item for item in required if item not in source or item not in orchestrator]
    assert missing == []


def test_no_phase35_or_phase4_workflow() -> None:
    text = "\n".join(_active_text().values())
    assert "Phase 3.5" not in text
    assert "Phase 4" not in text


def test_no_proposal_or_canonical_runtime_entry() -> None:
    runtime_files = [
        "pyproject.toml",
        "understand_operator/_operator/install_check.py",
        "skills/understand-operator/PATHS.md",
        "skills/understand-operator/SKILL.md",
    ]
    text = "\n".join(_read(rel) for rel in runtime_files)
    forbidden = (
        "uo-compile-kb",
        "uo-kb-compile",
        "uo-merge-fact-entries",
        "uo-kb-export",
        "promote_kb",
        "canonical_updates",
        "archive/proposals",
        "kb_compiler",
        "verify_subagent_barrier",
        "migrate_partitioned_facts",
    )
    hits = [term for term in forbidden if term in text]
    assert hits == []


def test_removed_legacy_files_are_absent() -> None:
    removed = (
        "understand_operator/_operator/kb_compiler.py",
        "understand_operator/_operator/update_plan.py",
        "understand_operator/_operator/yaml_gate.py",
        "understand_operator/scripts/compile_kb.py",
        "understand_operator/scripts/kb_query_export.py",
        "understand_operator/scripts/merge_fact_entries.py",
        "understand_operator/scripts/migrate_partitioned_facts.py",
        "understand_operator/scripts/verify_subagent_barrier.py",
        "agents/uo-kernel-path.md",
    )
    assert [rel for rel in removed if (ROOT / rel).exists()] == []
