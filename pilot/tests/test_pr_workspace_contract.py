# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ENGINE = Path(__file__).resolve().parents[2] / "engines" / "workspace"
if str(WORKSPACE_ENGINE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ENGINE))

import pr_workspace  # noqa: E402


def _operator(root: Path, name: str, arch: str = "arch35") -> Path:
    op = root / "operators" / name
    (op / "op_host" / arch).mkdir(parents=True)
    (op / "op_kernel" / arch).mkdir(parents=True)
    return op


def test_changed_file_resolves_structural_operator_root(tmp_path: Path):
    repo = tmp_path / "repo"
    op_a = _operator(repo, "op_a")
    _operator(repo, "op_b")
    changed = "operators/op_a/op_kernel/arch35/kernel.cpp"
    (repo / changed).write_text("// changed\n", encoding="utf-8")

    roots = pr_workspace.detect_operator_roots(repo, [changed])
    assert roots == [op_a.resolve()]


def test_no_filename_basename_operator_heuristic(tmp_path: Path):
    repo = tmp_path / "repo"
    op_b = _operator(repo, "op_b")
    (op_b / "op_kernel" / "arch35" / "same_name.cpp").write_text("// unrelated\n", encoding="utf-8")
    (repo / "docs").mkdir(parents=True)
    changed = "docs/same_name.cpp"
    (repo / changed).write_text("// docs only\n", encoding="utf-8")

    assert pr_workspace.detect_operator_roots(repo, [changed]) == []


def test_changed_architecture_comes_from_changed_path_tokens(tmp_path: Path):
    repo = tmp_path / "repo"
    op = _operator(repo, "op_a", "arch22")
    _operator(repo, "op_a", "arch35")
    changed = [
        "operators/op_a/op_kernel/arch35/kernel.cpp",
        "operators/op_a/op_host/arch35/tiling.cpp",
    ]
    assert pr_workspace.changed_architectures(op, changed) == ["arch35"]
