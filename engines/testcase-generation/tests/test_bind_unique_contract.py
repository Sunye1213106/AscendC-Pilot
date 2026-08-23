# -*- coding: utf-8 -*-
"""Wave 2: bind unique contract is control/relation/confidence + sources[]."""

from __future__ import annotations

from testcase_agent import bind_parts as BP
from testcase_agent import products


def _confirmed(*, uo_id: str, relation: str = "direct") -> dict:
    return {
        "control": {"status": "active"},
        "relation": relation,
        "confidence": "confirmed",
        "runtime": {"target": uo_id, "path": []},
        "uo": {"id": uo_id, "candidate": ""},
        "encoding": "",
        "evidence": "",
    }


def _v3_fence(controls: list[str], *, relation_eq: bool = True) -> dict:
    return {
        "schema": products.PLAN_SCHEMA,
        "requirement": {"id": "R-x", "text": "x"},
        "targets": [
            {
                "id": "T-dispatch",
                "evidence": {"kind": "replay_field", "field": "tiling_key", "expected": 1},
            }
        ],
        "guards": [],
        "dimensions": [
            {
                "id": "D-x",
                "target": "T-dispatch",
                "controls": list(controls),
                "partitions": [
                    {
                        "id": "p0",
                        "predicate": {"op": "eq", "field": "case.x", "value": 0},
                    },
                    {
                        "id": "p1",
                        "predicate": {"op": "eq", "field": "case.x", "value": 1},
                    },
                ],
            }
        ],
        "coverage": {
            "L0": {"dimensions": ["D-x"]},
            "L1": {"combinations": []},
            "L2": [],
            "L3": {"guards": []},
        },
        "oracle": [],
    }


def test_empty_mapping_row_has_unique_contract_not_role() -> None:
    row = products.empty_mapping_row()
    assert "role" not in row
    assert "uo_id" not in row
    assert "control" in row
    assert "relation" in row
    assert "confidence" in row
    emit = BP._empty_mapping_row()
    assert "role" not in emit
    assert emit["control"]["status"] == ""


def test_old_role_uo_id_is_not_confirmed() -> None:
    assert products.is_confirmed_active({"role": "api_arg", "uo_id": "DeterType"}) is False
    assert products.is_solve_control({"role": "api_arg", "uo_id": "DeterType"}) is False


def test_validate_bind_part_rejects_legacy_fields() -> None:
    errors = products.validate_bind_part(
        {
            "call": {"kind": "pta"},
            "mapping": {"B": {"role": "api_arg", "uo_id": "b"}},
            "call_args": [{"name": "batch", "source_column": "B"}],
        }
    )
    assert any("role" in e or "uo_id" in e for e in errors)
    assert any("source_column" in e for e in errors)


def test_validate_bind_part_accepts_sources_and_empty_uo_id() -> None:
    errors = products.validate_bind_part(
        {
            "call": {"kind": "pta"},
            "mapping": {
                "prefix": {
                    "control": {"status": "unwired"},
                    "relation": "direct",
                    "confidence": "unresolved",
                    "uo": {"id": "", "candidate": ""},
                }
            },
            "call_args": [
                {
                    "name": "query",
                    "runtime_expr": "q",
                    "sources": [{"column": "B", "relation": "tensor_shape"}],
                }
            ],
        }
    )
    assert errors == []


def test_confirmed_active_is_solve_control() -> None:
    row = _confirmed(uo_id="InputDType")
    assert products.is_confirmed_active(row) is True
    assert products.is_solve_control(row) is True


def test_danger_fixtures_are_not_solve_controls() -> None:
    is_deter = {
        "control": {"status": "metadata"},
        "relation": "candidate",
        "confidence": "unresolved",
        "uo": {"id": "", "candidate": "DeterType"},
    }
    cu_seqlens = {
        "control": {"status": "shadowed"},
        "relation": "derived",
        "confidence": "partial",
        "uo": {"id": "", "candidate": "actualSeqQlen"},
    }
    prefix = {
        "control": {"status": "unwired"},
        "relation": "direct",
        "confidence": "unresolved",
        "uo": {"id": "", "candidate": "prefix"},
    }
    out_dtype = {
        "control": {"status": "active"},
        "relation": "tensor_dtype",
        "confidence": "unresolved",
        "uo": {"id": "", "candidate": "OutDType"},
    }
    assert products.is_solve_control(is_deter) is False
    assert products.is_solve_control(cu_seqlens) is False
    assert products.is_solve_control(prefix) is False
    assert products.is_solve_control(out_dtype) is False
    assert products.is_confirmed_active(out_dtype) is False


def test_plan_rejects_unconfirmed_control() -> None:
    fence = _v3_fence(["is_deter"])
    errors = products.validate_plan_fence(
        fence,
        init_columns=["is_deter"],
        init_mapping={
            "is_deter": {
                "control": {"status": "metadata"},
                "relation": "candidate",
                "confidence": "unresolved",
                "uo": {"candidate": "DeterType"},
            }
        },
    )
    assert any("untestable" in e and "needs_binding" in e for e in errors)


def test_plan_rejects_projection_as_equality() -> None:
    fence = _v3_fence(["Input_Layout"])
    errors = products.validate_plan_fence(
        fence,
        init_columns=["Input_Layout"],
        init_mapping={
            "Input_Layout": {
                "control": {"status": "active"},
                "relation": "projection",
                "confidence": "confirmed",
                "uo": {"id": "IsTnd"},
            }
        },
    )
    assert any("projection" in e for e in errors)


def test_plan_accepts_confirmed_active_direct() -> None:
    fence = _v3_fence(["B"])
    errors = products.validate_plan_fence(
        fence,
        init_columns=["B"],
        init_mapping={"B": _confirmed(uo_id="b")},
    )
    assert not any("untestable" in e or "projection" in e for e in errors)
