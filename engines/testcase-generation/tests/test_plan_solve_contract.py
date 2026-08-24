# -*- coding: utf-8 -*-
"""Plan → Solve executability contract: validator rejects, compiler does not repair."""

from __future__ import annotations

import pytest

from testcase_agent import products
from testcase_agent.coverage.compile import PlanCompileError, compile_obligations
from testcase_agent.coverage.contract import (
    CASE_REFINABLE,
    CONTROL_GAP,
    OBSERVATION_GAP,
)
from testcase_agent.coverage.eval import classify_eval_failure, evaluate_obligation
from testcase_agent.coverage.predicate import Truth, evaluate, validate_predicate
from testcase_agent.closure.finite_predicate import evaluate as finite_evaluate


def _confirmed(uo_id: str = "b") -> dict:
    return {
        "control": {"status": "active"},
        "relation": "direct",
        "confidence": "confirmed",
        "uo": {"id": uo_id, "candidate": ""},
    }


def _plan() -> dict:
    return {
        "schema": products.PLAN_SCHEMA,
        "requirement": {"id": "R-x", "text": "x"},
        "targets": [
            {"id": "T-hit", "evidence": {"kind": "replay_field", "field": "tiling_key", "expected": 1}}
        ],
        "dimensions": [
            {
                "id": "D-a",
                "target": "T-hit",
                "controls": ["A"],
                "partitions": [
                    {"id": "a0", "predicate": {"op": "eq", "field": "case.A", "value": 0}},
                    {"id": "a1", "predicate": {"op": "eq", "field": "case.A", "value": 1}},
                ],
            },
            {
                "id": "D-b",
                "target": "T-hit",
                "controls": ["B"],
                "partitions": [
                    {"id": "b0", "predicate": {"op": "eq", "field": "case.B", "value": 0}},
                    {"id": "b1", "predicate": {"op": "eq", "field": "case.B", "value": 1}},
                ],
            },
        ],
        "guards": [],
        "coverage": {
            "L0": {"dimensions": ["D-a"]},
            "L1": {"combinations": []},
            "L2": [],
            "L3": {"guards": []},
        },
        "oracle": [],
    }


def test_l1_three_dims_rejected_and_compiler_does_not_truncate() -> None:
    fence = _plan()
    fence["coverage"]["L1"] = {
        "combinations": [{"dims": ["D-a", "D-b", "D-a"], "reason": "too many"}]
    }
    errors = products.validate_plan_fence(fence, init_columns=["A", "B"])
    assert any("exactly two unique" in e or "L1" in e for e in errors)
    with pytest.raises(PlanCompileError):
        compile_obligations(fence)


def test_dimension_target_required_no_compiler_fallback() -> None:
    fence = _plan()
    fence["dimensions"][0]["target"] = ""
    errors = products.validate_plan_fence(fence, init_columns=["A", "B"])
    assert any("target required" in e for e in errors)
    with pytest.raises(PlanCompileError):
        compile_obligations(fence)


def test_l1_mixed_targets_rejected() -> None:
    fence = _plan()
    fence["targets"].append(
        {"id": "T-other", "evidence": {"kind": "replay_field", "field": "tiling_key", "expected": 2}}
    )
    fence["dimensions"][1]["target"] = "T-other"
    fence["coverage"]["L1"] = {
        "combinations": [{"dims": ["D-a", "D-b"], "reason": "cross-target"}]
    }
    errors = products.validate_plan_fence(fence, init_columns=["A", "B"])
    assert any("different Targets" in e for e in errors)


def test_overlapping_eq_partitions_rejected() -> None:
    fence = _plan()
    fence["dimensions"][0]["partitions"][1]["predicate"]["value"] = 0
    errors = products.validate_plan_fence(fence, init_columns=["A", "B"])
    assert any("overlap" in e for e in errors)


def test_mixed_case_columns_in_one_dimension_rejected() -> None:
    fence = _plan()
    fence["dimensions"][0]["controls"] = ["A", "B"]
    fence["dimensions"][0]["partitions"][1]["predicate"]["field"] = "case.B"
    errors = products.validate_plan_fence(fence, init_columns=["A", "B"])
    assert any("H6" in e or "same case columns" in e for e in errors)


def test_observe_nested_replay_field_rejected() -> None:
    fence = _plan()
    fence["targets"][0]["evidence"]["field"] = "replay.s1.base.mode"
    errors = products.validate_plan_fence(fence, init_columns=["A", "B"])
    assert any("two segments" in e for e in errors)


def test_replay_field_list_expected_rejected() -> None:
    fence = _plan()
    fence["targets"][0]["evidence"]["expected"] = [1, 2, 3]
    errors = products.validate_plan_fence(fence, init_columns=["A", "B"])
    assert any("scalar" in e and "derived" in e for e in errors)


def test_constraint_eq_rejects_mapping_field() -> None:
    errors = validate_predicate(
        {"op": "eq", "left": {"field": "probe.blockOuter"}, "right": {"field": "environment.aicNum"}},
        path="constraints.c",
    )
    assert any("field" in e or "value" in e for e in errors)


def test_predicate_eq_requires_field_and_value() -> None:
    errors = validate_predicate({"op": "eq"}, path="p")
    assert any("field" in e for e in errors)
    assert any("value" in e for e in errors)


def test_case_field_not_in_controls_is_control_gap() -> None:
    fence = _plan()
    fence["dimensions"][0]["partitions"][0]["predicate"]["field"] = "case.Z"
    fence["dimensions"][0]["partitions"][1]["predicate"]["field"] = "case.Z"
    errors = products.validate_plan_fence(
        fence,
        init_columns=["A", "B", "Z"],
        init_mapping={"A": _confirmed("a"), "B": _confirmed("b"), "Z": _confirmed("z")},
    )
    assert any(CONTROL_GAP in e and "controls" in e for e in errors)


def test_unconfirmed_construct_field_is_control_gap() -> None:
    fence = _plan()
    errors = products.validate_plan_fence(
        fence,
        init_columns=["A", "B"],
        init_mapping={
            "A": {
                "control": {"status": "metadata"},
                "relation": "",
                "confidence": "unresolved",
                "uo": {"id": "", "candidate": "AKind"},
            },
            "B": _confirmed("b"),
        },
    )
    assert any(CONTROL_GAP in e or "confirmed+active" in e for e in errors)


def test_unknown_replay_field_is_observation_gap_when_vocab_given() -> None:
    fence = _plan()
    fence["targets"][0]["evidence"]["field"] = "replay.notARealField"
    errors = products.validate_plan_fence(
        fence,
        init_columns=["A", "B"],
        observe_fields={"tiling_key", "s2Inner"},
    )
    assert any(OBSERVATION_GAP in e for e in errors)


def test_gap_fence_ignores_prose_heading() -> None:
    text = "# test_harness_gap\n\nprose only\n"
    fence = _plan()
    assert products.pending_test_harness_gap(text, fence) is False
    fence["test_harness_gap"] = {"done": False, "reason": "missing column"}
    assert products.pending_test_harness_gap("", fence) is True
    fence["test_harness_gap"]["done"] = True
    assert products.pending_test_harness_gap(text, fence) is False


def test_semantic_plan_hash_ignores_approval_stamps() -> None:
    fence = _plan()
    a = products.semantic_plan_hash(fence)
    fence["approved"] = True
    fence["decision"] = "approve"
    fence["plan_hash"] = "deadbeef"
    fence["approved_at"] = "now"
    assert products.semantic_plan_hash(fence) == a


def test_missing_replay_field_after_run_is_observation_gap() -> None:
    fence = _plan()
    obl = compile_obligations(fence)[0]
    result = evaluate_obligation(obl, fence, observe={"case": {"A": 0}, "replay": {"ok": True}})
    assert result["status"] == "UNKNOWN"
    assert classify_eval_failure(fence, obl, result, {"case": {"A": 0}, "replay": {"ok": True}}) == OBSERVATION_GAP


def test_miss_is_case_refinable() -> None:
    fence = _plan()
    obl = compile_obligations(fence)[0]
    observe = {"case": {"A": 1, "B": 0}, "replay": {"tiling_key": 1, "ok": True}}
    result = evaluate_obligation(obl, fence, observe)
    if result["status"] == "MISS":
        assert classify_eval_failure(fence, obl, result, observe) == CASE_REFINABLE


def test_large_int_equality_does_not_use_float() -> None:
    n = 2**60
    assert finite_evaluate({"op": "eq", "field": "x", "value": n}, {"x": str(n)}).result is Truth.TRUE
    assert finite_evaluate({"op": "eq", "field": "x", "value": n}, {"x": str(n + 1)}).result is Truth.FALSE
    assert evaluate({"op": "eq", "field": "x", "value": n}, {"x": str(n)}).result is Truth.TRUE


def test_inf_is_not_a_number() -> None:
    assert finite_evaluate({"op": "eq", "field": "x", "value": 1}, {"x": "inf"}).result is Truth.FALSE
