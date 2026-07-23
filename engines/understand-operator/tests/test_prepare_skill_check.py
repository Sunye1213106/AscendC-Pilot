"""Regression: prepare requires uo-init only; no legacy skill probing."""

from __future__ import annotations

from pathlib import Path

import yaml

from uo.scripts.prepare_operator import _resolve_installed_skill_check, main as prepare_main


def _fake_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


def test_resolve_check_uses_uo_init(tmp_path: Path, monkeypatch) -> None:
    _fake_home(tmp_path, monkeypatch)
    cfg = tmp_path / ".config" / "opencode" / "skills"
    cfg.mkdir(parents=True)
    (cfg / "uo-init").mkdir()
    (tmp_path / ".config" / "opencode" / "ascendc-pilot-plugin").mkdir()

    check = _resolve_installed_skill_check(Path(__file__).resolve().parents[1])
    assert check.get("primary_skill") == "uo-init"
    assert check.get("skill_present") is True
    assert str(check.get("installed_skill_root") or "").replace("\\", "/").endswith("uo-init")


def test_resolve_check_missing_uo_init_is_hard_error(tmp_path: Path, monkeypatch) -> None:
    _fake_home(tmp_path, monkeypatch)
    cfg = tmp_path / ".config" / "opencode" / "skills"
    cfg.mkdir(parents=True)

    check = _resolve_installed_skill_check(Path(__file__).resolve().parents[1])
    assert check.get("skill_present") is False
    assert check.get("error_code") == "MISSING_INSTALLED_SKILL"
    assert "legacy_leftovers" not in check


def test_prepare_writes_stubs_even_on_version_mismatch(tmp_path: Path, monkeypatch) -> None:
    _fake_home(tmp_path, monkeypatch)
    repo = tmp_path / "op"
    (repo / "op_host").mkdir(parents=True)
    (repo / "op_kernel").mkdir(parents=True)
    (repo / "op_host" / "x.cpp").write_text("//\n", encoding="utf-8")

    cfg = tmp_path / ".config" / "opencode"
    (cfg / "skills" / "uo-init").mkdir(parents=True)
    (cfg / "ascendc-pilot-plugin").mkdir(parents=True)

    def _fake_compare(repo_plugin_root: Path, installed_skill_root: Path) -> dict:
        return {
            "version": 2,
            "consistent": False,
            "error_code": "INSTALLED_SKILL_VERSION_MISMATCH",
            "installed_skill_root": str(installed_skill_root),
            "mismatches": [{"path": "skills/uo-init/SKILL.md"}],
        }

    monkeypatch.setattr(
        "uo.scripts.prepare_operator.compare_installed_skill",
        _fake_compare,
    )

    code = prepare_main([str(repo), "--op-name", "op", "--force-new-run"])
    assert code == 3
    scope_dirs = list((repo / ".ascendc-pilot" / "uo" / "runs").glob("*/scope"))
    assert scope_dirs
    phase0 = scope_dirs[0]
    assert (phase0 / "semantic_enrichment.yaml").is_file()
    assert (phase0 / "scope_scan.yaml").is_file()
    text = (phase0 / "installed_skill_check.yaml").read_text(encoding="utf-8")
    assert "uo-init" in text
    assert "legacy_leftovers" not in text
