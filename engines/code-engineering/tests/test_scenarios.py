# -*- coding: utf-8 -*-
"""Scenario catalog mapping, infer, and harness adapter contracts."""

from __future__ import annotations

import csv
from pathlib import Path

from code_engineering.harness import evidence_receipt, load_adapter
from code_engineering.harness.host_replay import HostReplayAdapter
from code_engineering.scenarios import anchors_from_slice, infer_scenario_set
from code_engineering.scenarios.catalog import LEGAL_IDS, scenarios_for_anchor


def test_catalog_ids_match_skill_doc() -> None:
    skill = (
        Path(__file__).resolve().parents[3]
        / "skills"
        / "code-engineering"
        / "references"
        / "scenario-catalog.md"
    )
    text = skill.read_text(encoding="utf-8")
    for sid in sorted(LEGAL_IDS):
        assert f"`{sid}`" in text


def test_cast_anchor_maps_precision_only() -> None:
    ids = scenarios_for_anchor(
        {"kind": "OPERATION", "name": "Cast", "facts": {"callee": "Cast"}}
    )
    assert ids == ("P-CAST", "P-DTYPE")
    assert "F-SPLIT" not in ids


def test_split_field_maps_perf() -> None:
    ids = scenarios_for_anchor({"kind": "TILING_FIELD", "name": "usedCoreNum"})
    assert "F-SPLIT" in ids
    assert "F-SHAPE-TYPICAL" in ids
    assert "F-BALANCE" in ids


def test_illegal_name_maps_p_illegal() -> None:
    ids = scenarios_for_anchor({"kind": "INPUT", "name": "illegal_pse"})
    assert "P-ILLEGAL" in ids
    assert "P-OPTIONAL" in ids


def test_infer_from_slice_groups_and_drops_unknown() -> None:
    impact = {
        "anchors": [
            {"kind": "OPERATION", "name": "Cast", "facts": {"callee": "Cast"}, "file": "k.cpp", "line_start": 10},
            {"kind": "UNKNOWN", "name": "skip-me"},
        ]
    }
    doc = infer_scenario_set(anchors_from_slice(impact), entry="diff")
    assert doc["schema"] == "ce-scenario-set/v1"
    assert {row["id"] for row in doc["items"]} == {"P-CAST", "P-DTYPE"}
    assert all(row["id"] in LEGAL_IDS for row in doc["items"])


def test_merge_knobs_overlays_skeleton_and_drops_unknown() -> None:
    from code_engineering.scenarios import merge_knobs

    skeleton = infer_scenario_set(
        [{"kind": "OPERATION", "name": "Cast", "facts": {"callee": "Cast"}}],
        entry="diff",
    )
    overlay = {
        "schema": "ce-scenario-knobs/v1",
        "items": [
            {
                "id": "P-CAST",
                "knobs": {"dtype": "fp16"},
                "budget": {"max_cases": 2},
                "oracle": "cast golden",
            },
            {"id": "NOT-A-SCENE", "knobs": {"x": 1}},
        ],
    }
    merged = merge_knobs(skeleton, overlay)
    by_id = {row["id"]: row for row in merged["items"]}
    assert by_id["P-CAST"]["knobs"]["dtype"] == "fp16"
    assert by_id["P-CAST"]["budget"]["max_cases"] == 2
    assert by_id["P-CAST"]["oracle"] == "cast golden"
    assert "NOT-A-SCENE" not in by_id
    assert {row["id"] for row in merged["items"]} <= set(LEGAL_IDS)


def test_host_replay_precision_is_harness_missing(tmp_path: Path) -> None:
    adapter = HostReplayAdapter(tmp_path)
    csv_path = tmp_path / "case.csv"
    adapter.emit([], csv_path)
    result = adapter.run(csv_path, "only_grad")
    assert result["reason"] == "harness_missing"
    receipt = adapter.to_evidence(
        result, change_head_sha="abc", obligation_ids=["ce-precision-1"]
    )
    assert receipt["schema"] == "ce-external-evidence/v1"
    assert receipt["ok"] is False
    assert receipt["verified_obligations"] == []
    assert receipt["reason"] == "harness_missing"


def test_load_adapter_defaults_to_host_replay(tmp_path: Path) -> None:
    adapter = load_adapter(tmp_path, architecture="arch20")
    assert adapter.identity()["kind"] == "host_replay"


def test_fag_retrieve_emit_without_npu(tmp_path: Path) -> None:
    from code_engineering.harness.fag import FagHarnessAdapter

    root = tmp_path / "fag_debug_tools"
    data = root / "data"
    data.mkdir(parents=True)
    corpus = data / "fag_arch35_reachable_cases.csv"
    with corpus.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Testcase_Name", "enable", "Dtype", "B", "N1", "S1"],
        )
        writer.writeheader()
        writer.writerow(
            {"Testcase_Name": "cast_fp16", "enable": "enable", "Dtype": "fp16", "B": "1", "N1": "2", "S1": "128"}
        )
        writer.writerow(
            {"Testcase_Name": "bad_pse", "enable": "disable", "Dtype": "bf16", "B": "1", "N1": "2", "S1": "128"}
        )
    adapter = FagHarnessAdapter(
        tmp_path,
        manifest={"kind": "fag", "root": str(root), "corpus": ["data/fag_arch35_reachable_cases.csv"]},
    )
    hits = adapter.retrieve({"id": "P-CAST", "budget": {"max_cases": 4}, "knobs": {"dtype": "fp16"}})
    assert len(hits) == 1
    dest = tmp_path / "out.csv"
    adapter.emit(hits, dest)
    text = dest.read_text(encoding="utf-8")
    assert "cast_fp16" in text
    illegal = adapter.retrieve({"id": "P-ILLEGAL", "budget": {"max_cases": 0}})
    assert illegal and illegal[0]["enable"] == "disable"


def test_evidence_receipt_requires_schema() -> None:
    doc = evidence_receipt(
        change_head_sha="deadbeef",
        obligation_ids=["o1"],
        kind="precision_compare",
        artifact="a.csv",
        ok=True,
    )
    assert doc["schema"] == "ce-external-evidence/v1"
    assert doc["verified_obligations"] == ["o1"]
