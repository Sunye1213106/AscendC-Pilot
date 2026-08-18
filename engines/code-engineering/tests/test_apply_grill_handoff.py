# -*- coding: utf-8 -*-
"""CE apply gate, patch guard, and session handoff markdown."""

from __future__ import annotations

from pathlib import Path

from code_engineering.apply import apply_gate, patch_guard
from code_engineering.git import parse_pr_url
from code_engineering.handoff import write_session_handoff
from code_engineering.plan_md import unfinished_todos


def _write_plan(tmp_path: Path, *, open_todo: bool = True) -> Path:
    arch = "arch35"
    plan = tmp_path / ".ascendc-pilot" / arch / "ce" / "plan" / "sync_plan.md"
    plan.parent.mkdir(parents=True)
    box = "- [ ] Host SaveToTilingData" if open_todo else "- [x] Host SaveToTilingData"
    plan.write_text(
        "# sync\n\n"
        f"{box}\n"
        "- [x] done item\n\n"
        "Files: `op_kernel/foo.cpp` `op_host/bar.cpp`\n",
        encoding="utf-8",
    )
    return plan


def test_unfinished_todos_parses_checkboxes(tmp_path: Path) -> None:
    plan = _write_plan(tmp_path)
    assert unfinished_todos(plan) == ["Host SaveToTilingData"]


def test_apply_gate_requires_open_todos(tmp_path: Path) -> None:
    missing = apply_gate(tmp_path, architecture="arch35")
    assert missing.get("ok") is False
    assert missing.get("reason_code") == "APPLY_PLAN_MISSING"
    _write_plan(tmp_path, open_todo=False)
    done = apply_gate(tmp_path, architecture="arch35")
    assert done.get("ok") is False
    assert done.get("reason_code") == "APPLY_TODOS_DONE"
    plan = tmp_path / ".ascendc-pilot" / "arch35" / "ce" / "plan" / "sync_plan.md"
    plan.write_text("# x\n\n- [ ] still open\n\n`op_kernel/foo.cpp`\n", encoding="utf-8")
    allowed = apply_gate(tmp_path, architecture="arch35")
    assert allowed.get("ok") is True, allowed


def test_patch_guard_rejects_files_outside_plan(tmp_path: Path) -> None:
    _write_plan(tmp_path)
    result = patch_guard(
        tmp_path,
        architecture="arch35",
        capture_payload={
            "diff_spans": {
                "op_kernel/foo.cpp": [[1, 2]],
                "op_host/other.cpp": [[3, 4]],
            }
        },
    )
    assert result.get("ok") is False
    assert "op_host/other.cpp" in (result.get("extra_files") or [])


def test_write_session_handoff_is_pointer_only(tmp_path: Path) -> None:
    out = write_session_handoff(
        tmp_path,
        architecture="arch35",
        next_slash="/ce-apply",
        artifact_paths=["ce/plan/sync_plan.md"],
        open_items=[],
    )
    assert out.get("ok") is True, out
    path = Path(out["artifact"])
    assert path.name == "session_handoff.md"
    assert path.parent.name == "arch35"
    text = path.read_text(encoding="utf-8")
    assert "/ce-apply" in text
    assert "ce/plan/sync_plan.md" in text
    assert "grill-with-docs" not in text


def test_parse_pr_url_gitcode_shape() -> None:
    owner, repo, number = parse_pr_url("https://gitcode.com/org/repo/pulls/9851")
    assert (owner, repo, number) == ("org", "repo", 9851)


def test_named_plan_is_markdown_not_yaml(tmp_path: Path) -> None:
    plan = _write_plan(tmp_path)
    assert plan.suffix == ".md"
    ce = tmp_path / ".ascendc-pilot" / "arch35" / "ce"
    assert list(ce.rglob("*.yaml")) == []
