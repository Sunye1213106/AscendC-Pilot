# -*- coding: utf-8 -*-
"""detect_kb_changes must see uncommitted overlays, not just commit ranges."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from uo_init.extract_cache import compute_extract_fingerprint, store_extract_fingerprint
from uo_init.update.artifacts import load_change_set_if_fresh
from uo_init.update.changes import detect_kb_changes
from uo_init.update.plan import plan_kb_update


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _init_git(root: Path) -> None:
    _git(root, "init")


def _commit(root: Path, message: str) -> None:
    _git(
        root,
        "-c",
        "user.name=uo-test",
        "-c",
        "user.email=uo-test@example.invalid",
        "commit",
        "-m",
        message,
    )


def _seed_uo(
    root: Path,
    rels: list[str],
    *,
    source: str | dict | None = "string",
    revision: str = "",
) -> Path:
    uo = root / ".ascendc-pilot" / "arch35" / "uo"
    summary = uo / "summary"
    summary.mkdir(parents=True, exist_ok=True)
    man: dict = {
        "op_name": "Toy",
        "architecture": "arch35",
        "current_run_id": "r1",
        "scope_revision": 1,
        "status": "ready",
    }
    if source == "string":
        man["source"] = "uo_init.pilot_engines.prepare_layout"
    elif isinstance(source, dict):
        man["source"] = source
        if revision:
            man["source"]["revision"] = revision
    if revision and source != "string":
        man["source_revision"] = revision
    (uo / "manifest.yaml").write_text(yaml.safe_dump(man), encoding="utf-8")
    payload = {
        "confirmed_source_files": rels,
        "files": [{"path": rel, "provenance": "clang_tu"} for rel in rels],
        "notes": ["clang_scope_status=complete"],
    }
    (summary / "scope_set.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    return uo


def test_operator_subdirectory_paths_match_scope(tmp_path: Path) -> None:
    """Project root is the operator; git toplevel is the ops repo above it."""
    _init_git(tmp_path)
    op = tmp_path / "attention" / "flash_attention_score_grad"
    host = op / "op_host" / "tiling.cpp"
    host.parent.mkdir(parents=True)
    host.write_text("v1\n", encoding="utf-8")
    other = tmp_path / "other_op" / "op_host" / "x.cpp"
    other.parent.mkdir(parents=True)
    other.write_text("other\n", encoding="utf-8")
    _git(tmp_path, "add", "attention/flash_attention_score_grad/op_host/tiling.cpp")
    _git(tmp_path, "add", "other_op/op_host/x.cpp")
    _commit(tmp_path, "base")
    _seed_uo(op, ["op_host/tiling.cpp"], source="string")
    host.write_text("v2-overlay\n", encoding="utf-8")
    other.write_text("other-dirty\n", encoding="utf-8")

    payload = detect_kb_changes(op, "Toy", architecture="arch35", write=False)

    assert payload["git_ok"] is True
    assert payload["scoped_change_count"] == 1
    assert payload["files"][0]["path"] == "op_host/tiling.cpp"
    assert payload["files"][0]["in_scope"] is True
    assert all("other_op" not in str(item.get("path")) for item in payload["files"])
    assert all(not str(item.get("path")).startswith("attention/") for item in payload["files"])


def test_dirty_tree_same_head_lists_scoped_files(tmp_path: Path) -> None:
    _init_git(tmp_path)
    host = tmp_path / "op_host" / "tiling.cpp"
    host.parent.mkdir()
    host.write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "op_host/tiling.cpp")
    _commit(tmp_path, "base")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    _seed_uo(tmp_path, ["op_host/tiling.cpp"], source="string")
    host.write_text("v2-pr-overlay\n", encoding="utf-8")

    payload = detect_kb_changes(tmp_path, "Toy", architecture="arch35", write=False)

    assert payload["git_ok"] is True
    assert payload["worktree_dirty"] is True
    assert payload["scoped_change_count"] == 1
    assert payload["files"][0]["path"] == "op_host/tiling.cpp"
    assert payload["files"][0]["in_scope"] is True
    assert payload["head_sha"] == head
    assert payload["base_revision"] == head
    assert "+dirty:" in str(payload["head_revision"])
    plan = plan_kb_update(tmp_path, "Toy", change_set=payload, write=False, architecture="arch35")
    assert plan["mode"] != "noop"
    assert "host" in plan["affected_layers"]


def test_committed_range_still_detected(tmp_path: Path) -> None:
    _init_git(tmp_path)
    host = tmp_path / "op_host" / "tiling.cpp"
    host.parent.mkdir()
    host.write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "op_host/tiling.cpp")
    _commit(tmp_path, "base")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    host.write_text("v2\n", encoding="utf-8")
    _git(tmp_path, "add", "op_host/tiling.cpp")
    _commit(tmp_path, "pr")
    _seed_uo(
        tmp_path,
        ["op_host/tiling.cpp"],
        source={"kind": "prepare", "revision": base},
        revision=base,
    )

    payload = detect_kb_changes(tmp_path, "Toy", architecture="arch35", write=False)

    assert payload["scoped_change_count"] == 1
    assert payload["base_revision"] == base
    assert payload["worktree_dirty"] is False


def test_change_set_stale_when_worktree_changes(tmp_path: Path) -> None:
    _init_git(tmp_path)
    host = tmp_path / "op_host" / "tiling.cpp"
    host.parent.mkdir()
    host.write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "op_host/tiling.cpp")
    _commit(tmp_path, "base")
    uo = _seed_uo(tmp_path, ["op_host/tiling.cpp"], source="string")
    host.write_text("v2\n", encoding="utf-8")
    first = detect_kb_changes(tmp_path, "Toy", architecture="arch35", write=True)
    assert first["scoped_change_count"] == 1
    reused = load_change_set_if_fresh(uo, repo_root=tmp_path)
    assert reused is not None
    host.write_text("v3\n", encoding="utf-8")
    assert load_change_set_if_fresh(uo, repo_root=tmp_path) is None


def test_missing_git_falls_back_to_content_fingerprint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = tmp_path / "op_host" / "tiling.cpp"
    host.parent.mkdir()
    host.write_text("v1\n", encoding="utf-8")
    uo = _seed_uo(tmp_path, ["op_host/tiling.cpp"], source="string")
    meta = compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")
    store_extract_fingerprint(uo, meta)
    host.write_text("v2-overlay\n", encoding="utf-8")

    monkeypatch.setattr(
        "uo_init.update.changes.inspect_git_changes",
        lambda *_args, **_kwargs: {
            "git_ok": False,
            "rows": [],
            "worktree_rows": [],
            "worktree_dirty": False,
            "worktree_fingerprint": "none",
            "head_sha": "",
            "base_sha": "",
        },
    )
    monkeypatch.setattr("uo_init.update.changes.git_head", lambda *_args, **_kwargs: "")

    payload = detect_kb_changes(tmp_path, "Toy", architecture="arch35", write=False)

    assert payload["detection"] == "content_fingerprint"
    assert payload["scoped_change_count"] == 1
    assert payload["files"][0]["path"] == "op_host/tiling.cpp"


def test_does_not_raise_when_head_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uo = _seed_uo(tmp_path, ["op_host/tiling.cpp"], source="string")
    (tmp_path / "op_host").mkdir(exist_ok=True)
    (tmp_path / "op_host" / "tiling.cpp").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(
        "uo_init.update.changes.inspect_git_changes",
        lambda *_args, **_kwargs: {
            "git_ok": False,
            "rows": [],
            "worktree_rows": [],
            "worktree_dirty": False,
            "worktree_fingerprint": "none",
            "head_sha": "",
            "base_sha": "",
        },
    )
    monkeypatch.setattr("uo_init.update.changes.git_head", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        "uo_init.update.changes._product_source_revision",
        lambda *_args, **_kwargs: "",
    )
    payload = detect_kb_changes(tmp_path, "Toy", architecture="arch35", write=True)
    assert (uo / "diff" / "change_set.yaml").is_file()
    assert payload["head_sha"] == "unknown"


def test_content_fallback_lists_only_changed_confirmed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "op_host"
    host.mkdir()
    (host / "a.cpp").write_text("void f() {}\n", encoding="utf-8")
    (host / "b.cpp").write_text("void g() {}\n", encoding="utf-8")
    uo = _seed_uo(tmp_path, ["op_host/a.cpp", "op_host/b.cpp"], source="string")
    meta = compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")
    store_extract_fingerprint(uo, meta)
    (host / "b.cpp").write_text("void g() { return; }\n", encoding="utf-8")

    monkeypatch.setattr(
        "uo_init.update.changes.inspect_git_changes",
        lambda *_args, **_kwargs: {
            "git_ok": False,
            "rows": [],
            "worktree_rows": [],
            "worktree_dirty": False,
            "worktree_fingerprint": "none",
            "head_sha": "",
            "base_sha": "",
        },
    )
    monkeypatch.setattr("uo_init.update.changes.git_head", lambda *_args, **_kwargs: "")

    payload = detect_kb_changes(tmp_path, "Toy", architecture="arch35", write=False)

    assert payload["detection"] == "content_fingerprint"
    assert payload["scoped_change_count"] == 1
    assert payload["files"][0]["path"] == "op_host/b.cpp"
    plan = plan_kb_update(tmp_path, "Toy", change_set=payload, write=False, architecture="arch35")
    assert plan["mode"] != "noop"
    assert plan["scoped_changed_files"] == ["op_host/b.cpp"]


def test_git_rows_are_noop_when_extract_fingerprint_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uo-update must follow extract stamps, not a stale git range."""
    host = tmp_path / "op_host"
    host.mkdir()
    (host / "tiling.cpp").write_text("v1\n", encoding="utf-8")
    uo = _seed_uo(tmp_path, ["op_host/tiling.cpp"], source="string")
    meta = compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")
    store_extract_fingerprint(uo, meta)

    monkeypatch.setattr(
        "uo_init.update.changes.inspect_git_changes",
        lambda *_args, **_kwargs: {
            "git_ok": True,
            "rows": [("M", "op_host/tiling.cpp")],
            "worktree_rows": [("M", "op_host/tiling.cpp")],
            "worktree_dirty": True,
            "worktree_fingerprint": "stale-git",
            "head_sha": "abc",
            "base_sha": "abc",
        },
    )
    monkeypatch.setattr("uo_init.update.changes.git_head", lambda *_args, **_kwargs: "abc")

    payload = detect_kb_changes(tmp_path, "Toy", architecture="arch35", write=False)

    assert payload["scoped_change_count"] == 0
    assert payload["files"] == []
    plan = plan_kb_update(tmp_path, "Toy", change_set=payload, write=False, architecture="arch35")
    assert plan["mode"] == "noop"
