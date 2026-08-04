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
    from ascendc_pilot.workflows import specs as specs_mod
    from ascendc_pilot.workflows.consistency import check_all

    fake_wid = "_ssot_test_workflow"
    base = copy.deepcopy(specs_mod.WORKFLOWS["uo-query"])
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
            "policy_ids": [],
            "capability_ids": ["kb-query"],
            "action_method_id": "uo-query/kb-lookup",
            "task_prompt_id": None,
            "context_profile_id": "ssot-broken",
            "output_contract_id": None,
            "actors": ["uo-query"],
        }
    ]
    patched = dict(specs_mod.WORKFLOWS)
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
        "pipelines": {"p": []},
        "actions": [
            {
                "id": "bad_contract",
                "label_zh": "x",
                "phases": ["p"],
                "checker_required": True,
                "referee_required": False,
                "gates": [],
                "agent_id": "deterministic-uo-engine",
                "role_id": "deterministic_engine",
                "policy_ids": [],
                "capability_ids": [],
                "action_method_id": "uo-init/prepare-layout",
                "task_prompt_id": None,
                "context_profile_id": "x",
                "output_contract_id": "not-registered-contract-xyz",
                "actors": ["deterministic-uo-engine"],
            }
        ],
    }
    errors = check_all(repo_root, workflows={wid: wf})
    assert any("unknown output_contract_id" in e for e in errors)


def test_shared_prompts_use_workflow_placeholder(repo_root: Path) -> None:
    from ascendc_pilot.workflows.consistency import _collect_shared_task_prompts
    from ascendc_pilot.workflows.specs import WORKFLOWS

    shared = _collect_shared_task_prompts(WORKFLOWS)
    # KEY triage/resolution live on uo-update; confidence review may be shared.
    for tpid in ("uo/key-triage", "uo/key-resolution", "uo/confidence-review"):
        if tpid not in shared:
            continue
        dom, name = tpid.split("/", 1)
        text = (repo_root / "prompts" / "tasks" / dom / f"{name}.md").read_text(encoding="utf-8")
        assert "`<WORKFLOW_ID>`" in text, tpid
    # At least one shared prompt must still use the placeholder convention.
    assert shared == {} or any(
        "`<WORKFLOW_ID>`" in (repo_root / "prompts" / "tasks" / tpid.split("/")[0] / f"{tpid.split('/')[1]}.md").read_text(encoding="utf-8")
        for tpid in shared
    )


def test_uo_init_extract_normalize_pipeline_matches_preferred() -> None:
    from ascendc_pilot.workflows import phase_pipeline
    from ascendc_pilot.workflows.pipeline import preferred_pipeline

    for phase in ("extract", "normalize"):
        assert phase_pipeline("uo-init", phase) == preferred_pipeline("uo-init", phase)
        assert preferred_pipeline("uo-init", phase)
