# -*- coding: utf-8 -*-
"""Per-round growth classification must drive lemma/construct routing."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
_TG = REPO / "engines" / "testcase-generation"
_PILOT = REPO / "pilot"
for p in (_TG, _PILOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from testcase_agent.closure import search_round as SR


def test_classify_growth_expected_when_declared_r_grows():
    growth = SR._classify_growth(
        progress={"new_declared_R": 3, "new_R": 3, "domain_suspect": False},
        sat={"target_hit_rate": 0.4, "rewrite_share": 0.2, "refuse_share": 0.5, "judged": 10},
        res={"mostly_distance_1": True, "open_patterns": [{"exclusive_to_open": True}]},
    )
    assert growth["growth_match"] == "expected"
    assert growth["exclusive_open_patterns"] == 1


def test_classify_growth_unexpected_on_rewrite_without_delta_r():
    growth = SR._classify_growth(
        progress={"new_declared_R": 0, "new_R": 0, "domain_suspect": False},
        sat={"target_hit_rate": 0.0, "rewrite_share": 0.9, "refuse_share": 0.1, "judged": 20},
        res={"mostly_distance_1": False, "open_patterns": []},
    )
    assert growth["growth_match"] == "unexpected"


def test_route_expected_growth_goes_to_lemma(tmp_path: Path, monkeypatch):
    rounds = tmp_path / "rounds" / "round_0001"
    rounds.mkdir(parents=True)
    (rounds / "progress.yaml").write_text(
        yaml.safe_dump(
            {
                "new_R": 2,
                "new_declared_R": 2,
                "new_undeclared_R": 0,
                "domain_suspect": False,
                "distance_histogram": {1: 3},
            }
        ),
        encoding="utf-8",
    )

    class _WS:
        state = tmp_path

        def ensure(self):
            return self

    monkeypatch.setattr(SR.W, "default_workspace", lambda: _WS())
    monkeypatch.setattr(
        SR.ledger,
        "state",
        lambda _ws=None: {"gap": 5, "declared": 10, "R": 5, "E": 0, "violation": 0},
    )
    monkeypatch.setattr(
        SR.R,
        "analyse",
        lambda _ws=None: {
            "mostly_distance_1": True,
            "open_patterns": [{"exclusive_to_open": True, "when": {"A": 1}}],
        },
    )
    monkeypatch.setattr(
        SR,
        "_oracle_saturation",
        lambda _ws: {
            "target_hit_rate": 0.5,
            "rewrite_share": 0.1,
            "refuse_share": 0.4,
            "judged": 8.0,
        },
    )
    monkeypatch.setattr(SR, "_leads_available", lambda _ws: False)
    monkeypatch.setattr(SR, "lockout_active", lambda _ws, _st: False)
    monkeypatch.setattr(SR, "set_lockout", lambda _ws, _st: {})

    routed = SR.route(_WS())
    assert routed["reason"] == "NEED_LEMMA"
    assert routed["growth_match"] == "expected"
    assert routed.get("lemma_trigger") == "expected_growth_rejects"


def test_route_unexpected_growth_goes_to_construct(tmp_path: Path, monkeypatch):
    rounds = tmp_path / "rounds" / "round_0001"
    rounds.mkdir(parents=True)
    (rounds / "progress.yaml").write_text(
        yaml.safe_dump(
            {
                "new_R": 0,
                "new_declared_R": 0,
                "new_undeclared_R": 0,
                "domain_suspect": False,
            }
        ),
        encoding="utf-8",
    )

    class _WS:
        state = tmp_path

        def ensure(self):
            return self

    monkeypatch.setattr(SR.W, "default_workspace", lambda: _WS())
    monkeypatch.setattr(
        SR.ledger,
        "state",
        lambda _ws=None: {"gap": 4, "declared": 8, "R": 4, "E": 0, "violation": 0},
    )
    monkeypatch.setattr(
        SR.R,
        "analyse",
        lambda _ws=None: {"mostly_distance_1": False, "open_patterns": []},
    )
    monkeypatch.setattr(
        SR,
        "_oracle_saturation",
        lambda _ws: {
            "target_hit_rate": 0.0,
            "rewrite_share": 0.85,
            "refuse_share": 0.15,
            "judged": 12.0,
        },
    )
    monkeypatch.setattr(SR, "_leads_available", lambda _ws: False)
    monkeypatch.setattr(SR, "lockout_active", lambda _ws, _st: False)

    routed = SR.route(_WS())
    assert routed["reason"] == "CONSTRUCT_TARGETS"
    assert routed["growth_match"] == "unexpected"
    assert routed.get("construct_trigger") == "unexpected_growth"


def test_tg_solve_open_rework_returns_to_construct():
    from ascendc_pilot.workflows.specs import WORKFLOWS

    construct_rework = [
        tr
        for tr in WORKFLOWS["tg-solve"]["transitions"]
        if tr.get("to") == "construct" and tr.get("kind") == "rework"
    ]
    assert construct_rework
    codes = set()
    for tr in construct_rework:
        codes.update(tr.get("reason_codes") or [])
    assert "REWORK_CONSTRUCT" in codes
    assert "OPEN_REMAINING" in codes
    assert "OPEN_NONEMPTY" in codes
    assert not any(
        tr.get("to") == "lemma"
        for tr in WORKFLOWS["tg-solve"]["transitions"]
        if isinstance(tr, dict)
    )
