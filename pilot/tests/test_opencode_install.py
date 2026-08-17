# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_doctor_treats_missing_cann_as_warning() -> None:
    text = (ROOT / "pilot" / "ascendc_pilot" / "cli.py").read_text(encoding="utf-8")
    assert 'warnings.append(f"cann: {item}")' in text
    assert 'issues.append(f"cann: {item}")' not in text


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
