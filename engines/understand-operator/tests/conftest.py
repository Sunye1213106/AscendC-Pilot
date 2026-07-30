# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

import pytest

UO_ROOT = Path(__file__).resolve().parents[1]
SPEC = UO_ROOT / "spec"
REPO = UO_ROOT.parents[1]  # AscendC-Pilot
PR_REVIEW = REPO.parent  # PR-review

FAG = PR_REVIEW / "TEST" / "ops-transformer" / "attention" / "flash_attention_score_grad"
OPS = PR_REVIEW / "TEST" / "ops-transformer"
CANN = PR_REVIEW / "_cann" / "pkg"


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_cann: needs CANN headers")
    config.addinivalue_line("markers", "requires_fag: needs FAG sources")


@pytest.fixture
def uo_root() -> Path:
    return UO_ROOT


@pytest.fixture
def spec_dir() -> Path:
    return SPEC


@pytest.fixture
def fag_dir() -> Path:
    if not FAG.exists():
        pytest.skip("FAG sources not found")
    return FAG


@pytest.fixture
def cann_root() -> Path:
    if not CANN.exists():
        pytest.skip("CANN pkg not extracted")
    return CANN


@pytest.fixture
def ops_root() -> Path:
    if not OPS.exists():
        pytest.skip("ops-transformer not found")
    return OPS


@pytest.fixture
def build_ctx(fag_dir, cann_root, ops_root):
    from uo_init.build_context import BuildContext

    return BuildContext.load(
        cann_root=str(cann_root),
        ops_root=str(ops_root),
        op_dir=str(fag_dir),
        arch_dir="arch35",
    )


@pytest.fixture(scope="session")
def clang_exe():
    from uo_init.harness import find_clang

    exe = find_clang()
    if exe is None:
        pytest.skip("no clang driver available")
    return exe


@pytest.fixture(scope="session")
def host_walks():
    """Parse the three FAG arch35 host TUs once; clang parsing costs ~8s each."""
    from uo_init.branch_inventory import inventory_clang
    from uo_init.build_context import BuildContext

    if not (FAG.exists() and CANN.exists() and OPS.exists()):
        pytest.skip("FAG/CANN/ops sources not available")
    ctx = BuildContext.load(
        cann_root=str(CANN), ops_root=str(OPS), op_dir=str(FAG), arch_dir="arch35"
    )
    targets = {
        "flash_attention_score_grad_tiling.cpp": FAG
        / "op_host"
        / "flash_attention_score_grad_tiling.cpp",
        "flash_attention_score_grad_tiling_normal_regbase.cpp": FAG
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp",
        "flash_attention_score_grad_tiling_common_regbase.cpp": FAG
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_common_regbase.cpp",
    }
    return {name: inventory_clang(p, ctx) for name, p in targets.items()}
