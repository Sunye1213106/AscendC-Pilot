"""A stale installed methodology copy must not silently out-vote the checkout."""

from __future__ import annotations

from pathlib import Path

import ascendc_pilot.contract_sync as contract_sync


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "prompts" / "tasks" / "tg").mkdir(parents=True)
    refs = repo / "skills" / "test-plan" / "references"
    refs.mkdir(parents=True)
    (repo / "prompts" / "tasks" / "tg" / "plan-owner.md").write_text("owner\n", encoding="utf-8")
    (refs / "coverage-planning.md").write_text(
        "predicate TRUE = SATISFIED\n", encoding="utf-8"
    )
    (repo / "skills" / "test-plan" / "SKILL.md").write_text("skill\n", encoding="utf-8")
    return repo


def _install(tmp_path: Path, body: str) -> Path:
    plugin = tmp_path / "plugin"
    dst = plugin / "cognitive-skills" / "test-plan" / "references"
    dst.mkdir(parents=True)
    (dst / "coverage-planning.md").write_text(body, encoding="utf-8")
    return plugin


def test_matching_install_is_not_drift(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    plugin = _install(tmp_path, "predicate TRUE = SATISFIED\n")
    monkeypatch.setattr(contract_sync, "installed_roots", lambda: [plugin])
    assert contract_sync.contract_drift(repo) == []
    assert contract_sync.contract_drift_gate(repo) is None


def test_missing_install_is_not_drift(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(contract_sync, "installed_roots", lambda: [])
    assert contract_sync.contract_drift_gate(repo) is None


def test_stale_guard_semantics_blocks_the_window(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    plugin = _install(tmp_path, "predicate = the killer state\n")
    monkeypatch.setattr(contract_sync, "installed_roots", lambda: [plugin])

    drift = contract_sync.contract_drift(repo)
    assert len(drift) == 1
    assert drift[0]["repo"] == "skills/test-plan/references/coverage-planning.md"

    gate = contract_sync.contract_drift_gate(repo)
    assert gate is not None
    assert gate["ok"] is False
    assert gate["reason_code"] == contract_sync.DRIFT_REASON
    # The message must name the file to refresh and a command that actually
    # replaces the installed bundle, not one that only rebuilds generated/.
    assert "coverage-planning.md" in gate["message_zh"]
    assert "refresh-opencode" in gate["message_zh"]
