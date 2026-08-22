# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_gen():
    path = (
        Path(__file__).resolve().parents[2] / "tools" / "uo_init_generalization.py"
    )
    spec = importlib.util.spec_from_file_location("uo_init_generalization", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _load_gen()


def test_pick_arch_numeric_newest_not_string_order(tmp_path: Path, gen):
    op = tmp_path / "toy"
    for name in ("arch9", "arch22", "arch100"):
        (op / "op_kernel" / name).mkdir(parents=True)
    assert gen._list_archs(op) == ["arch9", "arch22", "arch100"]
    assert gen._pick_arch(op) == "arch100"


def test_pick_arch_prefers_discovered_arch35(tmp_path: Path, gen):
    op = tmp_path / "toy"
    (op / "op_kernel" / "arch22").mkdir(parents=True)
    (op / "op_host" / "arch35").mkdir(parents=True)
    assert gen._pick_arch(op) == "arch35"


def test_pick_arch_newest_wins_over_arch35(tmp_path: Path, gen):
    op = tmp_path / "toy"
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_host" / "arch-920r1").mkdir(parents=True)
    assert gen._pick_arch(op) == "arch-920r1"
    assert gen._list_archs(op)[-1] == "arch-920r1"


def test_list_archs_includes_hyphenated_920r1(tmp_path: Path, gen):
    op = tmp_path / "toy"
    (op / "op_kernel" / "arch22").mkdir(parents=True)
    (op / "op_host" / "arch-920r1").mkdir(parents=True)
    assert gen._list_archs(op) == ["arch22", "arch-920r1"]
    assert gen._pick_arch(op) == "arch-920r1"


def test_pick_arch_unified_when_no_arch_dirs(tmp_path: Path, gen):
    op = tmp_path / "toy"
    (op / "op_kernel").mkdir(parents=True)
    assert gen._pick_arch(op) == "default"


def test_discover_ops_keeps_single_implementation_trees(tmp_path: Path, gen, capsys):
    fam = tmp_path / "attention" / "noarch"
    (fam / "op_kernel").mkdir(parents=True)
    has_arch = tmp_path / "attention" / "widget"
    (has_arch / "op_kernel" / "arch22").mkdir(parents=True)
    cases = gen.discover_ops(tmp_path)
    by_rel = {c["rel"]: c for c in cases}
    assert by_rel["attention/widget"]["arch"] == "arch22"
    assert by_rel["attention/noarch"]["arch"] == "default"
    assert "NO_ARCHITECTURE_DISCOVERED" not in capsys.readouterr().out
