"""Regression: prepare requires uo-init only; no legacy skill probing."""

from __future__ import annotations

from pathlib import Path

from uo._operator.install_check import compare_installed_skill
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


def test_prepare_bound_run_id_uses_pilot_path(tmp_path: Path, monkeypatch) -> None:
    _fake_home(tmp_path, monkeypatch)
    repo = tmp_path / "op"
    (repo / "op_host").mkdir(parents=True)
    (repo / "op_kernel").mkdir(parents=True)
    (repo / "op_host" / "x.cpp").write_text("//\n", encoding="utf-8")

    cfg = tmp_path / ".config" / "opencode"
    (cfg / "skills" / "uo-init").mkdir(parents=True)
    (cfg / "ascendc-pilot-plugin").mkdir(parents=True)

    monkeypatch.setattr(
        "uo.scripts.prepare_operator.compare_installed_skill",
        lambda *_a, **_k: {
            "version": 2,
            "consistent": True,
            "skill_present": True,
            "installed_skill_root": str(cfg / "skills" / "uo-init"),
            "mismatches": [],
        },
    )

    pilot_run = "RUN_20260724_091453_aa063141"
    code = prepare_main([str(repo), "--op-name", "op", "--run-id", pilot_run])
    assert code == 0
    phase0 = repo / ".ascendc-pilot" / "uo" / "runs" / pilot_run / "scope"
    assert phase0.is_dir()
    assert (phase0 / "context.yaml").is_file()
    manifest = (repo / ".ascendc-pilot" / "uo" / "manifest.yaml").read_text(encoding="utf-8")
    assert pilot_run in manifest
    # Must not mint a sibling UO_RUN_* for the same prepare.
    run_dirs = [p.name for p in (repo / ".ascendc-pilot" / "uo" / "runs").iterdir() if p.is_dir()]
    assert run_dirs == [pilot_run]


def test_compare_generated_tree_consistent_with_self(tmp_path: Path) -> None:
    """generated/opencode vs a mirror plugin tree → consistent."""
    bundle = Path(__file__).resolve().parents[3]  # AscendC-Pilot
    gen = bundle / "generated" / "opencode"
    if not (gen / "skills" / "uo-init" / "SKILL.md").is_file():
        import pytest

        pytest.skip("generated/opencode not composed")

    plugin = tmp_path / "ascendc-pilot-plugin"
    from uo._operator.install_check import CHECK_FILES_GENERATED, CHECK_FILES_REPO

    for rel in CHECK_FILES_GENERATED:
        src = gen / rel
        if not src.is_file():
            continue
        dst = plugin / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    for rel in CHECK_FILES_REPO:
        src = bundle / rel
        if not src.is_file():
            continue
        dst = plugin / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    skill = tmp_path / "skills" / "uo-init"
    skill.mkdir(parents=True)
    result = compare_installed_skill(bundle, skill)
    assert result.get("consistent") is True, result.get("mismatches")[:3]

    bad = plugin / "skills" / "uo-init" / "SKILL.md"
    bad.write_text(bad.read_text(encoding="utf-8") + "\n# tamper\n", encoding="utf-8")
    result2 = compare_installed_skill(bundle, skill)
    assert result2.get("consistent") is False
    assert result2.get("error_code") == "INSTALLED_SKILL_VERSION_MISMATCH"
