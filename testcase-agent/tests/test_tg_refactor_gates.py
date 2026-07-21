"""Smoke tests for tg-init gates and L1 level split."""

from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.cli import init_main, plan_main, _parse_levels
from testcase_agent.planner import build_plan


def _op_tree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "op"
    kb = repo / ".understand-operator" / "DemoOp"
    kb.mkdir(parents=True)
    (kb / "contracts").mkdir()
    (kb / "contracts" / "testcase.yaml").write_text("version: 1\nvariables: []\n", encoding="utf-8")
    return repo, kb


def test_parse_levels_l1_expands() -> None:
    assert _parse_levels("L1") == ["L1-BRANCH", "L1-REJECT"]
    assert "L1-BRANCH" in _parse_levels("all")


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
    real = repo / ".testcase-generator" / "DemoOp" / "realization"
    real.mkdir(parents=True)
    for name in ("realization_map.yaml", "consumer_schema.yaml", "consumer_evidence.yaml"):
        (real / name).write_text("version: 1\n", encoding="utf-8")
    code = plan_main([str(repo), "--op-name", "DemoOp", "--level", "L0"])
    err = capsys.readouterr().err
    assert code == 1
    assert "init_required" in err


def test_l1_reject_level_tags() -> None:
    files = {
        "contracts/testcase.yaml": {"version": 1, "variables": [], "coverage_obligations": {}},
        "tiling/coverage_model.yaml": {},
        "kernel/branches.yaml": {"branches": []},
        "tiling/constraints.yaml": {
            "key_unreachable": [
                {"id": "BAD", "matches": {"KEY_X": 1}, "reject_stage": "host_validation"},
            ]
        },
        "cross_layer/impact_graph.yaml": {},
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L1-REJECT")
    assert plan["test_level"] == "L1-REJECT"
    assert all(item.get("test_level") == "L1-REJECT" for item in plan["obligations"])
