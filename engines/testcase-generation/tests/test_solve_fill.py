# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from testcase_agent.coverage.compile import compile_obligations
from testcase_agent.coverage.eval import classify_guard, evaluate_obligation
from testcase_agent.plan_fill import AssembleError, assemble_plan
from testcase_agent.solve_fill import (
    _guard_seed,
    assemble_solve,
    falsify_predicate,
    index_plan,
    seed_from_predicate,
)


def _init() -> dict:
    return {
        "columns": [
            {"name": "Testcase_Name"},
            {"name": "sparse_mode"},
            {"name": "is_deter"},
            {"name": "N1"},
            {"name": "N2"},
            {"name": "B"},
        ],
        "defaults": {"sparse_mode": 0, "is_deter": 0, "N1": 4, "N2": 2, "B": 2},
        "domains": {
            "is_deter": {"values": [0, 1]},
            "sparse_mode": {"values": [0, 1, 2]},
        },
        "mapping": {
            "sparse_mode": {"confidence": "confirmed", "control": {"status": "active"}},
            "is_deter": {"confidence": "confirmed", "control": {"status": "active"}},
            "N1": {"confidence": "confirmed", "control": {"status": "active"}},
            "N2": {"confidence": "confirmed", "control": {"status": "active"}},
        },
    }


def _plan_fill() -> dict:
    return {
        "schema": "tg-plan-fill/v1",
        "requirement": "SelectGQADenseSchedule writes selectedRound when is_deter=1 and g>1.",
        "target": {"field": "probe.selectedRound", "op": "gt", "value": 0},
        "dimensions": [
            {
                "id": "D-sparse",
                "cuts": "sparse_mode",
                "arms": [{"id": "p-no-mask", "eq": 0}, {"id": "p-all-mask", "eq": 1}],
            },
            {
                "id": "D-gqa",
                "cuts": ["N1", "N2"],
                "arms": [
                    {"id": "p-g2", "eq": {"N1": 4, "N2": 2}},
                    {"id": "p-g4", "eq": {"N1": 8, "N2": 2}},
                ],
            },
            {
                "id": "D-align",
                "cuts": "probe.baseRound",
                "extra_controls": ["N1", "N2"],
                "arms": [{"id": "p-even", "mod": 0}, {"id": "p-odd", "mod": 1}],
            },
        ],
        "guards": [
            {"id": "G-deter-on", "field": "is_deter", "eq": 1, "violate": 0},
            {"id": "G-mha", "eq": {"N1": 4, "N2": 2}, "violate": {"N1": 4, "N2": 4}},
        ],
        "l1": [{"dims": ["D-sparse", "D-gqa"], "reason": "entry route and ratio are independent"}],
        "exclusions": [
            {
                "D-gqa": "p-g4",
                "D-align": "p-odd",
                "reason": "g=4 pins N1/N2 that the align dim does not use as a case predicate",
            }
        ],
        "oracle": "md5",
        "environment": {"aicNum": 32, "coreNum": 64},
    }


def _activation_plan() -> dict:
    return {
        "schema": "tg-plan/v3",
        "requirement": {"id": "R-deter", "text": "deterministic schedule"},
        "targets": [
            {
                "id": "T-active",
                "evidence": {"kind": "replay_field", "field": "replay.mode", "expected": 1},
            }
        ],
        "dimensions": [
            {
                "id": "D-sparse",
                "target": "T-active",
                "controls": ["sparse_mode"],
                "partitions": [
                    {"id": "p0", "predicate": {"op": "eq", "field": "case.sparse_mode", "value": 0}},
                    {"id": "p1", "predicate": {"op": "eq", "field": "case.sparse_mode", "value": 1}},
                ],
            }
        ],
        "guards": [
            {
                "id": "G-deter-on",
                "target": "T-active",
                "controls": ["is_deter"],
                "predicate": {"op": "eq", "field": "case.is_deter", "value": 1},
                "negate_hint": {"is_deter": 0},
            }
        ],
        "coverage": {
            "L0": {"dimensions": ["D-sparse"]},
            "L1": [],
            "L2": [],
            "L3": {"guards": ["G-deter-on"]},
        },
        "oracle": [],
        "constraints": [],
    }


def test_seed_from_eq_and_probe_incomplete():
    seed, ok = seed_from_predicate({"op": "eq", "field": "case.sparse_mode", "value": 0})
    assert ok and seed == {"sparse_mode": 0}
    seed, ok = seed_from_predicate({"op": "mod_eq", "field": "probe.baseRound", "value": 0})
    assert not ok and seed == {}
    seed, ok = seed_from_predicate({"op": "gt", "field": "case.S1", "value": 1024})
    assert ok and seed == {"S1": 1025}
    seed, ok = seed_from_predicate({"op": "ge", "field": "case.S1", "value": 1024})
    assert ok and seed == {"S1": 1024}


def test_index_marks_probe_arms_as_needs_hit():
    plan = assemble_plan(_plan_fill(), _init())
    idx = index_plan(plan, _init())
    auto_ids = {(r["dim"], r["arm"]) for r in idx["auto"]}
    need_ids = {(r["dim"], r["arm"]) for r in idx["needs_hit"]}
    assert ("D-sparse", "p-no-mask") in auto_ids
    assert ("D-gqa", "p-g2") in auto_ids
    assert ("D-align", "p-even") in need_ids
    assert ("D-align", "p-odd") in need_ids


def test_assemble_requires_probe_hits_and_emits_one_row_per_obligation():
    plan = assemble_plan(_plan_fill(), _init())
    idx = index_plan(plan, _init())
    assert idx["needs_hit"]
    fill = {
        "schema": "tg-solve-fill/v1",
        "baseline": {"is_deter": 1},
        "hits": [
            {"dim": "D-align", "arm": "p-even", "seed": {"B": 4}},
            {"dim": "D-align", "arm": "p-odd", "seed": {"B": 3}},
        ],
    }
    out = assemble_solve(fill, plan, _init())
    stats = out["stats"]
    assert stats["rows"] + stats["unreachable"] == stats["obligations"]
    assert stats["rows"] >= 1
    names = {r["Testcase_Name"] for r in out["rows"]}
    assert names


def test_assemble_errors_when_probe_hit_missing():
    plan = assemble_plan(_plan_fill(), _init())
    fill = {"schema": "tg-solve-fill/v1", "baseline": {"is_deter": 1}, "hits": []}
    try:
        assemble_solve(fill, plan, _init())
    except AssembleError as exc:
        assert "D-align" in str(exc)
    else:
        raise AssertionError("expected AssembleError")


def test_l3_row_violates_guard_and_closes():
    plan = _activation_plan()
    fill = {"schema": "tg-solve-fill/v1", "baseline": {"is_deter": 1}}
    out = assemble_solve(fill, plan, _init())
    l3 = next(row for row in compile_obligations(plan) if row["level"] == "L3")
    row = next(r for r in out["rows"] if r["Testcase_Name"] == l3["id"])
    assert row["is_deter"] == 0
    observe = {"case": dict(row), "replay": {"mode": 0}}
    assert classify_guard(plan["guards"][0], observe)["status"] == "violated"
    verdict = evaluate_obligation(l3, plan, observe)
    assert verdict["status"] == "CLOSED"


def test_guard_structural_negation_without_hint():
    init = _init()
    seed, ok = falsify_predicate({"op": "eq", "field": "case.is_deter", "value": 1}, init)
    assert ok and seed == {"is_deter": 0}
    seed, ok = falsify_predicate({"op": "ne", "field": "case.sparse_mode", "value": 0}, init)
    assert ok and seed == {"sparse_mode": 0}
    guard = {"predicate": {"op": "eq", "field": "case.is_deter", "value": 1}}
    seed, ok = _guard_seed(guard, {}, init)
    assert ok and seed == {"is_deter": 0}


def test_constraints_present_in_every_row():
    plan = _activation_plan()
    plan["constraints"] = [
        {"id": "C-n1", "predicate": {"op": "eq", "field": "case.N1", "value": 4}},
        {"id": "C-n2", "predicate": {"op": "eq", "field": "case.N2", "value": 4}},
    ]
    out = assemble_solve({"schema": "tg-solve-fill/v1", "baseline": {"is_deter": 1}}, plan, _init())
    assert out["stats"]["constraint_columns"] == ["N1", "N2"]
    assert out["stats"]["constraint_unseedable"] == []
    assert out["rows"]
    for row in out["rows"]:
        assert row["N1"] == 4
        assert row["N2"] == 4


def test_constraint_arm_conflict_is_explicit_unreachable():
    plan = _activation_plan()
    plan["constraints"] = [
        {"id": "C-sparse", "predicate": {"op": "eq", "field": "case.sparse_mode", "value": 0}},
    ]
    out = assemble_solve({"schema": "tg-solve-fill/v1", "baseline": {"is_deter": 1}}, plan, _init())
    reasons = [str(u.get("reason") or "") for u in out["unreachable"]]
    assert any("C-sparse" in r and "D-sparse.p1" in r and "sparse_mode" in r for r in reasons), reasons


def test_conflicting_constraints_are_unconstructible():
    plan = _activation_plan()
    plan["constraints"] = [
        {"id": "C-a", "predicate": {"op": "eq", "field": "case.N1", "value": 4}},
        {"id": "C-b", "predicate": {"op": "eq", "field": "case.N1", "value": 8}},
    ]
    with pytest.raises(AssembleError) as exc:
        assemble_solve({"schema": "tg-solve-fill/v1"}, plan, _init())
    assert "PLAN_UNCONSTRUCTIBLE" in str(exc.value)
    assert "N1" in str(exc.value)
