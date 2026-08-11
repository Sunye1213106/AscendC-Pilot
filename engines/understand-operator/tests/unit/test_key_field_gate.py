# -*- coding: utf-8 -*-
"""G0 / K7 gate: fixture truth + materialize invariants."""
from __future__ import annotations

from pathlib import Path

import yaml

from uo_init.platform_ini import load_platform_profile

FIX = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "flash_attention_score_grad"
)

def test_fixture_files_exist():
    assert (FIX / "key_field_truth.yaml").is_file()
    assert (FIX / "key_invariants.yaml").is_file()


def test_fixture_lists_19_fields():
    data = yaml.safe_load((FIX / "key_field_truth.yaml").read_text(encoding="utf-8"))
    assert len(data["fields"]) == 19


def test_fixture_platform_matches_ini(cann_root):
    data = yaml.safe_load((FIX / "key_field_truth.yaml").read_text(encoding="utf-8"))
    sku = data["platform"]["default_sku"]
    prof = load_platform_profile(cann_root, arch_dir="arch35", platform_sku=sku)
    assert prof.aic_num == data["platform"]["aic_num"]


def test_k7_invariants_file_has_i1_i12():
    data = yaml.safe_load((FIX / "key_invariants.yaml").read_text(encoding="utf-8"))
    ids = {i["id"] for i in data["invariants"]}
    assert ids >= {f"I{n}" for n in range(1, 13)}


def test_the_invariants_fixture_is_documentation_not_a_gate():
    """K7's invariants describe the operator; K6 must not assert them.

    They used to be three hand-written rules inside a legacy reachability
    helper, which made every key they did not object to `reachable` — a claim
    nothing had checked. Runtime closure now comes from replay or reviewed
    evidence, so this file is a reference to compare derived results against,
    not an input to them.
    """
    from uo_init import materialize_tiling

    assert not any(name.endswith("check_key_dims") for name in dir(materialize_tiling))
    assert not hasattr(materialize_tiling, "_hard_invariants")
