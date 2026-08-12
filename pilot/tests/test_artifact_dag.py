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
    # sees commit → ../uo/*.uo for product gates.
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
            assert "../uo/*.uo" in normalize_produces(action)


def test_check_artifact_dag_clean_on_full_workflows() -> None:
    from ascendc_pilot.workflows.artifact_dag import check_artifact_dag

    errors = check_artifact_dag()
    assert errors == [], errors


def test_synthetic_orphan_consume_detected() -> None:
    from ascendc_pilot.workflows.artifact_dag import check_artifact_dag
    from ascendc_pilot.workflows.specs import WORKFLOWS

    base = copy.deepcopy(WORKFLOWS["uo-query"])
    base["slash"] = "/artifact-dag-orphan"
    base["actions"] = [
        {
            "id": "broken_consume",
            "label_zh": "broken",
            "phases": ["route"],
            "gates": [],
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
