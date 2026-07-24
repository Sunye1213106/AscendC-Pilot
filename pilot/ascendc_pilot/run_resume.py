"""Detect interrupted runs and drive continue / reinit human decisions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ascendc_pilot.paths import context_root, runs_root, state_root, uo_root
from ascendc_pilot.state import RUNNING_LIKE, load_state

# OpenCode `question` UI options (label → decision value).
ASK_OPTIONS: list[dict[str, str]] = [
    {
        "label": "继续上次 (Recommended)",
        "description": "保留已有产物，从最近完整正确步骤之后继续执行",
        "value": "continue",
    },
    {
        "label": "删除重开",
        "description": "abort 当前 run，清除 .ascendc-pilot/uo 后重新 init",
        "value": "reinit",
    },
]

_DECISION_ALIASES = {
    "continue": "continue",
    "resume": "continue",
    "reuse": "continue",
    "继续": "continue",
    "继续上次": "continue",
    "reinit": "reinit",
    "reset": "reinit",
    "force-new": "reinit",
    "force_new": "reinit",
    "删除重开": "reinit",
    "重开": "reinit",
}


def normalize_decision(raw: str) -> str | None:
    key = str(raw or "").strip().lower()
    if not key:
        return None
    if key in _DECISION_ALIASES:
        return _DECISION_ALIASES[key]
    for opt in ASK_OPTIONS:
        label = opt["label"].lower()
        if key == label or key.startswith(opt["value"]) or opt["label"].split()[0].lower() in key:
            return opt["value"]
    if "继续" in key or "continue" in key or "reuse" in key:
        return "continue"
    if "删除" in key or "重开" in key or "reinit" in key or "reset" in key:
        return "reinit"
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _artifact_checklist(uo: Path) -> list[dict[str, Any]]:
    """Key UO artifacts: present = likely completed step output."""
    specs = [
        ("prepare_layout", "manifest.yaml", "布局/manifest"),
        ("scope_confirmation", "runs/*/scope/receipt.yaml", "范围确认收据"),
        ("scope_confirmation", "cbm/index_meta.json", "CBM 索引元数据"),
        ("detect_score_pre", "ir/entrypoint_graph.yaml", "入口图"),
        ("detect_score_pre", "ir/score_report_pre.yaml", "抽取前评分"),
        ("detect_score_pre", "ir/llm_tasks.yaml", "LLM 任务清单"),
        ("extract_plan", "ir/extract_plan_candidates.yaml", "抽取计划候选"),
        ("extract_plan", "ir/extract_plan.yaml", "抽取计划（确认后）"),
        ("extract_plan", "ir/host_subgraph.yaml", "Host 分层 IR"),
        ("apply_semantic_patch", "ir/semantic_resolution_ledger.yaml", "语义账本"),
        ("detect_score_post", "ir/score_report_post.yaml", "抽取后评分"),
        ("confidence_report", "summary/confidence_report.yaml", "置信度报告"),
        ("export_integrity", "checks/integrity.yaml", "完整性检查"),
        ("kb_review", "review/kb_product_review.yaml", "KB 审查"),
    ]
    out: list[dict[str, Any]] = []
    for action_id, rel, label in specs:
        if "*" in rel:
            present = any(uo.glob(rel)) if uo.is_dir() else False
        else:
            present = (uo / rel).is_file()
        out.append(
            {
                "action_id": action_id,
                "path": rel,
                "label_zh": label,
                "present": present,
                "complete": present,
            }
        )
    return out


def _receipt_actions(project_root: Path, run_id: str) -> list[str]:
    base = runs_root(project_root) / run_id / "subagents"
    if not base.is_dir():
        return []
    found: list[str] = []
    for path in sorted(base.glob("*.yaml")):
        data = _load_yaml(path)
        aid = str(data.get("action_id") or "").strip()
        if aid and data.get("issued_by") == "pilot":
            checker = data.get("checker_result") or {}
            if checker.get("ok") is False:
                continue
            found.append(aid)
    return found


def _active_action(project_root: Path) -> dict[str, Any]:
    return _load_yaml(state_root(project_root) / "active_action.yaml")


def build_run_resume_summary(project_root: Path, *, workflow_id: str = "uo-init") -> dict[str, Any]:
    """Human-facing summary of the last interrupted run."""
    root = Path(project_root).expanduser().resolve()
    state = load_state(root)
    uo = uo_root(root)
    has_uo = uo.is_dir() and any(uo.iterdir())
    artifacts = _artifact_checklist(uo) if has_uo else []
    complete_arts = [a for a in artifacts if a.get("complete")]
    missing_arts = [a for a in artifacts if not a.get("complete")]

    run_id = str((state or {}).get("run_id") or "")
    receipts = _receipt_actions(root, run_id) if run_id else []
    active = _active_action(root)

    passed_gates = [str(g) for g in ((state or {}).get("passed_gates") or [])]
    failed_gates: list[dict[str, Any]] = []
    for g in (state or {}).get("failed_gates") or []:
        if isinstance(g, dict):
            detail = g.get("detail") if isinstance(g.get("detail"), dict) else {}
            failed_gates.append(
                {
                    "id": g.get("id") or g.get("gate"),
                    "message": detail.get("error_code") or g.get("message") or "",
                    "at": g.get("at"),
                }
            )
        else:
            failed_gates.append({"id": str(g), "message": "", "at": ""})

    phase = str((state or {}).get("phase") or "")
    status = str((state or {}).get("status") or "")
    last_complete = {
        "phase": phase if "scope_receipt" in passed_gates or receipts else "",
        "passed_gates": passed_gates,
        "finalized_actions": receipts,
        "present_artifacts": [a["path"] for a in complete_arts],
    }

    interrupted = {
        "phase": phase,
        "status": status,
        "active_action": {
            "action_id": active.get("action_id"),
            "status": active.get("status"),
            "actor_id": active.get("actor_id"),
        }
        if active
        else None,
        "failed_gates": failed_gates,
        "missing_artifacts": [a["path"] for a in missing_arts[:12]],
    }

    next_hint = ""
    if active.get("status") == "prepared":
        next_hint = str(active.get("action_id") or "")
    if not next_hint:
        for a in missing_arts:
            next_hint = str(a.get("action_id") or "")
            break
    if not next_hint and phase == "extract":
        next_hint = "extract_plan"
    elif not next_hint and phase == "scope":
        next_hint = "scope_confirmation"
    elif not next_hint and phase == "prepare":
        next_hint = "prepare_layout"

    lines = [
        f"run_id: {run_id or '(无)'}",
        f"workflow: {(state or {}).get('workflow_id') or workflow_id}",
        f"phase/status: {phase or '-'} / {status or '-'}",
        f"architecture: {(state or {}).get('architecture') or '-'}",
        f"created_at: {(state or {}).get('created_at') or '-'}",
        f"updated_at: {(state or {}).get('updated_at') or '-'}",
        f"已通过 gates: {', '.join(passed_gates) or '(无)'}",
        f"已 finalize 的 actions: {', '.join(receipts) or '(无)'}",
        f"已有产物: {', '.join(a['label_zh'] for a in complete_arts) or '(无)'}",
        f"中断点: phase={phase or '-'}, active={active.get('action_id') or '-'} ({active.get('status') or '-'})",
    ]
    if failed_gates:
        lines.append(
            "失败 gates: " + ", ".join(f"{g.get('id')}({g.get('message') or ''})" for g in failed_gates)
        )
    lines.append(f"继续时下一步: {next_hint or 'acp next'}")

    has_existing_run = (
        bool(state)
        and str((state or {}).get("workflow_id") or "") == workflow_id
        and str((state or {}).get("status") or "") in RUNNING_LIKE
    )
    if has_existing_run:
        ask_opts = [{"label": o["label"], "description": o["description"]} for o in ASK_OPTIONS]
    else:
        ask_opts = [
            {
                "label": "删除重开",
                "description": "清除残留 .ascendc-pilot/uo 后重新 init（无可继续的活动 run）",
            }
        ]

    return {
        "has_existing_run": has_existing_run,
        "has_uo_artifacts": has_uo,
        "workflow_id": str((state or {}).get("workflow_id") or workflow_id),
        "run_id": run_id,
        "phase": phase,
        "status": status,
        "architecture": str((state or {}).get("architecture") or ""),
        "passed_gates": passed_gates,
        "failed_gates": failed_gates,
        "finalized_actions": receipts,
        "artifacts": artifacts,
        "last_complete": last_complete,
        "interrupted_at": interrupted,
        "resume_next_action": next_hint,
        "summary_text_zh": "\n".join(lines),
        "ask_question": {
            "header": "发现未完成的 uo-init",
            "question": (
                "检测到算子目录已有未完成的 uo-init run。请选择：继续上次，"
                "或删除 .ascendc-pilot/uo 后重新 init。\n\n" + "\n".join(lines)
                if has_existing_run
                else (
                    "检测到残留 UO 产物，但无活动 run。请确认是否删除后重新 init。\n\n"
                    + "\n".join(lines)
                )
            ),
            "options": ask_opts,
        },
        "decision_values": {o["label"]: o["value"] for o in ASK_OPTIONS},
        "commands": {
            "continue": f"acp start {workflow_id} --project . --decision continue",
            "reinit": f"acp start {workflow_id} --project . --decision reinit",
        },
    }


def needs_resume_decision(project_root: Path, workflow_id: str) -> bool:
    root = Path(project_root).expanduser().resolve()
    state = load_state(root)
    if (
        state
        and str(state.get("workflow_id") or "") == workflow_id
        and str(state.get("status") or "") in RUNNING_LIKE
    ):
        return True
    # Leftover UO KB only blocks uo-init (not tg-*/other workflows).
    if workflow_id != "uo-init":
        return False
    uo = uo_root(root)
    if uo.is_dir() and any(uo.iterdir()):
        wid = str((state or {}).get("workflow_id") or "")
        if not state or wid in {"", "uo-init"}:
            return True
    return False


def wipe_uo_for_reinit(project_root: Path) -> dict[str, Any]:
    """Delete UO KB + run sessions; keep HMAC key and memory."""
    root = Path(project_root).expanduser().resolve()
    removed: list[str] = []
    uo = uo_root(root)
    if uo.exists():
        shutil.rmtree(uo, ignore_errors=True)
        removed.append(uo.as_posix())
    runs = runs_root(root)
    if runs.exists():
        shutil.rmtree(runs, ignore_errors=True)
        removed.append(runs.as_posix())
    ctx = context_root(root)
    if ctx.exists():
        shutil.rmtree(ctx, ignore_errors=True)
        removed.append(ctx.as_posix())
    st = state_root(root)
    for name in ("workflow.yaml", "active_action.yaml", "action_lease.yaml", "resume.yaml"):
        path = st / name
        if path.is_file():
            path.unlink()
            removed.append(path.as_posix())
    return {"ok": True, "removed": removed, "kept": ["state/pilot_hmac.key", "memory/"]}


def apply_resume_decision(
    project_root: Path,
    workflow_id: str,
    decision: str,
    *,
    start_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply continue|reinit after AskQuestion."""
    from ascendc_pilot.state import mark_terminal, start_workflow
    from ascendc_pilot.todo import attach_todo

    root = Path(project_root).expanduser().resolve()
    choice = normalize_decision(decision)
    if choice is None:
        return {
            "ok": False,
            "error": "invalid_decision",
            "allowed": ["continue", "reinit"],
            "message_zh": f"无效决策 {decision!r}；请用 AskQuestion 选项 continue|reinit",
        }

    summary = build_run_resume_summary(root, workflow_id=workflow_id)
    kwargs = dict(start_kwargs or {})

    if choice == "continue":
        state = load_state(root)
        if not state or str(state.get("workflow_id") or "") != workflow_id:
            return {
                "ok": False,
                "error": "no_resumable_run",
                "message_zh": "没有可继续的活动 run；请改选删除重开",
                "run_summary": summary,
            }
        if str(state.get("status") or "") not in RUNNING_LIKE:
            return {
                "ok": False,
                "error": "run_not_running",
                "status": state.get("status"),
                "message_zh": f"当前状态为 {state.get('status')}，无法 continue；请选删除重开",
                "run_summary": summary,
            }
        payload = attach_todo(
            {
                **state,
                "resumed": True,
                "decision": "continue",
                "resume_next_action": summary.get("resume_next_action"),
                "run_summary": {
                    "last_complete": summary.get("last_complete"),
                    "interrupted_at": summary.get("interrupted_at"),
                    "summary_text_zh": summary.get("summary_text_zh"),
                },
                "message_zh": (
                    f"已复用 run {state.get('run_id')}；"
                    f"从最近完整状态之后继续（下一步建议：{summary.get('resume_next_action') or 'acp next'}）"
                ),
            },
            root,
            state=state,
        )
        return {"ok": True, **payload}

    state = load_state(root)
    if state and str(state.get("status") or "") in RUNNING_LIKE:
        try:
            from ascendc_pilot.authorize.lease import revoke_active_lease

            revoke_active_lease(root, reason="reinit")
        except Exception:  # noqa: BLE001
            pass
        mark_terminal(root, "failed", reason="reinit_by_operator")

    wipe = wipe_uo_for_reinit(root)
    fresh = start_workflow(root, workflow_id, **kwargs)
    return {
        "ok": True,
        "decision": "reinit",
        "wiped": wipe,
        "fresh_start": True,
        "message_zh": "已删除 UO 产物并重新 init；请从 prepare_layout 开始",
        **fresh,
    }


def existing_run_decision_payload(project_root: Path, workflow_id: str) -> dict[str, Any]:
    summary = build_run_resume_summary(project_root, workflow_id=workflow_id)
    return {
        "ok": False,
        "needs_human_decision": True,
        "error": "EXISTING_RUN_NEEDS_DECISION",
        "message_zh": (
            "检测到未完成的 uo-init run。必须用 OpenCode `question`（AskQuestion）弹出可点选框，"
            "等人选择后执行："
            f"`{summary['commands']['continue']}` 或 `{summary['commands']['reinit']}`。"
            "禁止静默复用或自动删除。"
        ),
        "ask_question": summary["ask_question"],
        "decision_values": summary["decision_values"],
        "commands": summary["commands"],
        "run_summary": summary,
    }
