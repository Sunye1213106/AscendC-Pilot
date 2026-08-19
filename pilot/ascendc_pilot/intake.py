# -*- coding: utf-8 -*-
"""Compatibility intake surface with PR-first isolated source handling.

The original intake implementation remains the authority for local workspace,
architecture and UO gates. This wrapper only intercepts explicit PR URLs before
those gates so a stale local fork can never become the PR source by accident.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import intake_legacy as _legacy

# Re-export the complete legacy surface, including private helpers used by tests
# and internal callers. Overrides below intentionally replace only PR handling.
for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)


def _workspace_engine():
    root = Path(__file__).resolve().parents[2]
    ws = root / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import pr_workspace as gw  # type: ignore[import-not-found]

    return gw


def extract_pr_url_from_intent(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        return str(_workspace_engine().extract_pr_url(raw) or "")
    except Exception:  # noqa: BLE001
        return ""


def _is_isolated_pr_path(root: Path) -> bool:
    try:
        return bool(_workspace_engine().is_isolated_pr_tree(root))
    except Exception:  # noqa: BLE001
        return False


def _resolve_operator_from_pr_workspace(
    root: Path, intent: str, workflow_id: str
) -> dict[str, Any] | None:
    """Materialize exact PR head under the Host open directory and pin (op, arch) pairs."""
    url = extract_pr_url_from_intent(intent)
    if not url:
        return None
    if _legacy._pilot_workspace_forbidden(root):
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "project",
            "reason_code": "PILOT_CHECKOUT_FORBIDDEN",
            "workflow_id": workflow_id,
            "project": str(root),
            "pr_url": url,
            "message_zh": (
                "当前 OpenCode 工作区是 AscendC-Pilot 仓，禁止把算子源码 clone 进来。"
                "请打开算子目录、算子仓根目录，或空目录后再贴 PR。"
            ),
            "ask_question": {
                "prompt_zh": "请换到算子目录、算子仓或空工作区",
                "options": list(_legacy.PROJECT_SWITCH_OPTIONS),
                "allow_free_text": True,
                "field": "project",
            },
        }
    gw = _workspace_engine()
    try:
        acquire = gw.acquire_pull_request(url, workspace_root=root)
    except Exception as exc:  # noqa: BLE001
        acquire = {
            "ok": False,
            "error": "WORKSPACE_ACQUIRE_FAILED",
            "message_zh": str(exc)[:400],
        }
    if not acquire.get("ok"):
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "project",
            "reason_code": str(acquire.get("error") or "WORKSPACE_ACQUIRE_FAILED"),
            "workflow_id": workflow_id,
            "project": str(root),
            "pr_url": url,
            "message_zh": str(
                acquire.get("message_zh")
                or "无法获取 PR exact head。请检查 GitHub/GitCode 鉴权，或改用本地算子目录。"
            ),
            "ask_question": {
                "prompt_zh": "获取 PR 失败。请重试，或改用本地算子目录。",
                "options": [{"label": "改用本地算子目录", "value": "local"}],
                "allow_free_text": True,
                "field": "project",
            },
        }
    resolved = gw.resolve_targets_or_ask(acquire, workflow_id=workflow_id, host_root=root)
    resolved["pr_url"] = url
    return resolved


_GOAL_INTAKE_IDS = frozenset({"auto", "goal-intake"})


def _should_materialize_pr_before_start(wf: str, root: Path, pr_url: str) -> bool:
    """Clone+pin before start so `.ascendc-pilot` never lands on an empty Host cwd."""
    if not pr_url or _is_isolated_pr_path(root):
        return False
    if wf in _legacy._workflows_need_operator():
        return True
    return wf in _GOAL_INTAKE_IDS and not _legacy.looks_like_operator_package(root)


def _operator_workdir_required(wf: str, root: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "needs_human_decision": True,
        "decision_kind": "project",
        "reason_code": "OPERATOR_WORKDIR_REQUIRED",
        "workflow_id": wf,
        "project": str(root),
        "message_zh": (
            "还没有算子工作目录，不能在空打开目录落下 .ascendc-pilot。"
            "请贴 PR URL（系统会 clone 并 pin 到含 op_host/ 或 op_kernel/ 的算子目录），"
            "或把 --project 指到已有算子包。"
        ),
        "ask_question": {
            "prompt_zh": "请打开算子目录，或贴 PR 链接后再启动",
            "options": list(_legacy.PROJECT_SWITCH_OPTIONS),
            "allow_free_text": True,
            "field": "project",
        },
    }


def _mark_workspace_step(root_before: Path, root_after: Path) -> None:
    """Best-effort close the non-workflow workspace utility step if a plan exists."""
    try:
        from ascendc_pilot.planning.task_plan import load_task_plan, mark_step_passed, write_task_plan

        for candidate in (root_before, root_after):
            if not _legacy.looks_like_operator_package(candidate):
                continue
            plan = load_task_plan(candidate)
            if not plan:
                continue
            if any(str(s.get("id") or "") == "workspace_acquire" for s in (plan.get("steps") or []) if isinstance(s, dict)):
                write_task_plan(candidate, mark_step_passed(plan, "workspace_acquire"))
                return
    except Exception:  # noqa: BLE001
        pass


def prepare_workflow_start(
    *,
    project: Path | str,
    workflow_id: str,
    architecture: str = "",
    project_explicit: bool = False,
    intent: str = "",
) -> dict[str, Any]:
    """Run legacy intake, intercepting explicit PR source before local gates."""
    wf = str(workflow_id or "").strip()
    original_root = Path(project).expanduser().resolve()
    root = original_root
    arch = str(architecture or "").strip()
    intent_text = str(intent or "").strip()
    pr_url = extract_pr_url_from_intent(intent_text)
    pr_context: dict[str, Any] = {}

    if pr_url and _legacy._pilot_workspace_forbidden(root):
        return _legacy._attach_intake_request(
            {
                "ok": False,
                "needs_human_decision": True,
                "decision_kind": "project",
                "reason_code": "PILOT_CHECKOUT_FORBIDDEN",
                "workflow_id": wf,
                "project": str(root),
                "pr_url": pr_url,
                "message_zh": (
                    "当前 OpenCode 工作区是 AscendC-Pilot 仓，禁止把算子源码 clone 进来。"
                    "请打开算子目录、算子仓根目录，或空目录后再贴 PR。"
                ),
                "ask_question": {
                    "prompt_zh": "请换到算子目录、算子仓或空工作区",
                    "options": list(_legacy.PROJECT_SWITCH_OPTIONS),
                    "allow_free_text": True,
                    "field": "project",
                },
            },
            original_root,
        )

    if _should_materialize_pr_before_start(wf, root, pr_url):
        resolved = _resolve_operator_from_pr_workspace(root, intent_text, wf)
        if resolved is not None:
            if not resolved.get("ok"):
                return _legacy._attach_intake_request(resolved, original_root)
            root = Path(str(resolved["project"])).expanduser().resolve()
            pr_context = dict(resolved)
            resolved_arch = str(resolved.get("architecture") or "").strip()
            # goal-intake occupancy stays under goal/; arch* is pinned for later uo-init.
            if wf not in _GOAL_INTAKE_IDS and not arch:
                arch = resolved_arch
            pin_arches = list(resolved.get("changed_architectures") or [])
            if not pin_arches and (arch or resolved_arch):
                pin_arches = [arch or resolved_arch]
            try:
                from ascendc_pilot.run_resume import save_pr_architecture_pin

                save_pr_architecture_pin(root, pin_arches)
            except Exception:  # noqa: BLE001
                pass
            _mark_workspace_step(original_root, root)
            # PR has already been materialized. Do not let legacy intake inspect
            # the original Host cwd or acquire the PR a second time.
            intent_text = ""
            project_explicit = True

    result = _legacy.prepare_workflow_start(
        project=root,
        workflow_id=wf,
        architecture=arch,
        project_explicit=project_explicit,
        intent=intent_text,
    )
    if result.get("ok") and wf in _GOAL_INTAKE_IDS:
        landed = Path(str(result.get("project") or root)).expanduser().resolve()
        if not _legacy.looks_like_operator_package(landed):
            return _legacy._attach_intake_request(
                _operator_workdir_required(wf, landed),
                original_root,
            )
    if result.get("ok") and pr_context:
        result = dict(result)
        for key in (
            "pr_url",
            "worktree_head",
            "workspace_mode",
            "source_revision",
            "changed_files",
            "changed_architectures",
            "changeset",
            "operator_targets",
            "operator_roots",
        ):
            if key in pr_context:
                result[key] = pr_context[key]
    return result


def start_intake_gate(
    *,
    project: Path | str,
    workflow_id: str,
    architecture: str = "",
    project_explicit: bool = False,
    intent: str = "",
) -> dict[str, Any] | None:
    result = prepare_workflow_start(
        project=project,
        workflow_id=workflow_id,
        architecture=architecture,
        project_explicit=project_explicit,
        intent=intent,
    )
    if result.get("ok"):
        return None
    return result
