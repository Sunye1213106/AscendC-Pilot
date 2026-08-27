# -*- coding: utf-8 -*-
from uo_init.query.exam_gate import compare, score_question


def test_score_question_counts_must_hits():
    spec = {
        "id": "Q1",
        "queries": [{"pattern": "SetSplitAxis"}],
        "must_names": ["SetSplitAxis", "SplitAxis"],
        "must_files": ["tiling_common_regbase.cpp"],
        "must_needles": ["BN2"],
        "related_allow": ["SetSplitAxis", "SplitAxis", "BN2"],
        "expect_first_kinds": {"SetSplitAxis": ["FUNCTION"]},
    }
    payload = {
        "ok": True,
        "shape": "name",
        "cards": [
            {
                "kind": "FUNCTION",
                "name": "SetSplitAxis",
                "file": "op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp",
                "snippet": "splitAxis = SplitAxisEnum::BN2;",
            }
        ],
        "next": ["SplitAxis"],
    }
    scored = score_question(spec, [payload], 4.0)
    assert scored["gold_hits"] == 4
    assert scored["noise"] == 0
    assert scored["first_kind_miss"] == 0


def test_compare_fails_on_noise_or_dropped_hits():
    gold = {
        "questions": [
            {"id": "Q1", "gold_hits": 4, "noise": 1, "ms": 10, "noise_names": ["Foo"]}
        ]
    }
    dropped = {
        "questions": [
            {"id": "Q1", "gold_hits": 3, "noise": 1, "ms": 10, "noise_names": ["Foo"]}
        ]
    }
    noisy = {
        "questions": [
            {
                "id": "Q1",
                "gold_hits": 4,
                "noise": 2,
                "ms": 10,
                "noise_names": ["Foo", "Bar"],
            }
        ]
    }
    assert any("gold_hits" in line for line in compare(gold, dropped))
    assert any("noise" in line for line in compare(gold, noisy))
    assert compare(gold, gold) == []
