# -*- coding: utf-8 -*-
"""Spec / Standards review fan-out isolates the two axes."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_review_axis_fanout_writes_isolated_stubs(tmp_path: Path) -> None:
    import sys

    if str(REPO / "pilot") not in sys.path:
        sys.path.insert(0, str(REPO / "pilot"))
    from ascendc_pilot.actions.runtime import _review_axis_fanout_tasks

    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "prompt.md").write_text("# p\n", encoding="utf-8")
    (sdir / "bundle.yaml").write_text("ok: true\n", encoding="utf-8")
    stub_kwargs = {
        "actor_id": "ce-reviewer",
        "action_id": "code_review",
        "run_id": "r1",
        "session_dir": sdir.as_posix(),
        "prompt_path": (sdir / "prompt.md").as_posix(),
        "method_path": (sdir / "method.md").as_posix(),
        "bundle_path": (sdir / "bundle.yaml").as_posix(),
        "project_root": tmp_path.as_posix(),
        "architecture": "arch0",
        "write_paths": ["ce/review/**"],
        "user_question": "review the patch",
    }
    tasks = _review_axis_fanout_tasks(
        action_id="code_review",
        actor_id="ce-reviewer",
        phase="review",
        sdir=sdir,
        stub_kwargs=stub_kwargs,
        repo=REPO,
        dispatch_targets={},
        write_paths=["ce/review/**"],
        project_root=tmp_path.as_posix(),
        architecture="arch0",
    )
    assert len(tasks) == 2
    ids = {t["slice_id"] for t in tasks}
    assert ids == {"spec", "standards"}
    spec = next(t for t in tasks if t["slice_id"] == "spec")
    std = next(t for t in tasks if t["slice_id"] == "standards")
    assert "AXIS=spec" in spec["task_prompt_stub"]
    assert "plan.md" in spec["task_prompt_stub"]
    assert "diff" in spec["task_prompt_stub"]
    assert "推断" in spec["task_prompt_stub"]
    assert "不要填 ce/review" in spec["task_prompt_stub"]
    assert "AXIS=standards" in std["task_prompt_stub"]
    assert "Do not Write ce/review" in spec["task_prompt_stub"]
    assert (sdir / "method_spec.md").is_file()
    assert (sdir / "method_standards.md").is_file()
    spec_method = (sdir / "method_spec.md").read_text(encoding="utf-8")
    std_method = (sdir / "method_standards.md").read_text(encoding="utf-8")
    assert "只做 **Spec** 轴" in spec_method
    assert "只做 **Standards** 轴" in std_method
    assert "bug_report.yaml" not in spec_method or "不要读 `ce/review/bug_report.yaml`" in spec_method
    assert (tmp_path / ".ascendc-pilot" / "arch0" / "ce" / "review" / "index.yaml").is_file()


def test_review_axis_fanout_skips_scope_phase(tmp_path: Path) -> None:
    import sys

    if str(REPO / "pilot") not in sys.path:
        sys.path.insert(0, str(REPO / "pilot"))
    from ascendc_pilot.actions.runtime import _review_axis_fanout_tasks

    sdir = tmp_path / "session"
    sdir.mkdir()
    tasks = _review_axis_fanout_tasks(
        action_id="code_review",
        actor_id="ce-reviewer",
        phase="scope",
        sdir=sdir,
        stub_kwargs={},
        repo=REPO,
        dispatch_targets=None,
        write_paths=None,
        project_root=tmp_path.as_posix(),
        architecture="arch0",
    )
    assert tasks == []
