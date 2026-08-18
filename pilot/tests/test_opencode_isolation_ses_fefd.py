# -*- coding: utf-8 -*-
"""ses_fefd regression: OpenCode Tab isolation + Host tools + no 120s bash drain."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.authorize import authorize
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import load_state, save_state, start_workflow

ROOT = Path(__file__).resolve().parents[2]


def test_plugin_always_registers_pilot_run_not_named_acp() -> None:
    plugin = (ROOT / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    driver = (ROOT / "opencode-plugin" / "pilot-driver.ts").read_text(encoding="utf-8")
    assert "function createPilotRunStub" in plugin
    assert "function createPilotCliTool" in plugin
    assert "createAcpCliTool" not in plugin
    assert ").acp = create" not in plugin
    assert "bag.pilot_cli = createPilotCliTool()" in plugin
    assert "isPilotCliLongCommand" in plugin
    assert "USE_PILOT_RUN" in plugin
    assert "formatPilotCliOutput" in plugin
    assert "FAIL ${code}" in plugin or "FAIL " in plugin
    assert "tools.pilot_run = true" in plugin
    assert "tools.pilot_cli = true" in plugin
    assert "NATIVE_OPENCODE_AGENTS" in plugin
    assert "3_600_000" in driver
    assert "ACP_TIMEOUT" in driver
    reject = driver.split('if (workflow === "uo-query")')[1].split("const parentSessionId")[0]
    assert "acp uo-query --project" not in reject
    assert "pilot_cli" in reject
    assert "uo-query" not in driver.split("args: {")[1].split("project:")[0] or (
        "Never uo-query" in driver
    )


def test_installers_expose_only_primary_opencode_tab() -> None:
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    un_sh = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
    un_ps1 = (ROOT / "uninstall.ps1").read_text(encoding="utf-8")
    refresh = (ROOT / "refresh-opencode.ps1").read_text(encoding="utf-8")
    assert "Only expose AscendC-Pilot" in sh
    assert "leftover OpenCode Tab" in ps1
    assert '"$AGENTS"/tg-*.md' not in sh
    assert '"$agents"/tg-*.md' not in sh
    assert '"$AGENTS"/tg-*.md' not in un_sh
    assert "^(tg-|uo-|ce-|ascendc-)" not in ps1
    assert "^(tg-|uo-|ce-|ascendc-)" not in un_ps1
    assert "^(tg-|uo-|ce-)" not in refresh
    assert "install-manifest.json" in sh
    assert "install-manifest.json" in ps1
    assert "install-manifest.json" in un_ps1
    assert "uninstall.ps1" in refresh
    assert "Skip uninstall" not in refresh
    assert "ascendc-cann-root" in sh
    assert "ascendc-cann-root" in ps1
    assert "Cached CANN root" in ps1


def test_compose_primary_has_pilot_tools_and_hides_children(tmp_path: Path) -> None:
    import sys

    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from compose_runtime import compose_host

    out = tmp_path / "opencode"
    result = compose_host(ROOT, "opencode", out_root=out)
    assert result["ok"]
    agents = out / "agents"
    assert (agents / "ascendc-pilot.md").is_file()
    assert not (agents / "tg-init-audit.md").exists()
    primary = (agents / "ascendc-pilot.md").read_text(encoding="utf-8")
    assert "pilot_run: allow" in primary
    assert "pilot_cli: allow" in primary
    assert "Get-Command acp" not in primary
    assert "PATH 上的 `acp`" not in primary
    assert "主控当前会话 `acp uo-query`" not in primary
    assert "pilot_cli" in primary
    assert "grep *" in primary
    lemma = (agents / "tg-analyst.md").read_text(encoding="utf-8")
    assert "hidden: true" in lemma
    yaml_src = (ROOT / "agents" / "ascendc-pilot.yaml").read_text(encoding="utf-8")
    assert "没有 Host 工具就调用 PATH" not in yaml_src
    assert "pilot_run" in yaml_src
    assert "pilot_cli" in yaml_src


def test_authorize_denies_bash_start_and_auto(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    start = authorize(
        op,
        tool="bash",
        command="acp start uo-init --project D:\\op --architecture arch35",
        agent="ascendc-pilot",
    )
    assert start.get("decision") == "deny", start
    assert start.get("reason_code") == "USE_PILOT_RUN"
    auto = authorize(
        op,
        tool="bash",
        command="acp run-action auto --project D:\\op",
        agent="ascendc-pilot",
    )
    assert auto.get("decision") == "deny", auto
    assert auto.get("reason_code") == "USE_PILOT_RUN"
    py_start = authorize(
        op,
        tool="bash",
        command="python -m ascendc_pilot start uo-init --project D:\\op",
        agent="ascendc-pilot",
    )
    assert py_start.get("decision") == "deny", py_start
    assert py_start.get("reason_code") == "USE_PILOT_RUN"


def test_authorize_pilot_cli_short_ok_long_denied(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    q = authorize(
        op,
        tool="pilot_cli",
        command="uo-query --project D:\\op s1Inner",
        agent="ascendc-pilot",
    )
    assert q.get("decision") == "allow", q
    assert q.get("reason_code") == "PILOT_CLI_OK"
    drain = authorize(
        op,
        tool="pilot_cli",
        command="run-action auto --project D:\\op",
        agent="ascendc-pilot",
    )
    assert drain.get("decision") == "deny", drain
    assert drain.get("reason_code") == "USE_PILOT_RUN"
    start = authorize(
        op,
        tool="pilot_cli",
        command="start uo-init --project D:\\op --architecture arch35",
        agent="ascendc-pilot",
    )
    assert start.get("decision") == "deny", start


def test_authorize_primary_diagnostic_python_in_containment(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    state = load_state(op) or {}
    state["status"] = "human_required"
    state["last_failure"] = {"error_code": "CANN_MISSING", "message_zh": "缺 CANN"}
    save_state(op, state)
    check = authorize(
        op,
        tool="bash",
        command="python scripts/dev/check_cann.py",
        agent="ascendc-pilot",
    )
    assert check.get("decision") == "allow", check
    assert check.get("reason_code") == "PRIMARY_DIAGNOSTIC"
    fixup = authorize(
        op,
        tool="bash",
        command="python scripts/cann_extract.py --fixup --dest D:\\cann\\pkg",
        agent="ascendc-pilot",
    )
    assert fixup.get("decision") == "allow", fixup
    doctor = authorize(
        op,
        tool="bash",
        command="python -m ascendc_pilot doctor --host opencode",
        agent="ascendc-pilot",
    )
    assert doctor.get("decision") == "allow", doctor
    envc = authorize(
        op,
        tool="bash",
        command='python -c "import os; print(os.environ.get(\'UO_CANN_ROOT\'))"',
        agent="ascendc-pilot",
    )
    assert envc.get("decision") == "allow", envc
    engine = authorize(
        op,
        tool="bash",
        command='python -c "import uo_init.pilot_engines"',
        agent="ascendc-pilot",
    )
    assert engine.get("decision") == "deny", engine
    bypass = authorize(
        op,
        tool="bash",
        command="python scripts/dev/build_layered_kb.py --project D:\\op",
        agent="ascendc-pilot",
    )
    assert bypass.get("decision") == "deny", bypass


def test_write_opencode_cann_root(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.paths import opencode_home, write_opencode_cann_root

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    pkg = tmp_path / "cann" / "pkg"
    pkg.mkdir(parents=True)
    cache = write_opencode_cann_root(pkg)
    assert cache == opencode_home() / "ascendc-cann-root"
    assert cache.read_text(encoding="utf-8").strip() == str(pkg.resolve())
