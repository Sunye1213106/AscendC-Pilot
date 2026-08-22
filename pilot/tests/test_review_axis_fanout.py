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
    from ascendc_pilot.workflows.specs import WORKFLOWS

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
    action = next(a for a in WORKFLOWS["ce-review"]["actions"] if a["id"] == "code_review")
    assert action.get("execution_variant") == "review_axis_fanout"
    tasks = _review_axis_fanout_tasks(
        action=action,
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
    assert "Spec 结论" in spec["task_prompt_stub"]
    assert "AXIS=standards" in std["task_prompt_stub"]
    assert "Standards 结论" in std["task_prompt_stub"]
    assert (sdir / "method_spec.md").is_file()
    assert (sdir / "method_standards.md").is_file()
    spec_method = (sdir / "method_spec.md").read_text(encoding="utf-8")
    std_method = (sdir / "method_standards.md").read_text(encoding="utf-8")
    assert "只做 **Spec** 这一路" in spec_method
    assert "推断" in spec_method and "完成度" in spec_method
    assert "只陈述变更理解" not in spec_method or "禁止只陈述" in spec_method
    assert "只做 **Standards** 这一路" in std_method
    assert "index.md" in spec_method or "plan.md" in spec_method
    assert not (tmp_path / ".ascendc-pilot" / "arch0" / "ce" / "review" / "index.yaml").is_file()


def test_review_axis_fanout_skips_scope_phase(tmp_path: Path) -> None:
    import sys

    if str(REPO / "pilot") not in sys.path:
        sys.path.insert(0, str(REPO / "pilot"))
    from ascendc_pilot.actions.runtime import _review_axis_fanout_tasks
    from ascendc_pilot.workflows.specs import WORKFLOWS

    sdir = tmp_path / "session"
    sdir.mkdir()
    action = next(a for a in WORKFLOWS["ce-review"]["actions"] if a["id"] == "code_review")
    tasks = _review_axis_fanout_tasks(
        action=action,
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


def test_bind_init_fanout_writes_isolated_yaml_stubs(tmp_path: Path) -> None:
    import sys

    if str(REPO / "pilot") not in sys.path:
        sys.path.insert(0, str(REPO / "pilot"))
    from ascendc_pilot.actions.runtime import _review_axis_fanout_tasks
    from ascendc_pilot.workflows.specs import WORKFLOWS

    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "prompt.md").write_text("# p\n", encoding="utf-8")
    (sdir / "bundle.yaml").write_text("ok: true\n", encoding="utf-8")
    stub_kwargs = {
        "actor_id": "tg-analyst",
        "action_id": "bind_init",
        "run_id": "r1",
        "session_dir": sdir.as_posix(),
        "prompt_path": (sdir / "prompt.md").as_posix(),
        "method_path": (sdir / "method.md").as_posix(),
        "bundle_path": (sdir / "bundle.yaml").as_posix(),
        "project_root": tmp_path.as_posix(),
        "architecture": "arch0",
        "write_paths": ["runs/{run_id}/actions/bind_init/parts/**"],
        "user_question": "bind",
    }
    action = next(a for a in WORKFLOWS["tg-init"]["actions"] if a["id"] == "bind_init")
    assert action.get("execution_variant") == "review_axis_fanout"
    tasks = _review_axis_fanout_tasks(
        action=action,
        action_id="bind_init",
        actor_id="tg-analyst",
        phase="bind",
        sdir=sdir,
        stub_kwargs=stub_kwargs,
        repo=REPO,
        dispatch_targets={},
        write_paths=["runs/{run_id}/actions/bind_init/parts/**"],
        project_root=tmp_path.as_posix(),
        architecture="arch0",
    )
    assert len(tasks) == 2
    ids = {t["slice_id"] for t in tasks}
    assert ids == {"harness", "bind"}
    harness = next(t for t in tasks if t["slice_id"] == "harness")
    bind = next(t for t in tasks if t["slice_id"] == "bind")
    assert "AXIS=harness" in harness["task_prompt_stub"]
    assert "harness.yaml" in harness["task_prompt_stub"]
    assert "AXIS=bind" in bind["task_prompt_stub"]
    assert "bind.yaml" in bind["task_prompt_stub"]
    assert "parts/bind.yaml" in bind["task_prompt_stub"]
    assert (sdir / "method_harness.md").is_file()
    assert (sdir / "method_bind.md").is_file()
    assert (sdir / "prompt_harness.md").is_file()
    assert (sdir / "prompt_bind.md").is_file()
    assert "golden" in (sdir / "method_harness.md").read_text(encoding="utf-8")
    assert "domains" in (sdir / "method_bind.md").read_text(encoding="utf-8")
    harness_method = (sdir / "method_harness.md").read_text(encoding="utf-8")
    bind_method = (sdir / "method_bind.md").read_text(encoding="utf-8")
    assert "refs/harness/harness-edge-cases.md" in harness_method
    assert "refs/bind/column-binding-edge-cases.md" in bind_method
    assert "refs/harness/test-script-repo.md" in harness_method
    assert "refs/bind/test-script-repo.md" in bind_method
    assert "column-binding-edge-cases" not in harness_method
    assert "harness-edge-cases" not in bind_method
    assert "construction-gotchas" not in harness_method
    assert "construction-gotchas" not in bind_method
    assert (sdir / "refs" / "harness" / "harness-edge-cases.md").is_file()
    assert (sdir / "refs" / "bind" / "column-binding-edge-cases.md").is_file()
    assert (sdir / "refs" / "harness" / "test-script-repo.md").is_file()
    assert (sdir / "refs" / "bind" / "test-script-repo.md").is_file()
    assert not (sdir / "refs" / "harness" / "column-binding-edge-cases.md").exists()
    assert not (sdir / "refs" / "bind" / "harness-edge-cases.md").exists()


def test_bind_init_fanout_skips_existing_part(tmp_path: Path) -> None:
    import sys

    if str(REPO / "pilot") not in sys.path:
        sys.path.insert(0, str(REPO / "pilot"))
    from ascendc_pilot.actions.runtime import _review_axis_fanout_tasks
    from ascendc_pilot.workflows.specs import WORKFLOWS

    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "prompt.md").write_text("# p\n", encoding="utf-8")
    (sdir / "bundle.yaml").write_text("ok: true\n", encoding="utf-8")
    (sdir / "parts").mkdir()
    (sdir / "parts" / "bind.yaml").write_text("columns: []\n", encoding="utf-8")
    stub_kwargs = {
        "actor_id": "tg-analyst",
        "action_id": "bind_init",
        "run_id": "r1",
        "session_dir": sdir.as_posix(),
        "prompt_path": (sdir / "prompt.md").as_posix(),
        "method_path": (sdir / "method.md").as_posix(),
        "bundle_path": (sdir / "bundle.yaml").as_posix(),
        "project_root": tmp_path.as_posix(),
        "architecture": "arch0",
        "write_paths": ["runs/{run_id}/actions/bind_init/parts/**"],
        "user_question": "bind",
    }
    action = next(a for a in WORKFLOWS["tg-init"]["actions"] if a["id"] == "bind_init")
    tasks = _review_axis_fanout_tasks(
        action=action,
        action_id="bind_init",
        actor_id="tg-analyst",
        phase="bind",
        sdir=sdir,
        stub_kwargs=stub_kwargs,
        repo=REPO,
        dispatch_targets={},
        write_paths=["runs/{run_id}/actions/bind_init/parts/**"],
        project_root=tmp_path.as_posix(),
        architecture="arch0",
    )
    assert {t["slice_id"] for t in tasks} == {"harness"}
