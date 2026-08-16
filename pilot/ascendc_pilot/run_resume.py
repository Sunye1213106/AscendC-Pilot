"""Detect interrupted runs and drive continue / reinit human decisions."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ascendc_pilot.paths import (
    agent_root,
    context_root,
    runs_root,
    state_root,
    try_discover_arch,
    uo_root,
)
from ascendc_pilot.state import RUNNING_LIKE, load_state, save_state

_INCOMPLETE_SESSION_STATUSES = frozenset(
    {"prepared", "finalize_failed", "revoked", "actor_running", "failed"}
)

_DECISION_ALIASES = {
    "continue": "continue",
    "resume": "continue",
    "reuse": "continue",
    "继续": "continue",
    "继续上次": "continue",
    "开始": "continue",
    "reinit": "reinit",
    "reset": "reinit",
    "force-new": "reinit",
    "force_new": "reinit",
    "删除重开": "reinit",
    "重开": "reinit",
    "query": "query",
    "去查询": "query",
}

_DEFAULT_RESET_POLICY: dict[str, Any] = {
    "reinit_delete": [],
    "reinit_preserve": ["uo", "tg", "ce"],
    "reinit_wipe_runs": "current",
    "continue_scrub": "from_contracts",
}

_STATE_FILES_ON_REINIT = (
    "workflow.yaml",
    "active_action.yaml",
    "action_lease.yaml",
    "resume.yaml",
)

# Staging inputs kept on continue-scrub retry (not re-produced by upstream receipts).
_CONTINUE_SCRUB_KEEP: dict[str, frozenset[str]] = {}


def _scrub_rels_for_action(
    aid: str,
    *,
    owned: dict[str, tuple[str, ...]],
    dirty: set[str],
    finalized: set[str],
) -> tuple[str, ...]:
    keep: set[str] = set(_CONTINUE_SCRUB_KEEP.get(aid, ()))
    for other_aid, other_rels in owned.items():
        if other_aid == aid or other_aid in dirty:
            continue
        if other_aid in finalized:
            keep.update(other_rels)
            continue
        # Upstream non-dirty actions may still own shared contract paths (e.g. entrypoint_graph).
        keep.update(other_rels)
    rels = owned.get(aid, ())
    return tuple(r for r in rels if r not in keep)


def reset_policy_for(workflow_id: str) -> dict[str, Any]:
    from ascendc_pilot.workflows import get_workflow

    meta = get_workflow(workflow_id)
    raw = meta.get("reset_policy")
    if not isinstance(raw, dict):
        return dict(_DEFAULT_RESET_POLICY)
    out = dict(_DEFAULT_RESET_POLICY)
    out.update(raw)
    return out


def _workflow_label(workflow_id: str) -> str:
    from ascendc_pilot.workflows import get_workflow

    meta = get_workflow(workflow_id)
    slash = meta.get("slash")
    if slash:
        return str(slash).lstrip("/")
    return workflow_id


def _pin_process_arch(architecture: str) -> str:
    """Pin ``UO_ARCH`` so path helpers can resolve before ``active_run.yaml`` exists."""
    arch = str(architecture or "").strip()
    if arch:
        os.environ["UO_ARCH"] = arch
    return arch


def _uo_present_any_arch(root: Path) -> bool:
    """True only when a real ``*.uo`` CodeMap product exists (not ``uo/checks/``)."""
    from ascendc_pilot.intake import discover_uo_products

    return bool(discover_uo_products(root))


def _resume_summary_without_arch_tree(root: Path, workflow_id: str) -> dict[str, Any]:
    """Resume payload when no arch tree / active_run exists yet (virgin start)."""
    wf_label = _workflow_label(workflow_id)
    has_uo = _uo_present_any_arch(root)
    ask_opts_src = ask_options_for(workflow_id)
    ask_opts = [
        {
            "label": src["label"],
            "description": src["description"],
            "value": src["value"],
        }
        for src in ask_opts_src
    ]
    if has_uo:
        ask_opts = leftover_uo_ask_options()
        lines = [
            "run_id: (无)",
            f"workflow: {workflow_id}",
            "phase/status: - / -",
            "architecture: -",
            "上一场建库已完成，产物锁已释放。新会话可直接查询，不是卡住。",
        ]
    else:
        ask_opts = [o for o in ask_opts if o.get("value") == "reinit"] or ask_opts
        lines = [
            "run_id: (无)",
            f"workflow: {workflow_id}",
            "phase/status: - / -",
            "architecture: -",
            "无活动 run。参数齐则可直接 start。",
        ]
    return {
        "has_existing_run": has_uo,
        "has_uo_artifacts": has_uo,
        "workflow_id": workflow_id,
        "requested_workflow_id": workflow_id,
        "cross_workflow": None,
        "run_id": "",
        "phase": "",
        "status": "",
        "architecture": "",
        "passed_gates": [],
        "failed_gates": [],
        "finalized_actions": [],
        "verified_receipts": [],
        "invalid_receipts": [],
        "missing_receipts": [],
        "artifacts": [],
        "action_owned_artifacts": action_owned_artifacts(workflow_id),
        "last_complete": {
            "phase": "",
            "passed_gates": [],
            "finalized_actions": [],
            "present_artifacts": [],
        },
        "interrupted_at": {
            "phase": "",
            "status": "",
            "active_action": None,
            "failed_gates": [],
            "missing_artifacts": [],
        },
        "resume_next_action": "",
        "summary_text_zh": "\n".join(lines),
        "ask_question": {
            "header": (
                f"CodeMap 已就绪（{wf_label} 已结束）" if has_uo else f"启动 {wf_label}"
            ),
            "question": "\n".join(lines),
            "options": ask_opts,
        },
        "decision_values": {o["label"]: o["value"] for o in ask_opts},
        "commands": {
            "continue": f"acp start {workflow_id} --project . --decision continue",
            "reinit": f"acp start {workflow_id} --project . --decision reinit",
        },
    }


def leftover_uo_ask_options() -> list[dict[str, str]]:
    """No live run + real ``*.uo``: never offer 继续上次."""
    reinit = next(o for o in ask_options_for("uo-init") if o.get("value") == "reinit")
    return [
        {
            "label": "去查询",
            "description": "保留已完成的 CodeMap，新会话直接查；上一场锁已释放",
            "value": "query",
        },
        {
            "label": reinit["label"],
            "description": reinit["description"],
            "value": "reinit",
        },
    ]


def ask_options_for(workflow_id: str) -> list[dict[str, str]]:
    label = _workflow_label(workflow_id)
    policy = reset_policy_for(workflow_id)
    delete_bits = ", ".join(policy.get("reinit_delete") or []) or "工作流产物"
    preserve = policy.get("reinit_preserve") or []
    preserve_note = (
        f"（保留 {', '.join(preserve)}）" if preserve else ""
    )
    return [
        {
            "label": "继续上次 (Recommended)",
            "description": (
                "先清理中断步骤的残缺/失败产物，回退到最近完整正确状态，再继续执行"
            ),
            "value": "continue",
        },
        {
            "label": "删除重开",
            "description": (
                f"abort 当前 run，按 {label} 策略清除 {delete_bits}{preserve_note} 后重新 start"
            ),
            "value": "reinit",
        },
    ]


def normalize_decision(raw: str) -> str | None:
    """Accept canonical values or exact AskQuestion option labels — no fuzzy free-text."""
    key = str(raw or "").strip()
    if not key:
        return None
    low = key.lower()
    if low in {"continue", "reinit", "query"}:
        return low
    if str(raw or "").strip().startswith("开始"):
        return "continue"
    if str(raw or "").strip().startswith("去查询"):
        return "query"
    if low in _DECISION_ALIASES:
        return _DECISION_ALIASES[low]
    for opt in ask_options_for("uo-init"):
        if key == opt["label"] or low == str(opt["label"]).lower():
            return opt["value"]
        if low == str(opt["value"]).lower():
            return opt["value"]
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


def action_owned_artifacts(workflow_id: str) -> dict[str, tuple[str, ...]]:
    """Action id → contract paths under .ascendc-pilot (from Spec output_contract_id)."""
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.workflows import get_workflow

    meta = get_workflow(workflow_id)
    out: dict[str, tuple[str, ...]] = {}
    for action in meta.get("actions") or []:
        if not isinstance(action, dict):
            continue
        aid = str(action.get("id") or "").strip()
        cid = str(action.get("output_contract_id") or "").strip()
        if not aid or not cid:
            continue
        paths = OUTPUT_CONTRACT_PATHS.get(cid)
        if not paths:
            continue
        out[aid] = tuple(str(p) for p in paths)
    return out


def _contract_paths_present(agent: Path, rels: tuple[str, ...]) -> bool:
    for rel in rels:
        if "*" in rel:
            if any(agent.glob(rel)):
                return True
        elif (agent / rel).exists():
            return True
    return False


def _remove_contract_paths(agent: Path, rels: tuple[str, ...]) -> list[str]:
    removed: list[str] = []
    for rel in rels:
        if "*" in rel:
            for path in sorted(agent.glob(rel)):
                if path.is_file():
                    path.unlink(missing_ok=True)
                    removed.append(path.relative_to(agent).as_posix())
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                    removed.append(path.relative_to(agent).as_posix() + "/")
            continue
        path = agent / rel
        if path.is_file():
            path.unlink(missing_ok=True)
            removed.append(rel)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed.append(rel + "/")
    return removed


def _artifact_checklist(agent: Path, workflow_id: str) -> list[dict[str, Any]]:
    """Key artifacts for summary display (workflow-scoped)."""
    owned = action_owned_artifacts(workflow_id)
    # Keyed by the action ids that own artifacts today. An id with no entry
    # falls back to itself, so a stale map silently shows raw ids instead of
    # labels — keep this in step with the Workflow Spec.
    label_map = {
        # uo-init
        "prepare": "准备范围",
        "extract": "Clang 抽取",
        "analyze": "CodeMap 分析",
        "commit": "写入 .uo",
        "verify": "结构校验",
        # Optional investigate / legacy labels
        "investigate": "调查 residual",
        "export_adapter_pack": "适配包导出",
        "export_tg_host_view": "TG Host 视图",
        "export_integrity": "完整性检查",
        "kb_review": "KB 审查",
        # tg / ce
        "kb_check": "UO KB 就绪",
        "contract_build": "TG 合同",
        "code_review": "CE 审查",
    }
    out: list[dict[str, Any]] = []
    for aid, rels in owned.items():
        present = _contract_paths_present(agent, rels)
        primary = rels[0] if rels else ""
        out.append(
            {
                "action_id": aid,
                "path": primary,
                "label_zh": label_map.get(aid, aid),
                "present": present,
                "complete": present,
            }
        )
    return out


def _classify_receipts(project_root: Path, run_id: str) -> dict[str, list[str]]:
    """Strict receipt classification via verify_receipt (HMAC + hashes + checker_ok)."""
    from ascendc_pilot.runs import verify_receipt
    from ascendc_pilot.workflows import get_workflow
    from ascendc_pilot.state import load_state

    verified: list[str] = []
    invalid: list[str] = []
    missing: list[str] = []

    state = load_state(project_root) or {}
    wid = str(state.get("workflow_id") or "")
    meta = get_workflow(wid) if wid else {}
    expected_actions: list[str] = []
    for action in meta.get("actions") or []:
        if isinstance(action, dict) and action.get("id"):
            expected_actions.append(str(action["id"]))

    base = runs_root(project_root) / run_id / "subagents"
    seen_files: set[str] = set()
    if base.is_dir():
        for path in sorted(base.glob("*.yaml")):
            data = _load_yaml(path)
            aid = str(data.get("action_id") or "").strip()
            if not aid:
                invalid.append(path.stem)
                continue
            seen_files.add(aid)
            checked = verify_receipt(
                project_root,
                action_id=aid,
                require_pilot_issued=True,
                require_hashes=True,
                require_action_id=True,
                require_spec_hash=True,
                require_signature=True,
                require_checker_ok=True,
            )
            if checked.get("ok"):
                if aid not in verified:
                    verified.append(aid)
            else:
                if aid not in invalid:
                    invalid.append(aid)

    # Pipeline actions with no receipt file are missing (not verified).
    from ascendc_pilot.workflows import phase_pipeline

    phase = str(state.get("phase") or "")
    for aid in phase_pipeline(wid, phase) if wid and phase else []:
        if aid not in seen_files and aid not in verified and aid not in missing:
            # Only report missing for actions we care about when summarizing;
            # dirty detection uses invalid + incomplete products separately.
            pass

    return {
        "verified_receipts": verified,
        "invalid_receipts": invalid,
        "missing_receipts": missing,
    }


def _receipt_actions(project_root: Path, run_id: str) -> list[str]:
    """Actions with a strictly verified Pilot receipt for the current run."""
    return list(_classify_receipts(project_root, run_id).get("verified_receipts") or [])


def _invalid_receipt_actions(project_root: Path, run_id: str) -> list[str]:
    return list(_classify_receipts(project_root, run_id).get("invalid_receipts") or [])


def _active_action(project_root: Path) -> dict[str, Any]:
    return _load_yaml(state_root(project_root) / "active_action.yaml")


def _action_session(project_root: Path, run_id: str, action_id: str) -> dict[str, Any]:
    if not run_id or not action_id:
        return {}
    sdir = runs_root(project_root) / run_id / "actions" / action_id
    for name in ("session_state.yaml", "session.yaml"):
        hit = _load_yaml(sdir / name)
        if hit:
            return hit
    return {}


def _detect_dirty_actions(project_root: Path, run_id: str, workflow_id: str) -> list[str]:
    """Actions that left incomplete / failed products and must be scrubbed on continue."""
    root = Path(project_root).expanduser().resolve()
    policy = reset_policy_for(workflow_id)
    if str(policy.get("continue_scrub") or "") != "from_contracts":
        return []

    owned = action_owned_artifacts(workflow_id)
    classified = _classify_receipts(root, run_id) if run_id else {
        "verified_receipts": [],
        "invalid_receipts": [],
        "missing_receipts": [],
    }
    finalized = set(classified.get("verified_receipts") or [])
    invalid = set(classified.get("invalid_receipts") or [])
    dirty: list[str] = []
    seen: set[str] = set()
    agent = agent_root(root)

    def _mark(aid: str) -> None:
        aid = str(aid or "").strip()
        if not aid or aid in finalized or aid in seen:
            return
        seen.add(aid)
        dirty.append(aid)

    for aid in sorted(invalid):
        _mark(aid)

    active = _active_action(root)
    active_id = str(active.get("action_id") or "").strip()
    active_status = str(active.get("status") or "").strip()
    state = load_state(root) or {}
    lf = state.get("last_failure") if isinstance(state.get("last_failure"), dict) else {}
    lf_action = str(lf.get("action_id") or "").strip()

    if active_id and active_status in _INCOMPLETE_SESSION_STATUSES:
        _mark(active_id)

    phase = str(state.get("phase") or "")
    from ascendc_pilot.workflows import phase_pipeline

    pipe = phase_pipeline(workflow_id, phase)
    if active_id and active_id in pipe:
        start_idx = pipe.index(active_id)
        for aid in pipe[start_idx:]:
            if aid in finalized:
                continue
            rels = owned.get(aid, ())
            if _contract_paths_present(agent, rels):
                _mark(aid)

    for aid, rels in owned.items():
        if aid in finalized:
            continue
        session = _action_session(root, run_id, aid)
        sess_status = str(session.get("status") or "").strip()
        if sess_status in _INCOMPLETE_SESSION_STATUSES:
            _mark(aid)
            continue
        if not _contract_paths_present(agent, rels):
            continue
        # Orphan finalize products: only the interrupted action (or last failure target).
        if aid == active_id or (not active_id and aid == lf_action):
            _mark(aid)

    return dirty


def _resolve_resume_next_action(project_root: Path) -> str:
    from ascendc_pilot.state import describe_next

    nxt = describe_next(project_root)
    if not nxt.get("ok"):
        return ""
    rec = nxt.get("recommended_next_action")
    if isinstance(rec, dict):
        return str(rec.get("id") or "").strip()
    return ""


def scrub_incomplete_on_continue(project_root: Path) -> dict[str, Any]:
    """Remove failed/partial products of interrupted actions; keep last complete state."""
    root = Path(project_root).expanduser().resolve()
    state = load_state(root)
    run_id = str((state or {}).get("run_id") or "")
    workflow_id = str((state or {}).get("workflow_id") or "uo-init")
    dirty = _detect_dirty_actions(root, run_id, workflow_id)
    dirty_set = set(dirty)
    removed: list[str] = []
    sessions_cleared: list[str] = []
    agent = agent_root(root)
    owned = action_owned_artifacts(workflow_id)
    finalized = set(_receipt_actions(root, run_id)) if run_id else set()

    for aid in dirty:
        rels = _scrub_rels_for_action(
            aid, owned=owned, dirty=dirty_set, finalized=finalized
        )
        for rel in rels:
            removed.extend(_remove_contract_paths(agent, (rel,)))
        if run_id:
            sdir = runs_root(root) / run_id / "actions" / aid
            if sdir.is_dir():
                shutil.rmtree(sdir, ignore_errors=True)
                sessions_cleared.append(aid)

    lease_revoked = False
    active = _active_action(root)
    active_id = str(active.get("action_id") or "").strip()
    if active_id and active_id in dirty:
        try:
            from ascendc_pilot.authorize.lease import clear_lease, revoke_active_lease

            revoke_active_lease(root, reason="continue_scrub_incomplete")
            clear_lease(root)
            lease_revoked = True
        except Exception:  # noqa: BLE001
            pass
        active_path = state_root(root) / "active_action.yaml"
        if active_path.is_file():
            active_path.unlink()
            removed.append("state/active_action.yaml")

    state_updates: dict[str, Any] = {}
    if state and dirty:
        failed = list(state.get("failed_gates") or [])
        if failed:
            state["failed_gates"] = []
            state_updates["cleared_failed_gates"] = len(failed)
        if str(state.get("status") or "") in {"rework_required", "human_required"}:
            state["status"] = "running"
            state_updates["status"] = "running"
        if state.get("last_failure"):
            state["last_failure"] = {}
            state_updates["cleared_last_failure"] = True
        save_state(root, state)

    resume_next = _resolve_resume_next_action(root)
    if not resume_next and dirty:
        resume_next = dirty[0]

    return {
        "ok": True,
        "scrubbed_actions": dirty,
        "removed_artifacts": removed,
        "sessions_cleared": sessions_cleared,
        "lease_revoked": lease_revoked,
        "state_updates": state_updates,
        "resume_next_action": resume_next,
        "message_zh": (
            (
                f"已清理残缺步骤 {', '.join(dirty)}（删除 {len(removed)} 项产物），"
                f"回退到最近完整状态；下一步：{resume_next or 'acp next'}"
            )
            if dirty
            else "无残缺产物，可直接从最近完整状态继续"
        ),
    }


def apply_reinit_wipe(
    project_root: Path,
    workflow_id: str,
    *,
    architecture: str = "",
) -> dict[str, Any]:
    """Workflow-scoped reinit wipe per Spec ``reset_policy``.

    Safe before an architecture tree exists: no-arch projects skip the
    arch-scoped wipe instead of raising ARCHITECTURE_MISSING_IN_RUN_STATE.
    """
    root = Path(project_root).expanduser().resolve()
    policy = reset_policy_for(workflow_id)
    from ascendc_pilot.paths import try_discover_arch

    arch = str(architecture or "").strip() or try_discover_arch(root)
    if not arch:
        return {
            "ok": True,
            "removed": [],
            "kept": ["control/pilot_hmac.key"],
            "skipped": "no_arch_tree",
            "policy": policy,
        }
    agent = agent_root(root, arch=arch)
    state = load_state(root, arch=arch) or {}
    run_id = str(state.get("run_id") or "")
    removed: list[str] = []
    preserve_roots = [str(x) for x in (policy.get("reinit_preserve") or [])]
    explicit_deletes = {str(x).strip().replace("\\", "/") for x in (policy.get("reinit_delete") or [])}

    for item in explicit_deletes:
        rel = str(item).strip().replace("\\", "/")
        if not rel:
            continue
        target = agent / rel
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(target.as_posix())
        elif target.is_file():
            target.unlink(missing_ok=True)
            removed.append(target.as_posix())
        elif "*" in rel:
            removed.extend(_remove_contract_paths(agent, (rel,)))

    wipe_runs = str(policy.get("reinit_wipe_runs") or "current")
    runs = runs_root(root, arch=arch)
    if wipe_runs == "all" and runs.exists():
        shutil.rmtree(runs, ignore_errors=True)
        removed.append(runs.as_posix())
    elif wipe_runs == "current" and run_id:
        run_dir = runs / run_id
        if run_dir.is_dir():
            shutil.rmtree(run_dir, ignore_errors=True)
            removed.append(run_dir.as_posix())

    ctx = context_root(root, arch=arch)
    if ctx.exists() and workflow_id in {"uo-init", "uo-update"}:
        shutil.rmtree(ctx, ignore_errors=True)
        removed.append(ctx.as_posix())

    st = state_root(root, arch=arch)
    for name in _STATE_FILES_ON_REINIT:
        path = st / name
        if path.is_file():
            path.unlink()
            removed.append(path.as_posix())

    kept = ["control/pilot_hmac.key", "memory/"]
    kept.extend(preserve_roots)
    historical_runs = wipe_runs != "all"
    if historical_runs and runs.is_dir():
        kept.append("runs/ (historical)")

    return {
        "ok": True,
        "removed": removed,
        "kept": kept,
        "policy": policy,
    }


def wipe_uo_for_reinit(project_root: Path) -> dict[str, Any]:
    """Backward-compatible alias: uo-init scoped wipe."""
    return apply_reinit_wipe(project_root, "uo-init")


def _cross_workflow_conflict(state: dict[str, Any] | None, workflow_id: str) -> dict[str, Any] | None:
    """Conflict only inside the same exclusive product-family lock.

    Shared (query/review) never occupies. Different families (uo vs tg vs ce-*)
    run in parallel against the same ``.uo``.
    """
    from ascendc_pilot.occupancy import is_shared, occupancy_group_of

    if not state:
        return None
    if is_shared(workflow_id):
        return None
    active_wid = str(state.get("workflow_id") or "")
    if not active_wid or is_shared(active_wid):
        return None
    status = str(state.get("status") or "")
    if active_wid == workflow_id or status not in RUNNING_LIKE:
        return None
    req_group = occupancy_group_of(workflow_id)
    active_group = occupancy_group_of(active_wid)
    if not req_group or not active_group or req_group != active_group:
        return None
    return {
        "error": "cross_workflow_active_run",
        "active_workflow_id": active_wid,
        "requested_workflow_id": workflow_id,
        "occupancy_group": req_group,
        "message_zh": (
            f"当前 {active_group} 产物锁由 {active_wid} 持有，与请求的 {workflow_id} 同族；"
            "禁止静默覆盖。点「开始」释放该族锁并 start 请求的工作流（不删正式产物），"
            "或显式删除重开。"
        ),
    }


def build_run_resume_summary(
    project_root: Path,
    *,
    workflow_id: str = "uo-init",
    architecture: str = "",
) -> dict[str, Any]:
    """Human-facing summary of the last interrupted run.

    Safe before an architecture tree exists: pass ``architecture`` (or pin
    ``UO_ARCH``) so path helpers do not raise ARCHITECTURE_MISSING_IN_RUN_STATE.
    """
    root = Path(project_root).expanduser().resolve()
    arch = _pin_process_arch(architecture) or try_discover_arch(root)
    if arch:
        _pin_process_arch(arch)
    try:
        state = load_state(root, arch=arch or None, workflow_id=workflow_id)
        agent = agent_root(root, arch=arch or None)
        uo = uo_root(root, arch=arch or None)
    except ValueError:
        return _resume_summary_without_arch_tree(root, workflow_id)
    from ascendc_pilot.intake import discover_uo_products

    has_uo = bool(discover_uo_products(root))
    del uo
    artifacts = _artifact_checklist(agent, workflow_id) if has_uo or workflow_id != "uo-init" else []
    if not artifacts and agent.is_dir():
        artifacts = _artifact_checklist(agent, workflow_id)
    complete_arts = [a for a in artifacts if a.get("complete")]
    missing_arts = [a for a in artifacts if not a.get("complete")]

    run_id = str((state or {}).get("run_id") or "")
    classified = (
        _classify_receipts(root, run_id)
        if run_id
        else {"verified_receipts": [], "invalid_receipts": [], "missing_receipts": []}
    )
    receipts = list(classified.get("verified_receipts") or [])
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
    state_wid = str((state or {}).get("workflow_id") or "")
    active_wid = state_wid or workflow_id
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

    next_hint = _resolve_resume_next_action(root) if state_wid == workflow_id else ""
    if not next_hint and active.get("status") == "prepared":
        next_hint = str(active.get("action_id") or "")
    if not next_hint:
        for a in missing_arts:
            next_hint = str(a.get("action_id") or "")
            break

    wf_label = _workflow_label(workflow_id)
    lines = [
        f"run_id: {run_id or '(无)'}",
        f"workflow: {active_wid}",
        f"phase/status: {phase or '-'} / {status or '-'}",
        f"architecture: {(state or {}).get('architecture') or '-'}",
        f"created_at: {(state or {}).get('created_at') or '-'}",
        f"updated_at: {(state or {}).get('updated_at') or '-'}",
        f"已通过 gates: {', '.join(passed_gates) or '(无)'}",
        f"已验证收据 actions: {', '.join(receipts) or '(无)'}",
        f"无效收据 actions: {', '.join(classified.get('invalid_receipts') or []) or '(无)'}",
        f"已有产物: {', '.join(a['label_zh'] for a in complete_arts) or '(无)'}",
        f"中断点: phase={phase or '-'}, active={active.get('action_id') or '-'} ({active.get('status') or '-'})",
    ]
    if failed_gates:
        lines.append(
            "失败 gates: " + ", ".join(f"{g.get('id')}({g.get('message') or ''})" for g in failed_gates)
        )
    lines.append(f"继续时下一步: {next_hint or 'acp next'}")

    cross = _cross_workflow_conflict(state, workflow_id)
    same_workflow_running = (
        bool(state)
        and state_wid == workflow_id
        and status in RUNNING_LIKE
    )
    has_existing_run = same_workflow_running and cross is None
    ask_opts_src = ask_options_for(workflow_id)

    def _ask_opt(src: dict[str, str]) -> dict[str, str]:
        # Host AskQuestion UI returns the label; ACP receipts must store canonical value.
        return {
            "label": src["label"],
            "description": src["description"],
            "value": src["value"],
        }

    if has_existing_run:
        ask_opts = [_ask_opt(o) for o in ask_opts_src]
        question_body = (
            f"检测到算子目录已有未完成的 {wf_label} run。请选择：继续上次，"
            f"或按策略删除后重新 start。\n\n" + "\n".join(lines)
        )
        header = f"发现未完成的 {wf_label}"
    elif cross:
        active_label = _workflow_label(active_wid)
        ask_opts = [
            {
                "label": f"开始 {wf_label} (Recommended)",
                "description": (
                    f"结束当前 {active_label} 产物族锁（保留 uo / tg / ce），开始 {wf_label}"
                ),
                "value": "continue",
            },
            _ask_opt(ask_opts_src[1]),
        ]
        question_body = (
            f"当前活动 run 属于 {active_wid}，与请求的 {workflow_id} 不一致。"
            f"「开始 {wf_label}」会释放该产物族锁并 start {workflow_id}（不删正式产物）。"
            f"「删除重开」会按 {wf_label} 策略清理后 start。\n\n"
            + "\n".join(lines)
        )
        header = f"工作流冲突（请求 {wf_label}）"
        has_existing_run = True
    elif workflow_id == "uo-init" and has_uo and (not state or state_wid in {"", "uo-init"}):
        ask_opts = leftover_uo_ask_options()
        question_body = (
            "上一场建库已经完成，产物锁已释放（不是卡住）。"
            "新会话可以直接查询，不必再走 uo-init。"
            "选「去查询」保留现有 CodeMap；只有要推倒重来才选「删除重开」。\n\n"
            + "\n".join(lines)
        )
        header = f"CodeMap 已就绪（{wf_label} 已结束）"
        has_existing_run = True
    else:
        ask_opts = [_ask_opt(ask_opts_src[1])]
        question_body = (
            f"无可继续的活动 {wf_label} run。请确认是否按策略删除后重新 start。\n\n"
            + "\n".join(lines)
        )
        header = f"启动 {wf_label}"

    return {
        "has_existing_run": has_existing_run,
        "has_uo_artifacts": has_uo,
        "workflow_id": active_wid,
        "requested_workflow_id": workflow_id,
        "cross_workflow": cross,
        "run_id": run_id,
        "phase": phase,
        "status": status,
        "architecture": str((state or {}).get("architecture") or ""),
        "passed_gates": passed_gates,
        "failed_gates": failed_gates,
        "finalized_actions": receipts,
        "verified_receipts": list(classified.get("verified_receipts") or []),
        "invalid_receipts": list(classified.get("invalid_receipts") or []),
        "missing_receipts": list(classified.get("missing_receipts") or []),
        "artifacts": artifacts,
        "action_owned_artifacts": action_owned_artifacts(workflow_id),
        "last_complete": last_complete,
        "interrupted_at": interrupted,
        "resume_next_action": next_hint,
        "summary_text_zh": "\n".join(lines),
        "ask_question": {
            "header": header,
            "question": question_body,
            "options": ask_opts,
        },
        "decision_values": {o["label"]: o["value"] for o in ask_opts},
        "commands": {
            "continue": f"acp start {workflow_id} --project . --decision continue",
            "reinit": f"acp start {workflow_id} --project . --decision reinit",
        },
    }


def discover_available_archs(project_root: Path) -> list[str]:
    """List architecture dirs under op_host/op_kernel (e.g. arch22, arch35)."""
    root = Path(project_root).expanduser().resolve()
    try:
        from uo_init.op_spec import _discover_archs

        return list(_discover_archs(root))
    except Exception:  # noqa: BLE001
        import re

        arch_re = re.compile(r"^arch\d+$")
        seen: set[str] = set()
        for parent in (root / "op_host", root / "op_kernel"):
            if not parent.is_dir():
                continue
            for child in parent.iterdir():
                if child.is_dir() and arch_re.match(child.name):
                    seen.add(child.name)
        return sorted(seen)


def architecture_decision_payload(
    project_root: Path,
    workflow_id: str,
    *,
    available: list[str] | None = None,
) -> dict[str, Any]:
    """AskQuestion payload when architecture is ambiguous."""
    root = Path(project_root).expanduser().resolve()
    arches = list(available if available is not None else discover_available_archs(root))
    ask_opts = [
        {
            "label": arch,
            "value": arch,
            "description": f"为 {arch} 建立/继续本工作流产物",
        }
        for arch in arches
    ]
    commands = {
        arch: f"acp start {workflow_id} --project . --architecture {arch}"
        for arch in arches
    }
    return {
        "ok": False,
        "needs_human_decision": True,
        "error": "ARCHITECTURE_NEEDS_DECISION",
        "message_zh": (
            f"算子存在多个架构目录（{', '.join(arches)}），且未指定 --architecture。"
            "必须用 OpenCode `question`（AskQuestion）弹出可点选框，等人选择后执行对应 "
            "`acp start … --architecture <arch>`。禁止静默默认 arch35。"
        ),
        "ask_question": {
            "header": "选择目标架构",
            "question": (
                f"检测到多个架构：{', '.join(arches)}。"
                "请选择本次要分析的 architecture："
            ),
            "options": ask_opts,
        },
        "decision_values": {arch: arch for arch in arches},
        "commands": commands,
        "available_architectures": arches,
        "workflow_id": workflow_id,
    }


def resolve_start_architecture(
    project_root: Path,
    architecture: str = "",
    *,
    workflow_id: str = "uo-init",
) -> dict[str, Any]:
    """Resolve architecture for a new start/reinit, or return AskQuestion payload.

    - Explicit --architecture: validate against discovered dirs when any exist.
    - Unspecified + 2+ dirs: needs_human_decision (no silent arch35).
    - Unspecified + exactly 1 dir: auto-select that dir.
    - Unspecified + 0 dirs: ARCHITECTURE_NOT_FOUND (never silent arch35).
    """
    root = Path(project_root).expanduser().resolve()
    available = discover_available_archs(root)
    arch = (architecture or "").strip()
    if arch:
        if available and arch not in available:
            return {
                "ok": False,
                "error": "ARCHITECTURE_NOT_PRESENT",
                "architecture": arch,
                "available_architectures": available,
                "message_zh": (
                    f"指定的 architecture={arch} 不在算子目录中；"
                    f"可选：{', '.join(available)}"
                ),
                "workflow_id": workflow_id,
            }
        return {
            "ok": True,
            "architecture": arch,
            "available_architectures": available,
            "selected_by": "explicit",
        }
    if len(available) >= 2:
        return architecture_decision_payload(root, workflow_id, available=available)
    if len(available) == 1:
        return {
            "ok": True,
            "architecture": available[0],
            "available_architectures": available,
            "selected_by": "sole_arch",
        }
    return {
        "ok": False,
        "error": "ARCHITECTURE_NOT_FOUND",
        "architecture": "",
        "available_architectures": available,
        "workflow_id": workflow_id,
        "message_zh": "算子目录没有可识别的 architecture；请指定 --architecture 或先 scan-architectures。",
        "selected_by": "none",
    }


def needs_resume_decision(project_root: Path, workflow_id: str) -> bool:
    from ascendc_pilot.occupancy import is_shared

    root = Path(project_root).expanduser().resolve()
    if is_shared(workflow_id):
        return False
    state = load_state(root, workflow_id=workflow_id)
    if _cross_workflow_conflict(state, workflow_id):
        return True
    if (
        state
        and str(state.get("workflow_id") or "") == workflow_id
        and str(state.get("status") or "") in RUNNING_LIKE
    ):
        return True
    if workflow_id != "uo-init":
        return False
    # Real ``*.uo`` products only — leftover ``uo/checks/`` is not a CodeMap.
    from ascendc_pilot.intake import discover_uo_products

    if discover_uo_products(root):
        wid = str((state or {}).get("workflow_id") or "")
        if not state or wid in {"", "uo-init"}:
            return True
    return False


def _switch_to_requested_workflow(
    root: Path,
    workflow_id: str,
    kwargs: dict[str, Any],
    *,
    switched_from: str,
) -> dict[str, Any]:
    """Release the occupying run and start the requested workflow. Do not wipe .uo."""
    from ascendc_pilot.state import release_live_execution, start_workflow
    from ascendc_pilot.todo import attach_todo
    from ascendc_pilot.workflows import entry_state, phase_pipeline

    old = load_state(root, workflow_id=workflow_id) or {}
    arch = str(kwargs.get("architecture") or old.get("architecture") or "").strip()
    try:
        from ascendc_pilot.authorize.lease import revoke_active_lease

        revoke_active_lease(root, reason=f"switch_to_{workflow_id}")
    except Exception:  # noqa: BLE001
        pass
    release_live_execution(
        root,
        reason=f"switched_to_{workflow_id}",
        state=old,
    )
    if not arch:
        arch_res = resolve_start_architecture(root, "", workflow_id=workflow_id)
        if arch_res.get("needs_human_decision"):
            return arch_res
        if not arch_res.get("ok"):
            return arch_res
        arch = str(arch_res.get("architecture") or "")
    start_kwargs = dict(kwargs)
    start_kwargs["architecture"] = arch
    fresh = start_workflow(root, workflow_id, **start_kwargs)
    entry = entry_state(workflow_id)
    pipe = phase_pipeline(workflow_id, entry)
    first_action = pipe[0] if pipe else ""
    payload = attach_todo(
        {
            **fresh,
            "ok": True,
            "decision": "continue",
            "switched_from": switched_from,
            "fresh_start": True,
            "message_zh": (
                f"已结束 {switched_from or '当前'} 产物族锁并 start {workflow_id}"
                f"（保留正式产物；下一步：{first_action or entry}）"
            ),
        },
        root,
        state=fresh,
        sync_merge=False,
    )
    return {"ok": True, **payload}


def apply_resume_decision(
    project_root: Path,
    workflow_id: str,
    decision: str,
    *,
    start_kwargs: dict[str, Any] | None = None,
    require_receipt: bool = True,
) -> dict[str, Any]:
    """Apply continue|reinit after AskQuestion + HumanDecisionReceipt.

    ``require_receipt=False`` is reserved for the ``--force-new`` script escape hatch.
    """
    from ascendc_pilot.human_interaction import (
        KIND_RESUME,
        clear_pending,
        load_pending,
        pending_is_intake,
        require_decision_receipt,
    )
    from ascendc_pilot.state import mark_terminal, start_workflow
    from ascendc_pilot.todo import attach_todo
    from ascendc_pilot.workflows import entry_state, phase_pipeline

    root = Path(project_root).expanduser().resolve()
    choice = normalize_decision(decision)
    if choice is None:
        return {
            "ok": False,
            "error": "invalid_decision",
            "allowed": ["continue", "reinit", "query"],
            "message_zh": f"无效决策 {decision!r}；请用 AskQuestion 选项 continue|reinit|query",
        }

    if require_receipt:
        pending = load_pending(root)
        if pending_is_intake(pending) and choice == "reinit":
            clear_pending(root)
        else:
            receipt = require_decision_receipt(
                root,
                expected_values=[choice],
                expected_kind=KIND_RESUME,
                consume=True,
            )
            if not receipt.get("ok"):
                return receipt

    if not require_receipt:
        clear_pending(root)

    kwargs = dict(start_kwargs or {})
    arch_hint = _pin_process_arch(str(kwargs.get("architecture") or ""))
    summary = build_run_resume_summary(
        root, workflow_id=workflow_id, architecture=arch_hint
    )
    cross = _cross_workflow_conflict(
        load_state(root, workflow_id=workflow_id), workflow_id
    )

    if choice == "query":
        clear_pending(root)
        return {
            "ok": True,
            "decision": "query",
            "next_workflow_id": "",
            "skipped_reinit": True,
            "already_ready": True,
            "message_zh": (
                "CodeMap 已就绪，产物锁已释放。不要重建，也不要 acp start / pilot_run uo-query。"
                "等人提问后由主控路由查询。"
            ),
            "run_summary": summary,
        }

    if choice == "continue":
        if cross:
            return _switch_to_requested_workflow(
                root,
                workflow_id,
                kwargs,
                switched_from=str(cross.get("active_workflow_id") or ""),
            )
        state = load_state(root, workflow_id=workflow_id)
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
        scrub = scrub_incomplete_on_continue(root)
        state = load_state(root, workflow_id=workflow_id) or state
        try:
            from ascendc_pilot.active_run import write_active_run

            write_active_run(
                root,
                architecture=str(state.get("architecture") or ""),
                run_id=str(state.get("run_id") or ""),
                workflow_id=str(state.get("workflow_id") or ""),
                status=str(state.get("status") or ""),
            )
        except ValueError:
            pass
        summary = build_run_resume_summary(root, workflow_id=workflow_id)
        next_action = scrub.get("resume_next_action") or summary.get("resume_next_action") or ""
        payload = attach_todo(
            {
                **state,
                "ok": True,
                "resumed": True,
                "decision": "continue",
                "resume_scrub": scrub,
                "resume_next_action": next_action,
                "run_summary": {
                    "last_complete": summary.get("last_complete"),
                    "interrupted_at": summary.get("interrupted_at"),
                    "summary_text_zh": summary.get("summary_text_zh"),
                    "scrub": scrub,
                },
                "message_zh": (
                    f"已复用 run {state.get('run_id')}；"
                    f"{scrub.get('message_zh') or '从最近完整状态之后继续'}"
                    f"（下一步建议：{next_action or 'acp next'}）"
                ),
            },
            root,
            state=state,
        )
        return {"ok": True, **payload}

    arch_res = resolve_start_architecture(
        root,
        str(kwargs.get("architecture") or ""),
        workflow_id=workflow_id,
    )
    if arch_res.get("needs_human_decision"):
        return arch_res
    if not arch_res.get("ok"):
        return arch_res
    kwargs["architecture"] = arch_res["architecture"]

    state = load_state(root, workflow_id=workflow_id)
    if cross and choice == "reinit":
        if state and str(state.get("workflow_id") or "") != workflow_id:
            if str(state.get("status") or "") in RUNNING_LIKE:
                try:
                    from ascendc_pilot.authorize.lease import revoke_active_lease

                    revoke_active_lease(root, reason="reinit_cross_workflow")
                except Exception:  # noqa: BLE001
                    pass
                mark_terminal(root, "failed", reason="reinit_cross_workflow")

    if state and str(state.get("status") or "") in RUNNING_LIKE and not cross:
        try:
            from ascendc_pilot.authorize.lease import revoke_active_lease

            revoke_active_lease(root, reason="reinit")
        except Exception:  # noqa: BLE001
            pass
        mark_terminal(root, "failed", reason="reinit_by_operator")

    wipe = apply_reinit_wipe(
        root, workflow_id, architecture=str(kwargs.get("architecture") or "")
    )
    fresh = start_workflow(root, workflow_id, **kwargs)
    entry = entry_state(workflow_id)
    pipe = phase_pipeline(workflow_id, entry)
    first_action = pipe[0] if pipe else ""
    return {
        "ok": True,
        "decision": "reinit",
        "wiped": wipe,
        "fresh_start": True,
        "message_zh": (
            f"已按 {workflow_id} 策略清理并重新 start；"
            f"请从 {first_action or entry} 开始"
        ),
        **fresh,
    }


def existing_run_decision_payload(
    project_root: Path,
    workflow_id: str,
    *,
    architecture: str = "",
) -> dict[str, Any]:
    from ascendc_pilot.human_interaction import KIND_RESUME, attach_interaction_request

    summary = build_run_resume_summary(
        project_root, workflow_id=workflow_id, architecture=architecture
    )
    wf_label = _workflow_label(workflow_id)
    running = str(summary.get("status") or "") in RUNNING_LIKE
    leftover_ready = (
        workflow_id == "uo-init"
        and bool(summary.get("has_uo_artifacts"))
        and not running
        and not summary.get("cross_workflow")
    )
    if leftover_ready:
        error = "UO_ALREADY_READY"
        message_zh = (
            "上一场建库已经完成，产物锁已释放。新会话可以直接查询，不必再 /uo-init。"
            "选「去查询」保留 CodeMap；只有要推倒重来才选「删除重开」。"
        )
    else:
        error = "EXISTING_RUN_NEEDS_DECISION"
        message_zh = (
            f"检测到未完成的 {wf_label} run 或同族写锁冲突。"
            "请等待 Host 弹出选项；选定后 Host 会继续执行。"
            "不要自己 bash `acp answer` 或 `acp start`。"
        )
    payload = {
        "ok": False,
        "needs_human_decision": True,
        "error": error,
        "already_ready": leftover_ready,
        "message_zh": message_zh,
        "ask_question": summary["ask_question"],
        "decision_values": summary["decision_values"],
        "commands": summary["commands"],
        "run_summary": summary,
        "run_id": (summary.get("run_id") or ""),
    }
    return attach_interaction_request(
        payload,
        project_root,
        kind=KIND_RESUME,
        decision_kind="resume",
    )
