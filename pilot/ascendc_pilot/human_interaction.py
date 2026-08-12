# -*- coding: utf-8 -*-
"""Human Interaction Broker: request → Host UI → signed decision receipt.

ACP emits ``human_interaction_request`` with a run-bound ``request_id`` nonce.
The Host (OpenCode plugin) must surface the question UI and call
``acp answer``. Finalize / resume / recovery commands consume the receipt;
``--finalize`` alone is never an affirmative human signal.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path
from typing import Any

import yaml

from ascendc_pilot.paths import AGENT_DIR
from ascendc_pilot.state import load_state


KIND_HUMAN_REQUIRED = "human_required"
KIND_PRIMARY_CONFIRM = "primary_confirm"
KIND_PRIMARY_APPROVE = "primary_approve"
KIND_RESUME = "resume"
KIND_INTAKE = "intake"


def _dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _control_root(project_root: Path) -> Path:
    """Arch-neutral control plane root (safe before --architecture is known)."""
    return Path(project_root).expanduser().resolve() / AGENT_DIR / "control"


def pending_path(project_root: Path) -> Path:
    return _control_root(project_root) / "pending_interaction.yaml"


def decisions_dir(project_root: Path) -> Path:
    return _control_root(project_root) / "decisions"


def _sign(project_root: Path, payload: dict[str, Any]) -> str:
    from ascendc_pilot.runs import sign_receipt_payload

    return sign_receipt_payload(Path(project_root), payload)


def _verify(project_root: Path, payload: dict[str, Any]) -> bool:
    from ascendc_pilot.runs import verify_receipt_signature

    return verify_receipt_signature(Path(project_root), payload)


def issue_interaction_request(
    project_root: Path,
    *,
    kind: str,
    ask_question: dict[str, Any],
    action_id: str = "",
    decision_kind: str = "",
    allowed_values: list[str] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """Persist pending interaction and return the public request envelope."""
    project_root = Path(project_root).expanduser().resolve()
    state = load_state(project_root) or {}
    rid = (run_id or str(state.get("run_id") or "")).strip()
    request_id = secrets.token_hex(16)
    values = list(allowed_values or [])
    if not values:
        for opt in ask_question.get("options") or []:
            if isinstance(opt, dict):
                v = str(opt.get("value") or opt.get("label") or "").strip()
                if v:
                    values.append(v)
    req = {
        "schema": "human-interaction-request/v1",
        "request_id": request_id,
        "run_id": rid,
        "workflow_id": str(state.get("workflow_id") or ""),
        "action_id": action_id,
        "kind": kind,
        "decision_kind": decision_kind or kind,
        "ask_question": ask_question,
        "allowed_values": values,
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "pending",
    }
    _dump(pending_path(project_root), req)
    return {
        "request_id": request_id,
        "run_id": rid,
        "workflow_id": req["workflow_id"],
        "action_id": action_id,
        "kind": kind,
        "decision_kind": req["decision_kind"],
        "allowed_values": values,
        "ask_question": ask_question,
    }


def attach_interaction_request(
    payload: dict[str, Any],
    project_root: Path | str | None,
    *,
    kind: str,
    action_id: str = "",
    decision_kind: str = "",
) -> dict[str, Any]:
    """If payload asks for a human decision, attach + persist a request envelope."""
    if not project_root:
        return payload
    ask = payload.get("ask_question")
    if not payload.get("needs_human_decision") and not ask:
        return payload
    if not isinstance(ask, dict):
        return payload
    root = Path(project_root).expanduser().resolve()
    try:
        env = issue_interaction_request(
            root,
            kind=kind,
            ask_question=ask,
            action_id=action_id or str(payload.get("action_id") or ""),
            decision_kind=decision_kind or str(payload.get("decision_kind") or kind),
            run_id=str(payload.get("run_id") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        payload["human_interaction_error"] = str(exc)[:200]
        return payload
    payload["human_interaction_request"] = env
    payload["primary_instruction_zh"] = (
        str(payload.get("primary_instruction_zh") or "")
        + " Host 必须弹出 question UI；回答后由 Host 调用 "
        f"`acp answer --request-id {env['request_id']} --value <选中> --project …`。"
        " 无 HumanDecisionReceipt 不得 finalize / resume / retry。"
    ).strip()
    return payload


def record_answer(
    project_root: Path,
    *,
    request_id: str,
    value: str,
) -> dict[str, Any]:
    """Validate pending request + write signed HumanDecisionReceipt."""
    project_root = Path(project_root).expanduser().resolve()
    pending = _load(pending_path(project_root))
    if not pending:
        return {
            "ok": False,
            "error": "NO_PENDING_INTERACTION",
            "message_zh": "没有待处理的人工交互请求",
        }
    if str(pending.get("request_id") or "") != str(request_id or "").strip():
        return {
            "ok": False,
            "error": "REQUEST_ID_MISMATCH",
            "message_zh": "request_id 与 pending_interaction 不匹配",
            "expected": pending.get("request_id"),
            "got": request_id,
        }
    allowed = [str(v) for v in (pending.get("allowed_values") or [])]
    answer = str(value or "").strip()
    if allowed and answer not in allowed:
        # Accept option labels mapped via ask_question.options
        for opt in (pending.get("ask_question") or {}).get("options") or []:
            if not isinstance(opt, dict):
                continue
            if answer in {
                str(opt.get("label") or ""),
                str(opt.get("value") or ""),
            }:
                answer = str(opt.get("value") or opt.get("label") or answer)
                break
    if allowed and answer not in allowed:
        return {
            "ok": False,
            "error": "VALUE_NOT_ALLOWED",
            "allowed_values": allowed,
            "message_zh": f"回答 {value!r} 不在允许选项中",
        }
    state = load_state(project_root) or {}
    run_id = str(pending.get("run_id") or state.get("run_id") or "")
    receipt = {
        "schema": "human-decision-receipt/v1",
        "request_id": str(pending.get("request_id")),
        "run_id": run_id,
        "workflow_id": str(pending.get("workflow_id") or state.get("workflow_id") or ""),
        "action_id": str(pending.get("action_id") or ""),
        "kind": str(pending.get("kind") or ""),
        "decision_kind": str(pending.get("decision_kind") or ""),
        "value": answer,
        "consumed": False,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "issued_by": "acp-answer",
    }
    receipt["signature"] = _sign(project_root, receipt)
    out = decisions_dir(project_root) / f"{receipt['request_id']}.yaml"
    _dump(out, receipt)
    pending["status"] = "answered"
    pending["answered_value"] = answer
    _dump(pending_path(project_root), pending)
    return {
        "ok": True,
        "receipt_path": str(out),
        "request_id": receipt["request_id"],
        "value": answer,
        "run_id": run_id,
        "kind": receipt["kind"],
        "action_id": receipt["action_id"],
    }


def require_decision_receipt(
    project_root: Path,
    *,
    expected_values: list[str] | None = None,
    expected_action_id: str = "",
    expected_kind: str = "",
    consume: bool = True,
) -> dict[str, Any]:
    """Require an unconsumed matching HumanDecisionReceipt."""
    project_root = Path(project_root).expanduser().resolve()
    pending = _load(pending_path(project_root))
    request_id = str(pending.get("request_id") or "").strip()
    if not request_id:
        # Fall back: newest unconsumed receipt for this run
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_REQUIRED",
            "message_zh": (
                "缺少 HumanDecisionReceipt。Host 必须先弹出 question UI，"
                "再用 `acp answer` 写入签名收据后才能继续。"
            ),
        }
    path = decisions_dir(project_root) / f"{request_id}.yaml"
    receipt = _load(path)
    if not receipt:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_REQUIRED",
            "request_id": request_id,
            "message_zh": "pending interaction 尚未通过 acp answer 产生收据",
        }
    if not _verify(project_root, receipt):
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_INVALID",
            "message_zh": "HumanDecisionReceipt 签名无效",
        }
    if receipt.get("consumed"):
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_CONSUMED",
            "message_zh": "HumanDecisionReceipt 已被消费，需重新 AskQuestion",
        }
    state = load_state(project_root) or {}
    run_id = str(state.get("run_id") or "")
    if run_id and str(receipt.get("run_id") or "") not in {"", run_id}:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_RUN_MISMATCH",
            "message_zh": "收据 run_id 与当前 run 不匹配",
        }
    if expected_action_id and str(receipt.get("action_id") or "") not in {
        "",
        expected_action_id,
    }:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_ACTION_MISMATCH",
            "expected_action_id": expected_action_id,
            "got": receipt.get("action_id"),
        }
    if expected_kind and str(receipt.get("kind") or "") not in {"", expected_kind}:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_KIND_MISMATCH",
            "expected_kind": expected_kind,
            "got": receipt.get("kind"),
        }
    value = str(receipt.get("value") or "")
    if expected_values and value not in expected_values:
        return {
            "ok": False,
            "error": "HUMAN_DECISION_RECEIPT_VALUE_MISMATCH",
            "expected_values": list(expected_values),
            "got": value,
            "message_zh": f"收据值 {value!r} 不是本次操作所需的肯定选择",
        }
    if consume:
        receipt["consumed"] = True
        receipt["consumed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        receipt["signature"] = _sign(project_root, receipt)
        _dump(path, receipt)
        if pending_path(project_root).is_file():
            pending_path(project_root).unlink()
    return {
        "ok": True,
        "value": value,
        "request_id": request_id,
        "receipt": receipt,
    }


def clear_pending(project_root: Path) -> None:
    path = pending_path(Path(project_root))
    if path.is_file():
        path.unlink()
