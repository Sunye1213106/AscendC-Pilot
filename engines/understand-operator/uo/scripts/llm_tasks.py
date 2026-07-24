"""LLM task lifecycle with stable ids, snapshot hashes, and supersede rules."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml

MAX_TASK_ATTEMPTS = 3
MAX_SEMANTIC_BATCHES = 8

TASK_TYPES = frozenset(
    {
        "entrypoint_dispatch_bind",
        "io_slot_bind",
        "tilingdata_bridge",
        "tilingkey_schema_bind",
        "macro_semantics",
        "mark_missing",
        "inspect_candidates",
        "choose_edge",
    }
)


def stable_task_id(
    *,
    task_type: str,
    target_role_or_edge: str,
    candidate_ids: list[str] | tuple[str, ...] | None,
    source_snapshot_hash: str,
) -> str:
    cand = ",".join(sorted(str(c) for c in (candidate_ids or [])))
    raw = f"{task_type}|{target_role_or_edge}|{cand}|{source_snapshot_hash}"
    return "TASK_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def candidate_set_hash(candidates: list[dict[str, Any]] | None) -> str:
    ids = sorted(str(c.get("id") or c.get("symbol_ref") or c.get("file_path") or "") for c in (candidates or []))
    return hashlib.sha256(",".join(ids).encode("utf-8")).hexdigest()[:16]


def load_llm_tasks(uo_root: Path) -> dict[str, Any]:
    path = uo_root / "ir" / "llm_tasks.yaml"
    data = read_yaml(path) or {}
    if not data:
        data = {"version": 1, "tasks": [], "total_semantic_batches": 0}
    data.setdefault("version", 1)
    data.setdefault("tasks", [])
    data.setdefault("total_semantic_batches", 0)
    return data


def save_llm_tasks(uo_root: Path, payload: dict[str, Any]) -> Path:
    path = uo_root / "ir" / "llm_tasks.yaml"
    write_yaml(path, payload)
    return path


def upsert_tasks_from_score_items(
    uo_root: Path,
    items: list[dict[str, Any]],
    *,
    checkpoint: str,
    run_id: str = "",
    source_snapshot_hash: str = "",
) -> dict[str, Any]:
    """Create/update tasks for items with disposition=llm_task. Same id → no re-open."""
    doc = load_llm_tasks(uo_root)
    by_id = {str(t.get("task_id")): t for t in doc.get("tasks") or [] if isinstance(t, dict)}
    created = 0
    for item in items:
        if item.get("disposition") != "llm_task":
            continue
        severity = str(item.get("severity") or "degraded")
        if severity == "none":
            continue
        hint = str(item.get("task_hint") or "choose_edge")
        if hint == "mark_missing":
            task_type = "mark_missing"
        elif item.get("object_type") == "io_slot_bind":
            task_type = "io_slot_bind"
        elif item.get("object_type") == "tilingdata_bridge":
            task_type = "tilingdata_bridge"
        elif item.get("object_type") == "tilingkey_binding":
            task_type = "tilingkey_schema_bind"
        elif item.get("object_type") in {"registration_edge", "call_edge", "entrypoint_node"}:
            task_type = "entrypoint_dispatch_bind"
        else:
            task_type = hint if hint in TASK_TYPES else "inspect_candidates"

        target = str(item.get("target_id") or item.get("role") or item.get("edge_type") or "unknown")
        candidates = item.get("candidates") or _default_candidates(item)
        if hint == "choose_edge" and not candidates:
            # Critical but ungrounded → mark_missing with empty candidate set forbidden for choose.
            task_type = "mark_missing"
            hint = "mark_missing"
        cand_hash = candidate_set_hash(candidates)
        tid = stable_task_id(
            task_type=task_type,
            target_role_or_edge=target,
            candidate_ids=[str(c.get("id") or "") for c in candidates],
            source_snapshot_hash=source_snapshot_hash or "nosnap",
        )
        existing = by_id.get(tid)
        if existing and existing.get("status") == "open":
            # Same stable id — do not duplicate.
            continue
        if existing and existing.get("status") in {"resolved", "rejected"}:
            continue
        # Supersede older open tasks for same target+type with different snapshot.
        for old in list(by_id.values()):
            if (
                old.get("type") == task_type
                and old.get("target") == target
                and old.get("status") == "open"
                and old.get("task_id") != tid
            ):
                old["status"] = "superseded"
                old["superseded_by"] = tid

        # Empty candidate window / mark_missing: no accept_edge (false closure).
        if task_type == "mark_missing" or not candidates:
            allowed_actions = ["mark_missing", "inspect_candidates", "reject_edge"]
        else:
            allowed_actions = [
                "accept_edge",
                "reject_edge",
                "choose_one",
                "mark_missing",
                "inspect_candidates",
            ]
        task = {
            "task_id": tid,
            "status": "open",
            "run_id": run_id,
            "checkpoint": checkpoint,
            "source_snapshot_hash": source_snapshot_hash or "nosnap",
            "candidate_set_hash": cand_hash,
            "task_attempts": 0,
            "type": task_type,
            "severity": severity,
            "target": target,
            "object_type": item.get("object_type"),
            "score": item.get("score"),
            "necessity": item.get("necessity"),
            "candidates": candidates,
            "allowed_actions": allowed_actions,
            "forbidden": ["invent_symbol", "repo_wide_search"],
            "resolution": None,
        }
        by_id[tid] = task
        created += 1

    doc["tasks"] = list(by_id.values())
    save_llm_tasks(uo_root, doc)
    return {
        "task_count": len(doc["tasks"]),
        "open_blocking": sum(
            1 for t in doc["tasks"] if t.get("status") == "open" and t.get("severity") == "blocking"
        ),
        "created": created,
        "total_semantic_batches": int(doc.get("total_semantic_batches") or 0),
    }


def _default_candidates(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Build grounded candidates; refuse empty placeholders for choose_edge."""
    existing = item.get("candidates")
    if isinstance(existing, list) and existing:
        grounded = []
        for c in existing:
            if not isinstance(c, dict):
                continue
            if not (c.get("file_path") or c.get("snippet") or c.get("signature_snippet")):
                continue
            grounded.append(
                {
                    "id": str(c.get("id") or f"cand_{c.get('symbol_ref') or c.get('name') or 'x'}"),
                    "file_path": c.get("file_path") or "",
                    "symbol_ref": c.get("symbol_ref") or c.get("qualified_name") or c.get("name") or "",
                    "snippet": c.get("snippet") or c.get("signature_snippet") or "",
                    "start_line": c.get("start_line"),
                    "score": c.get("score") or item.get("score"),
                }
            )
        if grounded:
            return grounded
    # Fall back to locator / evidence on the scored item itself.
    loc = item.get("locator") or {}
    evidence = item.get("evidence") or []
    file_path = loc.get("file_path") or item.get("file_path") or ""
    snippet = item.get("snippet") or item.get("signature_snippet") or ""
    start_line = loc.get("start_line") or item.get("start_line")
    if not file_path and evidence and isinstance(evidence[0], dict):
        file_path = evidence[0].get("file_path") or ""
        start_line = evidence[0].get("line") or start_line
        snippet = snippet or str(evidence[0].get("macro") or evidence[0].get("reason") or "")
    tid = str(item.get("target_id") or "unknown")
    if not file_path and not snippet:
        # No grounded window — caller should use mark_missing, not choose_edge.
        return []
    return [
        {
            "id": f"cand_{tid}",
            "file_path": file_path,
            "symbol_ref": tid,
            "snippet": snippet,
            "start_line": start_line,
            "score": item.get("score"),
        }
    ]


def open_blocking_tasks(uo_root: Path) -> list[dict[str, Any]]:
    doc = load_llm_tasks(uo_root)
    return [t for t in doc.get("tasks") or [] if t.get("status") == "open" and t.get("severity") == "blocking"]


def apply_task_patch(
    uo_root: Path,
    patch: dict[str, Any],
    *,
    current_source_hash: str | None = None,
) -> dict[str, Any]:
    """Validate and apply one LLM patch into the resolution ledger; bump attempts.

    Does NOT mutate derived graphs — writes ledger only (⑦).
    """
    from uo.scripts.semantic_resolution_ledger import append_semantic_patch

    doc = load_llm_tasks(uo_root)
    task_id = str(patch.get("task_id") or "")
    task = next((t for t in doc.get("tasks") or [] if t.get("task_id") == task_id), None)
    if task is None:
        return {"ok": False, "error": "unknown_task_id", "task_id": task_id}
    if task.get("status") != "open":
        return {"ok": False, "error": "task_not_open", "status": task.get("status")}

    src_hash = current_source_hash or task.get("source_snapshot_hash")
    if src_hash and task.get("source_snapshot_hash") and src_hash != task.get("source_snapshot_hash"):
        task["status"] = "superseded"
        save_llm_tasks(uo_root, doc)
        return {"ok": False, "error": "source_snapshot_stale", "task_id": task_id}

    cand_ids = {str(c.get("id")) for c in (task.get("candidates") or []) if str(c.get("id") or "").strip()}
    accepted = [str(x) for x in (patch.get("accepted_candidate_ids") or [])]
    rejected = [str(x) for x in (patch.get("rejected_candidate_ids") or [])]

    # Optional: reject invent_symbol
    for sym in patch.get("invented_symbols") or []:
        return {"ok": False, "error": "forbidden_invent_symbol", "symbol": sym}

    action = str(patch.get("action") or ("mark_missing" if task.get("type") == "mark_missing" else "accept_edge"))
    allowed = {str(a) for a in (task.get("allowed_actions") or [])}
    if allowed and action not in allowed:
        return {
            "ok": False,
            "error": "action_not_allowed",
            "action": action,
            "allowed_actions": sorted(allowed),
            "task_id": task_id,
        }

    accept_actions = {"accept_edge", "choose_one", "accept", "select_edge", "select"}
    if action in accept_actions:
        # Empty candidate window must stay mark_missing / unresolved — never invent a close.
        if not cand_ids:
            return {
                "ok": False,
                "error": "empty_candidate_false_closure",
                "task_id": task_id,
                "message": "accept_edge forbidden when candidates are empty; use mark_missing",
            }
        if not accepted:
            return {"ok": False, "error": "accept_requires_candidate", "task_id": task_id}
        for cid in accepted + rejected:
            if cid not in cand_ids:
                return {"ok": False, "error": "candidate_out_of_window", "candidate_id": cid}
    else:
        for cid in accepted + rejected:
            if cand_ids and cid not in cand_ids:
                return {"ok": False, "error": "candidate_out_of_window", "candidate_id": cid}
        # Honest mark_missing must not smuggle accepted edge ids for ledger upgrade.
        if action == "mark_missing" and accepted:
            return {
                "ok": False,
                "error": "mark_missing_forbids_accepted_ids",
                "task_id": task_id,
            }

    attempts = int(task.get("task_attempts") or 0) + 1
    task["task_attempts"] = attempts
    batches = int(doc.get("total_semantic_batches") or 0) + 1
    doc["total_semantic_batches"] = batches

    if attempts > MAX_TASK_ATTEMPTS:
        task["status"] = "rejected"
        task["resolution"] = {"error": "task_attempts_exhausted", "patch": patch}
        save_llm_tasks(uo_root, doc)
        return {"ok": False, "error": "task_attempts_exhausted", "task_attempts": attempts}

    if batches > MAX_SEMANTIC_BATCHES:
        save_llm_tasks(uo_root, doc)
        return {"ok": False, "error": "total_semantic_batches_exhausted", "batches": batches}

    if action == "mark_missing":
        task["status"] = "resolved"
        task["resolution"] = {"action": "mark_missing", "patch": patch}
    else:
        task["status"] = "resolved"
        task["resolution"] = {"action": action, "patch": patch}

    ledger_entry = append_semantic_patch(
        uo_root,
        {
            "task_id": task_id,
            "accepted_candidate_ids": accepted,
            "rejected_candidate_ids": rejected,
            "relation": patch.get("relation") or task.get("type"),
            "evidence": patch.get("evidence") or [],
            "source_snapshot_hash": task.get("source_snapshot_hash"),
            "candidate_set_hash": task.get("candidate_set_hash"),
            "verification_source": "llm",
            "confidence": "semantic_verified",
            "action": action,
        },
    )
    save_llm_tasks(uo_root, doc)
    return {
        "ok": True,
        "task_id": task_id,
        "task_attempts": attempts,
        "total_semantic_batches": batches,
        "ledger_entry": ledger_entry,
    }


def recheck_does_not_increment(uo_root: Path) -> dict[str, Any]:
    """⑥ Recheck helper — read budgets without mutating attempts."""
    doc = load_llm_tasks(uo_root)
    return {
        "ok": True,
        "open_blocking": open_blocking_tasks(uo_root),
        "total_semantic_batches": int(doc.get("total_semantic_batches") or 0),
        "tasks": doc.get("tasks") or [],
    }
