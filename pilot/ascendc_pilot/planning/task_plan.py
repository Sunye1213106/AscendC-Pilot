# -*- coding: utf-8 -*-
"""Persist an explicitly listed workflow Task Plan.

Primary decides what the user means via OpenCode Todos. This module does not
parse natural language or invent prerequisite slashes; it records the listed
workflow ids, optional PR acquire tool-step, progress, and acceptance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ascendc_pilot.paths import AGENT_DIR

TASK_PLAN_SCHEMA = "pilot-task-plan/v1"

PUBLIC_PLAN_TEST_GENERATION: tuple[dict[str, str], ...] = (
    {"id": "acquire_change", "summary_zh": "获取 PR 与代码"},
    {"id": "ensure_knowledge", "summary_zh": "建立算子理解"},
    {"id": "review_change", "summary_zh": "审查改动并确定影响范围"},
    {"id": "generate_cases", "summary_zh": "规划并生成测试用例"},
    {"id": "validate_cases", "summary_zh": "回放验证"},
    {"id": "deliver", "summary_zh": "输出结果"},
)

PUBLIC_PLAN_REVIEW: tuple[dict[str, str], ...] = (
    {"id": "acquire_change", "summary_zh": "获取改动"},
    {"id": "ensure_knowledge", "summary_zh": "建立算子理解"},
    {"id": "review_change", "summary_zh": "审查改动"},
    {"id": "deliver", "summary_zh": "输出结论"},
)

PUBLIC_PLAN_IMPLEMENT: tuple[dict[str, str], ...] = (
    {"id": "ensure_knowledge", "summary_zh": "建立算子理解"},
    {"id": "plan_change", "summary_zh": "问清需求并写出计划"},
    {"id": "apply_change", "summary_zh": "按计划改码"},
    {"id": "deliver", "summary_zh": "输出结果"},
)

PUBLIC_PLAN_KNOWLEDGE: tuple[dict[str, str], ...] = (
    {"id": "ensure_knowledge", "summary_zh": "建立算子理解"},
    {"id": "deliver", "summary_zh": "输出结果"},
)

_WORKFLOW_TO_PUBLIC = {
    "workspace_acquire": "acquire_change",
    "goal-intake": "acquire_change",
    "uo-init": "ensure_knowledge",
    "uo-update": "ensure_knowledge",
    "ce-review": "review_change",
    "ce-plan": "plan_change",
    "ce-apply": "apply_change",
    "tg-init": "generate_cases",
    "tg-plan": "generate_cases",
    "tg-solve": "validate_cases",
}

_STEP_ORDER = (
    "workspace_acquire",
    "uo-init",
    "uo-update",
    "uo-investigate",
    "ce-plan",
    "ce-apply",
    "ce-review",
    "tg-init",
    "tg-plan",
    "tg-solve",
    "handoff",
)


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def task_plan_path(project_root: Path | str) -> Path:
    return Path(project_root).expanduser().resolve() / AGENT_DIR / "control" / "task_plan.yaml"


def load_task_plan(project_root: Path | str) -> dict[str, Any] | None:
    path = task_plan_path(project_root)
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def write_task_plan(project_root: Path | str, doc: dict[str, Any]) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    path = task_plan_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(doc)
    payload.setdefault("schema", TASK_PLAN_SCHEMA)
    payload["updated_at"] = _now()
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return payload


def public_plan_for(
    capabilities: list[str] | None = None,
    *,
    workflows: list[str] | None = None,
) -> list[dict[str, Any]]:
    wids = {str(w).strip() for w in (workflows or []) if str(w).strip()}
    caps = set(capabilities or [])
    if not wids and caps:
        from ascendc_pilot.harness.intent import workflows_from_capabilities

        wids = set(workflows_from_capabilities(list(caps)))
    if wids & {"tg-init", "tg-plan", "tg-solve"} or "test_generation" in caps:
        spec = PUBLIC_PLAN_TEST_GENERATION
    elif wids & {"ce-plan", "ce-apply"} or "implement" in caps:
        spec = PUBLIC_PLAN_IMPLEMENT
    elif "ce-review" in wids or "code_review" in caps:
        spec = PUBLIC_PLAN_REVIEW
    else:
        spec = PUBLIC_PLAN_KNOWLEDGE
    rows = [
        {"id": item["id"], "summary_zh": item["summary_zh"], "status": "pending"}
        for item in spec
    ]
    if rows:
        rows[0]["status"] = "in_progress"
    return rows


def plan_kind(
    capabilities: list[str] | None = None,
    *,
    workflows: list[str] | None = None,
) -> str:
    wids = {str(w).strip() for w in (workflows or []) if str(w).strip()}
    caps = set(capabilities or [])
    if not wids and caps:
        from ascendc_pilot.harness.intent import workflows_from_capabilities

        wids = set(workflows_from_capabilities(list(caps)))
    if wids & {"tg-init", "tg-plan", "tg-solve"} or "test_generation" in caps:
        return "generate_change_tests"
    if wids & {"ce-plan", "ce-apply"} or "implement" in caps:
        return "implement_change"
    if "ce-review" in wids or "code_review" in caps:
        return "review_change"
    return "ensure_knowledge"


def plan_for(
    llm_intent: dict[str, Any],
    available: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist explicitly listed workflows. Do not invent prerequisite slashes.

    ``llm_intent`` is a compatibility API name. No NL parsing happens here.
    """
    from ascendc_pilot.harness.intent import (
        WORKFLOW_SUMMARY_ZH,
        capabilities_from_workflows,
    )

    del available
    raw_wfs = [
        str(w).strip()
        for w in (llm_intent.get("needed_workflows") or [])
        if str(w).strip()
    ]
    caps = [
        str(c).strip()
        for c in (llm_intent.get("needed_capabilities") or [])
        if str(c).strip()
    ]
    selected: list[str] = []
    for wid in raw_wfs:
        if not wid or wid in {"uo-query", "goal-impact"}:
            continue
        if wid not in selected:
            selected.append(wid)

    source = llm_intent.get("source") if isinstance(llm_intent.get("source"), dict) else {}

    targets: list[dict[str, Any]] = []
    for raw in llm_intent.get("operator_targets") or []:
        if not isinstance(raw, dict):
            continue
        root = str(raw.get("operator_root") or raw.get("project") or "").strip()
        arch = str(raw.get("architecture") or "").strip()
        if not root or not arch:
            continue
        targets.append(
            {
                "operator_root": root,
                "operator_name": str(raw.get("operator_name") or Path(root).name),
                "architecture": arch,
            }
        )

    steps: list[dict[str, Any]] = []

    def _add(
        wid: str,
        *,
        kind: str = "workflow",
        summary_zh: str = "",
        target: dict[str, Any] | None = None,
        index: int | None = None,
    ) -> None:
        sid = wid if index is None else f"{wid}#{index}"
        if any(str(s.get("id")) == sid for s in steps):
            return
        label = summary_zh or WORKFLOW_SUMMARY_ZH.get(wid, wid)
        if target is not None:
            label = f"{label}（{target['operator_name']}/{target['architecture']}）"
        step: dict[str, Any] = {
            "id": sid,
            "kind": kind,
            "workflow_id": wid if kind == "workflow" else "",
            "summary_zh": label,
            "status": "pending",
        }
        if target is not None:
            step["project"] = target["operator_root"]
            step["architecture"] = target["architecture"]
        steps.append(step)

    if str(source.get("kind") or "").strip().lower() in {"pull_request", "pr"}:
        _add("workspace_acquire", kind="harness_action", summary_zh="获取隔离 PR workspace")

    ordered = [w for w in _STEP_ORDER if w in selected]
    ordered.extend([w for w in selected if w not in _STEP_ORDER and w != "workspace_acquire"])
    if len(targets) > 1:
        for index, target in enumerate(targets):
            for wid in ordered:
                _add(wid, target=target, index=index)
    else:
        target = targets[0] if targets else None
        for wid in ordered:
            _add(wid, target=target)

    if steps:
        for step in steps:
            if str(step.get("status")) == "pending":
                step["status"] = "in_progress"
                break

    wids_in_plan = [
        str(s.get("workflow_id") or s.get("id") or "")
        for s in steps
        if str(s.get("kind") or "workflow") == "workflow"
    ]
    derived_caps = capabilities_from_workflows(wids_in_plan) or caps
    kind = plan_kind(derived_caps, workflows=wids_in_plan)
    acceptance: list[str]
    if "test_generation" in derived_caps or any(w.startswith("tg-") for w in wids_in_plan):
        acceptance = ["required_obligations_covered", "cases_validated"]
    elif "ce-review" in wids_in_plan or "code_review" in derived_caps:
        acceptance = ["review_delivered"]
    elif "implement" in derived_caps or any(w in {"ce-plan", "ce-apply"} for w in wids_in_plan):
        acceptance = ["change_applied"]
    else:
        acceptance = ["knowledge_ready"]

    return {
        "schema": TASK_PLAN_SCHEMA,
        "kind": kind,
        "needed_workflows": list(selected),
        "needed_capabilities": list(derived_caps),
        "steps": steps,
        "operator_targets": targets,
        "acceptance": acceptance,
        "acceptance_status": {item: "pending" for item in acceptance},
        "source": dict(source),
        "created_at": _now(),
    }


def current_workflow_id(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ""
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("status") or "") not in {"passed", "skipped"}:
            if str(step.get("kind") or "workflow") == "workflow":
                return str(step.get("workflow_id") or step.get("id") or "")
            continue
    return ""


def current_step(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not plan:
        return None
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("status") or "") not in {"passed", "skipped"}:
            if str(step.get("kind") or "workflow") == "workflow":
                return dict(step)
            continue
    return None


def mark_step_passed(plan: dict[str, Any], step_id: str) -> dict[str, Any]:
    """Mark a plan step passed and advance the next pending step."""
    steps = [dict(s) for s in (plan.get("steps") or []) if isinstance(s, dict)]
    found = False
    for i, step in enumerate(steps):
        if str(step.get("id") or step.get("workflow_id") or "") != str(step_id):
            continue
        found = True
        step["status"] = "passed"
        for nxt in steps[i + 1 :]:
            if str(nxt.get("status") or "") in {"passed", "skipped"}:
                continue
            nxt["status"] = "in_progress"
            break
        break
    if not found:
        for i, step in enumerate(steps):
            if str(step.get("workflow_id") or "") != str(step_id):
                continue
            step["status"] = "passed"
            for nxt in steps[i + 1 :]:
                if str(nxt.get("status") or "") in {"passed", "skipped"}:
                    continue
                nxt["status"] = "in_progress"
                break
            found = True
            break
    plan = dict(plan)
    plan["steps"] = steps
    remaining = [
        s
        for s in steps
        if str(s.get("status") or "") not in {"passed", "skipped"}
    ]
    plan["status"] = "active" if remaining else "steps_complete"
    return plan


def _ledger_required_covered(project_root: Path) -> bool:
    try:
        from ascendc_pilot.obligations.ledger import load_ledger

        ledger = load_ledger(project_root)
    except Exception:  # noqa: BLE001
        return False
    items = ledger.get("items") if isinstance(ledger, dict) else {}
    if not isinstance(items, dict) or not items:
        return False
    for row in items.values():
        if not isinstance(row, dict):
            return False
        if str(row.get("status") or "") != "verified":
            return False
    return True


def _cases_validated(project_root: Path, architecture: str) -> bool:
    try:
        from ascendc_pilot.actions.scenario_certificate import evaluate_scenario_certificate

        cert = evaluate_scenario_certificate(project_root, architecture=architecture or None)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(cert, dict):
        return False
    if cert.get("ok"):
        return True
    return bool(cert.get("construction_complete")) and bool(
        cert.get("replay_target_receipts_all_pass")
    )


def _knowledge_ready(project_root: Path, architecture: str) -> bool:
    try:
        from ascendc_pilot.planning.prerequisites import available_state

        avail = available_state(project_root, architecture=architecture)
    except Exception:  # noqa: BLE001
        avail = {}
    if not avail.get("has_uo"):
        return False
    try:
        from ascendc_pilot.paths import uo_root

        checks = uo_root(project_root, arch=architecture or None) / "checks" / "integrity.yaml"
        if not checks.is_file():
            return True
        doc = yaml.safe_load(checks.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            return False
        if doc.get("ok") is True or doc.get("passed") is True:
            return True
        return str(doc.get("status") or "").lower() in {"passed", "ok", "pass"}
    except Exception:  # noqa: BLE001
        return True


def _change_applied(project_root: Path, architecture: str) -> bool:
    try:
        import sys

        repo = Path(__file__).resolve().parents[3]
        ce = repo / "engines" / "code-engineering"
        if str(ce) not in sys.path:
            sys.path.insert(0, str(ce))
        from code_engineering.plan_md import all_todos, list_plan_files, unfinished_todos

        files = list_plan_files(project_root, architecture)
        if not files:
            return False
        saw = False
        for path in files:
            todos = all_todos(path)
            if todos:
                saw = True
            if unfinished_todos(path):
                return False
        return saw
    except Exception:  # noqa: BLE001
        return False


def _review_delivered(project_root: Path) -> bool:
    try:
        from ascendc_pilot.user_goal import load_user_goal

        goal = load_user_goal(project_root) or {}
        arts = goal.get("artifacts") if isinstance(goal.get("artifacts"), dict) else {}
        return bool(arts.get("review") or arts.get("ce_review") or arts.get("review_report"))
    except Exception:  # noqa: BLE001
        return False


def evaluate_acceptance(
    plan: dict[str, Any] | None,
    project_root: Path | str | None = None,
    *,
    architecture: str = "",
) -> dict[str, str]:
    """Evaluate Goal acceptance predicates. Never infer pass from empty remaining steps."""
    items = [str(k) for k in ((plan or {}).get("acceptance") or [])]
    out = {k: "pending" for k in items}
    if not items or project_root is None:
        return out
    root = Path(project_root).expanduser().resolve()
    arch = str(architecture or "").strip()
    for key in items:
        ok = False
        if key == "required_obligations_covered":
            ok = _ledger_required_covered(root)
        elif key == "cases_validated":
            ok = _cases_validated(root, arch)
        elif key == "knowledge_ready":
            ok = _knowledge_ready(root, arch)
        elif key == "change_applied":
            ok = _change_applied(root, arch)
        elif key == "review_delivered":
            ok = _review_delivered(root)
        out[key] = "passed" if ok else "pending"
    return out


def acceptance_failure_zh(plan: dict[str, Any] | None, status: dict[str, str] | None = None) -> str:
    acc = dict(status or (plan or {}).get("acceptance_status") or {})
    missing: list[str] = []
    labels = {
        "required_obligations_covered": "测试义务未闭合",
        "cases_validated": "缺少回放验证收据",
        "knowledge_ready": "算子理解尚未就绪",
        "change_applied": "改码计划还有未完成项",
        "review_delivered": "还没有审查结论",
    }
    for key in (plan or {}).get("acceptance") or []:
        if str(acc.get(key) or "") != "passed":
            missing.append(labels.get(str(key), str(key)))
    if not missing:
        return ""
    return "目标尚未完成：" + "；".join(missing) + "。"


def acceptance_satisfied(
    plan: dict[str, Any] | None,
    project_root: Path | str | None = None,
    *,
    architecture: str = "",
) -> bool:
    if not plan:
        return False
    items = [str(k) for k in (plan.get("acceptance") or [])]
    if not items:
        steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
        if not steps:
            return False
        return all(str(s.get("status") or "") in {"passed", "skipped"} for s in steps)
    evaluated = evaluate_acceptance(plan, project_root, architecture=architecture)
    if project_root is None:
        acc = dict(plan.get("acceptance_status") or {})
        return all(str(acc.get(k) or "") == "passed" for k in items)
    return all(str(evaluated.get(k) or "") == "passed" for k in items)


def executed_public_ids(plan: dict[str, Any] | None) -> set[str]:
    """Public Todo ids whose corresponding Task Plan steps have already run."""
    out: set[str] = set()
    if not plan:
        return out
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("status") or "") not in {"passed", "skipped"}:
            continue
        sid = str(step.get("id") or step.get("workflow_id") or "").strip()
        pid = public_id_for_workflow(sid)
        if pid:
            out.add(pid)
        if sid == "workspace_acquire":
            out.add("acquire_change")
        if sid in {"uo-init", "uo-update"}:
            out.add("ensure_knowledge")
        if sid == "tg-solve":
            out.add("generate_cases")
            out.add("validate_cases")
    return out


def public_id_for_workflow(workflow_id: str) -> str:
    return _WORKFLOW_TO_PUBLIC.get(str(workflow_id or "").strip(), "")


def invalidate_from(plan: dict[str, Any], *, from_step_id: str) -> dict[str, Any]:
    """Mark from_step and everything after it pending (keep earlier passed)."""
    steps = [dict(s) for s in (plan.get("steps") or []) if isinstance(s, dict)]
    reached = False
    for step in steps:
        sid = str(step.get("id") or step.get("workflow_id") or "")
        if sid == from_step_id or reached:
            reached = True
            if str(step.get("status") or "") != "skipped":
                step["status"] = "pending"
    if reached:
        for step in steps:
            if str(step.get("status") or "") == "pending":
                step["status"] = "in_progress"
                break
    out = dict(plan)
    out["steps"] = steps
    out["status"] = "active"
    acc = dict(out.get("acceptance_status") or {})
    for key in out.get("acceptance") or []:
        if str(acc.get(key) or "") == "passed":
            acc[str(key)] = "pending"
    out["acceptance_status"] = acc
    return out
