# -*- coding: utf-8 -*-
"""Branch-outcome ledger + field pins (engine ports of td-probe)."""
from __future__ import annotations

from testcase_agent.closure.branch_eval import Env, evaluate
from testcase_agent.closure.branch_outcome import (
    KeyBranchLedger,
    absorb_observation,
    build_env,
    close_key,
    site_id,
)
from testcase_agent.closure import field_pins


def test_evaluate_pinned_excludes_opposite() -> None:
    from testcase_agent.closure.branch_outcome import index_field_aliases
    env = Env(
        fields=index_field_aliases({"dropoutIsDivisibleBy8": 1}),
        dims={"IsDrop": 0},
        pinned=index_field_aliases({"dropoutIsDivisibleBy8": 1}),
    )
    oc = evaluate("tilingData->preTilingData.dropoutIsDivisibleBy8 == 0", env)
    assert oc.value is False
    assert oc.key_determined is True


def test_close_key_gap_with_pin_and_observation() -> None:
    branches = [
        {
            "id": "b1",
            "file": "k.h",
            "line": 1,
            "condition": "tilingData->base.sinkOptional",
            "fields": ["sinkOptional"],
        },
        {
            "id": "b2",
            "file": "k.h",
            "line": 2,
            "condition": "tilingData->pre.dropoutIsDivisibleBy8 == 0",
            "fields": ["dropoutIsDivisibleBy8"],
        },
    ]
    dims = {"IsDrop": 0}
    rules = [{
        "id": "drop_off",
        "field": "dropoutIsDivisibleBy8",
        "when": {"IsDrop": "0"},
        "value": 1,
    }]
    # observation covers sink True; pin excludes dropout==0 True
    obs = [
        {"fields": {"sinkOptional": 1, "dropoutIsDivisibleBy8": 1}, "block_num": 1},
        {"fields": {"sinkOptional": 0, "dropoutIsDivisibleBy8": 1}, "block_num": 1},
    ]
    ledger = KeyBranchLedger(key=1, dims=dims)
    for o in obs:
        env = build_env(
            fields=o["fields"], dims=dims, block_num=o["block_num"],
            pins=field_pins.load_pinned(dims, rules=rules),
        )
        absorb_observation(ledger, branches, env)
    s = ledger.summary()
    assert s["live"] == 2
    assert s["gap"] == 0, s
    assert ("b1", True) in ledger.covered
    assert ("b1", False) in ledger.covered
    assert ("b2", False) in ledger.covered
    assert ("b2", True) in ledger.excluded or ("b2", True) not in ledger.open_set


def test_refute_overwide_pin() -> None:
    rules = [{
        "id": "sparse_dense",
        "field": "sparseType",
        "when": {"IsAttenMask": "0"},
        "value": 0,
    }]
    obs = [
        {"dims": {"IsAttenMask": "0", "DeterType": "1"}, "fields": {"sparseType": 3}},
    ]
    report = field_pins.refute_pins(rules, obs)
    assert "sparse_dense" in report["refuted"]
