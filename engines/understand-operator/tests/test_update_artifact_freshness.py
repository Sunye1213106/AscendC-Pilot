"""change_set / update_plan freshness bound to scope fingerprints (fail-closed)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.detect_kb_changes import detect_kb_changes
from uo.scripts.plan_kb_update import plan_kb_update
from uo.scripts.update_artifact_io import (
    compute_change_set_fingerprint,
    current_scope_identity,
    load_change_set_if_fresh,
    load_update_plan_if_fresh,
)


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
    scope = uo / "runs" / "run-1" / "scope"
    scope.mkdir(parents=True)
    write_yaml(
        scope / "scope_confirmed.yaml",
        {"confirmed_source_files": [{"path": "op_host/a.cpp"}], "scope_revision": 1},
    )
    # Snapshot may lag; identity must come from confirmed content.
    write_yaml(
        scope / "scope_snapshot.yaml",
        {"scope_fingerprint": "stale_persisted_fp", "source_snapshot_hash": "stale_persisted_fp"},
    )
    manifest = {
        "op_name": op,
        "source": {"root": str(repo.resolve()), "revision": base},
        "current_run_id": "run-1",
    }
    write_yaml(uo / "manifest.yaml", manifest)
    return repo, uo, base


def _write_fresh_cs(uo: Path, repo: Path, base: str) -> dict:
    head = _git(repo, "rev-parse", "HEAD")
    scope_id = current_scope_identity(uo)
    scope_fp = str(scope_id["scope_fingerprint"])
    files: list = []
    fp = compute_change_set_fingerprint(
        head_revision=head,
        base_revision=base,
        scope_fingerprint=scope_fp,
        changed_files=files,
    )
    doc = {
        "base_revision": base,
        "head_revision": head,
        "scope_revision": scope_id.get("scope_revision"),
        "scope_fingerprint": scope_fp,
        "confirmed_sources_hash": scope_id.get("confirmed_sources_hash"),
        "change_set_fingerprint": fp,
        "files": files,
    }
    write_yaml(uo / "diff" / "change_set.yaml", doc)
    return doc


def test_load_change_set_rejects_stale_head(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    (repo / "op_host" / "a.cpp").write_text("void A() { int x=1; }\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "head-a")
    _write_fresh_cs(uo, repo, base)
    assert load_change_set_if_fresh(uo, repo_root=repo) is not None

    (repo / "op_host" / "a.cpp").write_text("void A() { int x=2; }\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "head-b")
    assert load_change_set_if_fresh(uo, repo_root=repo) is None


def test_load_change_set_rejects_base_mismatch(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    head = base
    scope_fp = current_scope_identity(uo)["scope_fingerprint"]
    fp = compute_change_set_fingerprint(
        head_revision=head,
        base_revision="deadbeef",
        scope_fingerprint=scope_fp,
        changed_files=[],
    )
    write_yaml(
        uo / "diff" / "change_set.yaml",
        {
            "base_revision": "deadbeef",
            "head_revision": head,
            "scope_fingerprint": scope_fp,
            "change_set_fingerprint": fp,
            "files": [],
        },
    )
    assert load_change_set_if_fresh(uo, repo_root=repo) is None


def test_load_update_plan_requires_change_set(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    scope_fp = current_scope_identity(uo)["scope_fingerprint"]
    write_yaml(
        uo / "summary" / "update_plan.yaml",
        {
            "base_revision": base,
            "head_revision": base,
            "scope_fingerprint": scope_fp,
            "change_set_fingerprint": "x",
            "plan_fingerprint": "y",
            "mode": "noop",
        },
    )
    assert load_update_plan_if_fresh(uo) is None
    cs = _write_fresh_cs(uo, repo, base)
    plan = plan_kb_update(repo, "DemoOp", change_set=cs, write=True)
    assert load_update_plan_if_fresh(uo, change_set=cs) is not None
    assert plan.get("plan_fingerprint")


def test_scope_change_invalidates_change_set(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    cs = detect_kb_changes(repo, "DemoOp", write=True)
    assert load_change_set_if_fresh(uo, repo_root=repo) is not None
    # Git HEAD unchanged; confirmed scope content changes (snapshot may stay stale).
    write_yaml(
        uo / "runs" / "run-1" / "scope" / "scope_snapshot.yaml",
        {"scope_fingerprint": "stale_persisted_fp", "source_snapshot_hash": "stale_persisted_fp"},
    )
    write_yaml(
        uo / "runs" / "run-1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [{"path": "op_host/a.cpp"}, {"path": "op_host/b.cpp"}],
            "scope_revision": 2,
        },
    )
    assert load_change_set_if_fresh(uo, repo_root=repo) is None
    assert cs.get("scope_fingerprint") != current_scope_identity(uo)["scope_fingerprint"]


def test_stale_snapshot_alone_does_not_mask_confirmed_change(tmp_path: Path) -> None:
    """Confirmed files changed + snapshot fingerprint unchanged → change_set must go stale."""
    repo, uo, base = _setup(tmp_path)
    cs = _write_fresh_cs(uo, repo, base)
    assert load_change_set_if_fresh(uo, repo_root=repo) is not None
    write_yaml(
        uo / "runs" / "run-1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [{"path": "op_host/a.cpp"}, {"path": "op_host/new.cpp"}],
            "scope_revision": 1,
        },
    )
    # Keep snapshot fp identical to old persisted value.
    write_yaml(
        uo / "runs" / "run-1" / "scope" / "scope_snapshot.yaml",
        {"scope_fingerprint": "stale_persisted_fp", "source_snapshot_hash": "stale_persisted_fp"},
    )
    assert load_change_set_if_fresh(uo, repo_root=repo) is None
    now = current_scope_identity(uo)
    assert now["status"] == "inconsistent"
    assert now["scope_fingerprint"] != cs["scope_fingerprint"]


def test_scope_change_invalidates_update_plan(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    cs = detect_kb_changes(repo, "DemoOp", write=True)
    plan_kb_update(repo, "DemoOp", change_set=cs, write=True)
    assert load_update_plan_if_fresh(uo, change_set=cs) is not None
    write_yaml(
        uo / "runs" / "run-1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [{"path": "op_host/a.cpp"}, {"path": "op_host/b.cpp"}],
            "scope_revision": 3,
        },
    )
    assert load_update_plan_if_fresh(uo, change_set=cs) is None


def test_detect_kb_changes_sees_confirmed_source_files(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    (repo / "op_host" / "b.cpp").write_text("void B() {}\n", encoding="utf-8")
    # Do not commit — HEAD unchanged; file exists on disk for role inference.
    write_yaml(
        uo / "runs" / "run-1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [
                {"path": "op_host/a.cpp", "role": "host"},
                {"path": "op_host/b.cpp", "role": "host"},
            ],
            "scope_revision": 2,
        },
    )
    # Simulate a "change" that is in-scope for b.cpp via name-status empty + scope membership
    # by checking the scope index used by detect.
    from uo.scripts.detect_kb_changes import _load_scope_index

    index = _load_scope_index(uo)
    assert "op_host/b.cpp" in index
    assert index["op_host/b.cpp"] == "host"


def test_missing_fingerprint_is_stale(tmp_path: Path) -> None:
    repo, uo, base = _setup(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    write_yaml(
        uo / "diff" / "change_set.yaml",
        {"base_revision": base, "head_revision": head, "files": []},
    )
    assert load_change_set_if_fresh(uo, repo_root=repo) is None
    write_yaml(
        uo / "summary" / "update_plan.yaml",
        {"base_revision": base, "head_revision": head, "mode": "noop"},
    )
    cs = _write_fresh_cs(uo, repo, base)
    assert load_update_plan_if_fresh(uo, change_set=cs) is None
