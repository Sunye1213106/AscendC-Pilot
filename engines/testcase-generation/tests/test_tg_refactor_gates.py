"""Smoke tests for tg-init gates and L1 level split."""

from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.cli import init_main, plan_main, _parse_levels
from testcase_agent.planner import build_plan


def _op_tree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "op"
    kb = repo / ".ascendc-pilot" / "uo"
    kb.mkdir(parents=True)
    (kb / "contracts").mkdir()
    (kb / "contracts" / "testcase.yaml").write_text("version: 1\nvariables: []\n", encoding="utf-8")
    return repo, kb


def test_parse_levels_default_l0_l1() -> None:
    assert _parse_levels("L1") == ["L1"]
    assert _parse_levels("") == ["L0", "L1"]
    # `all` deliberately stops at L2: L3 multiplies keys by branch outcomes.
    assert _parse_levels("all") == ["L0", "L1", "L2"]
    assert _parse_levels("L0,L1-branch") == ["L0", "L1"]
    # L3 is the branch-outcome level and must be asked for by name.
    assert _parse_levels("L3") == ["L3"]
    assert _parse_levels("branch_outcome") == ["L3"]
    with pytest.raises(ValueError, match="L1-REJECT"):
        _parse_levels("L1-REJECT")


def test_init_main_uo_init_required(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "bare"
    repo.mkdir()
    code = init_main([str(repo), "--op-name", "MissingOp", "--test-script-root", str(tmp_path / "scripts")])
    err = capsys.readouterr().err
    assert code == 1
    assert "uo_init_required" in err


def test_plan_main_init_required(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, _kb = _op_tree(tmp_path)
    # Fake realization so path resolve can reuse_init, but init not confirmed.
    real = repo / ".ascendc-pilot" / "tg" / "realization"
    real.mkdir(parents=True)
    for name in ("realization_map.yaml", "consumer_schema.yaml", "consumer_evidence.yaml"):
        (real / name).write_text("version: 1\n", encoding="utf-8")
    code = plan_main([str(repo), "--op-name", "DemoOp", "--level", "L0"])
    err = capsys.readouterr().err
    assert code == 1
    assert "init_required" in err


def test_l1_tags_kernel_branches() -> None:
    files = {
        "contracts/testcase.yaml": {"version": 1, "variables": [], "coverage_obligations": {}},
        "tiling/coverage_model.yaml": {},
        "kernel/branches.yaml": {
            "branches": [
                {"id": "BR_A", "condition": "x", "then": "a", "else": "b"},
            ]
        },
        "tiling/constraints.yaml": {},
        "cross_layer/impact_graph.yaml": {},
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L1")
    assert plan["test_level"] == "L1"
    assert all(item.get("test_level") == "L1" for item in plan["obligations"])
    with pytest.raises(Exception, match="L1-REJECT|Unsupported"):
        build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L1-REJECT")
