# -*- coding: utf-8 -*-
"""Unit tests for CANN platform_config INI locking (K5)."""
from __future__ import annotations

from pathlib import Path

from uo_init.platform_ini import (
    DEFAULT_SKU_BY_ARCH,
    load_platform_profile,
    list_profiles,
)
from uo_init.variable_model import PLATFORM_VARS, apply_platform_profile, build_variable_model

CANN = Path(r"d:\PR-review\_cann\pkg")


def test_load_default_arch35_sku():
    if not CANN.is_dir():
        return
    prof = load_platform_profile(CANN, arch_dir="arch35")
    assert prof.soc_version == DEFAULT_SKU_BY_ARCH["arch35"]
    assert prof.npu_arch == 3510
    assert prof.aic_num == 32
    assert prof.l2_size > 0


def test_load_pcie_sku():
    if not CANN.is_dir():
        return
    prof = load_platform_profile(
        CANN, arch_dir="arch35", platform_sku="Ascend950PR_957b"
    )
    assert prof.aic_num == 28


def test_apply_platform_closes_domains():
    if not CANN.is_dir():
        return
    model = build_variable_model()
    prof = load_platform_profile(CANN, arch_dir="arch35")
    apply_platform_profile(model, prof)
    core = model.get(PLATFORM_VARS["PLATFORM_CORE_COUNT"])
    assert core is not None
    assert core.domain.completeness == "closed"
    assert core.domain.values == [32]
    assert model.named_constants.get("aicNum") == 32
    assert model.platform_profile is prof


def test_list_3510_profiles_have_closed_cube_set():
    if not CANN.is_dir():
        return
    profiles = list_profiles(CANN, npu_arch=3510)
    assert profiles
    cubes = {p.aic_num for p in profiles}
    assert 28 in cubes or 32 in cubes
