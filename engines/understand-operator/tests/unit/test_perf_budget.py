# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init.perf import TimeBudget, kernel_root_trace_budget_s


def test_default_kernel_root_trace_budget_does_not_cut_off(monkeypatch):
    monkeypatch.delenv("UO_KERNEL_ROOT_TRACE_BUDGET_S", raising=False)
    monkeypatch.delenv("UO_KERNEL_ROOT_TRACE_BUDGET_FAST", raising=False)
    assert kernel_root_trace_budget_s() == 0.0
    budget = TimeBudget(kernel_root_trace_budget_s())
    assert budget.expired() is False
    assert budget.remaining() == float("inf")


def test_explicit_budget_still_expires(monkeypatch):
    monkeypatch.setenv("UO_KERNEL_ROOT_TRACE_BUDGET_S", "0.001")
    assert kernel_root_trace_budget_s() == 0.001
    budget = TimeBudget(0.0)
    assert budget.expired() is False
