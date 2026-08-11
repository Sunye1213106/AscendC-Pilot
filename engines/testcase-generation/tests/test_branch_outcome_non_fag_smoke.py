# -*- coding: utf-8 -*-
"""Non-FAG smoke: one-key branch-outcome gap=0 (no FAG semantics)."""
from __future__ import annotations

from testcase_agent.closure.branch_outcome import (
    KeyBranchLedger,
    absorb_observation,
    build_env,
)
from testcase_agent.closure import field_pins


def test_non_fag_one_key_gap_zero() -> None:
    """Synthetic key closed with observation + pin — same shape as FAG pilot."""
    branches = [
        {
            "id": "opt",
            "condition": "tilingData->base.optOn",
            "fields": ["optOn"],
        },
        {
            "id": "mode0",
            "condition": "tilingData->pre.modeFlag == 0",
            "fields": ["modeFlag"],
        },
    ]
    dims = {"IsModeOff": "0"}
    rules = [{
        "id": "mode_stays_one",
        "field": "modeFlag",
        "when": {"IsModeOff": "0"},
        "value": 1,
    }]
    pins = field_pins.load_pinned(dims, rules=rules)
    ledger = KeyBranchLedger(key=42, dims=dims)
    for fields in (
        {"optOn": 1, "modeFlag": 1},
        {"optOn": 0, "modeFlag": 1},
    ):
        env = build_env(fields=fields, dims=dims, pins=pins)
        absorb_observation(ledger, branches, env)
    s = ledger.summary()
    assert s["gap"] == 0, s
    assert s["live"] == 2
