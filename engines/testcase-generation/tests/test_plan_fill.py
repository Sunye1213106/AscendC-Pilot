# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from testcase_agent.coverage.compile import compile_obligations
from testcase_agent.plan_fill import AssembleError, assemble_plan, ensure_v3, is_fill


def _init() -> dict:
    return {
        "columns": [{"name": "sparse_mode"}, {"name": "is_deter"}, {"name": "N1"}, {"name": "N2"}],
        "mapping": {
            "sparse_mode": {"confidence": "confirmed", "control": {"status": "active"}},
            "is_deter": {"confidence": "confirmed", "control": {"status": "active"}},
            "N1": {"confidence": "confirmed", "control": {"status": "active"}},
            "N2": {"confidence": "confirmed", "control": {"status": "active"}},
            "Dtype": {"confidence": "unresolved", "control": {"status": "active"}},
        },
    }


def _fill() -> dict:
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


def test_assemble_builds_v3_predicates_and_scaffold():
    plan = assemble_plan(_fill(), _init())
    assert plan["schema"] == "tg-plan/v3"
    assert plan["targets"][0]["evidence"]["predicate"]["field"] == "probe.selectedRound"
    sparse = plan["dimensions"][0]
    assert sparse["classifier"]["requires"] == ["case.sparse_mode"]
    assert sparse["controls"] == ["sparse_mode"]
    assert sparse["partitions"][0]["predicate"] == {
        "op": "eq",
        "field": "case.sparse_mode",
        "value": 0,
    }
    gqa = plan["dimensions"][1]
    assert gqa["partitions"][0]["predicate"]["op"] == "and"
    align = plan["dimensions"][2]
    assert align["partitions"][0]["predicate"]["op"] == "mod_eq"
    assert align["classifier"]["requires"] == ["probe.baseRound"]
    assert "N1" in align["controls"]
    g = plan["guards"][0]
    assert g["predicate"]["field"] == "case.is_deter"
    assert g["negate_hint"] == {"is_deter": 1}
    cover = plan["coverage"]
    assert cover["L0"]["dimensions"] == ["D-sparse", "D-gqa", "D-align"]
    assert cover["L2"]["mode"] == "full_cross"
    assert cover["L3"]["guards"] == ["G-deter-off", "G-mha"]
    assert cover["L1"]["combinations"][0]["dims"] == ["D-sparse", "D-gqa"]
    assert any(u["needs_binding"][0]["column"] == "Dtype" for u in plan["untestable"])
    assert plan["oracle"][0]["kind"] == "md5"
    compile_obligations(plan)


def test_ensure_v3_identity_and_fill():
    v3 = {"schema": "tg-plan/v3", "targets": [{"id": "T-x"}]}
    assert ensure_v3(v3) is v3
    assert is_fill(_fill())
    out = ensure_v3(_fill(), _init())
    assert out["schema"] == "tg-plan/v3"


def test_load_yaml_strips_trailing_fence():
    from testcase_agent.plan_fill import load_yaml

    doc = load_yaml("schema: tg-plan-fill/v1\noracle: md5\n```\n")
    assert doc["schema"] == "tg-plan-fill/v1"
    assert doc["oracle"] == "md5"


def test_load_yaml_accepts_unquoted_bang_reason():
    from testcase_agent.plan_fill import load_yaml

    doc = load_yaml("schema: tg-plan-fill/v1\nexclusions:\n  - {D-a: p-x, D-b: p-y, reason: !isDeterministic 时恒真}\n")
    assert "isDeterministic" in str(doc["exclusions"][0]["reason"])

    fill = _fill()
    fill["exclusions"] = [{"D-sparse": "p-no-mask", "reason": "oops"}]
    with pytest.raises(AssembleError) as exc:
        assemble_plan(fill, _init())
    assert ">=2 different dimensions" in str(exc.value)
