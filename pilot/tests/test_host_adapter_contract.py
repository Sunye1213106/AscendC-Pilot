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


def test_host_context_multi_arch_ambiguous(tmp_path: Path, monkeypatch) -> None:
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    ensure_agent_layout(tmp_path, arch="arch22")
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch22")
    # Clear env pin from start_workflow before second arch start.
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    start_workflow(tmp_path, "uo-query", architecture="arch35")
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    ctx = build_host_context(tmp_path, architecture="")
    assert ctx.get("ok") is False
    assert ctx.get("error") in {
        "ARCHITECTURE_MISSING_IN_RUN_STATE",
        "ARCHITECTURE_AMBIGUOUS",
    }
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
