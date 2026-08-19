"""Host dispatch tickets: bind prepare → subagent return → finalize without LLM choreography."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def _ticket_dir(project_root: Path, *, run_id: str = "") -> Path:
    from ascendc_pilot.authorize.lease import run_control_dir
    from ascendc_pilot.paths import agent_root

    rid = str(run_id or "").strip()
    if rid:
        try:
            d = run_control_dir(project_root, run_id=rid) / "dispatch_tickets"
            d.mkdir(parents=True, exist_ok=True)
            return d
        except ValueError:
            pass
    d = agent_root(project_root) / "state" / "dispatch_tickets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_ticket(project_root: Path, doc: dict[str, Any]) -> None:
    path = _ticket_dir(project_root, run_id=str(doc.get("run_id") or "")) / f"{doc['ticket_id']}.yaml"
    if yaml is not None:
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def issue_dispatch_ticket(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    actor_id: str,
    lease_id: str = "",
    session_dir: str = "",
    task_prompt_stub: str = "",
    session_id: str = "",
    workflow_id: str = "",
    prepare_nonce: str = "",
    uo_digest: str = "",
    source_revision: str = "",
) -> dict[str, Any]:
    """Create a one-shot ticket for Host Session Driver (status=open)."""
    from ascendc_pilot.occupancy import current_session_id, current_workflow_id, live_digest_for

    raw = f"{run_id}:{action_id}:{actor_id}:{time.time_ns()}"
    ticket_id = "dxt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    sid = str(session_id or current_session_id() or "").strip()
    wid = str(workflow_id or current_workflow_id() or "").strip()
    digest = str(uo_digest or "").strip()
    if not digest:
        try:
            digest = live_digest_for(project_root) or ""
        except Exception:  # noqa: BLE001
            digest = ""
    revision = str(source_revision or "").strip()
    if not revision:
        try:
            from testcase_agent.closure.ledger import baseline_fingerprint

            revision = str((baseline_fingerprint(project_root) or {}).get("source_revision") or "")
        except Exception:  # noqa: BLE001
            revision = ""
    doc = {
        "ticket_id": ticket_id,
        "run_id": run_id,
        "action_id": action_id,
        "actor_id": actor_id,
        "lease_id": lease_id,
        "session_dir": session_dir,
        "session_id": sid,
        "workflow_id": wid,
        "prepare_nonce": prepare_nonce,
        "uo_digest": digest,
        "source_revision": revision,
        "status": "open",
        "created_at": time.time(),
        "task_prompt_stub_sha256": hashlib.sha256(
            (task_prompt_stub or "").encode("utf-8")
        ).hexdigest()
        if task_prompt_stub
        else "",
    }
    _write_ticket(project_root, doc)
    return doc


def load_dispatch_ticket(project_root: Path, ticket_id: str) -> dict[str, Any]:
    tid = (ticket_id or "").strip()
    if not tid:
        return {}
    from ascendc_pilot.paths import runs_root

    candidates = [
        _ticket_dir(project_root) / f"{tid}.yaml",
    ]
    try:
        from ascendc_pilot.state import load_state

        rid = str((load_state(project_root) or {}).get("run_id") or "")
        if rid:
            candidates.insert(0, _ticket_dir(project_root, run_id=rid) / f"{tid}.yaml")
    except Exception:  # noqa: BLE001
        pass
    try:
        root = runs_root(project_root)
        if root.is_dir():
            for control in root.glob("*/control/dispatch_tickets"):
                candidates.append(control / f"{tid}.yaml")
    except Exception:  # noqa: BLE001
        pass
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            if yaml is not None:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception:  # noqa: BLE001
            continue
    return {}


def claim_dispatch_ticket(project_root: Path, ticket_id: str) -> dict[str, Any]:
    """open | retryable_failed → processing. Finalize must succeed before consume."""
    doc = load_dispatch_ticket(project_root, ticket_id)
    if not doc:
        return {"ok": False, "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
    status = str(doc.get("status") or "")
    if status not in {"open", "retryable_failed"}:
        return {
            "ok": False,
            "error": "TICKET_NOT_CLAIMABLE",
            "ticket_id": ticket_id,
            "status": status,
        }
    doc["status"] = "processing"
    doc["claimed_at"] = time.time()
    doc.pop("retryable_error", None)
    _write_ticket(project_root, doc)
    return {"ok": True, "ticket": doc}


def mark_dispatch_ticket_consumed(project_root: Path, ticket_id: str) -> dict[str, Any]:
    """processing → consumed (only after finalize success)."""
    doc = load_dispatch_ticket(project_root, ticket_id)
    if not doc:
        return {"ok": False, "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
    if str(doc.get("status") or "") != "processing":
        return {
            "ok": False,
            "error": "TICKET_NOT_PROCESSING",
            "ticket_id": ticket_id,
            "status": doc.get("status"),
        }
    doc["status"] = "consumed"
    doc["consumed_at"] = time.time()
    _write_ticket(project_root, doc)
    return {"ok": True, "ticket": doc}


def release_dispatch_ticket(
    project_root: Path,
    ticket_id: str,
    *,
    error: str = "",
) -> dict[str, Any]:
    """processing → retryable_failed → open so Host can resubmit return payload."""
    doc = load_dispatch_ticket(project_root, ticket_id)
    if not doc:
        return {"ok": False, "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
    if str(doc.get("status") or "") != "processing":
        return {
            "ok": False,
            "error": "TICKET_NOT_PROCESSING",
            "ticket_id": ticket_id,
            "status": doc.get("status"),
        }
    doc["status"] = "retryable_failed"
    doc["retryable_error"] = (error or "")[:400]
    doc["failed_at"] = time.time()
    _write_ticket(project_root, doc)
    # Immediately re-open for retry (one-shot claim, multi-attempt finalize).
    doc["status"] = "open"
    doc["reopened_at"] = time.time()
    _write_ticket(project_root, doc)
    return {"ok": True, "ticket": doc, "retryable": True}


def consume_dispatch_ticket(project_root: Path, ticket_id: str) -> dict[str, Any]:
    """Backward-compatible alias: claim (does not finalize-consume).

    Prefer ``claim_dispatch_ticket`` + ``mark_dispatch_ticket_consumed``.
    """
    return claim_dispatch_ticket(project_root, ticket_id)


def _compact_dispatch_tasks(raw: Any) -> list[dict[str, str]]:
    """Keep 2+ focused Task stubs for Cursor-style fan-out."""
    if not isinstance(raw, list) or len(raw) < 2:
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        stub = str(row.get("task_prompt_stub") or "").strip()
        if not stub:
            continue
        out.append(
            {
                "slice_id": str(row.get("slice_id") or ""),
                "focus": str(row.get("focus") or ""),
                "first_mode": str(row.get("first_mode") or ""),
                "actor_id": str(row.get("actor_id") or ""),
                "action_id": str(row.get("action_id") or ""),
                "task_prompt_stub": stub,
            }
        )
    return out if len(out) >= 2 else []


def _fanout_dispatch_message_zh(actor_id: str, tasks: list[dict[str, str]]) -> str:
    ids = ", ".join(t["slice_id"] for t in tasks if t.get("slice_id"))
    n = len(tasks)
    return (
        f"请在同一轮并行派发 {n} 个 OpenCode 原生 Task（agent={actor_id}）。"
        "每个 prompt 必须原样为 host_step.tasks[i].task_prompt_stub。"
        "不要用父 task_prompt_stub 再开一个。"
        "全部返回后按各 Task 原生全文综合再 finalize（一张 ticket）；"
        "禁止只转述某一个，禁止发明子代理没引用的事实。"
        + (f" 切片：{ids}。" if ids else "")
    )


def build_host_step(
    *,
    kind: str,
    project_root: Path | str = "",
    action_id: str = "",
    actor_id: str = "",
    ticket: dict[str, Any] | None = None,
    prepare: dict[str, Any] | None = None,
    ask_question: dict[str, Any] | None = None,
    message_zh: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured Host Session Driver step."""
    prep = prepare or {}
    step: dict[str, Any] = {
        # dispatch_subagent | ask_human | done | failed | continue_goal
        "kind": kind,
        "action_id": action_id or str(prep.get("action_id") or ""),
        "actor_id": actor_id or str(prep.get("actor_id") or ""),
        "cwd": str(project_root or ""),
        "message_zh": message_zh,
    }
    if ticket:
        step["dispatch_ticket"] = str(ticket.get("ticket_id") or "")
        step["ticket"] = ticket
    if prep:
        step["task_prompt_stub"] = prep.get("task_prompt_stub") or ""
        step["session_dir"] = prep.get("session_dir") or ""
        step["lease_id"] = prep.get("lease_id") or ""
        step["run_id"] = prep.get("run_id") or ""
        step["finalize_hint"] = prep.get("finalize_hint") or ""
        tasks = _compact_dispatch_tasks(prep.get("dispatch_tasks"))
        if tasks:
            step["tasks"] = tasks
    if ask_question:
        step["ask_question"] = ask_question
    if extra:
        step.update(extra)
    return step


def dispatch_result(
    project_root: Path,
    *,
    ticket_id: str,
    action_result: dict[str, Any] | None = None,
    result_file: Path | str | None = None,
    result_text: str = "",
) -> dict[str, Any]:
    """Claim ticket → finalize action → consume on success (else reopen) → drive."""
    from ascendc_pilot.actions import run_action
    from ascendc_pilot.actions.drive import drive_until_interaction
    from ascendc_pilot.actions.runtime import prepare_action

    claimed = claim_dispatch_ticket(project_root, ticket_id)
    if not claimed.get("ok"):
        return {**claimed, "ok": False}
    ticket = claimed.get("ticket") or {}
    action_id = str(ticket.get("action_id") or "").strip()
    if not action_id:
        release_dispatch_ticket(project_root, ticket_id, error="TICKET_MISSING_ACTION")
        return {"ok": False, "error": "TICKET_MISSING_ACTION"}

    payload = action_result
    if payload is None and result_text.strip():
        text = result_text.strip()
        if "```" in text:
            import re

            m = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.S | re.I)
            if m:
                text = m.group(1).strip()
        try:
            if yaml is not None:
                parsed = yaml.safe_load(text)
                if isinstance(parsed, dict):
                    payload = parsed
        except Exception:  # noqa: BLE001
            payload = None

    fin = run_action(
        project_root,
        action_id,
        finalize=True,
        result_file=Path(result_file) if result_file else None,
        action_result=payload,
    )
    if not fin.get("ok"):
        release_dispatch_ticket(
            project_root,
            ticket_id,
            error=str(fin.get("error") or fin.get("message_zh") or "finalize failed"),
        )
        return {
            "ok": False,
            "stop_reason": "finalize_failed",
            "finalize": fin,
            "ticket_retryable": True,
            "dispatch_ticket": ticket_id,
            "host_step": build_host_step(
                kind="failed",
                project_root=project_root,
                action_id=action_id,
                message_zh=str(fin.get("message_zh") or fin.get("error") or "finalize failed"),
                extra={"ticket_retryable": True, "dispatch_ticket": ticket_id},
            ),
        }

    mark_dispatch_ticket_consumed(project_root, ticket_id)

    driven = drive_until_interaction(project_root, prepare=prepare_action)
    driven = attach_host_step(project_root, driven)
    return {
        "ok": bool(driven.get("ok")),
        "finalize": fin,
        "drive": driven,
        "host_step": driven.get("host_step"),
        "todo": driven.get("todo"),
    }


def _posix_abs(path: Path) -> str:
    return Path(path).expanduser().resolve().as_posix()


def _done_read_hint(project_root: Path, complete: dict[str, Any]) -> dict[str, Any]:
    """Point Primary at verify/query artifacts. Do not synthesize a summary here."""
    st = complete.get("state") if isinstance(complete.get("state"), dict) else {}
    if not st:
        try:
            from ascendc_pilot.state import load_state

            st = load_state(project_root) or {}
        except Exception:  # noqa: BLE001
            st = {}
    wid = str(st.get("workflow_id") or complete.get("workflow_id") or "")
    arch = str(st.get("architecture") or "").strip() or None
    run_id = str(st.get("run_id") or "").strip()
    hint: dict[str, Any] = {"workflow_id": wid}
    try:
        if wid in {"uo-init", "uo-update"}:
            hint["message_zh"] = (
                "建库已完成。用 `pilot_cli` `uo-query --status-only` 查看产物是否就绪"
                "（节点/关系/未闭合）。禁止打开 .uo 二进制，禁止仅回复「完成」。"
                "有未完成 Goal 时跟随 `next_workflow_id`，不要把建库结束当成整个目标完成。"
            )
        elif wid == "uo-query" and run_id:
            hint["message_zh"] = (
                "查询完成。请将本次子代理返回的答案正文向用户陈述。"
                "禁止再 Glob/Read yaml。"
            )
    except Exception:  # noqa: BLE001
        pass
    return hint


def attach_host_step(project_root: Path, drive_payload: dict[str, Any]) -> dict[str, Any]:
    """Augment drive_until_interaction output with structured host_step + ticket."""
    out = dict(drive_payload or {})
    stop = str(out.get("stop_reason") or "")
    status = str(out.get("status") or "")

    if stop == "workflow_complete" or status == "passed":
        complete = out.get("complete") if isinstance(out.get("complete"), dict) else {}
        next_wf = str(
            complete.get("user_goal_next_workflow_id")
            or out.get("user_goal_next_workflow_id")
            or ""
        ).strip()
        acceptance_failed = bool(
            complete.get("user_goal_acceptance_failed")
            or out.get("user_goal_acceptance_failed")
        )
        if acceptance_failed and not next_wf:
            fail_zh = str(
                complete.get("user_goal_next_summary_zh")
                or complete.get("message_zh")
                or out.get("message_zh")
                or "目标尚未完成：缺少回放验证收据，或测试义务未闭合。"
            )
            out["host_step"] = build_host_step(
                kind="failed",
                project_root=project_root,
                message_zh=fail_zh,
                extra={
                    "status": "failed",
                    "reason_code": "GOAL_ACCEPTANCE_FAILED",
                    "acceptance_failed": True,
                },
            )
            out["message_zh"] = fail_zh
            return out
        if next_wf:
            arch = ""
            intent = ""
            project_from_goal = ""
            try:
                from ascendc_pilot.public_progress import message_zh_for_host
                from ascendc_pilot.user_goal import load_user_goal

                complete_st = (
                    complete.get("state") if isinstance(complete.get("state"), dict) else {}
                )
                arch = str(complete_st.get("architecture") or "").strip()
                if not arch:
                    from ascendc_pilot.state import load_state

                    arch = str((load_state(project_root) or {}).get("architecture") or "").strip()
                goal = load_user_goal(project_root) or {}
                if not arch:
                    arch = str(goal.get("architecture") or "").strip()
                if arch == "goal":
                    arch = ""
                intent_doc = goal.get("intent") if isinstance(goal.get("intent"), dict) else {}
                intent = str(
                    intent_doc.get("text")
                    or goal.get("intent_text")
                    or goal.get("label_zh")
                    or ""
                ).strip()
                project_from_goal = str(goal.get("project") or "").strip()
            except Exception:  # noqa: BLE001
                pass
            msg = str(
                complete.get("user_goal_next_summary_zh")
                or complete.get("message_zh")
                or ""
            )
            try:
                from ascendc_pilot.public_progress import message_zh_for_host

                pub = message_zh_for_host(project_root)
                if pub:
                    msg = pub
            except Exception:  # noqa: BLE001
                pass
            out["host_step"] = build_host_step(
                kind="continue_goal",
                project_root=project_root,
                message_zh=msg or f"continue goal → {next_wf}",
                extra={
                    "status": status or "passed",
                    "next_workflow_id": next_wf,
                    "architecture": arch,
                    "intent": intent,
                    "project": str(project_from_goal or ""),
                    "completed_workflow_id": str(
                        (complete.get("state") or {}).get("workflow_id")
                        if isinstance(complete.get("state"), dict)
                        else ""
                    ),
                },
            )
            return out
        done = _done_read_hint(project_root, complete)
        extra: dict[str, Any] = {"status": status or "passed"}
        extra.update({k: v for k, v in done.items() if k != "message_zh"})
        out["host_step"] = build_host_step(
            kind="done",
            project_root=project_root,
            message_zh=str(
                done.get("message_zh")
                or complete.get("message_zh")
                or out.get("message_zh")
                or "workflow complete"
            ),
            extra=extra,
        )
        out["message_zh"] = str(out["host_step"].get("message_zh") or "")
        return out

    if stop in {"deterministic_action_failed", "advance_failed", "completion_gate_failed"} or (
        out.get("ok") is False and stop not in {"interaction_required", "workflow_status"}
    ):
        from ascendc_pilot.actions.failure_text import (
            preferred_failure_text,
            with_failure_hint,
        )

        fail = out.get("failure") if isinstance(out.get("failure"), dict) else {}
        eng = fail.get("engine") if isinstance(fail.get("engine"), dict) else {}
        detail = with_failure_hint(
            preferred_failure_text(out, fallback=str(stop or "deterministic_action_failed")),
            out,
        )
        error_detail = preferred_failure_text(
            {"engine": eng, "failure": fail, "error": out.get("error")},
            fallback=str(out.get("error") or ""),
        )
        hint_zh = str(out.get("hint_zh") or "")
        out["message_zh"] = detail
        if not str(out.get("error") or "").strip():
            out["error"] = error_detail or stop
        extra = {
            "stop_reason": stop,
            "failed_action": out.get("failed_action") or "",
            "error_detail": error_detail or detail,
        }
        if hint_zh:
            extra["hint_zh"] = hint_zh
        issues = fail.get("issues") or eng.get("issues") or out.get("issues")
        if issues:
            extra["issues"] = issues
        out["host_step"] = build_host_step(
            kind="failed",
            project_root=project_root,
            action_id=str(out.get("failed_action") or ""),
            message_zh=detail,
            extra=extra,
        )
        return out

    if out.get("ask_question") or (
        stop == "interaction_required"
        and status in {
            "human_required",
            "waiting_for_confirmation",
        }
    ):
        out["host_step"] = build_host_step(
            kind="ask_human",
            project_root=project_root,
            ask_question=out.get("ask_question") if isinstance(out.get("ask_question"), dict) else None,
            message_zh=str(out.get("message_zh") or "human interaction required"),
            extra={"status": status, "stop_reason": stop},
        )
        return out

    nxt = out.get("next") if isinstance(out.get("next"), dict) else {}
    kind = str(nxt.get("execution_kind") or "")
    action_id = str(nxt.get("action_id") or "").strip()
    actor_id = str(nxt.get("actor_id") or "").strip()

    if stop == "interaction_required" and kind in {"subagent", "primary_interactive"} and action_id:
        from ascendc_pilot.actions.runtime import prepare_action

        prep = prepare_action(project_root, action_id)
        if not prep.get("ok"):
            out["host_step"] = build_host_step(
                kind="failed",
                project_root=project_root,
                action_id=action_id,
                actor_id=actor_id,
                message_zh=str(prep.get("message_zh") or prep.get("error") or "prepare failed"),
                extra={"prepare": prep},
            )
            out["prepare"] = prep
            return out

        if prep.get("auto_skip_human_gate") and prep.get("auto_finalize"):
            from ascendc_pilot.actions.drive import drive_until_interaction

            return drive_until_interaction(project_root, prepare=prepare_action)

        if kind == "primary_interactive" or prep.get("needs_human_decision"):
            out["host_step"] = build_host_step(
                kind="ask_human",
                project_root=project_root,
                action_id=action_id,
                actor_id=actor_id or str(prep.get("actor_id") or ""),
                prepare=prep,
                ask_question=prep.get("ask_question")
                if isinstance(prep.get("ask_question"), dict)
                else out.get("ask_question"),
                message_zh=str(prep.get("message_zh") or "primary interactive"),
            )
            out["prepare"] = prep
            return out

        ticket = issue_dispatch_ticket(
            project_root,
            run_id=str(prep.get("run_id") or ""),
            action_id=action_id,
            actor_id=str(prep.get("actor_id") or actor_id),
            lease_id=str(prep.get("lease_id") or ""),
            session_dir=str(prep.get("session_dir") or ""),
            task_prompt_stub=str(prep.get("task_prompt_stub") or ""),
            prepare_nonce=str(prep.get("prepare_nonce") or ""),
            workflow_id=str(prep.get("workflow_id") or ""),
        )
        actor = str(prep.get("actor_id") or actor_id)
        tasks = _compact_dispatch_tasks(prep.get("dispatch_tasks"))
        if tasks:
            dispatch_msg = str(prep.get("message_zh") or "") or _fanout_dispatch_message_zh(
                actor, tasks
            )
        else:
            dispatch_msg = str(
                prep.get("message_zh")
                or (
                    f"请用 OpenCode 原生 Task（agent={actor}）"
                    "原样派发 task_prompt_stub；可打开 Task 卡片查看子会话推理过程。禁止改写 stub。"
                )
            )
        out["host_step"] = build_host_step(
            kind="dispatch_subagent",
            project_root=project_root,
            action_id=action_id,
            actor_id=actor,
            ticket=ticket,
            prepare=prep,
            message_zh=dispatch_msg,
        )
        out["prepare"] = prep
        out["dispatch_ticket"] = ticket.get("ticket_id")
        return out

    out["host_step"] = build_host_step(
        kind="failed",
        project_root=project_root,
        message_zh=str(out.get("message_zh") or stop or "drive stopped"),
        extra={"stop_reason": stop, "status": status},
    )
    return out


__all__ = [
    "issue_dispatch_ticket",
    "load_dispatch_ticket",
    "claim_dispatch_ticket",
    "mark_dispatch_ticket_consumed",
    "release_dispatch_ticket",
    "consume_dispatch_ticket",
    "build_host_step",
    "dispatch_result",
    "attach_host_step",
]
