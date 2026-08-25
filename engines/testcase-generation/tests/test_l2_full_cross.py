# -*- coding: utf-8 -*-
"""L2 is a full crossing of a Target's Dimensions, minus the plan's exclusions.

A raw cartesian product means the plan did no reachability analysis, so an empty
exclusion set is rejected. What survives is the ledger Solve must prove.
"""
from __future__ import annotations

import pytest

import testcase_agent.coverage.compile as compile_mod
from testcase_agent import products
from testcase_agent.coverage.compile import (
    PlanCompileError,
    compile_obligations,
)

COLUMNS = ["Alpha", "Beta", "Gamma"]


def _dim(did: str, col: str, values: list[int], target: str = "T-main") -> dict:
    return {
        "id": did,
        "target": target,
        "controls": [col],
        "classifier": {"requires": [f"case.{col}"]},
        "partitions": [
            {"id": f"p-{did}-{v}", "predicate": {"op": "eq", "field": f"case.{col}", "value": v}}
            for v in values
        ],
    }


def _plan(*, exclusions: list[dict] | None = None, dims: list[dict] | None = None) -> dict:
    dims = dims if dims is not None else [
        _dim("D-a", "Alpha", [0, 1]),
        _dim("D-b", "Beta", [0, 1, 2]),
        _dim("D-c", "Gamma", [0, 1]),
    ]
    l2: dict = {"mode": "full_cross"}
    if exclusions is not None:
        l2["exclusions"] = exclusions
    return {
        "schema": "tg-plan/v3",
        "requirement": {"id": "R-x", "text": "x"},
        "targets": [{"id": "T-main", "evidence": {"kind": "replay_field", "field": "replay.f", "expected": 1}}],
        "dimensions": dims,
        "guards": [],
        "coverage": {
            "L0": {"dimensions": [d["id"] for d in dims]},
            "L1": {"combinations": []},
            "L2": l2,
            "L3": {"guards": []},
        },
        "oracle": [],
        "constraints": [],
    }


def _levels(obligations: list[dict]) -> dict[str, int]:
    out = {"L0": 0, "L1": 0, "L2": 0, "L3": 0}
    for row in obligations:
        lv = str(row.get("level"))
        if lv in out:
            out[lv] += 1
    return out


def test_full_cross_crosses_every_dimension_of_the_target() -> None:
    excl = [{"partitions": {"D-a": "p-D-a-0", "D-b": "p-D-b-0"}, "reason": "conflict"}]
    obligations = compile_obligations(_plan(exclusions=excl))
    levels = _levels(obligations)
    # 2 * 3 * 2 = 12 nominal; the excluded pair pins 2 of the 3 dimensions,
    # so it removes one cell per remaining Gamma partition -> 12 - 2 = 10.
    assert levels["L2"] == 10
    assert levels["L0"] == 2 + 3 + 2
    cells = [row["dimensions"] for row in obligations if row["level"] == "L2"]
    assert all(set(cell) == {"D-a", "D-b", "D-c"} for cell in cells)
    assert not any(
        cell["D-a"] == "p-D-a-0" and cell["D-b"] == "p-D-b-0" for cell in cells
    )


def test_full_cross_obligations_are_labeled_and_expect_target_hit() -> None:
    excl = [{"partitions": {"D-a": "p-D-a-1", "D-c": "p-D-c-1"}, "reason": "conflict"}]
    l2 = [row for row in compile_obligations(_plan(exclusions=excl)) if row["level"] == "L2"]
    assert l2 and all(row["kind"] == "full_cross" for row in l2)
    assert all(row["expected"]["targets"] == {"T-main": "HIT"} for row in l2)


def test_dimensions_of_different_targets_are_not_crossed() -> None:
    dims = [
        _dim("D-a", "Alpha", [0, 1], target="T-main"),
        _dim("D-b", "Beta", [0, 1, 2], target="T-main"),
        _dim("D-c", "Gamma", [0, 1], target="T-other"),
    ]
    plan = _plan(
        exclusions=[{"partitions": {"D-a": "p-D-a-0", "D-b": "p-D-b-0"}, "reason": "conflict"}],
        dims=dims,
    )
    plan["targets"].append(
        {"id": "T-other", "evidence": {"kind": "replay_field", "field": "replay.g", "expected": 1}}
    )
    levels = _levels(compile_obligations(plan))
    # Only T-main has >=2 dimensions: 2*3 = 6 nominal, minus 1 excluded cell.
    # T-other has a single dimension, so it contributes no crossing.
    assert levels["L2"] == 5


def test_exclusion_must_name_at_least_two_dimensions() -> None:
    plan = _plan(exclusions=[{"partitions": {"D-a": "p-D-a-0"}, "reason": "why"}])
    with pytest.raises(PlanCompileError) as exc:
        compile_obligations(plan)
    assert any("partitions must map >=2" in e for e in exc.value.errors)


def test_exclusion_requires_a_reason() -> None:
    plan = _plan(exclusions=[{"partitions": {"D-a": "p-D-a-0", "D-b": "p-D-b-0"}}])
    with pytest.raises(PlanCompileError) as exc:
        compile_obligations(plan)
    assert any("reason required" in e for e in exc.value.errors)


def test_exclusion_on_unknown_dimension_is_rejected() -> None:
    plan = _plan(
        exclusions=[{"partitions": {"D-a": "p-D-a-0", "D-nope": "p-x"}, "reason": "why"}]
    )
    with pytest.raises(PlanCompileError) as exc:
        compile_obligations(plan)
    assert any("unknown dimension D-nope" in e for e in exc.value.errors)


def test_full_cross_over_cap_is_refused_instead_of_materialized(monkeypatch) -> None:
    monkeypatch.setattr(compile_mod, "L2_FULL_CROSS_CAP", 5)
    excl = [{"partitions": {"D-a": "p-D-a-0", "D-b": "p-D-b-0"}, "reason": "conflict"}]
    with pytest.raises(PlanCompileError) as exc:
        compile_obligations(_plan(exclusions=excl))
    text = " ".join(exc.value.errors)
    assert "remaining 10" in text
    assert "nominal 12" in text
    assert "excluded 2" in text
    assert "cap 5" in text


def test_cap_applies_after_exclusions(monkeypatch) -> None:
    monkeypatch.setattr(compile_mod, "L2_FULL_CROSS_CAP", 10)
    excl = [{"partitions": {"D-a": "p-D-a-0", "D-b": "p-D-b-0"}, "reason": "conflict"}]
    obligations = compile_obligations(_plan(exclusions=excl))
    levels = _levels(obligations)
    assert levels["L2"] == 10


def test_validator_rejects_full_cross_without_exclusions() -> None:
    errors = products.validate_plan_fence(_plan(), init_columns=COLUMNS)
    assert any("non-empty exclusions" in e for e in errors)


def test_validator_rejects_full_cross_that_also_lists_tuples() -> None:
    plan = _plan(exclusions=[{"partitions": {"D-a": "p-D-a-0", "D-b": "p-D-b-0"}, "reason": "r"}])
    plan["coverage"]["L2"]["tuples"] = [{"dims": ["D-a", "D-b", "D-c"]}]
    errors = products.validate_plan_fence(plan, init_columns=COLUMNS)
    assert any("must not also list tuples" in e for e in errors)


def test_validator_rejects_exclusion_naming_unknown_partition() -> None:
    plan = _plan(
        exclusions=[{"partitions": {"D-a": "p-D-a-0", "D-b": "p-nope"}, "reason": "r"}]
    )
    errors = products.validate_plan_fence(plan, init_columns=COLUMNS)
    assert any("has no partition p-nope" in e for e in errors)


def test_legacy_tuple_mode_still_compiles() -> None:
    plan = _plan()
    plan["coverage"]["L2"] = {"tuples": [{"dims": ["D-a", "D-b", "D-c"], "reason": "chain"}]}
    levels = _levels(compile_obligations(plan))
    assert levels["L2"] == 12
