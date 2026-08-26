# -*- coding: utf-8 -*-
"""ses_fefd regression: OpenCode Tab isolation + Host tools + no 120s bash drain."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.authorize import authorize
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow

ROOT = Path(__file__).resolve().parents[2]


def test_plugin_always_registers_pilot_run_not_named_acp() -> None:
    plugin = (ROOT / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    driver_facade = (ROOT / "opencode-plugin" / "pilot-driver.ts").read_text(encoding="utf-8")
    driver_core = (ROOT / "opencode-plugin" / "pilot-driver-core.ts").read_text(encoding="utf-8")
    driver = driver_facade + "\n" + driver_core
    assert "function createPilotRunStub" in plugin
    assert "function createPilotCliTool" in plugin
    assert "createAcpCliTool" not in plugin
    assert ").acp = create" not in plugin
    assert "bag.pilot_cli = createPilotCliTool()" in plugin
    assert "isPilotCliLongCommand" in plugin
    assert "isPilotCliAllowedCommand" in plugin
    assert "PILOT_CLI_ALLOWED_HEADS" in plugin
    assert "USE_PILOT_RUN" in plugin
    assert "USE_UO_QUERY" in plugin
    assert "formatPilotCliOutput" in plugin
    assert "FAIL ${code}" in plugin or "FAIL " in plugin
    assert "/cann|" not in plugin
    assert "UO_CANN_ROOT" in plugin
    assert "gitcode.com--cann--" not in plugin.split("formatPilotCliOutput")[1].split("function createPilotRunStub")[0]
    assert "tools.pilot_run = true" in plugin
    assert "tools.pilot_cli = true" in plugin
    assert "NATIVE_OPENCODE_AGENTS" in plugin
    assert "3_600_000" in driver_core
    assert "ACP_TIMEOUT" in driver_core
    reject = driver_core.split('if (workflow === "uo-query")')[1].split("const parentSessionId")[0]
    assert "acp uo-query --project" not in reject
    assert "pilot_cli" in reject
    assert 'replace(/^\\/+/, "")' in driver_core.split("export function canonicalWorkflowId")[1].split(
        "export function resumeActiveGoal"
    )[0]
    assert "canonicalWorkflowId(String(args.workflow" in driver_core
    assert "readDispatchFor" in driver_facade
    assert "currentHostSessionHint" in driver_facade
    assert "uo-query" not in driver_core.split("args: {")[1].split("project:")[0] or (
        "禁止 uo-query" in driver_core
    )


def test_plugin_pilot_cli_allowlist_blocks_uo_bypass_without_spawn() -> None:
    plugin = (ROOT / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    start = plugin.index("const PILOT_CLI_ALLOWED_HEADS")
    end = plugin.index("])", start)
    block = plugin[start:end]
    for allowed in (
        "uo-query",
        "status",
        "inspect",
        "inspect-failure",
        "ro-search",
        "next",
        "scan-architectures",
        "abort",
        "answer",
        "retry-after-environment-fix",
    ):
        assert f'"{allowed}"' in block, allowed
    for forbidden in ("impact", "search", "locate", "explain-host-value", "start", "run-action"):
        assert f'"{forbidden}"' not in block, forbidden
    fn = plugin.split("function createPilotCliTool")[1].split("\nfunction ")[0]
    assert "USE_UO_QUERY" in fn
    assert fn.index("isPilotCliAllowedCommand") < fn.index("spawnSync")
    assert fn.index("USE_UO_QUERY") < fn.index("spawnSync")


def test_plugin_ts_parses_for_opencode() -> None:
    from ascendc_pilot.host_doctor import parse_opencode_plugin_ts, plugin_hook_redeclared_consts

    broken = (
        '"tool.execute.before": async () => {\n'
        "  const sessionId = 'a'\n"
        "  const sessionId = 'b'\n"
        "},\n"
        '"tool.execute.after": async () => { const x = 1 }\n'
    )
    hits = plugin_hook_redeclared_consts(broken)
    assert any("sessionId" in item for item in hits)

    root = ROOT / "opencode-plugin"
    for name in ("ascendc-pilot.ts", "pilot-driver.ts", "pilot-driver-core.ts"):
        parsed = parse_opencode_plugin_ts(root / name)
        assert parsed.get("ok"), f"{name}: {parsed.get('detail')}"


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
    assert '"$GEN/knowledge"' in sh
    assert 'Join-Path $genRoot "knowledge"' in ps1
    assert "generated knowledge missing" in sh
    assert "generated knowledge missing" in ps1
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


def test_write_opencode_cann_root(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.paths import opencode_home, write_opencode_cann_root

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    pkg = tmp_path / "cann" / "pkg"
    pkg.mkdir(parents=True)
    cache = write_opencode_cann_root(pkg)
    assert cache == opencode_home() / "ascendc-cann-root"
    assert cache.read_text(encoding="utf-8").strip() == str(pkg.resolve())
