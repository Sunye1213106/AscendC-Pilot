# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_UO_ROOT = Path(__file__).resolve().parents[1]
_COMMON = _UO_ROOT.parent / "common"
_SRC = _UO_ROOT / "src"
for path in (_SRC, _COMMON):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from uo_init import paths

UO_ROOT = Path(__file__).resolve().parents[1]
SPEC = UO_ROOT / "spec"
REPO = paths.repo_root()

#: None when the tree is absent. Tests that need one skip, and `--uo-strict`
#: turns those skips into failures so CI cannot go green by finding nothing.
#: The operator these tests are written against. Fixtures, recorded baselines
#: and the counts asserted below all describe this one; the code under test
#: must not (see test_no_operator_specialisation.py).
DEFAULT_OPERATOR = "attention/flash_attention_score_grad"

OPS = paths.ops_root()
CANN = paths.cann_root()
FAG = paths.op_dir(relative=DEFAULT_OPERATOR)

_STRICT = False

#: Architecture subdirectory under analysis. Every arch has its own host tiling
#: sources and its own TilingKey schema, so this selects which one is measured.
ARCH = "arch35"

UPDATE_BASELINES = False


def pytest_addoption(parser):
    parser.addoption(
        "--uo-strict",
        action="store_true",
        help="fail instead of skipping when CANN or the operator sources are missing",
    )
    parser.addoption(
        "--uo-arch",
        default=ARCH,
        help="architecture subdirectory to analyse (arch35, arch22, ...)",
    )
    parser.addoption(
        "--uo-update-baselines",
        action="store_true",
        help="rewrite recorded source-derived baselines to what was just measured",
    )


def pytest_configure(config):
    global _STRICT, ARCH, UPDATE_BASELINES
    _STRICT = bool(config.getoption("--uo-strict"))
    ARCH = str(config.getoption("--uo-arch"))
    UPDATE_BASELINES = bool(config.getoption("--uo-update-baselines"))
    config.addinivalue_line("markers", "requires_cann: needs CANN headers")
    config.addinivalue_line("markers", "requires_fag: needs FAG sources")


def pytest_report_header(config):
    """Say which external trees were found, so a skip is never a surprise."""
    lines = [f"uo arch: {ARCH}", "uo paths:"]
    lines += [f"  {line}" for line in paths.explain().splitlines()]
    if FAG is not None:
        tus = host_tiling_sources(FAG)
        lines.append(f"  host tiling TUs: {len(tus)} ({', '.join(p.name for p in tus)})")
    return lines


def _need(value: Path | None, what: str):
    if value is not None:
        return value
    message = f"{what} not available\n{paths.explain()}"
    if _STRICT:
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture
def uo_root() -> Path:
    return UO_ROOT


@pytest.fixture
def spec_dir() -> Path:
    return SPEC


@pytest.fixture(scope="session")
def fag_dir() -> Path:
    return _need(FAG, "operator sources")


@pytest.fixture(scope="session")
def cann_root() -> Path:
    return _need(CANN, "CANN packages")


@pytest.fixture(scope="session")
def ops_root() -> Path:
    return _need(OPS, "ops-transformer")


@pytest.fixture(scope="session")
def arch_dir() -> str:
    return ARCH


@pytest.fixture
def build_ctx(fag_dir, cann_root, ops_root):
    from uo_init.build_context import BuildContext

    return BuildContext.load(
        cann_root=str(cann_root),
        ops_root=str(ops_root),
        op_dir=str(fag_dir),
        arch_dir=ARCH,
    )


@pytest.fixture(scope="session")
def clang_exe():
    from uo_init.clang_cmd import find_clang

    exe = find_clang()
    if exe is None:
        pytest.skip("no clang driver available")
    return exe


def host_tiling_sources(op_dir: Path, arch: str | None = None) -> list[Path]:
    """Host translation units that take part in tiling, for any operator.

    Discovered rather than listed. A hand-written list silently omits whatever
    the operator gains next -- this operator had grown a third arch35 tiling TU
    that no analysis had ever looked at.

    `*_def.cpp` and `*_infershape.cpp` are excluded: they register the operator
    and infer output shapes, and neither runs on the path that computes a
    TilingKey.
    """
    host = op_dir / "op_host"
    if not host.is_dir():
        return []
    found = sorted(host.glob("*.cpp")) + sorted((host / (arch or ARCH)).glob("*.cpp"))
    return [
        p
        for p in found
        if not (p.stem.endswith("_def") or p.stem.endswith("_infershape"))
    ]


@pytest.fixture(scope="session")
def op_name() -> str:
    """The operator under analysis, taken from its directory name."""
    return FAG.name if FAG is not None else "unknown"


@pytest.fixture(scope="session")
def update_baselines() -> bool:
    return UPDATE_BASELINES


@pytest.fixture(scope="session")
def host_tus() -> dict[str, Path]:
    """Host tiling TU paths keyed by file name."""
    if FAG is None:
        _need(None, "operator sources")
    return {p.name: p for p in host_tiling_sources(FAG)}
