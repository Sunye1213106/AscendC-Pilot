"""extract_plan_subagent gate must not require receipt before finalize issues it."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.gates import gate_extract_plan_subagent
from ascendc_pilot.paths import ensure_agent_layout, uo_root
from ascendc_pilot.runs import file_sha256
from ascendc_pilot.state import start_workflow


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_extract_plan_gate_passes_without_receipt(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    cand = uo / "ir" / "extract_plan_candidates.yaml"
    _write(
        cand,
        "version: 1\nop_name: demo\nstatus: candidates\nok: true\nwriter_candidates: []\n",
    )
    sha = file_sha256(cand)
    _write(
        uo / "ir" / "extract_plan.yaml",
        (
            "version: 1\nop_name: demo\naction_id: extract_plan\n"
            "actor_id: uo-semantic-resolve\nstatus: resolved\n"
            f"candidates_sha256: {sha}\nwriters: []\nreceivers: []\naliases: []\n"
        ),
    )
    _write(uo / "ir" / "entrypoint_graph.yaml", "version: 2\nnodes: []\n")
    _write(uo / "ir" / "operator_boundary.yaml", "version: 1\nok: true\n")

    result = gate_extract_plan_subagent(tmp_path, uo)
    assert result["ok"] is True
    assert result.get("receipt_required") is False
    assert result.get("has_receipt") is False
    assert result.get("has_plan") is True


def test_extract_plan_gate_fails_when_plan_missing(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    _write(uo / "ir" / "extract_plan_candidates.yaml", "version: 1\nstatus: candidates\nok: true\n")
    _write(uo / "ir" / "entrypoint_graph.yaml", "version: 2\nnodes: []\n")
    _write(uo / "ir" / "operator_boundary.yaml", "version: 1\nok: true\n")
    result = gate_extract_plan_subagent(tmp_path, uo)
    assert result["ok"] is False
    assert result.get("has_plan") is False
