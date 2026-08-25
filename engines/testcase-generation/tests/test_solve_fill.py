# -*- coding: utf-8 -*-
from __future__ import annotations

from testcase_agent.plan_fill import AssembleError, assemble_plan
from testcase_agent.solve_fill import assemble_solve, index_plan, seed_from_predicate


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
            {"id": "G-deter-off", "field": "is_deter", "eq": 0, "hit": 1},
            {"id": "G-mha", "eq": {"N1": 4, "N2": 4}, "hit": {"N1": 4, "N2": 2}},
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


def test_seed_from_eq_and_probe_incomplete():
    seed, ok = seed_from_predicate({"op": "eq", "field": "case.sparse_mode", "value": 0})
    assert ok and seed == {"sparse_mode": 0}
    seed, ok = seed_from_predicate({"op": "mod_eq", "field": "probe.baseRound", "value": 0})
    assert not ok and seed == {}


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
