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


def test_producer_fence_does_not_forbid_its_own_contract_output(repo_root: Path) -> None:
    """A direct producer must not be fenced off from the canonical product it owns.

    `check_all` only intersects agent write_scopes with contract paths, so a
    `machine_constraints` / `forbidden` tag pointing at the producer's own output
    stays invisible there and only surfaces as a deny at write time. `ce-analyst`
    carried `write_canonical_ce_plan` (a fence meant for non-producers like
    `ce-applier`) against its own `ce/plan/*_plan.md` for exactly that reason.
    """
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.agents_registry import forbidden_blocks_write
    from ascendc_pilot.workflows import WORKFLOWS

    offenders = []
    for wid, wf in WORKFLOWS.items():
        for action in wf.get("actions") or []:
            if action.get("role_id") != "producer":
                continue
            if action.get("output_mode") == "staged":
                continue  # canonical path belongs to the merge action, not this one
            agent_id = str(action.get("agent_id") or "")
            contract_id = str(action.get("output_contract_id") or "")
            if not agent_id or not contract_id:
                continue
            for rel in OUTPUT_CONTRACT_PATHS.get(contract_id) or []:
                if str(rel).startswith("runs/"):
                    continue
                probe = str(rel).replace("*_plan.md", "demo_plan.md").replace("*", "demo")
                reason = forbidden_blocks_write(agent_id, probe, project_root=repo_root)
                if reason:
                    offenders.append(f"{wid}/{action['id']}: {agent_id} fenced from {rel} ({reason})")
    assert offenders == [], offenders


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
            "phases": ["answer"],
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
                # Registry normalization may pin deterministic-uo-engine; never a Host Task agent.
                actor = str(action.get("agent_id") or "")
                assert actor in {"", "deterministic-uo-engine"}, (workflow_id, action["id"], actor)


def test_uo_query_uses_codemap_prompt() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    action = next(a for a in WORKFLOWS["uo-query"]["actions"] if a["id"] == "kb_lookup")
    assert action["task_prompt_id"] == "uo/codemap-query"
    assert action["output_contract_id"] == "kb-answer-v1"
    assert action.get("output_mode") == "return_value"
    writes = [str(p).replace("\\", "/") for p in (action.get("allowed_write_paths") or [])]
    assert "answer.yaml" not in ",".join(writes)


def test_kb_answer_contract_is_lease_answer_not_integrity() -> None:
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.workflows.consistency import _PRECONDITION_CONTRACTS

    assert OUTPUT_CONTRACT_PATHS["kb-answer-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["code-review-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["tg-bind-review-v1"] == []
    assert "kb-answer-v1" not in _PRECONDITION_CONTRACTS


def test_uo_init_pipeline_matches_preferred() -> None:
    from ascendc_pilot.workflows import phase_pipeline
    from ascendc_pilot.workflows.pipeline import preferred_pipeline

    for phase in ("prepare", "heal", "extract", "analyze", "commit", "verify"):
        assert phase_pipeline("uo-init", phase) == preferred_pipeline("uo-init", phase)
        assert preferred_pipeline("uo-init", phase)


def test_direct_action_empty_write_paths_fail_closed(repo_root: Path) -> None:
    from ascendc_pilot.workflows.consistency import check_all

    wf = {
        "slash": "/x",
        "phases": ["p"],
        "gates": [],
        "pipelines": {"p": ["review_like"]},
        "actions": [
            {
                "id": "review_like",
                "label_zh": "x",
                "phases": ["p"],
                "checker_required": True,
                "referee_required": False,
                "gates": [],
                "agent_id": "ce-reviewer",
                "role_id": "readonly_reviewer",
                "execution_mode": "subagent",
                "policy_ids": [],
                "capability_ids": [],
                "task_prompt_id": None,
                "output_contract_id": "ce-plan-v1",
                "allowed_write_paths": [],
                "actors": ["ce-reviewer"],
            }
        ],
    }
    errors = check_all(repo_root, workflows={"_ssot_empty_writes": wf})
    assert any("not covered by allowed_write_paths" in e for e in errors)
