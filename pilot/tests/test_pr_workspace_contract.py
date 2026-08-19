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


def test_changed_architectures_are_scoped_per_operator(tmp_path: Path):
    repo = tmp_path / "repo"
    op_a = _operator(repo, "op_a", "arch35")
    op_b = _operator(repo, "op_b", "arch22")
    changed = [
        "operators/op_a/op_kernel/arch35/kernel.cpp",
        "operators/op_b/op_host/arch22/tiling.cpp",
    ]
    assert pr_workspace.changed_architectures(op_a, changed, worktree=repo) == ["arch35"]
    assert pr_workspace.changed_architectures(op_b, changed, worktree=repo) == ["arch22"]
    matrix = pr_workspace.operator_arch_matrix(repo, changed)
    by_name = {row["operator_name"]: row["architectures"] for row in matrix}
    assert by_name["op_a"] == ["arch35"]
    assert by_name["op_b"] == ["arch22"]
    pairs = pr_workspace.flatten_operator_targets(matrix)
    assert {(p["operator_name"], p["architecture"]) for p in pairs} == {
        ("op_a", "arch35"),
        ("op_b", "arch22"),
    }


def test_resolve_targets_auto_pins_single_pair(tmp_path: Path):
    repo = tmp_path / "repo"
    op = _operator(repo, "flash_attention_score_grad")
    changed = [
        "operators/flash_attention_score_grad/op_host/arch35/tiling.cpp",
    ]
    acquire = {
        "ok": True,
        "worktree_head": str(repo),
        "changed_files": changed,
        "operator_roots": [str(op)],
        "changeset": {"changed_files": changed},
    }
    resolved = pr_workspace.resolve_targets_or_ask(acquire, host_root=tmp_path)
    assert resolved.get("ok") is True
    assert Path(str(resolved["project"])).resolve() == op.resolve()
    assert resolved.get("architecture") == "arch35"
    assert resolved.get("reason_code") != "MULTI_OPERATOR"


def test_ses_fe87_style_fag_arch35_autopin(tmp_path: Path):
    """PR #9851 shape: seven arch35 paths under one operator → pin, do not AskQuestion."""
    repo = tmp_path / "ops-transformer"
    fag = repo / "attention" / "flash_attention_score_grad"
    (fag / "op_host" / "arch35").mkdir(parents=True)
    (fag / "op_kernel" / "arch35").mkdir(parents=True)
    changed = [
        "attention/flash_attention_score_grad/op_host/arch35/flash_attention_score_grad.cpp",
        "attention/flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling.cpp",
        "attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad.cpp",
        "attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_bngs1s2_b.h",
        "attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_post.h",
        "attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2.h",
        "attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_template.h",
    ]
    for rel in changed:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// pr\n", encoding="utf-8")
    acquire = {
        "ok": True,
        "worktree_head": str(repo),
        "changed_files": changed,
    }
    resolved = pr_workspace.resolve_targets_or_ask(acquire, host_root=tmp_path)
    assert resolved.get("ok") is True
    assert Path(str(resolved["project"])).resolve() == fag.resolve()
    assert resolved.get("architecture") == "arch35"
    assert resolved.get("reason_code") not in {
        "MULTI_OPERATOR",
        "MULTI_PR_ARCHITECTURE",
        "PR_ARCHITECTURE_UNRESOLVED",
    }
    assert "ask_question" not in resolved


def test_resolve_targets_accepts_flattened_pairs(tmp_path: Path):
    repo = tmp_path / "repo"
    op = _operator(repo, "flash_attention_score_grad")
    acquire = {
        "ok": True,
        "worktree_head": str(repo),
        "changed_files": ["operators/flash_attention_score_grad/op_host/arch35/tiling.cpp"],
        "operator_roots": [str(op)],
        "operator_targets": [
            {
                "operator_root": str(op),
                "operator_name": "flash_attention_score_grad",
                "architecture": "arch35",
            }
        ],
    }
    resolved = pr_workspace.resolve_targets_or_ask(acquire, host_root=tmp_path)
    assert resolved.get("ok") is True
    assert Path(str(resolved["project"])).resolve() == op.resolve()
    assert resolved.get("architecture") == "arch35"
    assert len(resolved.get("operator_targets") or []) == 1


def test_resolve_targets_expands_two_operator_pairs(tmp_path: Path):
    repo = tmp_path / "repo"
    op_a = _operator(repo, "op_a", "arch35")
    op_b = _operator(repo, "op_b", "arch22")
    changed = [
        "operators/op_a/op_kernel/arch35/kernel.cpp",
        "operators/op_b/op_host/arch22/tiling.cpp",
    ]
    acquire = {
        "ok": True,
        "worktree_head": str(repo),
        "changed_files": changed,
        "operator_roots": [str(op_a), str(op_b)],
    }
    resolved = pr_workspace.resolve_targets_or_ask(acquire, host_root=tmp_path)
    assert resolved.get("ok") is True
    assert resolved.get("reason_code") not in {"MULTI_OPERATOR", "MULTI_PR_ARCHITECTURE"}
    pairs = {
        (str(Path(p["operator_root"]).resolve()), p["architecture"])
        for p in (resolved.get("operator_targets") or [])
    }
    assert pairs == {
        (str(op_a.resolve()), "arch35"),
        (str(op_b.resolve()), "arch22"),
    }


def test_resolve_targets_asks_when_path_has_no_arch_token(tmp_path: Path):
    repo = tmp_path / "repo"
    op = _operator(repo, "op_a", "arch35")
    (op / "op_host" / "arch22").mkdir(parents=True)
    changed = ["operators/op_a/op_host/tiling.cpp"]
    (repo / changed[0]).write_text("// shared\n", encoding="utf-8")
    acquire = {
        "ok": True,
        "worktree_head": str(repo),
        "changed_files": changed,
        "operator_roots": [str(op)],
    }
    resolved = pr_workspace.resolve_targets_or_ask(acquire, host_root=tmp_path)
    assert resolved.get("ok") is False
    assert resolved.get("reason_code") == "PR_ARCHITECTURE_UNRESOLVED"
    values = [str(opt.get("value") or "") for opt in (resolved.get("ask_question") or {}).get("options") or []]
    assert any("arch35" in v for v in values)
    assert any("arch22" in v for v in values)
    assert not any("两个都要" in v for v in values)


def test_resolve_targets_asks_when_zero_operators(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    acquire = {
        "ok": True,
        "worktree_head": str(repo),
        "changed_files": ["docs/README.md"],
        "operator_roots": [],
    }
    resolved = pr_workspace.resolve_targets_or_ask(acquire, host_root=tmp_path)
    assert resolved.get("ok") is False
    assert resolved.get("reason_code") == "OPERATOR_ROOTS_EMPTY"


def test_create_worktree_reuses_matching_sha(tmp_path: Path, monkeypatch):
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: E402

    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=src, check=True, capture_output=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, check=True, capture_output=True, text=True
    ).stdout.strip()
    monkeypatch.setenv("ASCENDC_WORKSPACE_CACHE", str(tmp_path / "cache"))
    dest = tmp_path / "clone"
    first = gw.create_worktree(src, dest, sha, run_id="run-1")
    assert first.get("ok") is True
    marker = dest / "keep.txt"
    assert marker.is_file()
    marker.write_text("local-note\n", encoding="utf-8")
    second = gw.create_worktree(src, dest, sha, run_id="run-1")
    assert second.get("ok") is True
    assert second.get("reused") is True
    assert marker.read_text(encoding="utf-8") == "local-note\n"


def _git_init_commit(path: Path, body: str) -> str:
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    (path / "keep.txt").write_text(body, encoding="utf-8", newline="\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=path, check=True, capture_output=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_create_worktree_wipes_isolated_sha_mismatch(tmp_path: Path, monkeypatch):
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: E402

    monkeypatch.setenv("ASCENDC_WORKSPACE_CACHE", str(tmp_path / "cache"))
    src = tmp_path / "src"
    wanted = _git_init_commit(src, "wanted\n")
    dest = tmp_path / ".ascendc-pr" / "gitcode.com--cann--ops--pr-1"
    leftover = _git_init_commit(dest, "stale\n")
    assert leftover != wanted
    assert gw.is_isolated_pr_tree(dest)
    result = gw.create_worktree(src, dest, wanted, run_id="run-wipe")
    assert result.get("ok") is True, result
    assert not result.get("reused")
    got = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert (dest / "keep.txt").read_text(encoding="utf-8").replace("\r\n", "\n") == "wanted\n"


def test_create_worktree_refuses_rmtree_on_operator_sha_mismatch(tmp_path: Path, monkeypatch):
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: E402

    monkeypatch.setenv("ASCENDC_WORKSPACE_CACHE", str(tmp_path / "cache"))
    src = tmp_path / "src"
    wanted = _git_init_commit(src, "wanted\n")
    dest = tmp_path / "operator"
    stale = _git_init_commit(dest, "stale-operator\n")
    (dest / "op_host").mkdir(exist_ok=True)
    (dest / "op_kernel").mkdir(exist_ok=True)
    assert stale != wanted
    assert not gw.is_isolated_pr_tree(dest)
    result = gw.create_worktree(src, dest, wanted, run_id="run-keep")
    assert result.get("ok") is False
    assert result.get("error") == "WORKTREE_SHA_MISMATCH"
    assert (dest / "keep.txt").read_text(encoding="utf-8").replace("\r\n", "\n") == "stale-operator\n"
