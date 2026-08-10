from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.cli import plan_main
from testcase_agent.path_resolve import (
    install_contract_into_project,
    resolve_operator_project_root,
    resolve_plan_paths,
)


def _op_tree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "flash_attention_score_grad"
    kb = repo / ".ascendc-pilot" / "uo"
    kb.mkdir(parents=True)
    (kb / "marker.yaml").write_text("version: 1\n", encoding="utf-8")
    (kb / "manifest.yaml").write_text("op_name: flash_attention_score_grad\nversion: 1\n", encoding="utf-8")
    (repo / ".understand-operator").mkdir(parents=True, exist_ok=True)
    return repo, kb


def _contract_dir(tmp_path: Path) -> Path:
    root = tmp_path / "prior_realization"
    root.mkdir()
    for name in ("realization_map.yaml", "consumer_schema.yaml", "consumer_evidence.yaml"):
        (root / name).write_text("version: 1\n", encoding="utf-8")
    return root


def test_resolve_operator_project_root_from_kb_paths(tmp_path: Path) -> None:
    repo, kb = _op_tree(tmp_path)
    assert resolve_operator_project_root(repo) == repo.resolve()
    assert resolve_operator_project_root(repo / ".ascendc-pilot") == repo.resolve()
    assert resolve_operator_project_root(repo / ".understand-operator") == repo.resolve()
    assert resolve_operator_project_root(kb) == repo.resolve()


def test_resolve_plan_paths_build_contract_from_test_tool(tmp_path: Path) -> None:
    repo, kb = _op_tree(tmp_path)
    test_root = tmp_path / "fag_debug_tools"
    test_root.mkdir()
    bundle = resolve_plan_paths(
        project_root=kb,
        op_name=None,
        csv_consumer_root=None,
        test_script_root=test_root,
    )
    assert bundle.mode == "build_contract"
    assert bundle.project_root == repo.resolve()
    assert bundle.op_name == "flash_attention_score_grad"
    assert bundle.test_tool_root == test_root.resolve()
    assert bundle.contract_root is None


def test_resolve_plan_paths_reuse_contract(tmp_path: Path) -> None:
    repo, _kb = _op_tree(tmp_path)
    contract = _contract_dir(tmp_path)
    bundle = resolve_plan_paths(
        project_root=repo,
        op_name="flash_attention_score_grad",
        csv_consumer_root=None,
        contract_root=contract,
    )
    assert bundle.mode == "reuse_contract"
    assert bundle.contract_root == contract.resolve()
    assert bundle.test_tool_root is None


def test_resolve_plan_paths_prefers_test_tool_when_both(tmp_path: Path) -> None:
    repo, _kb = _op_tree(tmp_path)
    test_root = tmp_path / "tools"
    test_root.mkdir()
    contract = _contract_dir(tmp_path)
    bundle = resolve_plan_paths(
        project_root=repo,
        op_name="flash_attention_score_grad",
        csv_consumer_root=test_root,
        contract_root=contract,
    )
    assert bundle.mode == "build_contract"
    assert bundle.test_tool_root == test_root.resolve()


def test_resolve_plan_paths_requires_inputs(tmp_path: Path) -> None:
    repo, _kb = _op_tree(tmp_path)
    with pytest.raises(ValueError, match="PLAN_INPUTS_REQUIRED"):
        resolve_plan_paths(
            project_root=repo,
            op_name="flash_attention_score_grad",
            csv_consumer_root=None,
        )


def test_plan_main_missing_inputs_asks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, _kb = _op_tree(tmp_path)
    code = plan_main([str(repo), "--op-name", "flash_attention_score_grad", "--level", "L1"])
    captured = capsys.readouterr()
    assert code == 1
    # Without tg-init confirmed / realization, CLI asks for init (or reports missing inputs as init_required).
    assert "ask" in captured.err
    assert "init_required" in captured.err or "uo_init_required" in captured.err or "PLAN_INPUTS_REQUIRED" in captured.err


def test_parse_levels_l0_l1_default() -> None:
    from testcase_agent.cli import _parse_levels

    assert _parse_levels("L1") == ["L1"]
    assert _parse_levels("") == ["L0", "L1"]
    assert _parse_levels("all") == ["L0", "L1", "L2"]
    assert _parse_levels("L0,L1-branch") == ["L0", "L1"]


def test_install_contract_into_project(tmp_path: Path) -> None:
    repo, _kb = _op_tree(tmp_path)
    contract = _contract_dir(tmp_path)
    dest = install_contract_into_project(repo, "flash_attention_score_grad", contract)
    assert (dest / "realization_map.yaml").is_file()
    assert dest == (repo / ".ascendc-pilot" / "arch35" / "tg" / "realization").resolve()
