"""FAG E2E hooks — fixture-level acceptance for Phase A/B/C (no full acp run)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uo.scripts._ir_io import read_yaml
from uo.scripts.evidence_score import score_entrypoint_node
from uo.scripts.llm_tasks import open_blocking_tasks, validate_mark_missing_patch
from uo.scripts.semantic_task_triage import write_semantic_task_triage

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fag_macro_semantic_failure"
RUN_ID = "RUN_20260726_121719_0d48474d"


@pytest.mark.fag_e2e
def test_fag_fixture_macro_nodes_auto_accept() -> None:
    ep = read_yaml(FIXTURE / "entrypoint_graph.yaml") or {}
    macro_nodes = [n for n in (ep.get("nodes") or []) if isinstance(n, dict) and n.get("macro")]
    assert macro_nodes
    for n in macro_nodes:
        # Simulate post-materializer confidence.
        n = dict(n)
        n.setdefault("confidence", "source_verified")
        scored = score_entrypoint_node(n, architecture="arch35")
        assert scored["disposition"] == "auto_accept"


@pytest.mark.fag_e2e
def test_fag_fixture_pre_tasks_not_adjudicable(tmp_path: Path) -> None:
    from uo.scripts._ir_io import write_yaml

    uo = tmp_path / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(uo / "manifest.yaml", {"current_run_id": RUN_ID})
    write_yaml(uo / "ir" / "llm_tasks.yaml", read_yaml(FIXTURE / "llm_tasks_pre.yaml") or {})
    write_semantic_task_triage(uo, run_id=RUN_ID)
    assert open_blocking_tasks(uo, current_run_id=RUN_ID) == []


@pytest.mark.fag_e2e
def test_fag_score_only_mark_missing_rejected() -> None:
    task = {
        "task_id": "TASK_fag",
        "triage_category": "macro_contract_resolvable",
        "allowed_actions": ["mark_missing"],
    }
    err = validate_mark_missing_patch(
        task,
        {
            "task_id": "TASK_fag",
            "action": "mark_missing",
            "evidence": ["score 0.0 below auto_accept"],
        },
    )
    assert err is not None
    assert err["error"] == "mark_missing_forbidden_macro_contract"
