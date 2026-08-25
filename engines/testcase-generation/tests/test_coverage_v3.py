# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from shutil import copytree

from testcase_agent import products
from testcase_agent.coverage.compile import compile_obligations
from testcase_agent.coverage.eval import evaluate_obligation
from testcase_agent.coverage.ledger import ledger_closed, seed_ledger, upsert_obligation
from testcase_agent.coverage.predicate import Truth, evaluate
from testcase_agent.coverage.probe import inject_probes, required_fields
from testcase_agent.coverage.signature import semantic_signature


def _plan(**overrides: object) -> dict:
    fence = {
        "schema": products.PLAN_SCHEMA,
        "requirement": {"id": "R-kvmerge", "text": "kvMerge TND"},
        "targets": [
            {
                "id": "T-kvmerge",
                "state": {"symbol": "kvMerge", "expected": True},
                "evidence": {"kind": "replay_field", "field": "kvMerge", "expected": True},
            }
        ],
        "guards": [
            {
                "id": "G-v-null",
                "target": "T-kvmerge",
                "controls": ["v"],
                "predicate": {"op": "is_present", "field": "case.v"},
                "negate_hint": {"v": None},
                "fallback": {"target": "T-separate-kv", "optional": True},
            }
        ],
        "dimensions": [
            {
                "id": "D-dtype",
                "target": "T-kvmerge",
                "controls": ["dtype"],
                "partitions": [
                    {"id": "fp16", "predicate": {"op": "eq", "field": "case.dtype", "value": "fp16"}},
                    {"id": "bf16", "predicate": {"op": "eq", "field": "case.dtype", "value": "bf16"}},
                ],
            },
            {
                "id": "D-tail",
                "target": "T-kvmerge",
                "controls": ["S2"],
                "classifier": {"requires": ["case.S2", "replay.s2Inner"]},
                "partitions": [
                    {
                        "id": "aligned",
                        "predicate": {"op": "mod_eq", "left": "case.S2", "right": "replay.s2Inner", "value": 0},
                    },
                    {
                        "id": "remainder",
                        "predicate": {
                            "op": "not",
                            "arg": {"op": "mod_eq", "left": "case.S2", "right": "replay.s2Inner", "value": 0},
                        },
                    },
                ],
            },
        ],
        "coverage": {
            "L0": {"dimensions": ["D-dtype", "D-tail"]},
            "L1": {"combinations": [{"dims": ["D-dtype", "D-tail"], "reason": "shared merge copy"}]},
            "L2": [],
            "L3": {"guards": ["G-v-null"]},
        },
        "oracle": [],
    }
    fence.update(overrides)
    return fence


def test_v3_plan_accepts_structured_predicates() -> None:
    errors = products.validate_plan_fence(_plan(), init_columns=["v", "dtype", "S2"])
    assert errors == []


def test_v3_rejects_free_text_predicate_and_v2_fields() -> None:
    fence = _plan(
        schema="tg-plan/v2",
        variables=[{"id": "V-dtype"}],
        direction={"columns": ["B"]},
        ladder={"L0": ["V-dtype"], "L1": [], "L2": [], "L3": []},
        obligations=[{"id": "o1"}],
        dimensions=[
            {
                "id": "D-tail",
                "target": "T-kvmerge",
                "controls": ["S2"],
                "partitions": [
                    {"id": "aligned", "predicate": "S2 % s2Inner == 0"},
                    {"id": "remainder", "predicate": {"op": "eq", "field": "x", "value": 1}},
                ],
            }
        ],
    )
    errors = products.validate_plan_fence(fence, init_columns=["S2", "v", "dtype"])
    assert any("tg-plan/v3" in e or "schema" in e for e in errors)
    assert any("variables" in e for e in errors)
    assert any("direction" in e for e in errors)
    assert any("ladder" in e for e in errors)
    assert any("obligations" in e for e in errors)
    assert any("predicate" in e for e in errors)


def test_l1_not_required_when_two_dimensions() -> None:
    fence = _plan(coverage={"L0": {"dimensions": ["D-dtype", "D-tail"]}, "L1": {"combinations": []}, "L2": [], "L3": {"guards": []}})
    errors = products.validate_plan_fence(fence, init_columns=["v", "dtype", "S2"])
    assert errors == []


def test_l1_combination_needs_reason() -> None:
    fence = _plan(coverage={"L0": {"dimensions": ["D-dtype"]}, "L1": {"combinations": [{"dims": ["D-dtype", "D-tail"]}]}, "L2": [], "L3": {"guards": []}})
    errors = products.validate_plan_fence(fence, init_columns=["v", "dtype", "S2"])
    assert any("reason" in e for e in errors)


def test_plan_rejects_td_mode() -> None:
    errors = products.validate_plan_fence(_plan(mode="tilingkey_full_coverage"), init_columns=["v", "dtype", "S2"])
    assert any("T=D" in e or "tilingkey_full_coverage" in e for e in errors)


def test_plan_prose_headings() -> None:
    errors = products.validate_plan_prose("# plan\n")
    assert any("测什么" in e for e in errors)
    assert products.validate_plan_prose("## 测什么\n\n## 覆盖什么\n\n## 怎么判定\n") == []


def test_compile_l0_l1_l3() -> None:
    obs = compile_obligations(_plan())
    levels = [row["level"] for row in obs]
    assert levels.count("L0") == 4
    assert levels.count("L1") == 4
    assert levels.count("L3") == 1
    l3 = next(row for row in obs if row["level"] == "L3")
    assert l3["expected"]["targets"]["T-kvmerge"] == "MISS"
    assert l3["expected"]["guards"]["G-v-null"] == "violated"


def test_compile_target_only_witness() -> None:
    plan = {
        "targets": [{"id": "T-kvmerge", "evidence": {"kind": "replay_field", "field": "kvMerge", "expected": True}}],
        "coverage": {"L0": {"dimensions": []}, "L1": {"combinations": []}, "L2": [], "L3": {"guards": []}},
    }
    obs = compile_obligations(plan)
    assert len(obs) == 1
    assert obs[0]["kind"] == "target_witness"


def test_compile_legal_keys() -> None:
    plan = {
        "targets": [{"id": "T-dispatch"}],
        "coverage": {"enumerate": "legal_keys", "L0": {}, "L1": {}, "L2": [], "L3": {}},
    }
    obs = compile_obligations(plan, legal_keys=[10, 11, {"tiling_key": 12}])
    assert [row["tiling_key"] for row in obs] == [10, 11, 12]


def test_mod_eq_and_null_predicates() -> None:
    values = {"case.S2": 4097, "replay.s2Inner": 128, "case.v": None}
    rem = evaluate({"op": "mod_eq", "left": "case.S2", "right": "replay.s2Inner", "value": 0}, values)
    assert rem.result is Truth.FALSE
    null = evaluate({"op": "is_null", "field": "case.v"}, values)
    assert null.result is Truth.TRUE


def test_eval_unknown_not_hit() -> None:
    plan = _plan()
    obl = compile_obligations(plan)[0]
    out = evaluate_obligation(obl, plan, observe={"case": {"dtype": "fp16"}, "replay": {}})
    assert out["status"] in {"UNKNOWN", "MISS"}
    assert out["status"] != "CLOSED"


def test_eval_closed_and_redundant_signature() -> None:
    plan = _plan()
    dtype_fp16 = next(row for row in compile_obligations(plan) if row.get("dimensions") == {"D-dtype": "fp16"})
    observe = {
        "case": {"dtype": "fp16", "S2": 256, "v": None},
        "replay": {"kvMerge": True, "s2Inner": 128, "tiling_key": 107},
    }
    first = evaluate_obligation(dtype_fp16, plan, observe)
    assert first["status"] == "CLOSED"
    second = evaluate_obligation(dtype_fp16, plan, observe, seen_signatures={first["signature"]})
    assert second["status"] == "REDUNDANT"
    other_bn = {
        "case": {"dtype": "fp16", "S2": 512, "B": 4, "N": 4, "v": None},
        "replay": {"kvMerge": True, "s2Inner": 128, "tiling_key": 107},
    }
    sig_a = semantic_signature(plan, observe, obligation=dtype_fp16)
    sig_b = semantic_signature(plan, other_bn, obligation=dtype_fp16)
    assert sig_a == sig_b
    assert "B=" not in sig_a and "N=" not in sig_a


def test_l3_guard_leak_vs_miss() -> None:
    plan = _plan()
    l3 = next(row for row in compile_obligations(plan) if row["level"] == "L3")
    leak = evaluate_obligation(
        l3,
        plan,
        observe={"case": {"v": "present", "dtype": "fp16"}, "replay": {"kvMerge": True, "s2Inner": 128}},
    )
    assert leak["status"] == "GUARD_LEAK"
    closed = evaluate_obligation(
        l3,
        plan,
        observe={"case": {"v": None, "dtype": "fp16"}, "replay": {"kvMerge": False, "s2Inner": 128}},
    )
    assert closed["status"] == "CLOSED"


def test_ledger_closed_requires_all_mandatory() -> None:
    obs = compile_obligations(_plan())
    ledger = seed_ledger(obs)
    ok, problems = ledger_closed(ledger)
    assert ok is False
    for row in obs:
        upsert_obligation(ledger, row["id"], status="CLOSED")
    ok, problems = ledger_closed(ledger)
    assert ok is True
    upsert_obligation(ledger, obs[-1]["id"], status="GUARD_LEAK")
    ok, _ = ledger_closed(ledger)
    assert ok is False


def test_inject_probes_does_not_touch_original(tmp_path: Path) -> None:
    original = tmp_path / "ops-git"
    original.mkdir()
    (original / "host.cpp").write_text("int kvMerge = 0;\nvoid f() {}\n", encoding="utf-8")
    sandbox = tmp_path / "sandbox"
    copytree(original, sandbox)
    out = inject_probes(sandbox, ["kvMerge"])
    assert out.get("patched")
    assert "TG_PROBE kvMerge=" in (sandbox / "host.cpp").read_text(encoding="utf-8")
    assert "TG_PROBE" not in (original / "host.cpp").read_text(encoding="utf-8")


def test_probe_fields_from_partition_and_guard_predicates() -> None:
    fence = _plan()
    fence["dimensions"].append(
        {
            "id": "D-round",
            "target": "T-kvmerge",
            "controls": ["S2"],
            "partitions": [
                {"id": "even", "predicate": {"op": "eq", "field": "probe.baseRound", "value": 0}},
                {"id": "odd", "predicate": {"op": "eq", "field": "probe.baseRound", "value": 1}},
            ],
        }
    )
    fence["guards"].append(
        {
            "id": "G-swizzle",
            "target": "T-kvmerge",
            "controls": ["S2"],
            "predicate": {"op": "eq", "field": "probe.enableSwizzle", "value": 1},
            "negate_hint": {"S2": 0},
        }
    )
    names = required_fields(fence)
    assert "baseRound" in names
    assert "enableSwizzle" in names


def test_inject_probes_scope_unique_vs_ambiguous(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "a.cpp").write_text("int foo = 1;\n", encoding="utf-8")
    (sandbox / "b.cpp").write_text("int foo = 2;\n", encoding="utf-8")
    amb = inject_probes(sandbox, ["foo"])
    assert amb.get("error") == "PROBE_AMBIGUOUS"
    assert "TG_PROBE" not in (sandbox / "a.cpp").read_text(encoding="utf-8")
    scoped = inject_probes(sandbox, ["foo"], scope=["a.cpp"])
    assert scoped.get("ok")
    assert "TG_PROBE foo=" in (sandbox / "a.cpp").read_text(encoding="utf-8")
    assert "TG_PROBE" not in (sandbox / "b.cpp").read_text(encoding="utf-8")
