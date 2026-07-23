"""Guardrails: old dual control-plane narratives must not return in active sources."""

from __future__ import annotations

from pathlib import Path

# Repo root: engines/understand-operator/tests → parents[3] = AscendC-Pilot-upload
REPO = Path(__file__).resolve().parents[3]

ACTIVE_GLOBS = (
    "skills/**/*.md",
    "prompts/**/*.md",
    "agents/**/*.yaml",
    "agents/**/*.md",
    "docs/*-workflow.md",
    "docs/overview/*.md",
    "README.md",
)


def _active_texts() -> dict[str, str]:
    out: dict[str, str] = {}
    for pattern in ACTIVE_GLOBS:
        for path in REPO.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO).as_posix()
            out[rel] = path.read_text(encoding="utf-8")
    return out


def test_no_independent_uo_diff_skill() -> None:
    assert not (REPO / "skills" / "uo-diff").exists()
    assert not (REPO / "skills" / "workflows" / "uo-diff").exists()
    for host in ("opencode", "cursor", "codex"):
        assert not (REPO / "generated" / host / "skills" / "uo-diff").exists()


def test_prepare_operator_requires_uo_init_only() -> None:
    text = (REPO / "engines" / "understand-operator" / "uo" / "scripts" / "prepare_operator.py").read_text(encoding="utf-8")
    assert '_PRIMARY_SKILL_NAME = "uo-init"' in text
    assert "_LEGACY_SKILL_NAMES" not in text
    assert "legacy_leftovers" not in text
    assert "MISSING_INSTALLED_SKILL" in text
    fwd = (REPO / "skills" / "capabilities" / "kb-query" / "scripts" / "uo_kb_query.py").read_text(
        encoding="utf-8"
    )
    assert "ascendc-pilot-plugin" in fwd
    assert "understand-operator-plugin" not in fwd


def test_pilot_control_policy_native_todo_is_shared_via_route() -> None:
    text = (REPO / "skills" / "policies" / "pilot-control" / "POLICY.md").read_text(encoding="utf-8")
    assert "原生 Todo（所有 workflow 共用" in text
    assert "todo.todo_sync" in text
    assert "todowrite" in text
    assert "require_full" in text or "todo.todo_sync.items" in text
    assert "forbid_partial_overwrite" in text or "禁止省略" in text or "只写当前阶段" in text
    assert "不得**写死在各 Skill" in text or "不得写死在各 Skill" in text
    assert "禁止在主对话输出工作流状态面板" in text or "禁止**向用户粘贴" in text
    uo = (REPO / "skills" / "workflows" / "uo-init" / "SKILL.md").read_text(encoding="utf-8")
    assert "## 原生 Todo" not in uo
    assert "| `prepare` | 环境准备 |" not in uo
    assert "pilot-control" in uo


def test_no_skill_owned_phase_machine_titles() -> None:
    forbidden_titles = (
        "# Phase0",
        "# Phase 0",
        "uo-init Phase 1",
        "uo-init Phase 2",
        "Skill 管流程",
    )
    hits: list[str] = []
    for rel, text in _active_texts().items():
        if "pilot-迭代" in rel or "harness-迭代" in rel:
            continue
        for term in forbidden_titles:
            if term in text:
                hits.append(f"{rel}: {term}")
    assert hits == []


def test_no_retired_uo_contracts_as_write_target() -> None:
    """tg-csv-contract must write TG contract/, not UO contracts/**."""
    yaml_text = (REPO / "agents" / "tg-csv-contract.yaml").read_text(encoding="utf-8")
    assert "tg/contract/**" in yaml_text
    assert "tg/contracts/**" not in yaml_text


def test_workflow_docs_are_not_executable_state_machines() -> None:
    for name in (
        "uo-init-workflow.md",
        "uo-update-workflow.md",
        "uo-query-workflow.md",
        "ce-review-workflow.md",
        "tg-init-workflow.md",
        "tg-plan-workflow.md",
        "tg-solve-workflow.md",
    ):
        text = (REPO / "docs" / name).read_text(encoding="utf-8")
        assert "非可执行状态机" in text or "Pilot" in text or "Harness" in text
        assert "Entry：" not in text
        assert "Exit：" not in text


def test_readme_uses_chinese_stages_not_phase0() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "范围确认" in text
    assert "Phase0 →" not in text
    assert "Phase 0 →" not in text


def test_no_uo_orchestrator_in_active_agent_sources() -> None:
    hits = [
        rel
        for rel, text in _active_texts().items()
        if "uo-orchestrator" in text and "pilot-迭代" not in rel and "harness-迭代" not in rel
    ]
    assert hits == []


def test_generated_scope_method_not_titled_phase0() -> None:
    for host in ("opencode", "cursor", "codex"):
        path = (
            REPO
            / "generated"
            / host
            / "skills"
            / "uo-init"
            / "actions"
            / "scope-confirmation"
            / "METHOD.md"
        )
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "# Phase0" not in text
        assert "范围确认" in text or "scope_confirmation" in text
