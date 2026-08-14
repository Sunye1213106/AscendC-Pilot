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


def _ticket_dir(project_root: Path) -> Path:
    from ascendc_pilot.paths import agent_root

    d = agent_root(project_root) / "state" / "dispatch_tickets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_ticket(project_root: Path, doc: dict[str, Any]) -> None:
    path = _ticket_dir(project_root) / f"{doc['ticket_id']}.yaml"
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
) -> dict[str, Any]:
    """Create a one-shot ticket for Host Session Driver (status=open)."""
    raw = f"{run_id}:{action_id}:{actor_id}:{time.time_ns()}"
    ticket_id = "dxt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    doc = {
        "ticket_id": ticket_id,
        "run_id": run_id,
        "action_id": action_id,
        "actor_id": actor_id,
        "lease_id": lease_id,
        "session_dir": session_dir,
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
    path = _ticket_dir(project_root) / f"{tid}.yaml"
    if not path.is_file():
        return {}
    try:
        if yaml is not None:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
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


def _existing_quality_yaml(project_root: Path, *, arch: str | None) -> Path:
    """On-disk verify receipt under ``.ascendc-pilot/<arch>/uo/``, never the unscoped tree."""
    from ascendc_pilot.paths import AGENT_DIR, uo_root

    root = Path(project_root).expanduser().resolve()
    expected: Path | None = None
    if arch:
        expected = uo_root(root, arch=arch) / "checks" / "quality.yaml"
        if expected.is_file():
            return expected
    hits: list[Path] = []
    pilot = root / AGENT_DIR
    if pilot.is_dir():
        hits = sorted(p for p in pilot.glob("arch*/uo/checks/quality.yaml") if p.is_file())
    if arch:
        for hit in hits:
            if hit.parent.parent.parent.name == arch:
                return hit
    if hits:
        return hits[0]
    if expected is not None:
        return expected
    raise FileNotFoundError("quality.yaml")


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
        from ascendc_pilot.paths import agent_root

        if wid in {"uo-init", "uo-update"}:
            quality = _existing_quality_yaml(Path(project_root), arch=arch)
            unresolved = quality.parent.parent / "ir" / "unresolved.yaml"
            q_abs = _posix_abs(quality)
            u_abs = _posix_abs(unresolved)
            hint["quality_path"] = q_abs
            hint["unresolved_path"] = u_abs
            hint["read_after_done"] = [q_abs, u_abs]
            hint["message_zh"] = (
                f"建库完成。请 Read `{q_abs}`（verify 收据），"
                "对人总结节点/关系数量、未闭合桶及原因；"
                f"要名单再读 `{u_abs}`。"
                "不要打开 .uo 二进制，不要只说完成。"
                "禁止读 `.ascendc-pilot/uo/`（无 arch 段的旧路径）。"
            )
        elif wid == "uo-query" and run_id:
            ans = (
                agent_root(project_root, arch)
                / "runs"
                / run_id
                / "actions"
                / "kb_lookup"
                / "answer.yaml"
            )
            answer_zh = ""
            status = ""
            if ans.is_file() and yaml is not None:
                try:
                    body = yaml.safe_load(ans.read_text(encoding="utf-8")) or {}
                    if isinstance(body, dict):
                        answer_zh = str(
                            body.get("answer_zh") or body.get("answer") or ""
                        ).strip()
                        status = str(body.get("status") or "")
                except Exception:  # noqa: BLE001
                    answer_zh = ""
            if answer_zh:
                hint["answer_zh"] = answer_zh
                hint["answer_status"] = status
                hint["message_zh"] = (
                    "查询完成。下面是答案，直接对人说（含 path:line）。"
                    "禁止再 Glob/Read answer.yaml 或其它 yaml。\n\n"
                    f"{answer_zh}"
                )
            else:
                hint["message_zh"] = (
                    "查询完成。把本次子代理返回的答案正文说给人听。"
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
        if next_wf:
            arch = ""
            intent = ""
            try:
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
                intent = str(goal.get("intent_text") or goal.get("label_zh") or "").strip()
            except Exception:  # noqa: BLE001
                pass
            out["host_step"] = build_host_step(
                kind="continue_goal",
                project_root=project_root,
                message_zh=str(
                    complete.get("user_goal_next_summary_zh")
                    or complete.get("message_zh")
                    or f"continue goal → {next_wf}"
                ),
                extra={
                    "status": status or "passed",
                    "next_workflow_id": next_wf,
                    "architecture": arch,
                    "intent": intent,
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
        out["host_step"] = build_host_step(
            kind="failed",
            project_root=project_root,
            message_zh=str(out.get("message_zh") or out.get("error") or stop),
            extra={"stop_reason": stop, "failure": out.get("failure")},
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
        )
        out["host_step"] = build_host_step(
            kind="dispatch_subagent",
            project_root=project_root,
            action_id=action_id,
            actor_id=str(prep.get("actor_id") or actor_id),
            ticket=ticket,
            prepare=prep,
            message_zh=str(
                prep.get("message_zh")
                or (
                    f"请用 OpenCode 原生 Task（agent={prep.get('actor_id') or actor_id}）"
                    "原样派发 task_prompt_stub；点 Task 卡片可跳进子会话看思考。不要改写 stub。"
                )
            ),
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
