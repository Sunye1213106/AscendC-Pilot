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
    return _load(runs_root(project_root) / run_id / "actions" / action_id / "session.yaml")


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
    goal = str(gctx.get("label_zh") or "") or f"为 {op}（{arch}）建立 TilingKey 全覆盖测试"
    n = _declared_key_count(project_root)
    scale = f"（约 {n} 个合法 Key）" if n else ""
    background = f"覆盖合同已建立{scale}，检查已通过。"
    if gctx.get("progress_line"):
        background = f"{gctx['progress_line']} {background}"
    return decision_question(
        header="覆盖合同已就绪，是否进入规划？",
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
    goal = str(gctx.get("label_zh") or "") or f"为 {op}（{arch}）建立 TilingKey 全覆盖测试"
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


def _ask_scenario_plan(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    ids = _scenario_ids(project_root, state)
    listed = "、".join(ids) if ids else "（尚未读到已确认场景列表）"
    return decision_question(
        header="是否把精度/性能场景冻结为规划目标？",
        goal=f"为 {op}（{arch}）按场景构造少量用例，而不是覆盖全部合法 Key",
        background=f"将把已确认的 ScenarioSet 冻成规划目标：{listed}。这一步不构造用例、不跑 Host。",
        decide="是否按这些场景进入规划？",
        consequences={
            "确认按场景规划": "只针对这些场景规划测试义务",
            "返工": "回到场景确认，增删场景后再规划",
            "停止": "结束本次目标",
        },
        options=[
            {"label": "确认按场景规划", "value": "confirm"},
            {"label": "返工场景", "value": "rework"},
            {"label": "停止本次目标", "value": "stop"},
        ],
    )


def _ask_ce_intent(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    op, arch = _op_arch(project_root, state)
    return decision_question(
        header="变更计划已审阅，是否确认？",
        goal=f"确认 {op}（{arch}）的改码范围、锚点与验收条件",
        background="特性分解已经过审查。确认后冻结变更计划；返工则回到分解/审查。",
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


def _find_plan_dir(tg: Path, level: str) -> Path | None:
    preferred = tg / "plan" / "levels" / (level or "L0")
    if preferred.is_dir():
        return preferred
    levels = tg / "plan" / "levels"
    if not levels.is_dir():
        return None
    candidates = sorted(
        (
            path
            for path in levels.iterdir()
            if path.is_dir()
            and any(
                (path / name).is_file()
                for name in ("coverage_obligations.yaml", "coverage_matrix.yaml", "unresolved.yaml")
            )
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _plan_hashes(plan_dir: Path) -> tuple[str, str]:
    snapshot_hash = ""
    plan_hash = ""
    for name in (
        "coverage_obligations.yaml",
        "plan.yaml",
        "snapshot.yaml",
        "coverage_matrix.yaml",
        "unresolved.yaml",
    ):
        doc = _load(plan_dir / name)
        snapshot_hash = snapshot_hash or str(doc.get("snapshot_hash") or "")
        plan_hash = plan_hash or str(doc.get("plan_hash") or "")
    return snapshot_hash, plan_hash


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
    watched = [
        tg / "init" / "status.yaml",
        tg / "init" / "kb_fingerprint.yaml",
        tg / "init" / "confirmation.yaml",
    ]
    backups = {candidate: candidate.read_bytes() if candidate.is_file() else None for candidate in watched}
    try:
        from testcase_agent.init_status import mark_init_confirmed

        mark_init_confirmed(
            tg,
            notes="Confirmed by Pilot primary_interactive Action",
            require_merge=False,
        )
    except Exception as exc:  # noqa: BLE001
        rollback_primary_decision({"backups": backups})
        return {
            "ok": False,
            "error": "INIT_CONFIRM_DOMAIN_GATE_FAILED",
            "message_zh": str(exc)[:400],
        }
    confirm_path = tg / "init" / "confirmation.yaml"
    _dump(
        confirm_path,
        {
            "schema": "tg-init-confirmation/v1",
            "status": "confirmed",
            "mode": "tilingkey_full_coverage",
            "confirmed_at": now,
            **identity,
        },
    )
    path = tg / "init" / "status.yaml"
    doc = _load(path)
    doc.update(
        {
            "version": int(doc.get("version") or 1),
            "status": "confirmed",
            "confirmed": True,
            "init_confirmed": True,
            "human_confirmed": True,
            "decision": "confirm",
            "confirmed_at": str(doc.get("confirmed_at") or now),
            "op_name": str(state.get("op_name") or doc.get("op_name") or project_root.name),
            **identity,
            "artifact_identity": identity,
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
    level = str(state.get("level") or "L0")
    plan_dir = _find_plan_dir(tg, level)
    if plan_dir is None:
        return {
            "ok": False,
            "error": "PLAN_DIR_MISSING",
            "message_zh": "未找到当前 level 的规划目录，禁止生成批准文件",
        }
    snapshot_hash, plan_hash = _plan_hashes(plan_dir)
    if not snapshot_hash or not plan_hash:
        return {
            "ok": False,
            "error": "PLAN_HASH_MISSING",
            "plan_dir": plan_dir.as_posix(),
            "snapshot_hash_present": bool(snapshot_hash),
            "plan_hash_present": bool(plan_hash),
            "message_zh": "规划产物缺少 snapshot_hash/plan_hash，禁止批准陈旧或无身份计划",
        }
    path = plan_dir / "human_supplement.yaml"
    backups = {path: path.read_bytes() if path.is_file() else None}
    doc = _load(path)
    doc.update(
        {
            "version": int(doc.get("version") or 1),
            "status": "approved",
            "approved": True,
            "decision": "approve",
            "allow_solve": True,
            "approved_at": now,
            "approved_snapshot_hash": snapshot_hash,
            "approved_plan_hash": plan_hash,
            "supplements": list(doc.get("supplements") or []),
            "notes": str(doc.get("notes") or "Approved by Pilot primary_interactive Action"),
            "level": plan_dir.name,
            **identity,
            "artifact_identity": identity,
        }
    )
    _dump(path, doc)
    return {"ok": True, "path": path, "backups": backups, "identity": identity}


def _materialize_scenario_plan(
    project_root: Path,
    state: dict[str, Any],
    identity: dict[str, str],
    now: str,
) -> dict[str, Any]:
    ids = _scenario_ids(project_root, state)
    path = tg_root(project_root, arch=_arch(state)) / "plan" / "scenario_plan.yaml"
    doc = {
        "schema": "tg-scenario-plan/v1",
        "status": "confirmed",
        "mode": "scenario_targeted",
        "scenario_ids": ids,
        "confirmed_at": now,
        **identity,
        "artifact_identity": identity,
    }
    path, backups = _write_yaml_receipt(path, doc)
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
    return {"ok": True, "path": path, "backups": backups, "identity": identity}


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
        audit = tg_root(project_root, arch=_arch(state)) / "init" / "audit_report.yaml"
        rel = audit.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/tg/init/audit_report.yaml"
    return [f"Review {rel} before asking the user to enter planning."]


def _hints_plan_approve(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        levels = tg_root(project_root, arch=_arch(state)) / "plan" / "levels"
        rel = levels.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/tg/plan/levels/"
    return [f"Review the current level under {rel} before asking the user to start solving."]


def _hints_scenario_plan(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        path = ce_root(project_root, arch=_arch(state)) / "scenarios" / "scenario_set.yaml"
        rel = path.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/ce/scenarios/scenario_set.yaml"
    return [f"Review {rel}; freeze those scenario ids as the plan target, not all legal keys."]


def _hints_ce_intent(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        root = ce_root(project_root, arch=_arch(state)) / "intent"
        rel = root.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/ce/intent/"
    return [f"Review {rel}feature_decomposition.yaml and plan_review.yaml before asking to freeze the plan."]


def _hints_scenario_confirm(project_root: Path, state: dict[str, Any]) -> list[str]:
    try:
        path = ce_root(project_root, arch=_arch(state)) / "scenarios" / "scenario_set.yaml"
        rel = path.relative_to(Path(project_root).resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = ".ascendc-pilot/<arch>/ce/scenarios/scenario_set.yaml"
    return [f"Review {rel} (ids, knobs, budget). This is not tilingkey full coverage."]


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
        "compact": "plan_approve",
    },
    ("tg-plan", "scenario_plan"): {
        "kind": "primary_confirm",
        "expected_values": ["confirm"],
        "ask": _ask_scenario_plan,
        "materialize": _materialize_scenario_plan,
        "hints": _hints_scenario_plan,
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

    from ascendc_pilot.human_interaction import require_decision_receipt

    receipt = require_decision_receipt(
        project_root,
        expected_values=list(scenario["expected_values"]),
        expected_action_id=action_id,
        expected_kind=str(scenario["kind"]),
        consume=True,
    )
    if not receipt.get("ok"):
        return receipt

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    identity = _identity(session)
    identity["human_decision_request_id"] = str(receipt.get("request_id") or "")
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
