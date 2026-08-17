# -*- coding: utf-8 -*-
"""Unit tests for CANN platform_config INI locking (K5)."""
from __future__ import annotations

from uo_init.platform_ini import (
    DEFAULT_SKU_BY_ARCH,
    dav_name_for_arch,
    kernel_macros_for_arch,
    load_platform_profile,
    list_profiles,
    parse_family_for_arch,
)
from uo_init.variable_model import PLATFORM_VARS, apply_platform_profile, build_variable_model


def test_load_default_arch35_sku(cann_root):
    prof = load_platform_profile(cann_root, arch_dir="arch35")
    assert prof.soc_version == DEFAULT_SKU_BY_ARCH["arch35"]
    assert prof.npu_arch == 3510
    assert prof.aic_num == 32
    assert prof.l2_size > 0


def test_load_pcie_sku(cann_root):
    prof = load_platform_profile(
        cann_root, arch_dir="arch35", platform_sku="Ascend950PR_957b"
    )
    assert prof.aic_num == 28


def test_apply_platform_closes_domains(cann_root):
    model = build_variable_model()
    prof = load_platform_profile(cann_root, arch_dir="arch35")
    apply_platform_profile(model, prof)
    core = model.get(PLATFORM_VARS["PLATFORM_CORE_COUNT"])
    assert core is not None
    assert core.domain.completeness == "closed"
    assert core.domain.values == [32]
    assert model.named_constants.get("aicNum") == 32
    assert model.platform_profile is prof


def test_list_3510_profiles_have_closed_cube_set(cann_root):
    profiles = list_profiles(cann_root, npu_arch=3510)
    assert profiles
    cubes = {p.aic_num for p in profiles}
    assert 28 in cubes or 32 in cubes


def test_arch_920r1_is_distinct_identity_parsed_as_arch35():
    assert parse_family_for_arch("arch-920r1") == "arch35"
    assert parse_family_for_arch("arch35") == "arch35"
    assert dav_name_for_arch("arch-920r1") == "DAV_9201"
    assert dav_name_for_arch("arch35") == "DAV_3510"
    assert kernel_macros_for_arch("arch-920r1") == kernel_macros_for_arch("arch35")
    assert kernel_macros_for_arch("arch-920r1")["__NPU_ARCH__"] == "3510"
    assert kernel_macros_for_arch("arch-920r1")["__DAV_C310__"] == ""
    assert kernel_macros_for_arch("arch22")["__NPU_ARCH__"] == "2201"
