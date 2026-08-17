# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init.init_profile import (
    cold_budget_s,
    default_kernel_max_variants,
    default_with_kernel,
)


def test_product_defaults(monkeypatch):
    monkeypatch.delenv("UO_WITH_KERNEL", raising=False)
    monkeypatch.delenv("UO_KERNEL_MAX_VARIANTS", raising=False)
    monkeypatch.delenv("UO_COLD_BUDGET_S", raising=False)
    assert default_with_kernel({}) is True
    assert default_kernel_max_variants({}) == 1
    assert cold_budget_s() == 180.0


def test_ctx_overrides_env(monkeypatch):
    monkeypatch.setenv("UO_KERNEL_MAX_VARIANTS", "9")
    assert default_with_kernel({"with_kernel": False}) is False
    assert default_kernel_max_variants({"kernel_max_variants": 2}) == 2
    monkeypatch.delenv("UO_KERNEL_MAX_VARIANTS", raising=False)
    assert default_kernel_max_variants({}) == 1
