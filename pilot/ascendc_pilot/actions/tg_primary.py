"""Primary-session TG confirmation and approval helpers."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ascendc_pilot.paths import runs_root, tg_root
from ascendc_pilot.state import load_state


PRIMARY_TG_ACTIONS = frozenset({"human_confirm", "plan_approve"})


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


def primary_interactive_steps(action_id: str, project_root: Path, result: dict[str, Any]) -> list[str]:
    root = project_root.expanduser().resolve().as_posix()
    if action_id == "human_confirm":
        return [
            f"Review {root}/.ascendc-pilot/tg/init/audit_report.yaml and remaining realization gaps.",
            "AskQuestion: confirm | rework | stop.",
            "Only after `confirm`, run: "
            f"acp run-action human_confirm --finalize --project {root}",
            "For `rework` or `stop`, do not finalize and report the blocking reason.",
        ]
    if action_id == "plan_approve":
        return [
            f"Review the current level under {root}/.ascendc-pilot/tg/plan/levels/.",
            "Check coverage_obligations.yaml, unresolved.yaml, and any human-required items.",
            "AskQuestion: approve | rework | stop.",
            "Only after `approve`, run: "
            f"acp run-action plan_approve --finalize --project {root}",
            "For `rework` or `stop`, do not finalize and report the blocking reason.",
        ]
    return list(result.get("interactive_steps") or [])


def materialize_primary_decision(project_root: Path, action_id: str) -> dict[str, Any]:
    """Write the affirmative decision contract immediately before finalization.

    Calling ``--finalize`` is the affirmative signal. Rework/stop paths never
    call this function, so no approval artifact is produced accidentally.
    """

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

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    identity = _identity(session)
    tg = tg_root(project_root)
    backups: dict[Path, bytes | None] = {}

    if action_id == "human_confirm":
        # Use the domain engine's canonical confirmation path: it rechecks merge,
        # domain symmetry, full CSV closure, audit completeness, and writes the
        # UO fingerprint before status can become confirmed.
        from ascendc_pilot.workflows import resolve_tg_mode

        mode = resolve_tg_mode(project_root)
        require_merge = mode == "csv_consumer"
        watched = [
            tg / "init" / "status.yaml",
            tg / "init" / "kb_fingerprint.yaml",
            tg / "init" / "confirmation.yaml",
        ]
        if require_merge:
            watched.extend(
                [
                    tg / "realization" / "domain_review.yaml",
                    tg / "realization" / "binding_lexicon.yaml",
                ]
            )
        backups = {candidate: candidate.read_bytes() if candidate.is_file() else None for candidate in watched}
        try:
            from testcase_agent.init_status import mark_init_confirmed

            mark_init_confirmed(
                tg,
                notes="Confirmed by Pilot primary_interactive Action",
                require_merge=require_merge,
            )
        except Exception as exc:  # noqa: BLE001
            rollback_primary_decision({"backups": backups})
            return {
                "ok": False,
                "error": "INIT_CONFIRM_DOMAIN_GATE_FAILED",
                "message_zh": str(exc)[:400],
            }
        # Record a narrow confirmation receipt (ownership: human_confirm only).
        confirm_path = tg / "init" / "confirmation.yaml"
        _dump(
            confirm_path,
            {
                "schema": "tg-init-confirmation/v1",
                "status": "confirmed",
                "mode": mode,
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
    elif action_id == "plan_approve":
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
    else:
        return {"ok": False, "error": "NOT_PRIMARY_TG_ACTION", "action_id": action_id}

    _dump(path, doc)
    return {
        "ok": True,
        "path": path,
        "backups": backups,
        "identity": identity,
    }


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
