from __future__ import annotations

import subprocess
from pathlib import Path

from code_engineering.change.capture import capture
from code_engineering.impact import parse_diff_ranges


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
