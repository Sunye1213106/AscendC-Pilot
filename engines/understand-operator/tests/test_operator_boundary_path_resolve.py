"""Tests for scoped source path resolution and boundary fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.extract_operator_boundary import extract_operator_boundary
from uo.scripts.source_path_resolve import (
    ScopePathMismatchError,
    resolve_confirmed_sources,
    resolve_scoped_source_path,
    strip_operator_prefix,
)


def test_strip_operator_prefix() -> None:
    assert strip_operator_prefix("DemoOp/op_host/a.cpp", "DemoOp") == "op_host/a.cpp"
    assert strip_operator_prefix("op_host/a.cpp", "DemoOp") == "op_host/a.cpp"


def test_resolve_with_op_name_prefix(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    host = op / "op_host"
    host.mkdir(parents=True)
    (host / "reg.cpp").write_text('.Input("x")\n', encoding="utf-8")
    result = resolve_scoped_source_path(op, "DemoOp/op_host/reg.cpp", "DemoOp")
    assert result["ok"] is True
    assert Path(result["path"]).is_file()


def test_resolve_parent_repo_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    op = repo / "DemoOp"
    host = op / "op_host"
    host.mkdir(parents=True)
    (host / "reg.cpp").write_text('.Input("x")\n', encoding="utf-8")
    result = resolve_scoped_source_path(op, "DemoOp/op_host/reg.cpp", "DemoOp", repository_root=repo)
    assert result["ok"] is True


def test_fail_closed_when_none_readable(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    with pytest.raises(ScopePathMismatchError) as exc:
        resolve_confirmed_sources(op, ["DemoOp/op_host/missing.cpp"], "DemoOp")
    assert exc.value.code == "OPERATOR_BOUNDARY_SCOPE_PATH_MISMATCH"


def test_boundary_empty_is_blocking(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    run = root / "runs" / "r1" / "scope"
    run.mkdir(parents=True)
    host = repo / "op_host"
    host.mkdir()
    (host / "empty.cpp").write_text("// no OpDef\n", encoding="utf-8")
    write_yaml(
        run / "scope_confirmed.yaml",
        {"confirmed_source_files": [{"path": "op_host/empty.cpp"}]},
    )
    payload = extract_operator_boundary(repo, "DemoOp")
    assert payload["inputs"] == []
    assert payload["outputs"] == []
    codes = {u.get("code") for u in payload.get("unresolved") or []}
    assert "OPERATOR_BOUNDARY_EMPTY" in codes


def test_boundary_path_prefix_reads_reg(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    run = root / "runs" / "r1" / "scope"
    run.mkdir(parents=True)
    host = repo / "op_host"
    host.mkdir()
    (host / "reg.cpp").write_text(
        'REG_OP(Demo)\n.Input("query")\n.Output("dq")\n.Attr("keep_prob")\n',
        encoding="utf-8",
    )
    write_yaml(
        run / "scope_confirmed.yaml",
        {"confirmed_source_files": [{"path": "DemoOp/op_host/reg.cpp"}]},
    )
    payload = extract_operator_boundary(repo, "DemoOp")
    assert len(payload["inputs"]) >= 1
    assert len(payload["outputs"]) >= 1
