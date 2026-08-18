# -*- coding: utf-8 -*-
"""Human Interaction Broker: request → Host UI → signed decision receipt.

ACP emits ``human_interaction_request`` with a run-bound ``request_id`` nonce.
The Host (OpenCode plugin) must surface the question UI and call
``acp answer``. Finalize / resume / recovery commands consume the receipt;
``--finalize`` alone is never an affirmative human signal.
"""

from __future__ import annotations

import hashlib
import re
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


def load_pending(project_root: Path) -> dict[str, Any]:
    return _load(pending_path(Path(project_root).expanduser().resolve()))


def pending_is_open(pending: dict[str, Any] | None) -> bool:
    """True when a pending AskQuestion is still waiting (not answered/superseded)."""
    if not pending:
        return False
    if not str(pending.get("request_id") or "").strip():
        return False
    return str(pending.get("status") or "pending").strip().lower() == "pending"


def pending_is_intake(pending: dict[str, Any] | None) -> bool:
    """True when pending is pre-start intake (architecture / project / uo product)."""
    if not pending_is_open(pending):
        return False
    kind = str(pending.get("kind") or "").strip().lower()
    dkind = str(pending.get("decision_kind") or "").strip().lower()
    return kind == KIND_INTAKE or dkind in {
        "architecture",
        "intake",
        "project",
        "uo_product",
    }


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
            if not isinstance(opt, dict):
                continue
            for key in ("value", "label"):
                v = str(opt.get(key) or "").strip()
                if v and v not in values:
                    values.append(v)
    decision = decision_kind or kind
    existing = _load(pending_path(project_root))
    if pending_is_open(existing):
        same_kind = str(existing.get("kind") or "") == kind
        same_decision = str(existing.get("decision_kind") or "") == decision
        if same_kind and same_decision:
            return {
                "request_id": str(existing.get("request_id") or request_id),
                "run_id": str(existing.get("run_id") or rid),
                "workflow_id": str(existing.get("workflow_id") or ""),
                "action_id": str(existing.get("action_id") or action_id),
                "kind": kind,
                "decision_kind": decision,
                "allowed_values": list(existing.get("allowed_values") or values),
                "ask_question": existing.get("ask_question") or ask_question,
            }
    _clear_superseded_flag(project_root)
    req = {
        "schema": "human-interaction-request/v1",
        "request_id": request_id,
        "run_id": rid,
        "workflow_id": str(state.get("workflow_id") or ""),
        "action_id": action_id,
        "kind": kind,
        "decision_kind": decision,
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
        + " Host 弹出 question UI；点选后调用 "
        f"`acp answer --request-id {env['request_id']} --value <选中> --project …`。"
        " 若用户打断确认框并在对话里回复：用 `acp interpret-user-turn --text <本轮原文>`，"
        "能对应原选项则记为答复，否则取消上一问并跟新消息。不要重问上一题。"
        "未点选不等于批准删除/重开。无收据不得 finalize / resume / 破坏性 reinit。"
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
    try:
        from ascendc_pilot.run_resume import normalize_decision

        canon = normalize_decision(answer)
        if canon:
            answer = canon
        allowed_canon = {normalize_decision(v) or v for v in allowed} if allowed else set()
    except Exception:  # noqa: BLE001
        canon = None
        allowed_canon = set(allowed)
    if allowed and answer not in allowed and answer not in allowed_canon:
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
        try:
            from ascendc_pilot.run_resume import normalize_decision

            got = normalize_decision(value) or value
            allowed = {normalize_decision(v) or v for v in expected_values}
            if got not in allowed:
                return {
                    "ok": False,
                    "error": "HUMAN_DECISION_RECEIPT_VALUE_MISMATCH",
                    "expected_values": list(expected_values),
                    "got": value,
                    "message_zh": f"收据值 {value!r} 不是本次操作所需的肯定选择",
                }
        except Exception:  # noqa: BLE001
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


def consume_intake_architecture(
    project_root: Path,
    *,
    architecture: str,
    force_new: bool = False,
) -> dict[str, Any]:
    """Record or clear pre-start intake so start/reinit is not deadlocked.

    Architecture intake is answered with the chosen arch*. ``--force-new``
    may drop a stale intake when no arch is available yet.
    """
    root = Path(project_root).expanduser().resolve()
    pending = load_pending(root)
    if str(pending.get("status") or "") != "pending":
        return {"ok": True, "skipped": True}
    if force_new:
        clear_pending(root)
        return {"ok": True, "cleared": True, "kind": pending.get("kind")}
    if not pending_is_intake(pending):
        return {"ok": True, "skipped": True, "kind": pending.get("kind")}
    arch = str(architecture or "").strip()
    rid = str(pending.get("request_id") or "")
    allowed = [str(v) for v in (pending.get("allowed_values") or [])]
    if arch and rid and (not allowed or arch in allowed):
        rec = record_answer(root, request_id=rid, value=arch)
        if rec.get("ok"):
            return rec
    return {
        "ok": True,
        "pending": True,
        "request_id": rid,
        "kind": pending.get("kind"),
    }


_DESTRUCTIVE_VALUES = frozenset(
    {
        "reinit",
        "force_new",
        "force-new",
        "abort_run",
        "abort",
        "wipe",
    }
)

_ARCH_TOKEN = re.compile(r"\barch[0-9A-Za-z._-]+\b", re.I)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def _option_catalog(pending: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Canonical value → labels that count as that value."""
    rows: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    ask = pending.get("ask_question") if isinstance(pending.get("ask_question"), dict) else {}
    for opt in ask.get("options") or []:
        if not isinstance(opt, dict):
            continue
        value = str(opt.get("value") or "").strip()
        label = str(opt.get("label") or "").strip()
        if not value and not label:
            continue
        canon = value or label
        labels = [x for x in (value, label) if x]
        if canon in seen:
            for i, (v, labs) in enumerate(rows):
                if v == canon:
                    rows[i] = (v, list(dict.fromkeys([*labs, *labels])))
                    break
            continue
        seen.add(canon)
        rows.append((canon, labels))
    for raw in pending.get("allowed_values") or []:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        rows.append((value, [value]))
    return rows


def match_pending_option(pending: dict[str, Any] | None, text: str) -> str | None:
    """Map a free-text reply onto one pending option. None if it is not a choice.

    Conservative: exact value/label, resume-decision aliases, unique arch* token.
    Short messages may uniquely contain one option token. Long new requests do not
    silently confirm, and wipe/reinit never match a long off-topic message.
    """
    if not pending_is_open(pending):
        return None
    raw = str(text or "").strip()
    if not raw:
        return None
    catalog = _option_catalog(pending or {})
    if not catalog:
        return None
    compact = _compact(raw)
    allowed = {v for v, _ in catalog}
    allowed_l = {v.lower(): v for v in allowed}

    for value, labels in catalog:
        if raw == value or compact == _compact(value):
            return value
        for lab in labels:
            if raw == lab or compact == _compact(lab):
                return value

    try:
        from ascendc_pilot.run_resume import normalize_decision

        canon = normalize_decision(raw)
    except Exception:  # noqa: BLE001
        canon = None
    if canon:
        if canon in allowed:
            return canon
        mapped = allowed_l.get(canon.lower())
        if mapped:
            return mapped

    from ascendc_pilot.goal_turn import is_answer_shaped

    arches = [v for v in allowed if re.fullmatch(r"arch[0-9A-Za-z._-]+", v, re.I)]
    if arches and is_answer_shaped(raw, pending=pending):
        found: list[str] = []
        for token in _ARCH_TOKEN.findall(raw):
            hit = allowed_l.get(token.lower())
            if hit and hit not in found:
                found.append(hit)
        if len(found) == 1:
            return found[0]

    if len(raw) <= 24 and is_answer_shaped(raw, pending=pending):
        hits: list[str] = []
        for value, labels in catalog:
            tokens = [value, *labels]
            if any(_compact(t) and _compact(t) in compact for t in tokens):
                hits.append(value)
        uniq = list(dict.fromkeys(hits))
        if len(uniq) == 1:
            return uniq[0]
    return None


def _clear_superseded_flag(project_root: Path) -> None:
    from ascendc_pilot.state import load_state, save_state

    st = load_state(project_root)
    if not st:
        return
    if not st.get("human_decision_superseded"):
        return
    st.pop("human_decision_superseded", None)
    st.pop("human_decision_superseded_reason", None)
    save_state(project_root, st)


def supersede_pending(
    project_root: Path,
    *,
    reason: str = "user_interrupted",
    user_text: str = "",
    relation: str = "",
) -> dict[str, Any]:
    """Drop a pending AskQuestion because the user moved on. Never auto-confirms."""
    root = Path(project_root).expanduser().resolve()
    pending = _load(pending_path(root))
    if not pending_is_open(pending):
        return {
            "ok": True,
            "disposition": "idle",
            "needs_human_decision": False,
            "message_zh": "没有待确认的问题",
        }
    ask = pending.get("ask_question") if isinstance(pending.get("ask_question"), dict) else {}
    header = str(ask.get("header") or ask.get("question") or pending.get("kind") or "")
    pending["status"] = "superseded"
    pending["supersede_reason"] = str(reason or "user_interrupted")
    pending["user_text"] = str(user_text or "")[:500]
    pending["relation"] = str(relation or "")
    pending["superseded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _dump(pending_path(root), pending)

    from ascendc_pilot.state import load_state, save_state

    st = load_state(root)
    if st:
        st["human_decision_superseded"] = True
        st["human_decision_superseded_reason"] = str(reason or "user_interrupted")
        if relation:
            st["last_goal_relation"] = relation
        save_state(root, st)

    from ascendc_pilot.human_voice import FOLLOW_NEW_TURN_ZH

    effects = apply_goal_relation(root, relation or "side_question", user_text)
    paused = bool(effects.get("paused"))
    return {
        "ok": True,
        "disposition": "superseded",
        "relation": relation or effects.get("relation") or "side_question",
        "ask_interrupted": True,
        "paused": paused,
        "needs_human_decision": False,
        "previous_kind": str(pending.get("kind") or ""),
        "previous_header": header,
        "request_id": str(pending.get("request_id") or ""),
        **{k: v for k, v in effects.items() if k not in {"ok"}},
        "message_zh": (
            "上一问确认已被本轮新消息打断，已解除卡住。"
            "请按本轮用户消息继续，不要重问上一题。"
            "未点选不等于批准删除/重开。"
            + FOLLOW_NEW_TURN_ZH
        ),
    }


def apply_goal_relation(
    project_root: Path,
    relation: str,
    user_text: str = "",
) -> dict[str, Any]:
    """Apply Goal Relation side effects (pause lock / revise plan)."""
    from ascendc_pilot.goal_turn import REL_CANCEL, REL_REVISE, REL_SIDE, REL_SWITCH
    from ascendc_pilot.occupancy import LIVENESS_PAUSED, set_lock_lifecycle
    from ascendc_pilot.state import load_state
    from ascendc_pilot.user_goal import pause_user_goal, request_goal_revision

    root = Path(project_root).expanduser().resolve()
    rel = str(relation or "").strip() or REL_SIDE
    st = load_state(root) or {}
    out: dict[str, Any] = {"relation": rel, "paused": False}
    if rel == REL_SIDE:
        return out
    if rel in {REL_SWITCH, REL_CANCEL}:
        set_lock_lifecycle(root, LIVENESS_PAUSED, run_id=str(st.get("run_id") or ""))
        pause_user_goal(root, reason=rel)
        out["paused"] = True
        return out
    if rel == REL_REVISE:
        revised = request_goal_revision(root, user_text)
        out.update(revised)
        return out
    return out


def interpret_user_turn(
    project_root: Path,
    *,
    text: str = "",
    reason: str = "user_message",
) -> dict[str, Any]:
    """Latest user turn vs pending AskQuestion and the active Goal."""
    from ascendc_pilot.goal_turn import REL_ANSWER, classify_goal_turn
    from ascendc_pilot.state import load_state
    from ascendc_pilot.user_goal import load_user_goal

    root = Path(project_root).expanduser().resolve()
    pending = load_pending(root)
    st = load_state(root) or {}
    relation = classify_goal_turn(
        text,
        pending=pending,
        workflow_id=str(st.get("workflow_id") or ""),
        goal=load_user_goal(root),
    )
    if pending_is_open(pending) and relation == REL_ANSWER:
        mapped = match_pending_option(pending, text)
        if mapped and mapped.lower() in _DESTRUCTIVE_VALUES and len(str(text or "").strip()) > 24:
            mapped = None
        if mapped:
            rec = record_answer(
                root,
                request_id=str(pending.get("request_id") or ""),
                value=mapped,
            )
            if rec.get("ok"):
                _clear_superseded_flag(root)
                rec["disposition"] = "answered"
                rec["relation"] = REL_ANSWER
                rec["needs_human_decision"] = False
                rec["message_zh"] = f"已把本轮回复记为选项「{mapped}」"
                return rec
    if pending_is_open(pending):
        return supersede_pending(
            root, reason=reason, user_text=text, relation=relation
        )
    effects = apply_goal_relation(root, relation, text)
    from ascendc_pilot.human_voice import FOLLOW_NEW_TURN_ZH

    return {
        "ok": True,
        "disposition": relation,
        "relation": relation,
        "needs_human_decision": False,
        "paused": bool(effects.get("paused")),
        "message_zh": FOLLOW_NEW_TURN_ZH,
        **effects,
    }
