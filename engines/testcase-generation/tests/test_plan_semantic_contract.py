# -*- coding: utf-8 -*-
"""Wave 2 Plan semantic contract: Guard/Target, four-class, findings reconcile."""

from __future__ import annotations

from pathlib import Path

import yaml

from testcase_agent import products
from testcase_agent.coverage.contract import (
    GUARD_TARGET_INCONSISTENT,
    PLAN_PROSE_CONTRACT_DRIFT,
    PRIMARY_BEHAVIOR_UNCOVERED,
)
from testcase_agent.coverage.eval import classify_guard

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def _confirmed(uo_id: str) -> dict:
    return {
        "control": {"status": "active"},
        "relation": "direct",
        "confidence": "confirmed",
        "uo": {"id": uo_id, "candidate": ""},
    }


def test_render_plan_prose_does_not_invent_oracle() -> None:
    fence = _load_yaml("plan_fag_deter_band_active.yaml")
    prose = products.render_plan_prose(fence)
    assert "## 测什么" in prose
    assert "## 覆盖什么" in prose
    assert "## 怎么判定" in prose
    assert "T-deter-active" in prose
    assert "精度" not in prose
    assert "md5" not in prose.lower()
    doc = _load_yaml("init_fag_is_deter_unmapped.yaml")
    findings, caps = products.reconcile_findings(
        doc["mapping"],
        doc["findings"],
        generate_inputs=doc["generate_inputs"],
    )
    codes = [row.get("code") for row in findings if isinstance(row, dict)]
    assert "unmapped_column" in codes
    leftover = [row for row in findings if isinstance(row, dict) and row.get("code") == "unmapped_column"]
    assert len(leftover) == 1
    assert "sparse_mode" in str(leftover[0].get("detail") or "")
    assert not any("is_deter" in str(row) for row in leftover)
    assert not any("rope" in str(row) for row in leftover)
    assert not any("prefix" in str(row) for row in leftover)
    assert "test_harness_gap" not in codes
    assert any(row.get("code") == "missing_entry" for row in findings if isinstance(row, dict))
    keys = {row["key"] for row in caps["unsupported"]}
    assert keys == {"inf_nan", "empty_tensor"}


def test_fag_disabled_plus_g_deter_on_fails() -> None:
    fence = _load_yaml("plan_fag_deter_band_disabled.yaml")
    errors = products.validate_plan_fence(
        fence,
        init_columns=["is_deter"],
        init_mapping={"is_deter": _confirmed("isDeter")},
        observe_fields={"deterBandScheduleMode"},
    )
    assert any(GUARD_TARGET_INCONSISTENT in e for e in errors), errors


def test_fag_active_modes_plus_same_guard_passes() -> None:
    fence = _load_yaml("plan_fag_deter_band_active.yaml")
    errors = products.validate_plan_fence(
        fence,
        init_columns=["is_deter", "N1"],
        init_mapping={
            "is_deter": _confirmed("isDeter"),
            "N1": _confirmed("n1"),
        },
        observe_fields={"deterBandScheduleMode"},
        primary_observations={"deterBandScheduleMode"},
    )
    assert errors == [], errors


def test_untestable_derived_reason_rejected() -> None:
    fence = _load_yaml("plan_fag_deter_band_active.yaml")
    fence["untestable"] = [
        {
            "id": "u-causal",
            "reason": "CAUSAL 由非列派生，不能写成确定 classifier",
        }
    ]
    errors = products.validate_plan_fence(
        fence,
        init_columns=["is_deter", "N1"],
        init_mapping={"is_deter": _confirmed("isDeter"), "N1": _confirmed("n1")},
        observe_fields={"deterBandScheduleMode"},
    )
    assert any("constraints" in e or "environment" in e for e in errors), errors


def test_classifier_must_not_require_unused_replay() -> None:
    fence = _load_yaml("plan_fag_deter_band_active.yaml")
    fence["dimensions"][0]["classifier"] = {
        "requires": ["case.is_deter", "replay.deterBandScheduleMode"]
    }
    errors = products.validate_plan_fence(
        fence,
        init_columns=["is_deter", "N1"],
        init_mapping={"is_deter": _confirmed("isDeter"), "N1": _confirmed("n1")},
        observe_fields={"deterBandScheduleMode"},
    )
    assert any("classifier.requires" in e and "Target evidence" in e for e in errors), errors


def test_prose_oracle_drift() -> None:
    text = "## 测什么\n\n核对精度与 md5。\n\n## 覆盖什么\n\n## 怎么判定\n"
    fence = _load_yaml("plan_fag_deter_band_active.yaml")
    errors = products.validate_plan_prose(text, fence)
    assert any(PLAN_PROSE_CONTRACT_DRIFT in e for e in errors), errors


def test_primary_behavior_untestable_without_gap_fails() -> None:
    fence = _load_yaml("plan_fag_deter_band_disabled.yaml")
    fence["untestable"] = [
        {
            "id": "u-causal",
            "kind": "opaque",
            "reason": "deterBandScheduleMode CAUSAL/DENSE/BAND 无法反解",
        }
    ]
    errors = products.validate_plan_fence(
        fence,
        init_columns=["is_deter"],
        init_mapping={"is_deter": _confirmed("isDeter")},
        observe_fields={"deterBandScheduleMode"},
        primary_observations={"deterBandScheduleMode"},
    )
    assert any(PRIMARY_BEHAVIOR_UNCOVERED in e for e in errors), errors


def test_primary_behavior_opaque_with_blocking_gap_ok() -> None:
    fence = _load_yaml("plan_fag_deter_band_disabled.yaml")
    fence["targets"] = [
        {
            "id": "T-deter-active",
            "evidence": {
                "kind": "derived",
                "predicate": {"op": "in", "field": "replay.deterBandScheduleMode", "values": [1, 2, 3]},
            },
        }
    ]
    fence["dimensions"][0]["target"] = "T-deter-active"
    fence["guards"][0]["target"] = "T-deter-active"
    fence["untestable"] = [
        {
            "id": "u-inner",
            "kind": "opaque",
            "reason": "inner kernel latch cannot be inverted",
        }
    ]
    fence["test_harness_gap"] = {"done": False, "reason": "need a probe for the inner latch"}
    errors = products.validate_plan_fence(
        fence,
        init_columns=["is_deter"],
        init_mapping={"is_deter": _confirmed("isDeter")},
        observe_fields={"deterBandScheduleMode"},
        primary_observations={"deterBandScheduleMode"},
    )
    assert not any(PRIMARY_BEHAVIOR_UNCOVERED in e for e in errors), errors
    assert not any(GUARD_TARGET_INCONSISTENT in e for e in errors), errors


def test_all_l3_fixtures_violate_on_negate_hint() -> None:
    for path in sorted(FIXTURES.glob("plan_*.yaml")):
        fence = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(fence, dict):
            continue
        cov = fence.get("coverage") if isinstance(fence.get("coverage"), dict) else {}
        l3 = cov.get("L3")
        if isinstance(l3, dict):
            gids = [str(x).strip() for x in (l3.get("guards") or []) if str(x).strip()]
        elif isinstance(l3, list):
            gids = [str(x).strip() for x in l3 if str(x).strip()]
        else:
            gids = []
        guards = {
            str(row.get("id") or "").strip(): row
            for row in (fence.get("guards") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        for gid in gids:
            guard = guards.get(gid) or {}
            hint = guard.get("negate_hint") if isinstance(guard.get("negate_hint"), dict) else {}
            got = classify_guard(guard, {"case": hint})
            assert got["status"] == "violated", (path.name, gid, got)
