# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init.init_profile import (
    cold_budget_s,
    default_closure_max_nodes,
    default_closure_mode,
    default_fold_kernel,
    default_harness_limit,
    default_kernel_max_variants,
    default_with_api,
    default_with_kernel,
    profile_name,
    review_skips_closure_gate,
)


def test_fast_is_default(monkeypatch):
    monkeypatch.delenv("UO_INIT_PROFILE", raising=False)
    monkeypatch.delenv("UO_WITH_KERNEL", raising=False)
    monkeypatch.delenv("UO_WITH_API", raising=False)
    monkeypatch.delenv("UO_KERNEL_MAX_VARIANTS", raising=False)
    monkeypatch.delenv("UO_COLD_BUDGET_S", raising=False)
    monkeypatch.delenv("UO_FOLD_KERNEL", raising=False)
    monkeypatch.delenv("UO_HARNESS_LIMIT", raising=False)
    monkeypatch.delenv("UO_FAST_HARNESS_LIMIT", raising=False)
    assert profile_name() == "fast"
    assert default_closure_mode({}) == "keypath"
    # AscendC compile-time fold stays on; cost is capped by harness_limit.
    assert default_fold_kernel({}) is True
    assert default_harness_limit({}) == 8
    assert default_with_kernel({}) is True
    assert default_kernel_max_variants({}) == 1
    assert default_with_api({}) is False
    assert default_closure_max_nodes({}) == 96
    assert cold_budget_s() == 180.0


def test_full_profile(monkeypatch):
    monkeypatch.setenv("UO_INIT_PROFILE", "full")
    monkeypatch.delenv("UO_WITH_KERNEL", raising=False)
    monkeypatch.delenv("UO_WITH_API", raising=False)
    monkeypatch.delenv("UO_KERNEL_MAX_VARIANTS", raising=False)
    monkeypatch.delenv("UO_FOLD_KERNEL", raising=False)
    monkeypatch.delenv("UO_HARNESS_LIMIT", raising=False)
    assert profile_name() == "full"
    assert default_closure_mode({}) == "full"
    assert default_fold_kernel({}) is True
    assert default_harness_limit({}) is None
    assert default_with_kernel({}) is True
    assert default_kernel_max_variants({}) == 0
    assert default_with_api({}) is True


def test_ctx_overrides_env(monkeypatch):
    monkeypatch.setenv("UO_INIT_PROFILE", "full")
    assert default_closure_mode({"closure_mode": "off"}) == "off"
    assert default_fold_kernel({"fold_kernel": False}) is False
    assert default_with_kernel({"with_kernel": False}) is False
    assert default_kernel_max_variants({"kernel_max_variants": 2}) == 2
    assert default_harness_limit({"harness_limit": 4}) == 4


def test_review_skips_keypath():
    assert review_skips_closure_gate("keypath")
    assert review_skips_closure_gate("off")
    assert not review_skips_closure_gate("full")
