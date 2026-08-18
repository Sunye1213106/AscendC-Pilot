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
        import git_workspace_legacy as legacy_ws  # type: ignore[import-not-found]

        cache = (legacy_ws.cache_root() / "workspaces").resolve()
        root.resolve().relative_to(cache)
        return True
    except Exception:  # noqa: BLE001
        return False


def _resolve_operator_from_pr_workspace(
    root: Path, intent: str, workflow_id: str
) -> dict[str, Any] | None:
    """Materialize exact PR head and resolve a structural operator candidate."""
    url = extract_pr_url_from_intent(intent)
    if not url:
        return None
    try:
        acquire = _workspace_engine().acquire_pull_request(url, workspace_root=None)
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
    roots = [Path(p) for p in (acquire.get("operator_roots") or []) if str(p).strip()]
    common = {
        "pr_url": url,
        "worktree_head": str(acquire.get("worktree_head") or ""),
        "workspace_mode": "isolated_pr",
        "source_revision": str(acquire.get("head_sha") or ""),
        "changed_files": list(acquire.get("changed_files") or []),
        "changed_architectures": list(acquire.get("changed_architectures") or []),
        "changeset": dict(acquire.get("changeset") or {}),
    }
    if len(roots) == 1:
        return {"ok": True, "project": str(roots[0]), **common}
    if not roots:
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "project",
            "reason_code": "OPERATOR_ROOTS_EMPTY",
            "workflow_id": workflow_id,
            "project": str(root),
            **common,
            "message_zh": (
                "PR changed-files 无法结构化归属到含 op_host/ 或 op_kernel/ 的算子目录。"
                "请明确本次要分析的算子 workspace。"
            ),
            "ask_question": {
                "prompt_zh": "请提供要分析的算子目录（含 op_host/ 或 op_kernel/）",
                "options": [],
                "allow_free_text": True,
                "field": "project",
            },
        }
    return {
        "ok": False,
        "needs_human_decision": True,
        "decision_kind": "project",
        "reason_code": "MULTI_OPERATOR",
        "workflow_id": workflow_id,
        "project": str(root),
        **common,
        "operator_roots": [str(p) for p in roots],
        "message_zh": "这次 PR 改动跨多个算子目录，请选择本次分析的算子。",
        "ask_question": {
            "prompt_zh": "请选择要分析的算子 workspace",
            "options": [
                {"label": p.name, "value": str(p), "description": str(p)} for p in roots
            ],
            "allow_free_text": False,
            "field": "project",
        },
    }


def _mark_workspace_step(root_before: Path, root_after: Path) -> None:
    """Best-effort close the non-workflow workspace utility step if a plan exists."""
    try:
        from ascendc_pilot.planning.task_plan import load_task_plan, mark_step_passed, write_task_plan

        for candidate in (root_before, root_after):
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

    if pr_url and wf in _legacy._workflows_need_operator() and not _is_isolated_pr_path(root):
        resolved = _resolve_operator_from_pr_workspace(root, intent_text, wf)
        if resolved is not None:
            if not resolved.get("ok"):
                return _legacy._attach_intake_request(resolved, original_root)
            root = Path(str(resolved["project"])).expanduser().resolve()
            pr_context = dict(resolved)
            changed_arches = [str(a) for a in (resolved.get("changed_architectures") or []) if str(a)]
            if not arch and len(changed_arches) == 1:
                arch = changed_arches[0]
            elif not arch and len(changed_arches) > 1 and wf in _legacy._workflows_need_arch():
                payload = {
                    "ok": False,
                    "needs_human_decision": True,
                    "decision_kind": "architecture",
                    "reason_code": "MULTI_PR_ARCHITECTURE",
                    "workflow_id": wf,
                    "project": str(root),
                    "pr_url": pr_url,
                    "architecture_options": changed_arches,
                    "message_zh": "PR changed-files 同时涉及多个 architecture，请选择本次 UO target。",
                    "ask_question": {
                        "prompt_zh": "请选择本次分析的 architecture",
                        "options": [{"label": a, "value": a} for a in changed_arches],
                        "allow_free_text": False,
                        "field": "architecture",
                    },
                }
                return _legacy._attach_intake_request(payload, root)
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
