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
    state = start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    cand = uo / "ir" / "extract_plan_candidates.yaml"
    _write(
        cand,
        "version: 1\nop_name: demo\nstatus: candidates\nok: true\nwriter_candidates: []\n",
    )
    sha = file_sha256(cand)
    run_id = str(state.get("run_id") or "")
    _write(
        uo / "ir" / "extract_plan.yaml",
        (
            "version: 1\nop_name: demo\naction_id: extract_plan\n"
            "actor_id: uo-semantic-resolve\n"
            f"run_id: {run_id}\n"
            "workflow_id: uo-init\n"
            "status: resolved\n"
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


def test_extract_plan_gate_fails_empty_sinks_contract(tmp_path: Path) -> None:
    """Gate reuses apply validate — empty sinks with suggested candidates must fail."""
    ensure_agent_layout(tmp_path)
    state = start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    cand = uo / "ir" / "extract_plan_candidates.yaml"
    _write(
        cand,
        (
            "version: 1\nstatus: candidates\nok: true\n"
            "writer_candidates:\n"
            "  - name: SaveStuff\n"
            "    file_path: op_host/a.cpp\n"
            "    role_suggested: tiling_writer\n"
            "    score: 0.9\n"
            "receiver_candidates:\n"
            "  - name: blob_\n"
            "    file_path: op_host/a.cpp\n"
            "    is_tiling_sink_suggested: true\n"
            "alias_candidates: []\n"
            "non_sink_root_candidates: []\n"
            "extra_entry_candidates: []\n"
        ),
    )
    sha = file_sha256(cand)
    run_id = str(state.get("run_id") or "")
    _write(
        uo / "ir" / "extract_plan.yaml",
        (
            "version: 1\n"
            "actor_id: uo-semantic-resolve\n"
            f"run_id: {run_id}\n"
            "workflow_id: uo-init\n"
            f"candidates_sha256: {sha}\n"
            "writers:\n"
            "  - name: SaveStuff\n"
            "    file_path: op_host/a.cpp\n"
            "    role: tiling_writer\n"
            "    evidence_source: candidate_only\n"
            "receivers: []\n"
            "aliases: []\n"
        ),
    )
    _write(uo / "ir" / "entrypoint_graph.yaml", "version: 2\nnodes: []\n")
    _write(uo / "ir" / "operator_boundary.yaml", "version: 1\nok: true\n")
    result = gate_extract_plan_subagent(tmp_path, uo)
    assert result["ok"] is False
    assert result.get("contract_ok") is False
    assert result.get("receipt_required") is False
    assert result.get("receipt_informational") is True
    err_text = " ".join(str(e) for e in (result.get("errors") or []))
    assert "tiling_sink" in err_text or "promote" in err_text or "evidence" in err_text
