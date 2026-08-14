# -*- coding: utf-8 -*-
"""CANN VF / Reg compute API catalog loaded from headers."""

from __future__ import annotations

from uo_init.semantics.ascendc_vf import (
    cann_vf_api_names,
    is_ambiguous_vf_name,
    is_cann_vf_api,
    vf_root_spelling,
)
from uo_init.semantics import registry as semreg


def test_vf_aliases_and_ambiguous_or() -> None:
    assert vf_root_spelling("FusedExpSub") == "ExpSub"
    assert vf_root_spelling("FusedMulDstAdd") == "MulDstAdd"
    assert vf_root_spelling("ExpSub") == "ExpSub"
    assert is_cann_vf_api("ExpSub")
    assert is_cann_vf_api("FusedExpSub")
    assert is_cann_vf_api("Or")
    assert is_ambiguous_vf_name("Or")
    assert not is_ambiguous_vf_name("ExpSub")
    names = cann_vf_api_names()
    assert "ExpSub" in names
    assert "Or" in names


def test_registry_classifies_vf_spellings() -> None:
    semreg.load_registry.cache_clear()
    cat, engine, conf = semreg.classify("ExpSub")
    assert cat == "vector_compute"
    assert engine == "VECTOR"
    assert conf == "confirmed"
    cat_or, _, _ = semreg.classify("Or")
    assert cat_or == "vector_compute"
    cat_fused, _, _ = semreg.classify("FusedMulDstAdd")
    assert cat_fused == "vector_compute"
