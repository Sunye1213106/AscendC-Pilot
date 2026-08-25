"""Fail-close: every dispatched prompt/method must render without leftover tokens."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.runtime import (
    _axis_method_path,
    _axis_playbook_text,
    _load_method_and_prompt,
    _rel_repo_path,
    _render_placeholders,
    _repo_root,
    _resolve_capability_method,
    _task_prompt_path,
)
from ascendc_pilot.ownership import (
    format_unresolved_message,
    locate_unresolved_placeholders,
    unresolved_placeholders,
)
from ascendc_pilot.workflows import WORKFLOWS

REPO = Path(__file__).resolve().parents[2]


def _ph_kwargs(**extra: str) -> dict[str, str]:
    kw = {
        "run_id": "RUN_LINT",
        "action_id": "lint",
        "workflow_id": "tg-plan",
        "actor_id": "tg-analyst",
        "project_root": "D:/op",
        "uo_root": "D:/op/.ascendc-pilot/arch35/uo",
        "tg_root_path": "D:/op/.ascendc-pilot/arch35/tg",
        "topic": "lint",
        "op_name": "demo",
        "architecture": "arch35",
        "role_id": "producer",
        "lease_id": "lease",
        "action_session_id": "sess",
        "candidates_sha256": "abc",
        "shard_id": "0",
        "target": "demo",
    }
    kw.update({k: str(v) for k, v in extra.items()})
    return kw


def _iter_lint_targets():
    for wid, wf in WORKFLOWS.items():
        if not isinstance(wf, dict):
            continue
        for action in wf.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            if action.get("task_prompt_id") or action.get("method_ref") or action.get("skill_id"):
                yield wid, aid, action, None
            for axis in action.get("fanout_axes") or []:
                if not isinstance(axis, dict):
                    continue
                if axis.get("task_prompt_id") or axis.get("method_ref"):
                    yield wid, f"{aid}/{axis.get('id')}", action, axis


def test_locate_unresolved_reports_file_and_line() -> None:
    text = "ok\nuse replay.<TILING_FIELD> then probe\n"
    rows = locate_unresolved_placeholders(
        text, source="method", file="skills/test-plan/references/coverage-planning.md"
    )
    assert rows
    assert rows[0]["token"] == "<TILING_FIELD>"
    assert rows[0]["line"] == 2
    assert rows[0]["file"].endswith("coverage-planning.md")
    msg = format_unresolved_message(rows)
    assert "coverage-planning.md:2" in msg
    assert "<TILING_FIELD>" in msg


def test_render_leftover_upper_angle_becomes_unresolved() -> None:
    out = _render_placeholders(
        "replay.<TILING_FIELD>",
        **_ph_kwargs(),
    )
    assert "[UNRESOLVED:TILING_FIELD]" in out
    assert unresolved_placeholders(out)


def test_every_workflow_prompt_and_method_renders_clean() -> None:
    repo = _repo_root(REPO)
    failures: list[str] = []
    checked = 0
    for wid, label, action, axis in _iter_lint_targets():
        if axis is None:
            method, prompt = _load_method_and_prompt(repo, action)
            tpid = str(action.get("task_prompt_id") or "")
            prompt_file = _rel_repo_path(repo, _task_prompt_path(repo, tpid)) if tpid else ""
            mp = _resolve_capability_method(repo, action)
            method_file = _rel_repo_path(repo, mp) if mp is not None else ""
        else:
            tpid = str(axis.get("task_prompt_id") or "")
            prompt = ""
            prompt_file = ""
            if tpid:
                pp = _task_prompt_path(repo, tpid)
                prompt_file = _rel_repo_path(repo, pp)
                if pp.is_file():
                    prompt = pp.read_text(encoding="utf-8")
            method = _axis_playbook_text(repo, axis)
            method_file = _rel_repo_path(repo, _axis_method_path(repo, axis))
        if not prompt and not method:
            continue
        rendered_prompt = _render_placeholders(prompt, **_ph_kwargs(workflow_id=wid, action_id=label))
        rendered_method = _render_placeholders(method, **_ph_kwargs(workflow_id=wid, action_id=label))
        rows = locate_unresolved_placeholders(
            rendered_prompt, source="prompt", file=prompt_file
        ) + locate_unresolved_placeholders(rendered_method, source="method", file=method_file)
        checked += 1
        if rows:
            failures.append(f"action={label} {format_unresolved_message(rows)}")
    assert checked > 0
    assert not failures, "\n".join(failures)
