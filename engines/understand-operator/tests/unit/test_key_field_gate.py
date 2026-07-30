# -*- coding: utf-8 -*-
"""G0 / K7 gate: fixture truth + materialize invariants."""
from __future__ import annotations

from pathlib import Path

import yaml

from uo_init.materialize_tiling import z3_check_key_dims
from uo_init.platform_ini import load_platform_profile

FIX = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "flash_attention_score_grad"
)
CANN = Path(r"d:\PR-review\_cann\pkg")


def test_fixture_files_exist():
    assert (FIX / "key_field_truth.yaml").is_file()
    assert (FIX / "key_invariants.yaml").is_file()


def test_fixture_lists_19_fields():
    data = yaml.safe_load((FIX / "key_field_truth.yaml").read_text(encoding="utf-8"))
    assert len(data["fields"]) == 19


def test_fixture_platform_matches_ini():
    if not CANN.is_dir():
        return
    data = yaml.safe_load((FIX / "key_field_truth.yaml").read_text(encoding="utf-8"))
    sku = data["platform"]["default_sku"]
    prof = load_platform_profile(CANN, arch_dir="arch35", platform_sku=sku)
    assert prof.aic_num == data["platform"]["aic_num"]


def test_k7_invariants_file_has_i1_i12():
    data = yaml.safe_load((FIX / "key_invariants.yaml").read_text(encoding="utf-8"))
    ids = {i["id"] for i in data["invariants"]}
    assert ids >= {f"I{n}" for n in range(1, 13)}


def test_k6_hard_invariant_gate():
    # Sanity: empty-path with rich dims is rejected.
    st, reason, _ = z3_check_key_dims(
        {
            "IsEmptyTensor": "1",
            "IsRegbase": "1",
            "SplitAxis": "5",
            "InputDType": "2",
            "OutDType": "2",
            "IsTnd": "1",
            "IsDrop": "1",
            "IsPse": "1",
        }
    )
    assert st == "unreachable"
    assert reason == "Z3_UNSAT"
