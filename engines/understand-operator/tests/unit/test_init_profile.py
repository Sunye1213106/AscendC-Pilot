# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init.init_profile import (
    default_closure_max_nodes,
    default_closure_mode,
    default_fold_kernel,
    profile_name,
    review_skips_closure_gate,
)


def test_fast_is_default(monkeypatch):
    monkeypatch.delenv("UO_INIT_PROFILE", raising=False)
    assert profile_name() == "fast"
    assert default_closure_mode({}) == "keypath"
    assert default_fold_kernel({}) is False
    assert default_closure_max_nodes({}) == 96


def test_full_profile(monkeypatch):
    monkeypatch.setenv("UO_INIT_PROFILE", "full")
    assert profile_name() == "full"
    assert default_closure_mode({}) == "full"
    assert default_fold_kernel({}) is True


def test_ctx_overrides_env(monkeypatch):
    monkeypatch.setenv("UO_INIT_PROFILE", "full")
    assert default_closure_mode({"closure_mode": "off"}) == "off"
    assert default_fold_kernel({"fold_kernel": False}) is False


def test_review_skips_keypath():
    assert review_skips_closure_gate("keypath")
    assert review_skips_closure_gate("off")
    assert not review_skips_closure_gate("full")
