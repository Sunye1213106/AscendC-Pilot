"""change_set reuse must verify git HEAD and manifest base revision."""

from __future__ import annotations

import subprocess
from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.update_artifact_io import load_change_set_if_fresh, load_update_plan_if_fresh


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _setup(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "uo@example.com")
    _git(repo, "config", "user.name", "uo-test")
    (repo / "op_host").mkdir()
    (repo / "op_host" / "a.cpp").write_text("void A() {}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    op = "DemoOp"
    uo = operator_root(repo, op)
    init_operator_contract_layout(uo, op, repo)
    manifest = {
        "op_name": op,
        "source": {"root": str(repo.resolve()), "revision": base},
        "current_run_id": "run-1",
    }
    write_yaml(uo / "manifest.yaml", manifest)
    return repo, uo, base


def test_load_change_set_rejects_stale_head(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    (repo / "op_host" / "a.cpp").write_text("void A() { int x=1; }\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "head-a")
    head_a = _git(repo, "rev-parse", "HEAD")
    write_yaml(
        uo / "diff" / "change_set.yaml",
        {"base_revision": base, "head_revision": head_a, "files": []},
    )
    assert load_change_set_if_fresh(uo, repo_root=repo) is not None

    (repo / "op_host" / "a.cpp").write_text("void A() { int x=2; }\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "head-b")
    assert load_change_set_if_fresh(uo, repo_root=repo) is None


def test_load_change_set_rejects_base_mismatch(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    head = base
    write_yaml(
        uo / "diff" / "change_set.yaml",
        {"base_revision": "deadbeef", "head_revision": head, "files": []},
    )
    assert load_change_set_if_fresh(uo, repo_root=repo) is None


def test_load_update_plan_requires_change_set(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    write_yaml(
        uo / "summary" / "update_plan.yaml",
        {"base_revision": base, "head_revision": base, "mode": "noop"},
    )
    assert load_update_plan_if_fresh(uo) is None
    cs = {"base_revision": base, "head_revision": base}
    assert load_update_plan_if_fresh(uo, change_set=cs) is not None
