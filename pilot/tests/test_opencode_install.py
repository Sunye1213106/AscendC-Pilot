# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_doctor_treats_missing_cann_as_issue() -> None:
    text = (ROOT / "pilot" / "ascendc_pilot" / "cli.py").read_text(encoding="utf-8")
    assert 'issues.append(f"cann: {item}")' in text
    assert 'warnings.append(f"cann: {item}")' not in text
    assert "require_cann_ready" in text


def test_opencode_home_respects_xdg(tmp_path, monkeypatch) -> None:
    from ascendc_pilot.paths import opencode_home, opencode_plugin_root

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    home = opencode_home()
    assert home == tmp_path / "xdg-config" / "opencode"
    assert opencode_plugin_root() == home / "ascendc-pilot-plugin"


def test_host_doctor_requires_installed_bundle_not_source_tree(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    from ascendc_pilot.host_doctor import doctor_host

    payload = doctor_host("opencode")
    by_name = {c["name"]: c for c in payload["checks"]}
    assert by_name["plugin_ascendc_pilot_ts"]["ok"] is False
    assert by_name["plugin_pilot_driver_ts"]["ok"] is False
    assert "install.sh" in payload["message_zh"]
    assert "install.ps1" in payload["message_zh"]
    source_driver = ROOT / "opencode-plugin" / "pilot-driver.ts"
    assert source_driver.is_file()
    assert source_driver.as_posix() not in by_name["plugin_pilot_driver_ts"]["detail"]
    assert by_name["workflow_skills_plugin_internal"]["ok"] is False
    assert by_name["plugin_does_not_override_native_skill"]["ok"] is False
    assert by_name["workflow_skills_not_in_global_discovery"]["ok"] is True


def test_uninstall_scripts_exist_and_refresh_uninstalls_first() -> None:
    assert (ROOT / "uninstall.ps1").is_file()
    assert (ROOT / "uninstall.sh").is_file()
    refresh = (ROOT / "refresh-opencode.ps1").read_text(encoding="utf-8")
    uninstall_idx = refresh.find("Uninstall OpenCode AscendC bits")
    install_idx = refresh.find("Reinstall OpenCode AscendC bits")
    assert uninstall_idx != -1 and install_idx != -1
    assert uninstall_idx < install_idx
    assert "Skip uninstall" not in refresh
    assert "$UninstallPs1" in refresh
    assert "experimental-strip-types" in refresh
    assert "installed plugin failed to parse" in refresh


def test_install_manifest_does_not_claim_user_agents(tmp_path: Path) -> None:
    sys_path_scripts = str(ROOT / "scripts")
    import sys

    if sys_path_scripts not in sys.path:
        sys.path.insert(0, sys_path_scripts)
    from install_manifest import builtin_manifest, prune_global_agents

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "ce-helper.md").write_text("user", encoding="utf-8")
    (agents / "tg-playground.md").write_text("user", encoding="utf-8")
    (agents / "uo-personal.md").write_text("user", encoding="utf-8")
    (agents / "ascendc-debug-local.md").write_text("user", encoding="utf-8")
    (agents / "uo-query.md").write_text("ours leftover", encoding="utf-8")
    (agents / "ascendc-pilot.md").write_text("primary", encoding="utf-8")
    removed = prune_global_agents(agents, builtin_manifest("opencode"))
    names = {p.name for p in agents.glob("*.md")}
    assert "ce-helper.md" in names
    assert "tg-playground.md" in names
    assert "uo-personal.md" in names
    assert "ascendc-debug-local.md" in names
    assert "ascendc-pilot.md" in names
    assert "uo-query.md" not in names
    assert any(p.endswith("uo-query.md") for p in removed)


def test_plugin_resolve_acp_uses_opencode_home() -> None:
    plugin = (ROOT / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    driver = (ROOT / "opencode-plugin" / "pilot-driver.ts").read_text(encoding="utf-8")
    helper = (ROOT / "opencode-plugin" / "opencode-home.mjs").read_text(encoding="utf-8")
    assert "function openCodeHome()" in plugin
    assert "XDG_CONFIG_HOME" in plugin
    assert "from \"./opencode-home.mjs\"" in driver
    assert "export function resolveAcpBin" in helper
    assert "acp.exe" in helper
    assert "replace(/^\\uFEFF/" in helper or "\\uFEFF" in helper
    assert "replace(/^\\uFEFF/" in plugin or "\\uFEFF" in plugin


def test_doctor_cann_issue_mentions_repo_pkg_and_home() -> None:
    text = (ROOT / "pilot" / "ascendc_pilot" / "cli.py").read_text(encoding="utf-8")
    assert "_cann" in text
    assert "ASCEND_HOME_PATH" in text
    assert "require_cann_ready" in text
    assert "opencode_cann_root_cache_path" in text
