"""P2: Workflow model checker + user-facing session replay matrix."""

from __future__ import annotations

from pathlib import Path

import pytest

from ascendc_pilot.session_replay import (
    SCENARIO_HANDLERS,
    iter_matrix_cells,
    load_matrix,
    run_cell,
)
from ascendc_pilot.workflows.model_checker import (
    MATRIX_WORKFLOWS,
    TG_SOLVE_REWORK_CODES,
    check_all_models,
    check_tg_solve_routing,
)


def test_model_checker_clean() -> None:
    errors = check_all_models()
    assert errors == [], "\n".join(errors)


def test_tg_solve_routing_codes_declared() -> None:
    errors = check_tg_solve_routing()
    assert errors == [], "\n".join(errors)
    assert set(TG_SOLVE_REWORK_CODES) == {
        "SEARCH_PROGRESS",
        "CONSTRUCT_TARGETS",
        "SEARCH_STALLED",
        "NEED_LEMMA",
    }


def test_matrix_fixture_covers_matrix_workflows() -> None:
    from ascendc_pilot.workflows import list_user_workflows

    doc = load_matrix()
    assert list(doc.get("workflows") or []) == list(MATRIX_WORKFLOWS)
    assert set(MATRIX_WORKFLOWS) == set(list_user_workflows())
    scenario_ids = {str(s.get("id")) for s in (doc.get("scenarios") or []) if isinstance(s, dict)}
    assert set(SCENARIO_HANDLERS) == scenario_ids
    for sid in SCENARIO_HANDLERS:
        assert sid in scenario_ids


def _cells() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for wid, sid, appl in iter_matrix_cells():
        if appl == "run":
            out.append((wid, sid))
    return out


@pytest.mark.parametrize(("workflow_id", "scenario_id"), _cells())
def test_session_replay_matrix_cell(workflow_id: str, scenario_id: str, tmp_path: Path) -> None:
    result = run_cell(workflow_id, scenario_id, tmp_path)
    assert result.get("ok") is True, result
