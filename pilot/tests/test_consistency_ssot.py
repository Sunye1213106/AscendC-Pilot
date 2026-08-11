"""SSOT consistency checker tests."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def repo_root() -> Path:
    return REPO


def test_check_all_passes_on_real_repo(repo_root: Path) -> None:
    from ascendc_pilot.workflows.consistency import check_all

    errors = check_all(repo_root)
    assert errors == [], errors


def test_unknown_output_contract_fail_closed() -> None:
    from ascendc_pilot.actions.runtime import _check_output_contract

    r = _check_output_contract(Path("."), "not-a-real-contract-ssot-probe")
    assert r["ok"] is False
    assert r["error"] == "unknown_contract"


def test_injected_action_missing_contract_fails(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ascendc_pilot.workflows import WORKFLOWS
    from ascendc_pilot.workflows import specs as specs_mod
    from ascendc_pilot.workflows.consistency import check_all

    fake_wid = "_ssot_test_workflow"
    base = copy.deepcopy(WORKFLOWS["uo-query"])
    base["slash"] = "/ssot-test"
    base["actions"] = list(base["actions"]) + [
        {
            "id": "broken_semantic",
            "label_zh": "broken",
            "phases": ["route"],
            "checker_required": True,
            "referee_required": False,
            "gates": [],
            "agent_id": "uo-query",
            "role_id": "readonly_analyst",
            "execution_mode": "subagent",
            "policy_ids": [],
            "capability_ids": ["kb-query"],
            "action_method_id": "uo-query/kb-lookup",
            "task_prompt_id": None,
            "context_profile_id": "ssot-broken",
            "output_contract_id": None,
            "actors": ["uo-query"],
        }
    ]
    patched = dict(WORKFLOWS)
    patched[fake_wid] = base
    monkeypatch.setattr(specs_mod, "WORKFLOWS", patched)

    errors = check_all(repo_root, workflows=patched)
    assert any("broken_semantic" in e and "task_prompt_id" in e for e in errors)
    assert any("broken_semantic" in e and "output_contract_id" in e for e in errors)


def test_injected_unknown_contract_id_fails(repo_root: Path) -> None:
    from ascendc_pilot.workflows.consistency import check_all

    wid = "_ssot_unknown_contract"
    wf = {
        "slash": "/x",
        "phases": ["p"],
        "gates": [],
        "pipelines": {"p": ["bad_contract"]},
        "actions": [
            {
                "id": "bad_contract",
                "label_zh": "x",
                "phases": ["p"],
                "checker_required": True,
                "referee_required": False,
                "gates": [],
                "agent_id": None,
                "role_id": "deterministic_engine",
                "execution_mode": "deterministic",
                "policy_ids": [],
                "capability_ids": [],
                "action_method_id": "uo-init/extract",
                "task_prompt_id": None,
                "context_profile_id": "x",
                "output_contract_id": "not-registered-contract-xyz",
                "actors": [],
            }
        ],
    }
    errors = check_all(repo_root, workflows={wid: wf})
    assert any("unknown output_contract_id" in e for e in errors)


def test_uo_deterministic_actions_have_no_task_prompt() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    for workflow_id in ("uo-init", "uo-update"):
        for action in WORKFLOWS[workflow_id]["actions"]:
            if action.get("execution_mode") == "deterministic":
                assert not action.get("task_prompt_id"), (workflow_id, action["id"])
                assert not action.get("agent_id"), (workflow_id, action["id"])


def test_uo_query_uses_codemap_prompt() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    action = next(a for a in WORKFLOWS["uo-query"]["actions"] if a["id"] == "kb_lookup")
    assert action["task_prompt_id"] == "uo/codemap-query"


def test_uo_init_pipeline_matches_preferred() -> None:
    from ascendc_pilot.workflows import phase_pipeline
    from ascendc_pilot.workflows.pipeline import preferred_pipeline

    for phase in ("prepare", "extract", "analyze", "commit", "verify"):
        assert phase_pipeline("uo-init", phase) == preferred_pipeline("uo-init", phase)
        assert preferred_pipeline("uo-init", phase)
