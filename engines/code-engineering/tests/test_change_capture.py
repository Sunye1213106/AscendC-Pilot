from __future__ import annotations

import subprocess
from pathlib import Path

from code_engineering.change.capture import capture, parse_diff_ranges


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_parse_and_capture_smoke(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    source = tmp_path / "kernel.cpp"
    source.write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "kernel.cpp")
    _git(
        tmp_path, "-c", "user.name=CE Test", "-c", "user.email=ce@example.invalid",
        "commit", "-m", "initial",
    )
    source.write_text("one\ntwo\n", encoding="utf-8")

    payload = capture(tmp_path)

    assert payload["base_sha"] == payload["head_sha"]
    assert parse_diff_ranges(payload["diff"])["kernel.cpp"]
    assert payload["diff_spans"]["kernel.cpp"]


def test_capture_nested_operator_and_untracked(tmp_path: Path) -> None:
    repo = tmp_path / "ops-transformer"
    op = repo / "attention" / "flash_attention_score_grad"
    host = op / "op_host"
    host.mkdir(parents=True)
    tracked = host / "kernel.cpp"
    tracked.write_text("one\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", "attention/flash_attention_score_grad/op_host/kernel.cpp")
    _git(
        repo, "-c", "user.name=CE Test", "-c", "user.email=ce@example.invalid",
        "commit", "-m", "initial",
    )
    tracked.write_text("one\ntwo\n", encoding="utf-8")
    untracked = host / "new_helper.hpp"
    untracked.write_text("struct Helper {};\n", encoding="utf-8")

    payload = capture(op)
    paths = parse_diff_ranges(payload["diff"])
    assert "op_host/kernel.cpp" in paths
    assert "op_host/new_helper.hpp" in paths
    assert "attention/flash_attention_score_grad/op_host/kernel.cpp" not in paths


def test_capture_default_does_not_write_yaml(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    source = tmp_path / "kernel.cpp"
    source.write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "kernel.cpp")
    _git(
        tmp_path, "-c", "user.name=CE Test", "-c", "user.email=ce@example.invalid",
        "commit", "-m", "initial",
    )
    source.write_text("one\ntwo\n", encoding="utf-8")
    payload = capture(tmp_path, output=None)
    assert payload["diff"]
    assert "path" not in payload
    assert list(tmp_path.rglob("*.yaml")) == []


def test_capture_change_empty_workspace_is_no_code_change(tmp_path: Path) -> None:
    from code_engineering.git import capture_change

    _git(tmp_path, "init")
    source = tmp_path / "kernel.cpp"
    source.write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "kernel.cpp")
    _git(
        tmp_path, "-c", "user.name=CE Test", "-c", "user.email=ce@example.invalid",
        "commit", "-m", "initial",
    )
    payload = capture_change(tmp_path)
    assert payload.get("ok") is False
    assert payload.get("reason_code") == "NO_CODE_CHANGE"


def test_extract_pr_url_from_intent() -> None:
    from code_engineering.git import extract_pr_url

    text = "审一下 https://gitcode.com/cann/ops-transformer/pulls/9851 这个改动。"
    assert extract_pr_url(text) == "https://gitcode.com/cann/ops-transformer/pulls/9851"
    assert extract_pr_url("https://evil.example/org/repo/pull/1") == ""


def test_capture_pr_url_unknown_host_rejected(tmp_path: Path) -> None:
    from code_engineering.git import capture_change

    payload = capture_change(
        tmp_path,
        pr_url="https://evil.example/org/repo/pull/1",
        intent="see https://evil.example/org/repo/pull/1",
    )
    assert payload.get("ok") is False
    assert payload.get("reason_code") == "PR_HOST_NOT_ALLOWED"


def test_capture_pr_fetch_via_file_remote(tmp_path: Path) -> None:
    from code_engineering.git import capture_change

    origin = tmp_path / "org" / "repo"
    origin.mkdir(parents=True)
    _git(origin, "init")
    _git(origin, "config", "user.name", "CE Test")
    _git(origin, "config", "user.email", "ce@example.invalid")
    source = origin / "kernel.cpp"
    source.write_text("old\n", encoding="utf-8")
    _git(origin, "add", "kernel.cpp")
    _git(origin, "commit", "-m", "base")
    source.write_text("old\nnew\n", encoding="utf-8")
    _git(origin, "add", "kernel.cpp")
    _git(origin, "commit", "-m", "pr")
    _git(origin, "update-ref", "refs/pull/1/head", "HEAD")
    _git(origin, "reset", "--hard", "HEAD~1")

    work = tmp_path / "work"
    _git(tmp_path, "clone", str(origin), "work")
    dirty = work / "kernel.cpp"
    dirty.write_text("local dirty should not be the patch\n", encoding="utf-8")

    payload = capture_change(
        work,
        intent="请审 https://gitcode.com/org/repo/pulls/1",
    )
    assert payload.get("ok") is True, payload
    assert payload.get("source") == "pr_fetch"
    assert "new" in payload.get("diff", "")
    assert "local dirty should not be the patch" not in payload.get("diff", "")


def test_capture_pr_http_fallback(tmp_path: Path, monkeypatch) -> None:
    from code_engineering import git as git_mod
    from code_engineering.git import capture_change

    _git(tmp_path, "init")
    _git(tmp_path, "remote", "add", "origin", "https://github.com/other/place.git")

    def fake_http(url: str, headers: dict[str, str]) -> tuple[int, str, str]:
        del headers
        assert "github.com" in url or "api.github.com" in url
        return 200, "diff --git a/kernel.cpp b/kernel.cpp\n+++ b/kernel.cpp\n@@ -1 +1,2 @@\n one\n+two\n", ""

    monkeypatch.setattr(git_mod, "_http_get", fake_http)
    payload = capture_change(tmp_path, pr_url="https://github.com/org/repo/pull/2")
    assert payload.get("ok") is True, payload
    assert payload.get("source") == "pr_http"
    assert "two" in payload.get("diff", "")


def test_http_pr_diff_scopes_to_operator_pathspec(tmp_path: Path, monkeypatch) -> None:
    from code_engineering import git as git_mod
    from code_engineering.git import capture_change

    repo = tmp_path / "ops-transformer"
    op = repo / "attention" / "flash_attention_score"
    host = op / "op_host"
    host.mkdir(parents=True)
    tracked = host / "kernel.cpp"
    tracked.write_text("one\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", "attention/flash_attention_score/op_host/kernel.cpp")
    _git(
        repo, "-c", "user.name=CE Test", "-c", "user.email=ce@example.invalid",
        "commit", "-m", "initial",
    )
    _git(repo, "remote", "add", "origin", "https://github.com/other/place.git")

    body = (
        "diff --git a/unrelated/foo.cpp b/unrelated/foo.cpp\n"
        "--- a/unrelated/foo.cpp\n"
        "+++ b/unrelated/foo.cpp\n"
        "@@ -1 +1,2 @@\n one\n+leak\n"
        "diff --git a/attention/flash_attention_score/op_host/kernel.cpp "
        "b/attention/flash_attention_score/op_host/kernel.cpp\n"
        "--- a/attention/flash_attention_score/op_host/kernel.cpp\n"
        "+++ b/attention/flash_attention_score/op_host/kernel.cpp\n"
        "@@ -1 +1,2 @@\n one\n+two\n"
    )

    def fake_http(url: str, headers: dict[str, str]) -> tuple[int, str, str]:
        del url, headers
        return 200, body, ""

    monkeypatch.setattr(git_mod, "_http_get", fake_http)
    payload = capture_change(op, pr_url="https://github.com/org/repo/pull/9")
    assert payload.get("ok") is True, payload
    diff = payload.get("diff") or ""
    assert "op_host/kernel.cpp" in diff
    assert "two" in diff
    assert "unrelated/foo.cpp" not in diff
    assert "leak" not in diff
