"""Host adapter contract: acp host-context + OpenCode plugin path hygiene."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ascendc_pilot.cli import main as acp_main
from ascendc_pilot.host_context import build_host_context
from ascendc_pilot.paths import ensure_agent_layout, state_root
from ascendc_pilot.state import start_workflow

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "opencode-plugin" / "ascendc-pilot.ts"


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_host_context_arch_scoped_active_action(tmp_path: Path, capsys) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    aa = state_root(tmp_path, arch="arch35") / "active_action.yaml"
    _write(
        aa,
        {
            "version": 1,
            "action_id": "prepare",
            "actor_id": "deterministic-uo-engine",
        },
    )

    code = acp_main(["host-context", "--project", str(tmp_path), "--architecture", "arch35"])
    out = capsys.readouterr().out
    assert code == 0
    payload = yaml.safe_load(out) if out.strip().startswith("{") else None
    # print_json emits JSON; parse via yaml-compatible loader or json.
    import json

    payload = json.loads(out)
    assert payload.get("ok") is True
    assert payload.get("architecture") == "arch35"
    assert payload.get("action_id") == "prepare"
    assert payload.get("actor_id") == "deterministic-uo-engine"
    assert "active_action.yaml" in str(payload.get("active_action_path") or "")

    ctx = build_host_context(tmp_path, architecture="arch35")
    assert ctx.get("ok") is True
    assert ctx.get("architecture") == "arch35"
    assert ctx.get("action_id") == "prepare"
    assert ctx.get("actor_id") == "deterministic-uo-engine"
    assert Path(str(ctx.get("active_action_path") or "")).name == "active_action.yaml"
    assert "control" in str(ctx.get("pending_interaction_path") or "")
    assert "pending_interaction.yaml" in str(ctx.get("pending_interaction_path") or "")


def test_host_context_no_workflow_fails_closed(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    ctx = build_host_context(tmp_path, architecture="arch35")
    assert ctx.get("ok") is False
    assert ctx.get("error") == "NO_ACTIVE_WORKFLOW"
    assert ctx.get("project_root")
    assert "pending_interaction.yaml" in str(ctx.get("pending_interaction_path") or "")


def test_host_context_multi_arch_uses_active_run(tmp_path: Path, monkeypatch) -> None:
    """Two arch state trees + active_run → host-context selects current arch."""
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    ensure_agent_layout(tmp_path, arch="arch22")
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch22")
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    start_workflow(tmp_path, "uo-query", architecture="arch35")
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    ctx = build_host_context(tmp_path, architecture="")
    assert ctx.get("ok") is True
    assert ctx.get("architecture") == "arch22"
    assert ctx.get("workflow_id") == "uo-init"
    assert "active_run" in str(ctx.get("active_run_path") or "")
    start_workflow(tmp_path, "tg-init", architecture="arch35")
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    ctx = build_host_context(tmp_path, architecture="")
    assert ctx.get("ok") is True
    assert ctx.get("architecture") == "arch35"
    assert ctx.get("workflow_id") == "tg-init"


def test_host_context_multi_arch_ambiguous_without_pointer(
    tmp_path: Path, monkeypatch
) -> None:
    from ascendc_pilot.active_run import clear_active_run

    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    ensure_agent_layout(tmp_path, arch="arch22")
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch22")
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    start_workflow(tmp_path, "uo-query", architecture="arch35")
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    start_workflow(tmp_path, "tg-init", architecture="arch35")
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    clear_active_run(tmp_path)
    ctx = build_host_context(tmp_path, architecture="")
    assert ctx.get("ok") is False
    assert ctx.get("error") == "ARCHITECTURE_AMBIGUOUS"
    arches = set(ctx.get("architectures") or [])
    assert "arch22" in arches and "arch35" in arches


def test_plugin_source_no_flat_state_path_literals() -> None:
    text = PLUGIN.read_text(encoding="utf-8")
    # Flat layout concatenations must not appear outside findPilotStateFile.
    flat_state = re.compile(
        r"""["']\.ascendc-pilot["']\s*,\s*["']state["']"""
    )
    matches = list(flat_state.finditer(text))
    # Allowed only inside findPilotStateFile (legacy recognition).
    for m in matches:
        before = text[: m.start()]
        # Last function def before match must be findPilotStateFile.
        fns = list(re.finditer(r"function\s+(\w+)\s*\(", before))
        assert fns, "flat state path outside any function"
        assert fns[-1].group(1) == "findPilotStateFile", (
            f"flat .ascendc-pilot/state path outside findPilotStateFile "
            f"(in {fns[-1].group(1)})"
        )

    # workflow.yaml structure literal only in findPilotStateFile.
    wf_hits = [
        m.start()
        for m in re.finditer(r"""["']state["']\s*,\s*["']workflow\.yaml["']""", text)
    ]
    assert wf_hits, "expected workflow.yaml scan in findPilotStateFile"
    for pos in wf_hits:
        before = text[:pos]
        fns = list(re.finditer(r"function\s+(\w+)\s*\(", before))
        assert fns and fns[-1].group(1) == "findPilotStateFile"

    # readActiveAction must not open files itself — host-context only.
    assert "function readActiveAction" in text
    aa_start = text.index("function readActiveAction")
    aa_end = text.find("\nfunction ", aa_start + 1)
    body = text[aa_start:aa_end if aa_end > 0 else aa_start + 400]
    assert "readFileSync" not in body
    assert "fetchHostContext" in body
    # Must not resolve a filesystem path to active_action.yaml in this function.
    assert 'resolve(' not in body
    assert '", "state"' not in body and "', 'state'" not in body

    # control / pending_interaction stays arch-neutral.
    assert "pending_interaction.yaml" in text
    assert '".ascendc-pilot", "control"' in text or "'.ascendc-pilot', 'control'" in text
    assert "function findPilotStateFile" in text
    # Active-run pointer must be consulted before inventing an arch.
    assert "active_run.yaml" in text


def test_host_context_mjs_contract_executes() -> None:
    """Run the Node host-context resolver contract (fake acp, no OpenCode)."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not available")
    script = REPO / "opencode-plugin" / "host-context.test.mjs"
    assert script.is_file()
    proc = subprocess.run(
        [node, str(script)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "host-context.mjs contract OK" in (proc.stdout or "")


def test_pilot_progress_mjs_patches_tool_row_input() -> None:
    """Mock OpenCode 1.18 part.update: clean progress body succeeds, spread+raw 400s."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not available")
    script = REPO / "opencode-plugin" / "pilot-progress.test.mjs"
    assert script.is_file()
    proc = subprocess.run(
        [node, str(script)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "pilot-progress.mjs contract OK" in (proc.stdout or "")


def test_pilot_run_plugin_returns_string_output_and_streams_progress() -> None:
    """OpenCode Truncate.output crashes if plugin execute returns a bare object."""
    driver = REPO / "opencode-plugin" / "pilot-driver.ts"
    core = REPO / "opencode-plugin" / "pilot-driver-core.ts"
    text = driver.read_text(encoding="utf-8") + "\n" + core.read_text(encoding="utf-8")
    assert "toPluginToolResult" in text
    assert "compactPilotRunPayload" in text
    assert "compactPilotRunPayload(result)" in text
    assert "return toPluginToolResult(result)" in text
    assert "return runPilotDriver(" not in text
    assert '"uo-update": ["prepare"' not in text
    assert "JSON.stringify(rec, null, 2)" not in text
    assert "spawnSync" not in text
    assert "createProgressReporter" in text
    assert "isHumanDecision" in text
    assert "isAcpStartSuccess" in text
    assert "normalizeResumeDecision" in text
    assert "answer_from_source" in text
    assert 'startedKind === "primary_router"' in text
    assert 'decision === "uo-init"' in text
    assert 'decision === "source"' in text
    assert "renderPilotProgressBar" in text
    assert "invokeToolMetadata" not in text
    assert "Do not call ctx.metadata" in text
    assert "createToolRowProgressReporter" in text
    assert "publishVisibleProgress" in text
    assert "withProgressArg" in text
    assert "showToast" in text
    assert "await reporter.flushAsync()" in text
    progress = (REPO / "opencode-plugin" / "pilot-progress.mjs").read_text(encoding="utf-8")
    assert "buildToolPartProgressPatch" in progress
    assert "patchRunningToolPart" in progress
    assert "validateOpencodeToolPartPatch" in progress
    assert "raw not allowed on ToolStateRunning" in progress
    assert "session.message.v1" in progress
    assert "inner.patch.sessionID" in progress
    assert "inner.patch.v1" in progress
    assert "path: { id:" in progress
    assert "Never write stderr/stdout" in progress
    assert "console.error(" not in progress
    # EXISTING_RUN_NEEDS_DECISION includes run_id; must not treat run_id as start-ok.
    assert "!started.ok && !started.run_id" not in text
    # Successful start historically omitted ok:true — must not use !started.ok alone.
    assert "isAcpStartSuccess(started)" in text
    assert "ASCENDC_SESSION_ID" in text
    assert "ASCENDC_WORKFLOW_ID" in text
    assert "function acpControlEnv" in text


def test_missing_host_ask_ui_requires_primary_question() -> None:
    """Native AskQuestion miss must not be narrated as a visible confirmation box."""
    core = (REPO / "opencode-plugin" / "pilot-driver-core.ts").read_text(encoding="utf-8")
    plug = (REPO / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    assert "ask_ui_shown" in core
    assert "原生确认框没有出现" in core
    assert "禁止用文字告诉用户" in core
    assert "立刻用 question 按 ask_question.options" in core
    assert "ASK_UI_EMPTY" in core
    assert "Host 已弹出确认框时不要再开第二个 question" not in core
    assert "pending 不等于确认框已可见" in plug
    assert "Host 已询问；不要再开第二个 question" not in plug
    assert "禁止用文字告诉用户" in plug
    reason = (REPO / "pilot" / "policies" / "pilot-control" / "POLICY.md").read_text(
        encoding="utf-8"
    )
    assert "不等于" in reason and "确认框已弹出" in reason
    assert "禁止用文字告诉用户" in reason


def test_plugin_pending_lock_does_not_block_resume_start() -> None:
    """ses_0072: after acp answer, stale pending must not block start --decision."""
    plug = REPO / "opencode-plugin" / "ascendc-pilot.ts"
    text = plug.read_text(encoding="utf-8")
    assert 'status !== "pending"' in text
    assert "isAcpResumeStartCommand" in text
    assert "extractProjectFromAcpCommand" in text
    assert "pendingByProject.delete" in text
    assert "!isPilotDriver" not in text
    assert "applyForceNew" in (REPO / "opencode-plugin" / "pilot-driver.ts").read_text(
        encoding="utf-8"
    )


def test_pilot_run_intent_is_turn_payload_not_nl_routing() -> None:
    core = (REPO / "opencode-plugin" / "pilot-driver-core.ts").read_text(encoding="utf-8")
    stub = PLUGIN.read_text(encoding="utf-8")
    tools = (REPO / "docs" / "getting-started" / "acp-tools.md").read_text(encoding="utf-8")
    ctl = (REPO / "pilot" / "policies" / "pilot-control" / "POLICY.md").read_text(
        encoding="utf-8"
    )
    cli = (REPO / "pilot" / "ascendc_pilot" / "cli.py").read_text(encoding="utf-8")
    for text in (core, stub, tools, ctl):
        assert "不是读懂用户句子" in text
        assert "YAML" in text
        assert "PASS" in text
        assert "用户原话里的产品意图" not in text
    assert "e.g. diff_only" not in cli
    assert "Turn payload, not NL routing" in cli


def test_compact_host_step_keeps_pin_facts() -> None:
    core = (REPO / "opencode-plugin" / "pilot-driver-core.ts").read_text(encoding="utf-8")
    start = core.index("const HOST_STEP_MODEL_KEYS")
    chunk = core[start : start + 1200]
    for key in (
        '"project"',
        '"architecture"',
        '"selected_by"',
        '"changed_files_preview"',
        '"changed_files"',
    ):
        assert key in chunk, f"{key} missing from HOST_STEP_MODEL_KEYS"
    ack_start = core.index("export async function driveContinueGoalAfterAck")
    ack = core[ack_start : ack_start + 900]
    assert "args.step.message_zh" in ack
    assert "selected_by" in ack
    assert "changed_files_preview" in ack or "changed_files" in ack
