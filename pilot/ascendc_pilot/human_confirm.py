"""Host-owned primary confirmation.

One module derives AskQuestion copy, affirmative values, and the receipt
files from ``(workflow_id, action_id)``. Action ids stay unprefixed
(``human_confirm`` is shared); Primary only surfaces ``ask_question.options``
and never writes the canonical YAML itself.
"""

from __future__ import annotations

import hashlib
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


def _scenario_ids(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        doc = _load(ce_root(project_root, arch=_arch(state)) / "scenarios" / "scenario_set.yaml")
    except Exception:  # noqa: BLE001
        return []
    ids: list[str] = []
    for row in doc.get("items") or doc.get("scenarios") or []:
        if isinstance(row, dict) and row.get("id"):
            ids.append(str(row["id"]))
        elif isinstance(row, str) and row.strip():
            ids.append(row.strip())
    for key in ("ids", "scenario_ids"):
        val = doc.get(key)
        if isinstance(val, list):
            ids.extend(str(x) for x in val if x)
    seen: set[str] = set()
    out: list[str] = []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _ask_tg_init(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    gctx = _goal_context(project_root)
    goal = str(gctx.get("label_zh") or "") or f"为 {op}（{arch}）绑定测试脚本并规划义务"
    n = _declared_key_count(project_root)
    scale = f"（声明域约 {n} 个合法 Key，不是默认 T）" if n else ""
    background = f"init.yaml 已写出{scale}。"
    if gctx.get("progress_line"):
        background = f"{gctx['progress_line']} {background}"
    return decision_question(
        header="init.yaml 已写出，是否进入规划？",
        goal=goal,
        background=background,
        decide="是否进入「规划测试义务」阶段？",
        consequences={
            "确认进入规划": "开始规划测试义务（tg-plan）",
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
    goal = str(gctx.get("label_zh") or "") or f"为 {op}（{arch}）按列规划测试义务"
    background = "测试义务规划已生成，等待你批准后才能开始求解与生成用例。"
    if gctx.get("progress_line"):
        background = f"{gctx['progress_line']} {background}"
    return decision_question(
        header="规划已就绪，是否开始求解？",
        goal=goal,
        background=background,
        decide="是否批准规划并进入「求解并生成用例」？",
        consequences={
            "批准并开始求解": "启动求解与 Host Replay（tg-solve）",
            "返工": "回到规划阶段调整义务",
            "停止": "结束本次目标（不开始求解）",
        },
        options=[
            {"label": "批准并开始求解", "value": "approve"},
            {"label": "返工规划", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


def _ask_ce_intent(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    return decision_question(
        header="变更计划已审阅，是否确认？",
        goal=f"确认 {op}（{arch}）的改码范围、锚点与验收条件",
        background="特性分解已经过审查。确认后冻结变更计划并写入 ce/intent/plan.md；返工则回到分解/审查。",
        decide="是否确认这份变更计划？",
        consequences={
            "确认变更计划": "冻结范围与验收条件，后续可按计划改码/验证",
            "返工": "不冻结，回到特性分解或审查",
            "停止": "结束本次定位，不冻结计划",
        },
        options=[
            {"label": "确认变更计划", "value": "confirm"},
            {"label": "返工计划", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


def _ask_scenario_confirm(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    ids = _scenario_ids(project_root, state)
    listed = "、".join(ids) if ids else "（尚未读到场景骨架）"
    return decision_question(
        header="是否确认这些精度/性能测试场景？",
        goal=f"为 {op}（{arch}）的本次改动确定要测的精度/性能场景",
        background=f"引擎已推断场景骨架：{listed}。确认后才会按这些场景挂验证义务；不是全量 TilingKey 闭环。",
        decide="是否确认这组场景与条数预算？",
        consequences={
            "确认这些场景": "按已列场景继续建立验证义务",
            "返工": "回到场景推断，增删场景后再确认",
            "停止": "结束本次影响分析",
        },
        options=[
            {"label": "确认这些场景", "value": "confirm"},
            {"label": "返工场景", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


def _intent_doc(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    return _load(ce_root(project_root, arch=_arch(state)) / "intent" / "intent.yaml")


def material_decisions(intent: dict[str, Any]) -> list[Any]:
    """Questions that fork two legal implementation directions (not facts)."""
    raw = intent.get("material_decisions")
    if isinstance(raw, list) and raw:
        return [row for row in raw if row]
    open_q = intent.get("open_questions") or []
    if not isinstance(open_q, list):
        return []
    out = []
    for row in open_q:
        if isinstance(row, dict) and str(row.get("kind") or "").lower() in {"fact", "lookup"}:
            continue
        if row:
            out.append(row)
    return out


def grill_should_ask(project_root: Path, state: dict[str, Any], *, action_id: str = "") -> bool:
    """False → 0 human grill turns (complete PR / no material fork). CE-intent only."""
    if str(state.get("workflow_id") or "").strip() != "ce-intent":
        return True
    intent = _intent_doc(project_root, state)
    decisions = material_decisions(intent)
    complete = bool(
        intent.get("in_scope") and intent.get("out_of_scope") and intent.get("acceptance")
    )
    if action_id == "human_confirm":
        grilled = _load(ce_root(project_root, arch=_arch(state)) / "intent" / "grill_confirmation.yaml")
        prior = grilled.get("material_decision_count")
        if complete and not decisions:
            return False
        if prior is not None and int(prior or 0) == len(decisions):
            return False
        return bool(decisions)
    if complete and not decisions:
        return False
    return True


def _ask_grill_confirm(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    intent = _intent_doc(project_root, state)
    decisions = material_decisions(intent)[:5]
    n = len(decisions)
    listed = "；".join(
        str(row.get("question") or row.get("id") or row)[:80]
        for row in decisions
        if row
    ) or "无分叉决策"
    return decision_question(
        header="需求是否已经问清，可以分解特性？",
        goal=f"一次确认 {op}（{arch}）的 3–5 个会分叉实现方向的决策",
        background=f"本轮只问 material decision（{n} 题）：{listed}。事实类问题走 CodeMap / ro-search，不问人。",
        decide="是否确认这组决策并进入分解？",
        consequences={
            "确认需求已问清": "进入特性分解；未决分叉必须为空",
            "返工": "回到问需求，继续推进设计树",
            "停止": "结束本次定位，不分解",
        },
        options=[
            {"label": "确认需求已问清", "value": "confirm"},
            {"label": "返工继续问", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


def _ask_apply_report(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    return decision_question(
        header="改码与审查已完成。结论已在对话里；是否落盘报告并继续影响分析？",
        goal=f"确认 {op}（{arch}）本次改动与双轴审查结论",
        background="源码已改、CodeMap 已刷新。审查结论默认在会话中陈述。精度/性能仍要 /ce-impact → /ce-verify。",
        decide="只看结论，还是把审查报告写入 ce/review 后再进入 /ce-impact？",
        consequences={
            "只看结论": "不填审查 YAML，写入交接，后续步骤 /ce-impact",
            "落盘审查报告": "把 session 里的 findings 写入 ce/review，再进入 /ce-impact",
            "返工": "不交接，回到改码",
            "停止": "结束本次改码，不进入影响分析",
        },
        options=[
            {"label": "只看结论，进入影响分析", "value": "confirm"},
            {"label": "落盘审查报告，进入影响分析", "value": "persist"},
            {"label": "返工改码", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


def _ask_review_persist(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    return decision_question(
        header="审查结论已给出。是否把报告落到磁盘？",
        goal=f"告诉你 {op}（{arch}）哪里有问题",
        background="Spec / Standards 结论在对话里（path:line）。默认不写 ce/review YAML。",
        decide="只看结论，还是落盘审查报告？",
        consequences={
            "只看结论": "保持 skeleton，结束本次检视",
            "落盘审查报告": "把 session findings 写入 ce/review/*.yaml",
            "返工": "回到审查",
            "停止": "结束本次检视",
        },
        options=[
            {"label": "只看结论", "value": "confirm"},
            {"label": "落盘审查报告", "value": "persist"},
            {"label": "返工审查", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
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
        from testcase_agent.products import parse_plan_fence, pending_harness_intent

        text = path.read_text(encoding="utf-8")
        fence = parse_plan_fence(text)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "PLAN_FENCE_INVALID",
            "message_zh": str(exc)[:400],
        }
    if pending_harness_intent(text, fence):
        return {
            "ok": False,
            "error": "HARNESS_INTENT_PENDING",
            "message_zh": "harness_intent 未落地，禁止批准规划。先 CE apply 测试脚本仓再 /tg-init。",
        }
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


def _materialize_ce_intent(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    path = ce_root(project_root, arch=_arch(state)) / "intent" / "confirmation.yaml"
    doc = {
        "schema": "ce-intent-confirmation/v1",
        "status": "confirmed",
        "confirmed_by": "human",
        "confirmed_at": now,
        "decision": "confirm",
        **identity,
        "artifact_identity": identity,
    }
    path, backups = _write_yaml_receipt(path, doc)
    from code_engineering.intent import write_intent_plan

    plan = write_intent_plan(project_root, architecture=_arch(state))
    if not plan.get("ok"):
        return {
            "ok": False,
            "error": str(plan.get("error") or "INTENT_PLAN_WRITE_FAILED"),
            "message_zh": "变更计划 plan.md 未能写入，禁止确认。",
            "plan": plan,
        }
    return {
        "ok": True,
        "path": path,
        "plan_path": plan.get("artifact"),
        "backups": backups,
        "identity": identity,
    }


def _materialize_scenario_confirm(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    ids = _scenario_ids(project_root, state)
    path = ce_root(project_root, arch=_arch(state)) / "scenarios" / "confirmation.yaml"
    doc = {
        "schema": "ce-scenario-confirm/v1",
        "status": "confirmed",
        "confirmed_by": "human",
        "confirmed_at": now,
        "scenario_ids": ids,
        "decision": "confirm",
        **identity,
        "artifact_identity": identity,
    }
    path, backups = _write_yaml_receipt(path, doc)
    return {"ok": True, "path": path, "backups": backups, "identity": identity}


MaterializeFn = Callable[[Path, dict[str, Any], dict[str, str], str], dict[str, Any]]
AskFn = Callable[[Path, dict[str, Any]], dict[str, Any]]
HintsFn = Callable[[Path, dict[str, Any]], list[str]]


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


def _hints_ce_intent(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        root = ce_root(project_root, arch=_arch(state)) / "intent"
        rel = root.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/ce/intent/"
    return [f"Review {rel}feature_decomposition.yaml and plan_review.yaml before asking to freeze the plan. Confirm writes ce/intent/plan.md."]


def _hints_scenario_confirm(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        path = ce_root(project_root, arch=_arch(state)) / "scenarios" / "scenario_set.yaml"
        rel = path.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/ce/scenarios/scenario_set.yaml"
    return [f"Review {rel} (ids, knobs, budget). This is not tilingkey full coverage."]


def _materialize_grill_confirm(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    ce = ce_root(project_root, arch=_arch(state))
    intent = _load(ce / "intent" / "intent.yaml")
    decisions = material_decisions(intent)
    open_q = intent.get("open_questions") or []
    if isinstance(open_q, list) and open_q and decisions:
        return {
            "ok": False,
            "error": "GRILL_OPEN",
            "reason_code": "GRILL_OPEN",
            "message_zh": "未决问题未闭合，不能进入特性分解",
            "open_question_count": len(open_q),
        }
    path = ce / "intent" / "grill_confirmation.yaml"
    doc = {
        "schema": "ce-intent-grill-confirmation/v1",
        "status": "confirmed",
        "confirmed_by": "human" if decisions else "auto_skip",
        "confirmed_at": now,
        "decision": "confirm" if decisions else "skipped_no_material",
        "material_decision_count": len(decisions),
        **identity,
        "artifact_identity": identity,
    }
    path, backups = _write_yaml_receipt(path, doc)
    return {"ok": True, "path": path, "backups": backups, "identity": identity}


def _materialize_apply_report(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    ce = ce_root(project_root, arch=_arch(state))
    path = ce / "apply" / "report.yaml"
    doc = {
        "schema": "ce-apply-report/v1",
        "status": "reported",
        "confirmed_by": "human",
        "confirmed_at": now,
        "decision": "confirm",
        "next_slash": "/ce-impact",
        **identity,
        "artifact_identity": identity,
    }
    path, backups = _write_yaml_receipt(path, doc)
    try:
        from code_engineering.handoff import write_session_handoff

        from code_engineering.review_persist import persist_review_reports

        persist_review_reports(
            project_root,
            architecture=_arch(state) or "",
            run_id=str(state.get("run_id") or ""),
            persist=str(identity.get("human_decision_value") or "") == "persist",
        )
        write_session_handoff(
            project_root,
            architecture=_arch(state),
            next_slash="/ce-impact",
            artifact_paths=[
                "ce/intent/plan.md",
                "ce/apply/todo.md",
                "ce/apply/patch_report.yaml",
                "ce/apply/codemap_refresh.yaml",
            ],
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "path": path, "backups": backups, "identity": identity}


def _hints_grill_confirm(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        path = ce_root(project_root, arch=_arch(state)) / "intent" / "intent.yaml"
        rel = path.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/ce/intent/intent.yaml"
    return [f"Review {rel} in_scope / out_of_scope / acceptance; open_questions must be empty."]


def _hints_apply_report(project_root: Path, state: dict[str, Any]) -> list[str]:
    del project_root, state
    return ["Speak path:line findings. Persist review YAML only if the user chose 落盘审查报告."]


def _materialize_review_persist(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    from code_engineering.review_persist import persist_review_reports

    result = persist_review_reports(
        project_root,
        architecture=_arch(state) or "",
        run_id=str(state.get("run_id") or ""),
        persist=str(identity.get("human_decision_value") or "") == "persist",
    )
    path = Path(str(result.get("artifact") or ""))
    backups = {path: path.read_bytes() if path.is_file() else None} if path else {}
    return {"ok": bool(result.get("ok")), "path": path, "backups": backups, "identity": identity, **result}


def _hints_review_persist(project_root: Path, state: dict[str, Any]) -> list[str]:
    del project_root, state
    return ["Speak path:line findings. Persist ce/review/*.yaml only if the user chose 落盘审查报告."]


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
    ("ce-intent", "human_confirm"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm"],
        "ask": _ask_ce_intent,
        "materialize": _materialize_ce_intent,
        "hints": _hints_ce_intent,
        "compact": None,
    },
    ("ce-impact", "scenario_confirm"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm"],
        "ask": _ask_scenario_confirm,
        "materialize": _materialize_scenario_confirm,
        "hints": _hints_scenario_confirm,
        "compact": None,
    },
    ("ce-intent", "grill_confirm"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm"],
        "ask": _ask_grill_confirm,
        "materialize": _materialize_grill_confirm,
        "hints": _hints_grill_confirm,
        "compact": None,
    },
    ("ce-apply", "apply_report"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm", "persist"],
        "ask": _ask_apply_report,
        "materialize": _materialize_apply_report,
        "hints": _hints_apply_report,
        "compact": None,
    },
    ("ce-review", "review_persist"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm", "persist"],
        "ask": _ask_review_persist,
        "materialize": _materialize_review_persist,
        "hints": _hints_review_persist,
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
            f"Host records answer: acp answer --request-id {rid} --value <选中> --project {root.as_posix()}",
            f"Only after HumanDecisionReceipt for `{kind_label}`, run: "
            f"acp run-action {action_id} --finalize --project {root.as_posix()}",
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

    skip_gate = action_id in {"grill_confirm", "human_confirm"} and not grill_should_ask(
        project_root, state, action_id=action_id
    )
    if skip_gate:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        identity = _identity(session)
        identity["human_decision_request_id"] = "auto-skip-no-material"
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
