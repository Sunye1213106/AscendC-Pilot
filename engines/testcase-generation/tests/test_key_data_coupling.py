# -*- coding: utf-8 -*-
"""Key<->Data coupling: shared roots, free witnesses, inherited E."""
from __future__ import annotations

import base64

from testcase_agent.closure import key_data_coupling as KDC


def _drop_field() -> dict:
    """Field shaped like a flag with a default plus guarded rewrites."""
    return {
        "name": "divisibleFlag",
        "field_class": "control",
        "value_defining_sites": [
            {
                "file": "op_host/arch35/t.cpp", "line": 100, "rhs": "1",
                "function": "ProcessOptionalInput", "unconditional": True,
                "guards": [],
            },
            {
                "file": "op_host/arch35/t.cpp", "line": 180, "rhs": "0",
                "function": "ProcessDivisible", "unconditional": False,
                "guards": [{"condition": "p.s2 % BIT_NUMS != 0", "line": 179}],
                "caller_guards": [
                    {"line": 101, "guards": [{"condition": "p.keepProb < 1", "line": 101}]}
                ],
            },
        ],
    }


def _dims() -> list[dict]:
    return [
        {
            "name": "IsDrop",
            "allowed_values": ["0", "1"],
            "host_packing_expressions": ["static_cast<uint8_t>(dropValue)"],
            "packing_value_sites": [
                {"packing_symbol": "dropValue",
                 "rhs": "p.keepProb < 1 ? OptionEnum::ENABLE : OptionEnum::DISABLE"}
            ],
        },
        {
            "name": "IsRope",
            "allowed_values": ["0", "1"],
            "host_packing_expressions": ["static_cast<uint8_t>(p.hasRope)"],
            "packing_value_sites": [],
        },
    ]


def test_shared_root_yields_pin_lead() -> None:
    leads = KDC.derive_pin_leads(_dims(), [_drop_field()])
    ids = [l["id"] for l in leads]
    assert "PIN::IsDrop::divisibleFlag" in ids, ids
    # IsRope shares no host state with the guard, so it must not be proposed.
    assert "PIN::IsRope::divisibleFlag" not in ids
    lead = next(l for l in leads if l["id"] == "PIN::IsDrop::divisibleFlag")
    assert "keepProb" in lead["shared_roots"]
    assert lead["candidate_value_expr"] == "1"
    assert lead["status"] == "LEAD"
    # A lead may never behave like an exclusion on its own.
    assert "referee_review" in lead["requires"]
    assert "source_window_proof" in lead["requires"]


def test_no_lead_without_single_default() -> None:
    field = _drop_field()
    field["value_defining_sites"].append(
        {"file": "f", "line": 5, "rhs": "2", "unconditional": True, "guards": []}
    )
    assert KDC.derive_pin_leads(_dims(), [field]) == []


def test_leads_to_lemma_candidates_shape() -> None:
    leads = KDC.derive_pin_leads(_dims(), [_drop_field()])
    cands = KDC.leads_to_lemma_candidates(leads, dim_value="0")
    assert cands[0]["when"] == {"IsDrop": "0"}
    assert cands[0]["field"] == "divisibleFlag"
    assert cands[0]["status"] == "candidate"


def test_harvest_td_observations_from_key_log() -> None:
    payload = base64.b64encode(b"\x01\x00\x00\x00").decode()
    log = "\n".join([
        "###CASE c1",
        f"###TD 4 {payload}",
        "###BLOCK 32",
        "###WS 1024",
        "###DONE c1 ok=1 key=19703248907145264",
        "###CASE c2",
        "###DONE c2 ok=0 key=0",
        "###CASE c3",
        f"###TD 4 {payload}",
        "###DONE c3 ok=1 key=7",
    ])
    obs = KDC.harvest_td_observations(log)
    assert [o["case_id"] for o in obs] == ["c1", "c3"]
    assert obs[0]["tiling_key"] == 19703248907145264
    assert obs[0]["block_num"] == 32
    assert obs[1]["block_num"] == 0
    assert all(o["source"] == "tilingkey_closure_log" for o in obs)


def test_e_keys_prune_their_outcome_subtree() -> None:
    rows = [
        {"tiling_key": 1, "counts": {"td_obligations": 4, "runtime_branch_outcomes": 40}},
        {"tiling_key": 2, "counts": {"td_obligations": 4, "runtime_branch_outcomes": 40}},
    ]
    out = KDC.prune_outcomes_by_e_keys(rows, [2])
    assert out["dropped_keys"] == 1
    assert out["dropped_obligations"] == 44
    assert [r["tiling_key"] for r in out["kept"]] == [1]
