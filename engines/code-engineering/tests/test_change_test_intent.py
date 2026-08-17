"""ChangeTestIntent + planned vs actual scenario delta."""

from __future__ import annotations

from code_engineering.change_test_intent import build_change_test_intent, scenario_delta


def test_scenario_delta_splits_planned_and_actual() -> None:
    planned = {"items": [{"id": "P-CAST"}, {"id": "F-SPLIT"}]}
    actual = {"items": [{"id": "P-CAST"}, {"id": "P-DTYPE"}]}
    delta = scenario_delta(planned, actual)
    assert delta["planned_and_hit"] == ["P-CAST"]
    assert delta["newly_discovered"] == ["P-DTYPE"]
    assert delta["planned_but_not_impacted"] == ["F-SPLIT"]


def test_change_test_intent_is_typed() -> None:
    doc = build_change_test_intent(
        impact={"affected_keys": [17], "head": "abc123"},
        obligations=[
            {
                "id": "CE-OBL-17",
                "kind": "host_branch",
                "symbol": "ScatterAdd",
                "predicate": {"v_is_null": True},
            }
        ],
        uo_digest="deadbeef",
        source_fingerprint="ffff",
        change_revision="abc123",
    )
    assert doc["schema"] == "ce-change-test-intent/v1"
    kinds = {row["kind"] for row in doc["targets"]}
    assert "tiling_key" in kinds
    assert "host_branch" in kinds
    assert any(row.get("obligation_id") == "CE-OBL-17" for row in doc["targets"])


def test_tg_plan_intent_from_impact_keys() -> None:
    from code_engineering.change_test_intent import build_tg_plan_intent

    doc = build_tg_plan_intent(impact={"affected_keys": [3], "fields": ["DType"]})
    assert doc["mode"] == "ce_change_scoped"
    assert doc["target_keys"] == [3]
    empty = build_tg_plan_intent(impact={})
    assert empty["target_keys"] == []
    assert empty["target_mode"] == "explicit_keys"
