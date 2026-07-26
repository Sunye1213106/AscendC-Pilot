"""Rework prepare must reuse candidates (no sha churn)."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.engines import _run_extract_plan
from ascendc_pilot.paths import ensure_agent_layout, uo_root
from ascendc_pilot.state import load_state, save_state, start_workflow


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_extract_plan_prepare_reuses_candidates_on_rework(tmp_path: Path, monkeypatch) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    cand = uo / "ir" / "extract_plan_candidates.yaml"
    _write(
        cand,
        "version: 1\nstatus: candidates\nok: true\nwriter_candidates: []\n"
        "receiver_candidates: []\nalias_candidates: []\n"
        "non_sink_root_candidates: []\nextra_entry_candidates: []\n",
    )
    sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    (uo / "ir" / "extract_plan_candidates.sha256").write_text(sha + "\n", encoding="utf-8")
    _write(
        uo / "ir" / "extract_plan.yaml",
        "version: 1\nwriters: []\nreceivers: []\naliases: []\n",
    )
    st = load_state(tmp_path) or {}
    st["status"] = "rework_required"
    save_state(tmp_path, st)

    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("propose_extract_plan must not run on rework reuse")

    import uo.scripts.propose_extract_plan as pep

    monkeypatch.setattr(pep, "propose_extract_plan", boom)

    result = _run_extract_plan(
        tmp_path,
        {"op_name": tmp_path.name, "architecture": "arch35", "extract_plan_mode": "propose"},
    )
    assert result.get("ok") is True, result
    assert result.get("reused_candidates") is True
    assert result.get("candidates_sha256") == sha
    assert called["n"] == 0
    assert (uo / "ir" / "extract_plan_candidates.summary.yaml").is_file()
