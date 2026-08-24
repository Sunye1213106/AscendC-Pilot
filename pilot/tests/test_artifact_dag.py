"""Producer/Consumer artifact DAG tests."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def repo_root() -> Path:
    return REPO


def test_uo_init_prepare_produces_scope_validated() -> None:
    from ascendc_pilot.workflows.artifact_dag import normalize_produces
    from ascendc_pilot.workflows.specs import WORKFLOWS

    prepare = next(a for a in WORKFLOWS["uo-init"]["actions"] if a["id"] == "prepare")
    produced = normalize_produces(prepare)
    assert "uo/runs/{run_id}/scope/scope_validated.yaml" in produced
    assert prepare.get("schema_version") == "1"
    assert prepare.get("produces") is None
    assert prepare.get("consumes") == []


def test_uo_init_pipeline_gate_reads_have_producers() -> None:
    from ascendc_pilot.workflows.artifact_dag import (
        GATE_ARTIFACT_READS,
        check_artifact_dag,
        normalize_consumes,
        normalize_produces,
    )
    from ascendc_pilot.workflows.specs import WORKFLOWS

    wf = WORKFLOWS["uo-init"]
    # Restrict map to uo-init only so orphan scan is pipeline-local + still
    # sees commit → uo/*.uo for product gates.
    subset = {"uo-init": wf}
    errors = check_artifact_dag(subset)
    gate_orphans = [
        e
        for e in errors
        if e.startswith("ARTIFACT_ORPHAN_CONSUME: uo-init/")
        and any(
            path in e
            for paths in GATE_ARTIFACT_READS.values()
            for path in paths
        )
    ]
    assert gate_orphans == [], gate_orphans

    for aid in ("extract", "commit", "verify"):
        action = next(a for a in wf["actions"] if a["id"] == aid)
        consumes = normalize_consumes(action)
        for path in consumes:
            if path.startswith("context/") or path == "context/**":
                continue
            # Gate-declared reads for these actions must resolve via producers
            # in the full uo-init subset (checked above). Keep a local sanity:
            assert path  # non-empty
        # Commit must produce the formal product used by uo_product_ready.
        if aid == "commit":
            assert "uo/*.uo" in normalize_produces(action)


def test_check_artifact_dag_clean_on_full_workflows() -> None:
    from ascendc_pilot.workflows.artifact_dag import check_artifact_dag

    errors = check_artifact_dag()
    assert errors == [], errors


def test_rework_backedge_cannot_justify_future_producer() -> None:
    """Forward-only: C→A rework must not make C's produce precede B's consume."""
    from ascendc_pilot.workflows.artifact_dag import check_artifact_dag

    probe = {
        "slash": "/artifact-dag-rework-order",
        "entry_state": "A",
        "states": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
        "transitions": [
            {"from": "A", "to": "B", "kind": "forward"},
            {"from": "B", "to": "C", "kind": "forward"},
            {"from": "C", "to": "A", "kind": "rework"},
        ],
        "pipelines": {
            "A": ["act_a"],
            "B": ["act_b"],
            "C": ["act_c"],
        },
        "actions": [
            {
                "id": "act_a",
                "label_zh": "a",
                "phases": ["A"],
                "pre_gates": [],
                "post_gates": [],
                "produces": [],
                "consumes": [],
                "schema_version": "1",
            },
            {
                "id": "act_b",
                "label_zh": "b",
                "phases": ["B"],
                "pre_gates": [],
                "post_gates": [],
                "produces": [],
                "consumes": ["kb/future_x.yaml"],
                "schema_version": "1",
            },
            {
                "id": "act_c",
                "label_zh": "c",
                "phases": ["C"],
                "pre_gates": [],
                "post_gates": [],
                "produces": ["kb/future_x.yaml"],
                "consumes": [],
                "schema_version": "1",
            },
        ],
    }
    errors = check_artifact_dag({"_rework_order_probe": probe})
    assert any(
        "ARTIFACT_PRODUCER_NOT_BEFORE_CONSUMER" in e and "act_b" in e
        for e in errors
    ), errors


def test_synthetic_orphan_consume_detected() -> None:
    from ascendc_pilot.workflows.artifact_dag import check_artifact_dag
    from ascendc_pilot.workflows.specs import WORKFLOWS

    base = copy.deepcopy(WORKFLOWS["uo-query"])
    base["slash"] = "/artifact-dag-orphan"
    base["actions"] = [
        {
            "id": "broken_consume",
            "label_zh": "broken",
            "phases": ["answer"],
            "pre_gates": [],
            "post_gates": [],
            "output_contract_id": None,
            "produces": [],
            "consumes": ["tg/never/produced/by/anyone.yaml"],
            "schema_version": "1",
        }
    ]
    errors = check_artifact_dag({"_orphan_probe": base})
    assert any(
        "ARTIFACT_ORPHAN_CONSUME" in e
        and "broken_consume" in e
        and "tg/never/produced/by/anyone.yaml" in e
        for e in errors
    ), errors


def test_artifact_usage_receipts_are_run_scoped(repo_root: Path) -> None:
    from ascendc_pilot.workflows.artifact_dag import RECEIPT_ARTIFACTS, check_artifact_usage

    errors = check_artifact_usage(repo_root)
    assert errors == [], errors
    assert RECEIPT_ARTIFACTS == {
        "runs/{run_id}/receipts/uo_ready.yaml",
    }


def test_prepare_post_gates_do_not_self_consume() -> None:
    from ascendc_pilot.workflows.artifact_dag import normalize_consumes, normalize_published
    from ascendc_pilot.workflows.specs import WORKFLOWS

    prepare = next(a for a in WORKFLOWS["uo-init"]["actions"] if a["id"] == "prepare")
    assert "scope_receipt" in (prepare.get("post_gates") or [])
    published = normalize_published(prepare)
    consumes = normalize_consumes(prepare)
    assert "uo/runs/{run_id}/scope/scope_validated.yaml" in published
    assert "uo/runs/{run_id}/scope/scope_validated.yaml" not in consumes
    assert not (set(published) & set(consumes))


def test_verify_post_gates_do_not_self_consume() -> None:
    from ascendc_pilot.workflows.artifact_dag import normalize_consumes, normalize_published
    from ascendc_pilot.workflows.specs import WORKFLOWS

    verify = next(a for a in WORKFLOWS["uo-init"]["actions"] if a["id"] == "verify")
    assert "integrity" in (verify.get("post_gates") or [])
    published = set(normalize_published(verify))
    consumes = set(normalize_consumes(verify))
    assert "uo/checks/integrity.yaml" in published
    assert not (published & consumes)


def test_precheck_actions_publish_nothing() -> None:
    from ascendc_pilot.workflows.artifact_dag import normalize_published
    from ascendc_pilot.workflows.specs import WORKFLOWS

    plan_pc = next(a for a in WORKFLOWS["tg-plan"]["actions"] if a["id"] == "plan_precheck")
    solve_pc = next(a for a in WORKFLOWS["tg-solve"]["actions"] if a["id"] == "solve_precheck")
    assert plan_pc.get("pre_gates")
    assert solve_pc.get("pre_gates")
    assert normalize_published(plan_pc) == []
    assert normalize_published(solve_pc) == []


def test_construct_cases_write_allow_forbid_disjoint() -> None:
    from ascendc_pilot.ownership import write_paths_overlap
    from ascendc_pilot.workflows.specs import WORKFLOWS

    mine = next(a for a in WORKFLOWS["tg-solve"]["actions"] if a["id"] == "construct_cases")
    allow = list(mine.get("allowed_write_paths") or [])
    forbid = list(mine.get("forbidden_write_paths") or [])
    assert mine.get("output_mode") == "return_value"
    assert allow == []
    for a in allow:
        for b in forbid:
            assert not write_paths_overlap(a, b), (a, b)


def test_return_value_producer_does_not_publish_canonical() -> None:
    from ascendc_pilot.workflows.artifact_dag import is_staged_producer, normalize_published
    from ascendc_pilot.workflows.specs import WORKFLOWS

    ingest = next(a for a in WORKFLOWS["tg-plan"]["actions"] if a["id"] == "plan_ingest")
    assert ingest.get("output_mode") == "return_value"
    assert not is_staged_producer(ingest)
    published = normalize_published(ingest)
    assert published == []
