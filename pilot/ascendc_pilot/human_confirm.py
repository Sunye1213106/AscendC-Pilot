"""Host-owned primary confirmation.

One module derives AskQuestion copy, affirmative values, and the receipt
files from ``(workflow_id, action_id)``. Action ids stay unprefixed
(``human_confirm`` is shared); Primary only surfaces ``ask_question.options``
and never writes the canonical YAML itself.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from ascendc_pilot.human_voice import (
    _declared_key_count,
    _goal_context,
    decision_question,
)
from ascendc_pilot.paths import ce_root, runs_root, tg_root
from ascendc_pilot.state import load_state


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _session(project_root: Path, state: dict[str, Any], action_id: str) -> dict[str, Any]:
    run_id = str(state.get("run_id") or "").strip()
    if not run_id:
        return {}
    sdir = runs_root(project_root) / run_id / "actions" / action_id
    for name in ("session_state.yaml", "session.yaml"):
        hit = _load(sdir / name)
        if hit:
            return hit
    return {}


def _identity(session: dict[str, Any]) -> dict[str, str]:
    nonce = str(session.get("prepare_nonce") or "")
    return {
        "run_id": str(session.get("run_id") or ""),
        "workflow_id": str(session.get("workflow_id") or ""),
        "phase": str(session.get("phase") or ""),
        "action_id": str(session.get("action_id") or ""),
        "actor_id": str(session.get("actor_id") or ""),
        "role_id": str(session.get("role_id") or ""),
        "action_session_id": str(session.get("action_session_id") or ""),
        "lease_id": str(session.get("lease_id") or ""),
        "prepare_nonce_hash": hashlib.sha256(nonce.encode("utf-8")).hexdigest() if nonce else "",
    }


def _arch(state: dict[str, Any]) -> str | None:
    arch = str(state.get("architecture") or "").strip()
    return arch or None


def _op_arch(project_root: Path, state: dict[str, Any]) -> tuple[str, str]:
    op = str(state.get("op_name") or Path(project_root).name or "算子")
    arch = str(state.get("architecture") or "").strip() or "当前架构"
    return op, arch


def _ask_tg_init(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    gctx = _goal_context(project_root)
    goal = str(gctx.get("label_zh") or "") or f"为 {op}（{arch}）绑定测试脚本并规划覆盖"
    n = _declared_key_count(project_root)
    scale = f"（声明域约 {n} 个合法 Key，不是默认 T）" if n else ""
    background = f"init.yaml 已写出{scale}。"
    if gctx.get("progress_line"):
        background = f"{gctx['progress_line']} {background}"
    return decision_question(
        header="init.yaml 已写出，是否进入规划？",
        goal=goal,
        background=background,
        decide="是否进入「白盒测试规划」阶段？",
        consequences={
            "确认进入规划": "开始列出独立测试变量（tg-plan）",
            "返工": "回到建立合同阶段重做",
            "停止": "结束本次目标（不进入规划）",
        },
        options=[
            {"label": "确认进入规划", "value": "confirm"},
            {"label": "返工建立合同", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


def _ask_plan_approve(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    gctx = _goal_context(project_root)
    goal = str(gctx.get("label_zh") or "") or f"为 {op}（{arch}）列出独立测试变量并规划覆盖"
    background = "测试规划已生成，等待你批准后才能开始求解与生成用例。"
    if gctx.get("progress_line"):
        background = f"{gctx['progress_line']} {background}"
    return decision_question(
        header="规划已就绪，是否开始求解？",
        goal=goal,
        background=background,
        decide="是否批准规划并进入「求解并生成用例」？",
        consequences={
            "批准并开始求解": "启动求解与 Host Replay（tg-solve）",
            "返工": "回到规划阶段调整变量或观测",
            "停止": "结束本次目标（不开始求解）",
        },
        options=[
            {"label": "批准并开始求解", "value": "approve"},
            {"label": "返工规划", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


_PROCEED_PHRASES = (
    "按这个写",
    "直接出计划",
    "去改码",
    "不用再确认",
    "直接改码",
    "开始改码",
    "不用问了",
    "直接写计划",
    "去 /ce-apply",
    "去ce-apply",
)

_EMPTY_FORK_ITEM = re.compile(
    r"^(无|无未决|暂无|none|n/a|—|–|-|无。|暂无。)$",
    re.I,
)


def _intent_blob(project_root: Path, state: dict[str, Any]) -> str:
    parts = [str((state or {}).get("intent") or "")]
    try:
        from ascendc_pilot.user_goal import load_user_goal

        goal = load_user_goal(project_root) or {}
        parts.append(str(goal.get("intent_text") or ""))
        parts.append(str(goal.get("label_zh") or ""))
    except Exception:  # noqa: BLE001
        pass
    return " ".join(parts)


def _user_authorized_proceed(text: str) -> bool:
    s = str(text or "")
    if not s:
        return False
    low = s.lower()
    for phrase in _PROCEED_PHRASES:
        if phrase.lower() in low or phrase in s:
            return True
    return False


def _confirm_quality_blocked(state: dict[str, Any]) -> bool:
    return str((state or {}).get("status") or "") in {
        "rework_required",
        "human_required",
        "blocked",
        "failed",
    }


def _plan_has_open_forks(project_root: Path, state: dict[str, Any]) -> bool:
    """True when the current {slug}_plan.md has a non-empty 未决 section."""
    arch = _arch(state)
    if not arch:
        return False
    root = ce_root(project_root, arch=arch) / "plan"
    if not root.is_dir():
        return False
    files = sorted(p for p in root.glob("*_plan.md") if p.is_file())
    if not files:
        return False
    try:
        from code_engineering.plan_md import resolve_active_plan

        active = resolve_active_plan(project_root, architecture=arch, state=state)
        if active is not None and active.is_file():
            files = [active]
    except Exception:  # noqa: BLE001
        pass
    for path in files:
        if _section_has_open_forks(path):
            return True
    return False


def _section_has_open_forks(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    match = re.search(
        r"(?ims)^#{1,6}\s*[^\n]*未决[^\n]*\n(.*?)(?=^#{1,6}\s|\Z)",
        text,
    )
    if not match:
        return False
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            item = stripped[2:].strip()
            if item and not _EMPTY_FORK_ITEM.match(item):
                return True
    return False


def _ce_goal_going_to_apply(project_root: Path, state: dict[str, Any]) -> bool:
    try:
        from ascendc_pilot.user_goal import is_auto_session, load_user_goal
    except Exception:  # noqa: BLE001
        return False
    del state
    goal = load_user_goal(project_root) or {}
    if str(goal.get("status") or "") != "active" or not is_auto_session(goal):
        return False
    caps = list((goal.get("intent") or {}).get("needed_capabilities") or goal.get("needed_capabilities") or [])
    wfs = list((goal.get("intent") or {}).get("needed_workflows") or [])
    return "implement" in caps or any(w in {"ce-plan", "ce-apply"} for w in wfs)


def _auto_goal_wants_tests(project_root: Path) -> bool:
    """True when the active auto goal includes test generation (any current workflow)."""
    try:
        from ascendc_pilot.user_goal import is_auto_session, load_user_goal
    except Exception:  # noqa: BLE001
        return False
    goal = load_user_goal(project_root) or {}
    if not is_auto_session(goal) or str(goal.get("status") or "") != "active":
        return False
    caps = list((goal.get("intent") or {}).get("needed_capabilities") or [])
    wfs = list((goal.get("intent") or {}).get("needed_workflows") or [])
    return "test_generation" in caps or any(str(w).startswith("tg-") for w in wfs)


def _auto_goal_needs_tests(project_root: Path) -> bool:
    try:
        from ascendc_pilot.planning.task_plan import current_workflow_id, load_task_plan
    except Exception:  # noqa: BLE001
        return False
    if not _auto_goal_wants_tests(project_root):
        return False
    nxt = current_workflow_id(load_task_plan(project_root))
    return bool(nxt) and str(nxt).startswith("tg-")


def grill_should_ask(project_root: Path, state: dict[str, Any], *, action_id: str = "") -> bool:
    """Ask CE-plan grill/plan confirms unless the user already authorized and there is no fork."""
    del action_id
    if _confirm_quality_blocked(state):
        return True
    if _plan_has_open_forks(project_root, state):
        return True
    if _ce_goal_going_to_apply(project_root, state):
        return False
    if _user_authorized_proceed(_intent_blob(project_root, state)):
        return False
    return True


def _confirm_already_recorded(
    project_root: Path, action_id: str, state: dict[str, Any]
) -> bool:
    """True iff the confirm artifact already satisfies this action's post-gate."""
    if action_id == "plan_approve":
        try:
            from testcase_agent.products import is_plan_approved, load_plan

            _text, fence = load_plan(tg_root(project_root, arch=_arch(state)))
            return bool(is_plan_approved(fence))
        except Exception:  # noqa: BLE001
            return False
    if action_id == "human_confirm":
        try:
            from testcase_agent.init_status import require_init_confirmed

            require_init_confirmed(
                project_root,
                str((state or {}).get("op_name") or Path(project_root).name),
            )
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def hosted_confirm_should_ask(
    project_root: Path, state: dict[str, Any], *, action_id: str = ""
) -> bool:
    """Whether a hosted confirm gate should surface AskQuestion."""
    wid = str((state or {}).get("workflow_id") or "")
    aid = str(action_id or "")
    if wid in {"tg-init", "tg-plan"} and aid in {"human_confirm", "plan_approve"}:
        return False
    if aid == "apply_report" and _auto_goal_needs_tests(project_root):
        return False
    if aid == "review_report" and _auto_goal_wants_tests(project_root):
        return False
    if aid == "review_report":
        return True
    if aid == "apply_report":
        return True
    if wid == "ce-plan" and aid == "human_confirm":
        return grill_should_ask(project_root, state, action_id=aid)
    return True


def _ask_ce_plan(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    return decision_question(
        header="需求计划已写出。下一步？",
        goal=f"确认 {op}（{arch}）的当前计划 markdown 可以去改码",
        background="计划里应有实现分析、可勾选 todo、测试内容。返工则继续改计划。",
        decide="去 /ce-apply，还是继续改计划？",
        consequences={
            "去改码": "进入 /ce-apply，按未完成 todo 改源码",
            "继续改计划": "回到草稿，边问边改同一份计划",
            "交接": "写 session_handoff.md",
            "停止": "结束本次规划",
        },
        options=[
            {"label": "去 /ce-apply", "value": "confirm"},
            {"label": "继续改计划", "value": "rework"},
            {"label": "去 /handoff", "value": "handoff"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


def _ask_apply_report(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    return decision_question(
        header="改码已落地。下一步？",
        goal=f"确认 {op}（{arch}）本次 todo 的源码改动",
        background="CodeMap 已刷新。审查是可选的 /ce-review；测试走 /tg-plan（它会读当前计划 md）。",
        decide="建议审查、建议测试、回计划，还是交接？",
        consequences={
            "建议审查": "去 /ce-review 审这次 git diff",
            "建议测试": "去 /tg-plan，TG 自己从计划 md 列出独立测试变量",
            "回计划": "回到 /ce-plan",
            "交接": "写 /handoff",
        },
        options=[
            {"label": "建议审查 /ce-review", "value": "review"},
            {"label": "建议测试 /tg-plan", "value": "confirm"},
            {"label": "回 /ce-plan", "value": "rework"},
            {"label": "去 /handoff", "value": "handoff"},
        ],
    )


def _ask_review_report(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    return decision_question(
        header="审查结论已在对话里。下一步？",
        goal=f"根据 {op}（{arch}）双轴结论决定改码还是测试",
        background="不落盘 ce/review。建议测试时 TG 读本轮对话和若存在的计划 md。",
        decide="建议修改还是建议测试？",
        consequences={
            "建议修改": "去 /ce-plan 或 /ce-apply",
            "建议测试": "去 /tg-plan",
            "交接": "写 /handoff",
        },
        options=[
            {"label": "建议修改", "value": "rework"},
            {"label": "建议测试 /tg-plan", "value": "confirm"},
            {"label": "去 /handoff", "value": "handoff"},
        ],
    )


def _write_yaml_receipt(
    path: Path,
    doc: dict[str, Any],
) -> tuple[Path, dict[Path, bytes | None]]:
    backups = {path: path.read_bytes() if path.is_file() else None}
    _dump(path, doc)
    return path, backups


def _materialize_tg_init(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    tg = tg_root(project_root, arch=_arch(state))
    path = tg / "init.yaml"
    backups = {path: path.read_bytes() if path.is_file() else None}
    try:
        from testcase_agent.init_status import mark_init_confirmed

        mark_init_confirmed(
            tg,
            notes="Confirmed by Pilot primary_interactive Action",
            project_root=project_root,
        )
    except Exception as exc:  # noqa: BLE001
        rollback_primary_decision({"backups": backups})
        return {
            "ok": False,
            "error": "INIT_CONFIRM_DOMAIN_GATE_FAILED",
            "message_zh": str(exc)[:400],
        }
    doc = _load(path)
    if not isinstance(doc, dict):
        rollback_primary_decision({"backups": backups})
        return {
            "ok": False,
            "error": "INIT_YAML_MISSING",
            "message_zh": "确认后仍缺少 tg/init.yaml",
        }
    doc.update(
        {
            "confirmed": True,
            "status": "confirmed",
            "decision": "confirm",
            "confirmed_at": str(doc.get("confirmed_at") or now),
            **identity,
        }
    )
    _dump(path, doc)
    return {"ok": True, "path": path, "backups": backups, "identity": identity}


def _materialize_plan_approve(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    tg = tg_root(project_root, arch=_arch(state))
    path = tg / "plan.md"
    if not path.is_file():
        return {
            "ok": False,
            "error": "PLAN_MD_MISSING",
            "message_zh": "未找到 tg/plan.md，禁止批准",
        }
    backups = {path: path.read_bytes() if path.is_file() else None}
    try:
        from testcase_agent.products import parse_plan_fence, pending_test_harness_gap

        text = path.read_text(encoding="utf-8")
        fence = parse_plan_fence(text)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "PLAN_FENCE_INVALID",
            "message_zh": str(exc)[:400],
        }
    if pending_test_harness_gap(text, fence):
        return {
            "ok": False,
            "error": "TEST_HARNESS_GAP_PENDING",
            "message_zh": "test_harness_gap 未落地，禁止批准规划。先按说明书 /ce-apply 测试脚本仓（可补脚本、改列或随机数生成器）再 /tg-init。",
        }
    from testcase_agent.products import (
        column_names,
        is_plan_approved,
        load_init,
        mapping_as_dict,
        semantic_plan_hash,
        validate_plan_fence,
        validate_plan_prose,
    )

    try:
        init_doc = load_init(tg)
        raw_map = init_doc.get("mapping")
        init_mapping = mapping_as_dict(raw_map) if raw_map is not None else None
        observe_fields = None
        try:
            from testcase_agent import product_uo

            observe_fields = product_uo.replay_observe_fields(
                project_root,
                op_name=str(state.get("op_name") or ""),
                architecture=str(state.get("architecture") or ""),
            )
        except Exception:  # noqa: BLE001
            observe_fields = None
        errors = validate_plan_fence(
            fence,
            init_columns=column_names(init_doc),
            init_mapping=init_mapping,
            observe_fields=observe_fields,
        )
        errors.extend(validate_plan_prose(text, fence))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "PLAN_INVALID",
            "message_zh": str(exc)[:400],
        }
    if errors:
        return {
            "ok": False,
            "error": "PLAN_INVALID",
            "message_zh": "; ".join(str(e) for e in errors[:8]),
        }

    if is_plan_approved(fence):
        return {"ok": True, "path": path, "backups": backups, "identity": identity, "already_approved": True}
    fence["plan_hash"] = semantic_plan_hash(fence)
    fence["approved"] = True
    fence["decision"] = "approve"
    fence["approved_at"] = now
    fence.update({k: v for k, v in identity.items() if v})
    import re as _re

    body = yaml.safe_dump(fence, allow_unicode=True, sort_keys=False).rstrip() + "\n"
    matches = list(_re.finditer(r"```ya?ml\s*\n(.*?)```", text, _re.DOTALL | _re.IGNORECASE))
    if not matches:
        return {
            "ok": False,
            "error": "PLAN_FENCE_MISSING",
            "message_zh": "plan.md 没有 yaml 围栏，禁止批准",
        }
    start, end = matches[-1].span()
    new_text = text[: start] + "```yaml\n" + body + "```" + text[end:]
    path.write_text(new_text, encoding="utf-8")
    return {"ok": True, "path": path, "backups": backups, "identity": identity}


def _materialize_ce_plan_confirm(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    """Write ce-plan-confirmed-v1. Canonical markdown existing is not approval."""
    from code_engineering.apply import write_plan_confirmed
    from code_engineering.plan_md import resolve_active_plan

    arch = _arch(state) or ""
    if not arch:
        return {"ok": False, "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    plan = resolve_active_plan(project_root, architecture=arch, state=state)
    decision = str(identity.get("human_decision_value") or "confirm").strip() or "confirm"
    path = write_plan_confirmed(
        project_root,
        architecture=arch,
        decision=decision,
        plan=plan,
        extra={"confirmed_at": now, **identity},
    )
    backups = {path: None}
    return {"ok": True, "path": path, "backups": backups, "identity": identity}


def _materialize_ce_decision(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    del project_root, state, now
    return {"ok": True, "identity": identity, "backups": {}}


def _hints_tg_init(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        path = tg_root(project_root, arch=_arch(state)) / "init.yaml"
        rel = path.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/tg/init.yaml"
    return [f"Review {rel} before asking the user to enter planning."]


def _hints_plan_approve(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        path = tg_root(project_root, arch=_arch(state)) / "plan.md"
        rel = path.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/tg/plan.md"
    return [f"Review {rel} (prose + YAML fence) before asking the user to start solving."]


def _hints_ce_plan(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        root = ce_root(project_root, arch=_arch(state)) / "plan"
        rel = root.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/ce/plan/"
    return [f"Review {rel}*_plan.md (analysis / todos / 测试内容) before applying."]


def _hints_apply_report(project_root: Path, state: dict[str, Any]) -> list[str]:
    del project_root, state
    return ["Source is already patched. Next is /ce-review or /tg-plan, not a yaml product."]


def _hints_review_report(project_root: Path, state: dict[str, Any]) -> list[str]:
    del project_root, state
    return ["Keep findings in the dialogue. Do not write ce/review."]


SCENARIOS: dict[tuple[str, str], dict[str, Any]] = {
    ("tg-init", "human_confirm"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm"],
        "ask": _ask_tg_init,
        "materialize": _materialize_tg_init,
        "hints": _hints_tg_init,
        "compact": None,
    },
    ("tg-plan", "plan_approve"): {
        "kind": "primary_approve",
        "expected_values": ["approve"],
        "ask": _ask_plan_approve,
        "materialize": _materialize_plan_approve,
        "hints": _hints_plan_approve,
        "compact": None,
    },
    ("ce-plan", "human_confirm"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm"],
        "ask": _ask_ce_plan,
        "materialize": _materialize_ce_plan_confirm,
        "hints": _hints_ce_plan,
        "compact": None,
    },
    ("ce-apply", "apply_report"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm", "review", "handoff"],
        "ask": _ask_apply_report,
        "materialize": _materialize_ce_decision,
        "hints": _hints_apply_report,
        "compact": None,
    },
    ("ce-review", "review_report"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm", "rework", "handoff"],
        "ask": _ask_review_report,
        "materialize": _materialize_ce_decision,
        "hints": _hints_review_report,
        "compact": None,
    },
}

# Unique action ids (only one workflow owns them). Shared ids like
# ``human_confirm`` must be resolved with workflow_id.
_AID_OWNERS: dict[str, list[tuple[str, str]]] = {}
for _key in SCENARIOS:
    _AID_OWNERS.setdefault(_key[1], []).append(_key)
_UNIQUE_ACTIONS = {aid: keys[0] for aid, keys in _AID_OWNERS.items() if len(keys) == 1}

HOSTED_CONFIRM_ACTIONS = frozenset(aid for _, aid in SCENARIOS)
# Backward name: TG-only subset used by a few tests. Facade must not key on this
# for CE — ``human_confirm`` is shared across workflows.
PRIMARY_TG_ACTIONS = frozenset({"human_confirm", "plan_approve"})


def resolve_scenario(
    workflow_id: str,
    action_id: str,
) -> dict[str, Any] | None:
    key = (str(workflow_id or "").strip(), str(action_id or "").strip())
    if key in SCENARIOS:
        return SCENARIOS[key]
    unique = _UNIQUE_ACTIONS.get(key[1])
    if unique:
        return SCENARIOS[unique]
    return None


def lookup_scenario(
    project_root: Path | None,
    action_id: str,
    *,
    workflow_id: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    wid = str(workflow_id or "").strip()
    if not wid and state:
        wid = str(state.get("workflow_id") or "").strip()
    if not wid and project_root is not None:
        try:
            wid = str((load_state(project_root) or {}).get("workflow_id") or "").strip()
        except Exception:  # noqa: BLE001
            wid = ""
    found = resolve_scenario(wid, action_id)
    if found:
        return found
    # Tests / prepare without a workflow: unique actions still resolve.
    unique = _UNIQUE_ACTIONS.get(action_id)
    if unique:
        return SCENARIOS[unique]
    # Shared human_confirm without workflow → TG init (legacy unit tests).
    if action_id == "human_confirm":
        return SCENARIOS[("tg-init", "human_confirm")]
    return None


def is_hosted_confirm(
    project_root: Path | None,
    action_id: str,
    *,
    workflow_id: str = "",
    state: dict[str, Any] | None = None,
) -> bool:
    if action_id not in HOSTED_CONFIRM_ACTIONS:
        return False
    return lookup_scenario(project_root, action_id, workflow_id=workflow_id, state=state) is not None


def build_ask(
    project_root: Path,
    state: dict[str, Any] | None = None,
    *,
    workflow_id: str = "",
    action_id: str = "",
) -> dict[str, Any]:
    state = dict(state or {})
    if project_root is not None and not state.get("workflow_id"):
        try:
            loaded = load_state(project_root) or {}
            for key in ("workflow_id", "architecture", "op_name", "run_id"):
                if not state.get(key) and loaded.get(key):
                    state[key] = loaded[key]
        except Exception:  # noqa: BLE001
            pass
    aid = str(action_id or state.get("action_id") or "").strip()
    scenario = lookup_scenario(project_root, aid, workflow_id=workflow_id, state=state)
    if scenario is None:
        from ascendc_pilot.human_voice import build_generic_interactive_ask

        return build_generic_interactive_ask(aid or "confirm")
    ask_fn: AskFn = scenario["ask"]
    return ask_fn(project_root, state)


def interaction_kind(
    project_root: Path | None,
    action_id: str,
    *,
    workflow_id: str = "",
    state: dict[str, Any] | None = None,
) -> str:
    scenario = lookup_scenario(project_root, action_id, workflow_id=workflow_id, state=state)
    if scenario:
        return str(scenario["kind"])
    return "primary_confirm"


def expected_affirmative(
    project_root: Path | None,
    action_id: str,
    *,
    workflow_id: str = "",
    state: dict[str, Any] | None = None,
) -> list[str]:
    scenario = lookup_scenario(project_root, action_id, workflow_id=workflow_id, state=state)
    if scenario:
        return list(scenario["expected_values"])
    return ["confirm"]


def primary_interactive_steps(
    action_id: str,
    project_root: Path,
    result: dict[str, Any],
    *,
    workflow_id: str = "",
) -> list[str]:
    root = project_root.expanduser().resolve()
    req = result.get("human_interaction_request") or {}
    rid = str(req.get("request_id") or "<request_id>")
    state = load_state(project_root) or {}
    scenario = lookup_scenario(
        project_root,
        action_id,
        workflow_id=workflow_id or str(result.get("workflow_id") or ""),
        state=state,
    )
    hints: list[str] = []
    expected = ["confirm"]
    kind_label = "confirm"
    if scenario:
        hints_fn: HintsFn = scenario["hints"]
        hints = hints_fn(root, state)
        expected = list(scenario["expected_values"])
        kind_label = expected[0] if expected else "confirm"
    option_hint = " | ".join([*expected, "rework", "stop"])
    steps = list(hints)
    steps.extend(
        [
            f"Host must surface AskQuestion ({option_hint}) from ask_question.options verbatim.",
            f"Host records the click via the question UI (or `pilot_cli` interpret-user-turn if the user typed in chat). request_id={rid} project={root.as_posix()}",
            f"Only after HumanDecisionReceipt for `{kind_label}`, Host `pilot_run` finalizes `{action_id}`.",
            "For `rework` or `stop`, do not finalize. Primary must not Write canonical confirmation YAML.",
        ]
    )
    return steps


def materialize_primary_decision(project_root: Path, action_id: str) -> dict[str, Any]:
    """Write the affirmative decision contract immediately before finalization."""
    project_root = Path(project_root).expanduser().resolve()
    state = load_state(project_root) or {}
    session = _session(project_root, state, action_id)
    if not session:
        return {
            "ok": False,
            "error": "PRIMARY_DECISION_SESSION_MISSING",
            "message_zh": "缺少 primary Action prepare session；请先运行不带 --finalize 的 run-action",
        }
    if str(session.get("action_id") or "") != action_id:
        return {"ok": False, "error": "PRIMARY_DECISION_SESSION_MISMATCH"}

    scenario = lookup_scenario(project_root, action_id, state=state)
    if scenario is None:
        return {"ok": False, "error": "NOT_HOSTED_CONFIRM_ACTION", "action_id": action_id}

    skip_ask = action_id in {
        "human_confirm",
        "plan_approve",
        "apply_report",
        "review_report",
    } and not hosted_confirm_should_ask(
        project_root, state, action_id=action_id
    )
    host_owned = action_id in {"human_confirm", "plan_approve"}
    # Host-owned confirms still need a HumanDecisionReceipt. skip_ask only
    # means "don't use OpenCode native AskQuestion", not "skip the receipt".
    if skip_ask and not host_owned:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        identity = _identity(session)
        identity["human_decision_request_id"] = "auto-skip-no-material"
        materialize: MaterializeFn = scenario["materialize"]
        return materialize(project_root, state, identity, now)

    if _confirm_already_recorded(project_root, action_id, state):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        identity = _identity(session)
        identity["human_decision_request_id"] = "already-recorded"
        materialize: MaterializeFn = scenario["materialize"]
        return materialize(project_root, state, identity, now)

    from ascendc_pilot.human_interaction import require_decision_receipt

    receipt = require_decision_receipt(
        project_root,
        expected_values=list(scenario["expected_values"]),
        expected_action_id=action_id,
        expected_kind=str(scenario["kind"]),
        consume=False,
    )
    if not receipt.get("ok"):
        return receipt

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    identity = _identity(session)
    identity["human_decision_request_id"] = str(receipt.get("request_id") or "")
    identity["human_decision_value"] = str(receipt.get("value") or "")
    materialize: MaterializeFn = scenario["materialize"]
    return materialize(project_root, state, identity, now)


def rollback_primary_decision(materialized: dict[str, Any]) -> None:
    backups = materialized.get("backups")
    if not isinstance(backups, dict):
        return
    for path, previous in backups.items():
        if not isinstance(path, Path):
            continue
        if isinstance(previous, bytes):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(previous)
        elif path.is_file():
            path.unlink()


def compact_key(
    project_root: Path | None,
    action_id: str,
    *,
    workflow_id: str = "",
    state: dict[str, Any] | None = None,
) -> str | None:
    scenario = lookup_scenario(project_root, action_id, workflow_id=workflow_id, state=state)
    if not scenario:
        return None
    return scenario.get("compact")
