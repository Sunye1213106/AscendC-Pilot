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
        "evidence_enrichment",
        "candidate_generation",
    }
)

PATCH_TYPES = frozenset(
    {
        "edge_resolution",
        "entrypoint_node_resolution",
        "entrypoint_dispatch_resolution",
        "call_edge_resolution",
        "tilingdata_bridge_resolution",
        "template_instance_resolution",
        "mark_missing",
        "candidate_enrichment",
        "scope_expansion_request",
    }
)

_ACCEPT_CLOSE_ACTIONS = frozenset({"accept_edge", "choose_one", "accept", "select_edge", "select"})


# Task lifecycle (task_status):
#   open → adjudicated → pending_materialization → resolved
# Failure: pending_materialization → rework_required → (open/unresolved)
# semantic_status: unresolved | pending_materialization | closed

_SEMANTIC_OPEN = frozenset({"unresolved", "pending_materialization", ""})
_LIFECYCLE_GAP = frozenset(
    {"open", "adjudicated", "pending_materialization", "rework_required"}
)


def _semantic_status(task: dict[str, Any]) -> str:
    return str(task.get("semantic_status") or "unresolved")


def _task_lifecycle(task: dict[str, Any]) -> str:
    return str(task.get("task_status") or task.get("status") or "")


def _task_is_blocking(task: dict[str, Any]) -> bool:
    if "blocking" in task:
        return bool(task.get("blocking"))
    return str(task.get("severity") or "") == "blocking"


def _semantic_gap_open(task: dict[str, Any]) -> bool:
    """True when semantic closure still needs work (shared by Gate/Engine/recheck)."""
    if not _task_is_blocking(task):
        return False
    if _semantic_status(task) == "closed":
        return False
    # Phase-scoped: KEY gaps / tg_resolvable must not block extract advance.
    if task.get("blocks_extract_advance") is False:
        return False
    if str(task.get("resolution_class") or "") == "tg_resolvable":
        return False
    if str(task.get("resolution_class") or "") == "degraded":
        return False
    lifecycle = _task_lifecycle(task)
    if lifecycle in {"provisional"}:
        # Pre-semantic diagnostics are not extract-blocking gaps.
        return False
    if lifecycle in {"resolved"} and _semantic_status(task) == "closed":
        return False
    # pending_materialization / rework_required / adjudicated / open all count as gaps
    if lifecycle in _LIFECYCLE_GAP or _semantic_status(task) in _SEMANTIC_OPEN:
        return True
    return _semantic_status(task) != "closed"


def _task_eligible_for_adjudication(task: dict[str, Any]) -> bool:
    if task.get("eligible_for_adjudication") is False:
        return False
    score_phase = str(task.get("score_phase") or "")
    checkpoint = str(task.get("checkpoint") or "")
    if score_phase == "pre_semantic" or "pre_semantic" in checkpoint:
        return False
    if score_phase and score_phase != "post_semantic" and "post_semantic" not in checkpoint:
        return False
    route = str(task.get("route") or "")
    if route and route != "uo-semantic-resolve":
        return False
    return True


def _is_candidate_node_id(value: Any) -> bool:
    s = str(value or "").strip()
    return s.startswith("cand_") or s.startswith("cand_EP_")


def _is_real_edge_id(value: Any) -> bool:
    s = str(value or "").strip()
    return bool(s) and not _is_candidate_node_id(s)


def _bridge_identity_complete(item: dict[str, Any]) -> bool:
    return bool(
        (item.get("owning_type") or item.get("canonical_type"))
        and item.get("field_path")
        and (item.get("unit_id") or item.get("extraction_unit"))
    )


def _infer_patch_type(task: dict[str, Any], action: str) -> str:
    if action == "mark_missing":
        return "mark_missing"
    if action in {"candidate_enrichment", "enrich_candidates"}:
        return "candidate_enrichment"
    if action in {"scope_expansion_request", "request_scope_expansion"}:
        return "scope_expansion_request"
    ttype = str(task.get("type") or "")
    effective = str(task.get("effective_task_type") or "")
    obj = str(task.get("object_type") or "")
    if effective == "candidate_generation" or ttype == "candidate_generation":
        return "candidate_enrichment"
    if effective == "evidence_enrichment" or ttype == "evidence_enrichment":
        return "scope_expansion_request"
    if obj == "tilingdata_bridge" or ttype == "tilingdata_bridge":
        return "tilingdata_bridge_resolution"
    if obj == "entrypoint_node":
        return "entrypoint_node_resolution"
    if obj == "call_edge":
        # Legacy choose_edge patches without an explicit typed payload stay edge_resolution.
        return "edge_resolution"
    if obj in {"entrypoint_dispatch_bind"} or obj in {"registration_edge"}:
        return "entrypoint_dispatch_resolution"
    if ttype == "choose_edge":
        return "edge_resolution"
    return "edge_resolution"


def _effective_patch_type(task: dict[str, Any], patch: dict[str, Any], action: str) -> str:
    """Prefer explicit patch_type. Never silently downgrade typed patches to edge_resolution."""
    explicit = str(patch.get("patch_type") or "").strip()
    return explicit or _infer_patch_type(task, action)


def _require_current_run_id(current_run_id: str | None) -> dict[str, Any] | None:
    if not str(current_run_id or "").strip():
        return {"ok": False, "error": "SEMANTIC_DOCUMENT_RUN_ID_MISSING", "message": "current_run_id is required"}
    return None


def _assert_task_run(task: dict[str, Any], current_run_id: str) -> dict[str, Any] | None:
    task_run = str(task.get("run_id") or "").strip()
    if not task_run:
        return {
            "ok": False,
            "error": "SEMANTIC_TASK_RUN_ID_MISSING",
            "task_id": task.get("task_id"),
        }
    if task_run != str(current_run_id):
        return {
            "ok": False,
            "error": "SEMANTIC_TASK_RUN_MISMATCH",
            "task_id": task.get("task_id"),
            "task_run_id": task_run,
            "current_run_id": current_run_id,
        }
    return None


def _assert_patch_run(patch: dict[str, Any], current_run_id: str) -> dict[str, Any] | None:
    patch_run = str(patch.get("run_id") or "").strip()
    if not patch_run:
        # Also accept nested artifact_identity on single patch entries
        ident = patch.get("artifact_identity") if isinstance(patch.get("artifact_identity"), dict) else {}
        patch_run = str(ident.get("run_id") or "").strip()
    if not patch_run:
        return {
            "ok": False,
            "error": "SEMANTIC_PATCH_RUN_ID_MISSING",
            "task_id": patch.get("task_id"),
        }
    if patch_run != str(current_run_id):
        return {
            "ok": False,
            "error": "SEMANTIC_PATCH_RUN_MISMATCH",
            "task_id": patch.get("task_id"),
            "patch_run_id": patch_run,
            "current_run_id": current_run_id,
        }
    return None


def assert_llm_tasks_document_run(
    doc: dict[str, Any],
    current_run_id: str,
    *,
    workflow_id: str = "",
) -> dict[str, Any]:
    """Fail-closed document identity check for llm_tasks.yaml."""
    identity = doc.get("artifact_identity") if isinstance(doc.get("artifact_identity"), dict) else {}
    doc_run = str(identity.get("run_id") or doc.get("active_run_id") or "").strip()
    active = str(doc.get("active_run_id") or "").strip()
    if not doc_run and not active and not (doc.get("tasks") or []):
        # Empty fresh doc — caller should stamp identity on first write.
        return {"ok": True, "empty": True}
    if not doc_run:
        return {"ok": False, "error": "SEMANTIC_DOCUMENT_RUN_ID_MISSING"}
    if active and active != doc_run:
        return {
            "ok": False,
            "error": "SEMANTIC_DOCUMENT_RUN_MISMATCH",
            "active_run_id": active,
            "artifact_run_id": doc_run,
        }
    if doc_run != str(current_run_id):
        return {
            "ok": False,
            "error": "SEMANTIC_DOCUMENT_RUN_MISMATCH",
            "document_run_id": doc_run,
            "current_run_id": current_run_id,
        }
    if workflow_id:
        doc_wf = str(identity.get("workflow_id") or doc.get("workflow_id") or "").strip()
        if doc_wf and doc_wf != workflow_id:
            return {
                "ok": False,
                "error": "SEMANTIC_DOCUMENT_RUN_MISMATCH",
                "field": "workflow_id",
                "document_workflow_id": doc_wf,
                "current_workflow_id": workflow_id,
            }
    return {"ok": True}


def stamp_llm_tasks_identity(
    doc: dict[str, Any],
    *,
    run_id: str,
    workflow_id: str = "uo-init",
) -> dict[str, Any]:
    out = dict(doc)
    out["version"] = int(out.get("version") or 1)
    out["active_run_id"] = run_id
    out["artifact_identity"] = {
        "run_id": run_id,
        "workflow_id": workflow_id or "uo-init",
    }
    return out


def _tasks_for_run(doc: dict[str, Any], current_run_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in doc.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        err = _assert_task_run(t, current_run_id)
        if err is None:
            out.append(t)
        # Missing/mismatch tasks are excluded from processing lists; validators
        # surface explicit errors when those tasks are targeted by patches.
    return out


def _resolve_patch_edge_id(task: dict[str, Any], patch: dict[str, Any], *, accepted: list[str]) -> str | None:
    raw = patch.get("edge_id") or task.get("target")
    if _is_real_edge_id(raw):
        return str(raw)
    for cid in accepted:
        if _is_real_edge_id(cid):
            return str(cid)
    return None


def blocking_gap_tasks(uo_root: Path, *, current_run_id: str) -> list[dict[str, Any]]:
    """Blocking semantic gaps — shared SSOT for Gate / Engine / recheck.

    ``current_run_id`` is required. Tasks without matching run_id are ignored.
    """
    if not str(current_run_id or "").strip():
        raise ValueError("SEMANTIC_DOCUMENT_RUN_ID_MISSING: current_run_id required")
    doc = load_llm_tasks(uo_root)
    doc_check = assert_llm_tasks_document_run(doc, current_run_id)
    if not doc_check.get("ok") and not doc_check.get("empty"):
        return []
    out = []
    for t in _tasks_for_run(doc, current_run_id):
        if _semantic_gap_open(t):
            out.append(t)
    return out


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
    run_id: str,
    source_snapshot_hash: str = "",
    workflow_id: str = "",
    score_phase: str = "",
    eligible_for_adjudication: bool | None = None,
) -> dict[str, Any]:
    """Create/update tasks for items with disposition=llm_task. Same id → no re-open."""
    if not str(run_id or "").strip():
        raise ValueError("SEMANTIC_DOCUMENT_RUN_ID_MISSING: run_id required for upsert_tasks_from_score_items")
    current_run_id = str(run_id).strip()
    wf = workflow_id or "uo-init"
    phase = str(score_phase or "").strip()
    if not phase:
        phase = "pre_semantic" if "pre_semantic" in checkpoint else (
            "post_semantic" if "post_semantic" in checkpoint else ""
        )
    doc = load_llm_tasks(uo_root)
    doc_check = assert_llm_tasks_document_run(doc, current_run_id, workflow_id=wf)
    if not doc_check.get("ok") and not doc_check.get("empty"):
        raise ValueError(f"{doc_check.get('error')}: llm_tasks document run mismatch")
    doc = stamp_llm_tasks_identity(doc, run_id=current_run_id, workflow_id=wf)
    by_id = {str(t.get("task_id")): t for t in doc.get("tasks") or [] if isinstance(t, dict)}
    created = 0
    for item in items:
        if item.get("disposition") != "llm_task":
            continue
        severity = str(item.get("severity") or "degraded")
        if severity == "none":
            continue
        hint = str(item.get("task_hint") or "choose_edge")
        object_type = str(item.get("object_type") or "")
        target = str(item.get("target_id") or item.get("role") or item.get("edge_type") or "unknown")
        # Canonicalize candidates first; task type depends on final candidate set.
        candidates = _default_candidates(item)
        if not isinstance(candidates, list):
            candidates = []

        if hint == "mark_missing":
            task_type = "mark_missing"
        elif object_type == "io_slot_bind":
            task_type = "io_slot_bind"
        elif object_type == "tilingdata_bridge":
            task_type = "tilingdata_bridge"
        elif object_type == "tilingkey_binding":
            task_type = "tilingkey_schema_bind"
        elif object_type in {"registration_edge", "call_edge", "entrypoint_node"}:
            task_type = "entrypoint_dispatch_bind"
        else:
            task_type = hint if hint in TASK_TYPES else "inspect_candidates"

        # Empty candidates: scoring hint alone never implies mark_missing.
        # Keep mark_missing only with machine-verifiable negative_evidence.
        if not candidates:
            has_neg = _valid_negative_evidence(item.get("negative_evidence"))
            if hint == "mark_missing" and has_neg:
                task_type = "mark_missing"
                hint = "mark_missing"
            elif object_type in {"call_edge", "registration_edge", "entrypoint_node"} or task_type == "entrypoint_dispatch_bind":
                task_type = "candidate_generation"
                hint = "candidate_generation"
            elif object_type == "tilingdata_bridge" or task_type == "tilingdata_bridge":
                task_type = "evidence_enrichment"
                hint = "evidence_enrichment"
            elif hint in {"choose_edge", "mark_missing"} or severity == "blocking":
                task_type = "evidence_enrichment"
                hint = "evidence_enrichment"
        cand_hash = candidate_set_hash(candidates)
        tid = stable_task_id(
            task_type=task_type,
            target_role_or_edge=target,
            candidate_ids=[str(c.get("id") or "") for c in candidates],
            source_snapshot_hash=source_snapshot_hash or "nosnap",
        )
        existing = by_id.get(tid)
        if existing and existing.get("status") == "open":
            # Same stable id — do not duplicate; refresh phase flags.
            existing["score_phase"] = phase or existing.get("score_phase")
            if eligible_for_adjudication is not None:
                existing["eligible_for_adjudication"] = eligible_for_adjudication
            continue
        if existing and existing.get("status") in {"resolved", "rejected", "adjudicated"}:
            continue
        # Supersede older open/provisional tasks for same target+type with different snapshot.
        for old in list(by_id.values()):
            if (
                old.get("type") == task_type
                and old.get("target") == target
                and str(old.get("run_id") or "").strip() == current_run_id
                and old.get("status") in {"open", "provisional"}
                and old.get("task_id") != tid
            ):
                old["status"] = "superseded"
                old["task_status"] = "superseded"
                old["superseded_by"] = tid

        # Empty candidate window: never offer accept_edge / choose_one (false closure).
        if task_type in {"mark_missing", "evidence_enrichment", "candidate_generation"} or not candidates:
            allowed_actions = ["mark_missing", "inspect_candidates", "reject_edge"]
        else:
            allowed_actions = [
                "accept_edge",
                "reject_edge",
                "choose_one",
                "mark_missing",
                "inspect_candidates",
            ]
        blocking = severity == "blocking"
        is_pre = phase == "pre_semantic"
        elig = False if is_pre else eligible_for_adjudication
        if elig is None and not is_pre:
            elig = True  # triage may tighten later
        task = {
            "task_id": tid,
            # Keep status=open for document compatibility; task_status carries provisional.
            "status": "open",
            "task_status": "provisional" if is_pre else "open",
            "run_id": current_run_id,
            "workflow_id": wf,
            "checkpoint": checkpoint,
            "score_phase": phase,
            "eligible_for_adjudication": bool(elig) if elig is not None else (not is_pre),
            "source_snapshot_hash": source_snapshot_hash or "nosnap",
            "candidate_set_hash": cand_hash,
            "task_attempts": 0,
            "type": task_type,
            "task_hint": hint,
            "severity": severity,
            "blocking": blocking,
            "semantic_status": "unresolved",
            "target": target,
            "object_type": item.get("object_type"),
            "score": item.get("score"),
            "necessity": item.get("necessity"),
            "candidates": candidates,
            "allowed_actions": allowed_actions,
            "forbidden": ["invent_symbol", "repo_wide_search"],
            "resolution": None,
        }
        if isinstance(item.get("negative_evidence"), dict):
            task["negative_evidence"] = dict(item["negative_evidence"])
        by_id[tid] = task
        created += 1

    doc["tasks"] = list(by_id.values())
    doc = stamp_llm_tasks_identity(doc, run_id=current_run_id, workflow_id=wf)
    save_llm_tasks(uo_root, doc)
    run_tasks = _tasks_for_run(doc, current_run_id)
    return {
        "task_count": len(run_tasks),
        "open_blocking": sum(
            1
            for t in run_tasks
            if t.get("status") == "open" and _task_is_blocking(t) and _semantic_status(t) != "closed"
        ),
        "blocking_gap_count": sum(
            1 for t in run_tasks if _semantic_gap_open(t)
        ),
        "created": created,
        "total_semantic_batches": int(doc.get("total_semantic_batches") or 0),
        "active_run_id": current_run_id,
    }


def close_tasks_resolved_by_score(
    uo_root: Path,
    items: list[dict[str, Any]],
    *,
    current_run_id: str,
    reason: str = "post_semantic_auto_accept",
) -> dict[str, Any]:
    """Close open/provisional tasks whose targets are now auto_accept in score items."""
    if not str(current_run_id or "").strip():
        return {"ok": False, "closed": 0}
    accepted_targets = {
        str(i.get("target_id") or "")
        for i in items
        if isinstance(i, dict) and i.get("disposition") == "auto_accept" and i.get("target_id")
    }
    if not accepted_targets:
        return {"ok": True, "closed": 0}
    doc = load_llm_tasks(uo_root)
    closed = 0
    for t in _tasks_for_run(doc, current_run_id):
        if str(t.get("target") or "") not in accepted_targets:
            continue
        if t.get("status") not in {"open", "provisional", "rework_required"}:
            continue
        t["status"] = "resolved"
        t["task_status"] = "resolved"
        t["semantic_status"] = "closed"
        t["resolution"] = {"action": "auto_closed", "reason": reason}
        closed += 1
    if closed:
        save_llm_tasks(uo_root, doc)
    return {"ok": True, "closed": closed, "accepted_targets": sorted(accepted_targets)}


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


def open_blocking_tasks(uo_root: Path, *, current_run_id: str) -> list[dict[str, Any]]:
    """Tasks that still need LLM patch adjudication (post_semantic + routed)."""
    if not str(current_run_id or "").strip():
        raise ValueError("SEMANTIC_DOCUMENT_RUN_ID_MISSING: current_run_id required")
    doc = load_llm_tasks(uo_root)
    doc_check = assert_llm_tasks_document_run(doc, current_run_id)
    if not doc_check.get("ok") and not doc_check.get("empty"):
        return []
    out: list[dict[str, Any]] = []
    for t in _tasks_for_run(doc, current_run_id):
        lifecycle = _task_lifecycle(t)
        if lifecycle not in {"open", "rework_required"}:
            continue
        if not _task_is_blocking(t):
            continue
        if _semantic_status(t) == "closed":
            continue
        if not _task_eligible_for_adjudication(t):
            continue
        out.append(t)
    return out


_AUTO_MARK_MISSING_FORBIDDEN_CATEGORIES = frozenset(
    {
        "candidate_generation_required",
        "incomplete_scope_candidate",
        "identity_join_ambiguous",
        "true_multi_candidate",
        "macro_contract_resolvable",
        "key_derivation_gap",
        "tilingdata_type_unknown",
    }
)


def _valid_negative_evidence(evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    queries = evidence.get("queries")
    windows = evidence.get("inspected_windows")
    absence = str(evidence.get("absence_kind") or "").strip()
    if absence in {"scope_incomplete", ""}:
        return False
    if not isinstance(queries, list) or not queries:
        return False
    if not isinstance(windows, list) or not windows:
        return False
    if not str(evidence.get("scope_snapshot_sha256") or "").strip():
        return False
    return True


def can_auto_mark_missing(task: dict[str, Any]) -> bool:
    """Shared auto mark_missing predicate (Gate / pipeline / apply).

    Empty candidates alone never proves absence — triage category and
    machine-verifiable negative_evidence are required.
    """
    category = str(task.get("triage_category") or task.get("category") or "")
    if category in _AUTO_MARK_MISSING_FORBIDDEN_CATEGORIES:
        return False
    effective = str(
        task.get("effective_task_type")
        or task.get("type")
        or ""
    ).strip()
    if effective in {"evidence_enrichment", "candidate_generation", "macro_semantics", "key_derivation", "typed_bridge_resolution", "choose_edge"}:
        return False
    if effective != "mark_missing":
        return False
    if task.get("candidates"):
        return False
    return _valid_negative_evidence(task.get("negative_evidence"))


# Back-compat alias
_can_auto_mark_missing = can_auto_mark_missing

# Legacy error code from ses_0622; keep as alias for log search.
LEGACY_PATCH_CSET_MISSING = "patch_candidate_set_hash_missing"
PATCH_CSET_MISSING = "candidate_set_hash_missing_on_patch"


def normalize_patch_candidate_set_hash(patch: dict[str, Any]) -> dict[str, Any]:
    """Canonical field is ``candidate_set_hash``; accept legacy ``patch_candidate_set_hash``.

    Returns a shallow copy with the authoritative key filled when only the alias
    was written (ses_0622 Host/producer misread the old error code).
    """
    out = dict(patch)
    primary = str(out.get("candidate_set_hash") or "").strip()
    alias = str(out.get("patch_candidate_set_hash") or "").strip()
    if not primary and alias:
        out["candidate_set_hash"] = alias
    return out


def validate_task_patch(
    doc: dict[str, Any],
    patch: dict[str, Any],
    *,
    current_source_hash: str | None = None,
    current_run_id: str,
    uo_root: Path | None = None,
) -> dict[str, Any]:
    """Validate one patch against an in-memory llm_tasks doc (mark_missing may read scope artifacts)."""
    req = _require_current_run_id(current_run_id)
    if req is not None:
        return req
    patch = normalize_patch_candidate_set_hash(patch)
    task_id = str(patch.get("task_id") or "")
    task = next((t for t in doc.get("tasks") or [] if t.get("task_id") == task_id), None)
    if task is None:
        return {"ok": False, "error": "unknown_task_id", "task_id": task_id}
    task_err = _assert_task_run(task, current_run_id)
    if task_err is not None:
        return task_err
    patch_err = _assert_patch_run(patch, current_run_id)
    if patch_err is not None:
        return patch_err
    lifecycle = str(task.get("task_status") or task.get("status") or "")
    if lifecycle not in {"open", "rework_required"}:
        return {"ok": False, "error": "task_not_open", "status": task.get("status"), "task_id": task_id}

    task_src = str(task.get("source_snapshot_hash") or "").strip()
    if not task_src:
        return {"ok": False, "error": "source_snapshot_hash_missing", "task_id": task_id}
    cur_src = str(current_source_hash or "").strip()
    if not cur_src:
        return {"ok": False, "error": "current_source_hash_missing", "task_id": task_id}
    if cur_src != task_src:
        return {"ok": False, "error": "source_snapshot_stale", "task_id": task_id}
    patch_src = str(patch.get("source_snapshot_hash") or "").strip()
    if patch_src and patch_src != task_src:
        return {"ok": False, "error": "source_snapshot_stale", "task_id": task_id}

    task_cset = str(task.get("candidate_set_hash") or "").strip()
    if not task_cset:
        return {"ok": False, "error": "candidate_set_hash_missing", "task_id": task_id}
    patch_cset = str(patch.get("candidate_set_hash") or "").strip()
    if not patch_cset:
        return {
            "ok": False,
            "error": PATCH_CSET_MISSING,
            "legacy_error": LEGACY_PATCH_CSET_MISSING,
            "task_id": task_id,
            "hint_zh": "在 patch 上填写 candidate_set_hash（从 llm_tasks 同 task_id 原样复制）；"
            "勿只写 patch_candidate_set_hash",
        }
    if patch_cset != task_cset:
        return {
            "ok": False,
            "error": "candidate_set_hash_mismatch",
            "task_id": task_id,
            "expected": task_cset,
            "got": patch_cset,
        }

    cand_ids = {str(c.get("id")) for c in (task.get("candidates") or []) if str(c.get("id") or "").strip()}
    accepted = [str(x) for x in (patch.get("accepted_candidate_ids") or [])]
    rejected = [str(x) for x in (patch.get("rejected_candidate_ids") or [])]

    for sym in patch.get("invented_symbols") or []:
        return {"ok": False, "error": "forbidden_invent_symbol", "symbol": sym, "task_id": task_id}

    action = str(patch.get("action") or ("mark_missing" if task.get("type") == "mark_missing" else "accept_edge"))
    patch_type_hint = str(patch.get("patch_type") or "").strip()
    # Enrichment / scope-expansion patches may omit accept ids; validate before accept path.
    if action in {"candidate_enrichment", "enrich_candidates"} or patch_type_hint == "candidate_enrichment":
        nested = patch.get("payload") if isinstance(patch.get("payload"), dict) else {}
        new_cands = patch.get("candidates") or nested.get("candidates") or []
        if not isinstance(new_cands, list) or not new_cands:
            return {
                "ok": False,
                "error": "candidate_enrichment_empty",
                "task_id": task_id,
                "message": "candidate_enrichment requires non-empty candidates; mark_missing forbidden here",
            }
        action = "candidate_enrichment"
    elif action in {"scope_expansion_request", "request_scope_expansion"} or patch_type_hint == "scope_expansion_request":
        nested = patch.get("payload") if isinstance(patch.get("payload"), dict) else {}
        proposed = patch.get("proposed_files") or nested.get("proposed_files") or []
        if not isinstance(proposed, list) or not proposed:
            return {
                "ok": False,
                "error": "scope_expansion_empty",
                "task_id": task_id,
                "message": "scope_expansion_request requires proposed_files",
            }
        action = "scope_expansion_request"

    allowed = {str(a) for a in (task.get("allowed_actions") or [])}
    # Implicitly allow enrichment actions for generation/scope triage categories.
    effective = str(task.get("effective_task_type") or task.get("type") or "")
    if effective == "candidate_generation":
        allowed = allowed | {"candidate_enrichment", "enrich_candidates"}
    if effective == "evidence_enrichment":
        allowed = allowed | {"scope_expansion_request", "request_scope_expansion"}
    if allowed and action not in allowed:
        return {
            "ok": False,
            "error": "action_not_allowed",
            "action": action,
            "allowed_actions": sorted(allowed),
            "task_id": task_id,
        }

    edge_claim = patch.get("edge_id") or (
        task.get("target") if action in _ACCEPT_CLOSE_ACTIONS else None
    )
    if _is_candidate_node_id(edge_claim):
        return {
            "ok": False,
            "error": "LEDGER_TARGET_TYPE_MISMATCH",
            "task_id": task_id,
            "edge_id": str(edge_claim),
        }
    if action in _ACCEPT_CLOSE_ACTIONS:
        for cid in accepted:
            if _is_candidate_node_id(cid) and str(task.get("object_type") or "") in {
                "registration_edge",
                "call_edge",
            }:
                # Accepting a candidate node id as an edge binding is forbidden.
                if not _is_real_edge_id(task.get("target")):
                    return {
                        "ok": False,
                        "error": "LEDGER_TARGET_TYPE_MISMATCH",
                        "task_id": task_id,
                        "candidate_id": cid,
                    }

    accept_actions = _ACCEPT_CLOSE_ACTIONS
    if action in {"candidate_enrichment", "scope_expansion_request"}:
        # Candidate ids in enrichment patches are new window members, not accept/reject.
        pass
    elif action in accept_actions:
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
                return {"ok": False, "error": "candidate_out_of_window", "candidate_id": cid, "task_id": task_id}
    else:
        for cid in accepted + rejected:
            if cand_ids and cid not in cand_ids:
                return {"ok": False, "error": "candidate_out_of_window", "candidate_id": cid, "task_id": task_id}
        if action == "mark_missing" and accepted:
            return {
                "ok": False,
                "error": "mark_missing_forbids_accepted_ids",
                "task_id": task_id,
            }

    if action == "mark_missing":
        mm_err = validate_mark_missing_patch(task, patch, uo_root=uo_root)
        if mm_err is not None:
            return mm_err

    next_attempts = int(task.get("task_attempts") or 0) + 1
    if next_attempts > MAX_TASK_ATTEMPTS:
        return {
            "ok": False,
            "error": "task_attempts_exhausted",
            "task_attempts": next_attempts,
            "task_id": task_id,
        }

    return {
        "ok": True,
        "task_id": task_id,
        "task": task,
        "action": action,
        "accepted": accepted,
        "rejected": rejected,
        "next_attempts": next_attempts,
        "patch": patch,
    }


_SCORE_ONLY_MARKERS = (
    "score",
    "confidence too low",
    "低于",
    "auto_accept",
    "阈值",
    "threshold",
    "评分",
)

_ABSENCE_KINDS = frozenset(
    {
        "negative_verified",
        "external_exact_contract",
        "project_definition_absent",
        "project_definition_not_indexed",
        "generated_definition",
        "scope_incomplete",
        "conditional_definition",
    }
)


def validate_mark_missing_patch(
    task: dict[str, Any],
    patch: dict[str, Any],
    *,
    uo_root: Path | None = None,
) -> dict[str, Any] | None:
    """Hard Gate for mark_missing. Returns error dict or None if ok."""
    task_id = str(task.get("task_id") or patch.get("task_id") or "")
    if str(task.get("triage_category") or "") == "macro_contract_resolvable":
        return {
            "ok": False,
            "error": "mark_missing_forbidden_macro_contract",
            "task_id": task_id,
            "message": "macro_contract_resolvable tasks cannot be mark_missing; use materializer",
        }
    # Detect score-only rationales in evidence strings.
    evidence = patch.get("evidence") or []
    evidence_text = " ".join(str(x) for x in evidence).casefold()
    neg = patch.get("negative_evidence")
    if not isinstance(neg, dict) or not neg:
        if any(m.casefold() in evidence_text for m in _SCORE_ONLY_MARKERS) or not evidence_text.strip():
            return {
                "ok": False,
                "error": "mark_missing_score_only_forbidden",
                "task_id": task_id,
                "message": "mark_missing requires machine-verifiable negative_evidence; score/confidence alone is forbidden",
            }
        return {
            "ok": False,
            "error": "mark_missing_negative_evidence_required",
            "task_id": task_id,
        }

    absence = str(neg.get("absence_kind") or "").strip()
    if absence not in _ABSENCE_KINDS:
        return {
            "ok": False,
            "error": "mark_missing_absence_kind_invalid",
            "task_id": task_id,
            "allowed": sorted(_ABSENCE_KINDS),
        }
    queries = neg.get("queries") or []
    if not isinstance(queries, list) or not queries:
        return {
            "ok": False,
            "error": "mark_missing_queries_required",
            "task_id": task_id,
        }
    windows = neg.get("inspected_windows") or []
    if not isinstance(windows, list):
        return {
            "ok": False,
            "error": "mark_missing_inspected_windows_invalid",
            "task_id": task_id,
        }
    for w in windows:
        if not isinstance(w, dict):
            return {
                "ok": False,
                "error": "mark_missing_inspected_windows_invalid",
                "task_id": task_id,
            }
        if not (w.get("file") or w.get("file_path")):
            return {
                "ok": False,
                "error": "mark_missing_window_file_missing",
                "task_id": task_id,
            }
        if not (w.get("window_sha256") or w.get("sha256")):
            return {
                "ok": False,
                "error": "mark_missing_window_sha_missing",
                "task_id": task_id,
            }

    # Do not trust model-claimed include_scope_complete; require artifact status when claimed complete.
    claimed = str(neg.get("include_closure_status") or "").casefold()
    if claimed in {"complete", "closed", "ok"} and uo_root is not None:
        artifact = str(neg.get("include_closure_artifact") or "ir/include_closure.yaml")
        path = uo_root / artifact if not artifact.startswith("uo/") else uo_root.parent.parent / artifact
        # Prefer relative to uo_root/ir
        candidates = [
            uo_root / artifact,
            uo_root / "ir" / Path(artifact).name,
            uo_root / artifact.removeprefix("uo/"),
        ]
        data = None
        for p in candidates:
            if p.is_file():
                data = read_yaml(p) or {}
                break
        if data is None:
            return {
                "ok": False,
                "error": "mark_missing_include_closure_unverified",
                "task_id": task_id,
                "message": "include_closure_status=complete but closure artifact missing/unreadable",
            }
        status = str(
            data.get("include_closure_status") or data.get("status") or data.get("closure_status") or ""
        ).casefold()
        if status not in {"complete", "closed", "ok"}:
            return {
                "ok": False,
                "error": "mark_missing_include_closure_unverified",
                "task_id": task_id,
            }
    return None


def validate_patches_batch(
    uo_root: Path,
    patches: list[dict[str, Any]],
    *,
    current_source_hash: str | None = None,
    current_run_id: str,
) -> dict[str, Any]:
    """Validate an entire batch with zero side effects."""
    return validate_semantic_patch_set(
        uo_root,
        patches,
        current_source_hash,
        current_run_id=current_run_id,
        require_full_coverage=False,
        mutate=False,
    )


def validate_semantic_patch_set(
    uo_root: Path,
    patches: list[dict[str, Any]],
    current_source_hash: str | None,
    *,
    current_run_id: str,
    require_full_coverage: bool = True,
    mutate: bool = False,
) -> dict[str, Any]:
    """Single SSOT entry for Gate (validate-only) and Apply (validate then commit).

    ``mutate`` must always be False here; commit happens only via ``commit_patches_batch``.
    """
    if mutate:
        return {
            "ok": False,
            "error": "mutate_not_allowed",
            "message": "validate_semantic_patch_set is validate-only; use apply_patches_batch to commit",
        }
    req = _require_current_run_id(current_run_id)
    if req is not None:
        return req

    doc = load_llm_tasks(uo_root)
    doc_check = assert_llm_tasks_document_run(doc, current_run_id)
    if not doc_check.get("ok") and not doc_check.get("empty"):
        return {**doc_check, "errors": [doc_check], "doc": doc}

    # Producer document-level identity (if present) must match current run.
    if isinstance(patches, list) and patches:
        # When caller passes full patches_doc via wrapper, identity is checked separately.
        pass

    if not patches:
        if require_full_coverage:
            needs = [
                str(t.get("task_id") or "")
                for t in open_blocking_tasks(uo_root, current_run_id=current_run_id)
                if not can_auto_mark_missing(t)
            ]
            needs = [t for t in needs if t]
            if needs:
                return {
                    "ok": False,
                    "error": "semantic_patches_required",
                    "missing_task_ids": needs,
                    "errors": [{"ok": False, "error": "semantic_patches_required", "missing_task_ids": needs}],
                    "doc": doc,
                }
        return {
            "ok": True,
            "validated": [],
            "doc": doc,
            "next_batches": int(doc.get("total_semantic_batches") or 0),
        }

    batches = int(doc.get("total_semantic_batches") or 0)
    next_batches = batches + 1
    if next_batches > MAX_SEMANTIC_BATCHES:
        return {
            "ok": False,
            "error": "total_semantic_batches_exhausted",
            "batches": next_batches,
            "errors": [{"ok": False, "error": "total_semantic_batches_exhausted", "batches": next_batches}],
            "doc": doc,
        }

    validated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_tasks: set[str] = set()
    for patch in patches:
        if not isinstance(patch, dict):
            errors.append({"ok": False, "error": "invalid_patch_entry"})
            continue
        tid = str(patch.get("task_id") or "")
        if tid and tid in seen_tasks:
            errors.append({"ok": False, "error": "duplicate_task_in_batch", "task_id": tid})
            continue
        if tid:
            seen_tasks.add(tid)
        result = validate_task_patch(
            doc,
            normalize_patch_candidate_set_hash(patch),
            current_source_hash=current_source_hash,
            current_run_id=current_run_id,
            uo_root=uo_root,
        )
        if result.get("ok"):
            # Fail closed on typed patch incomplete payloads (no silent downgrade).
            from uo.scripts.semantic_patches import validate_typed_patch

            action = str(result.get("action") or patch.get("action") or "")
            patch_type = _effective_patch_type(result["task"], patch, action)
            if action != "mark_missing" and patch_type not in {"", "edge_resolution", "mark_missing"}:
                typed = validate_typed_patch(patch, patch_type=patch_type)
                if not typed.get("ok"):
                    errors.append(
                        {
                            "ok": False,
                            "error": typed.get("error") or "TYPED_PATCH_PAYLOAD_INCOMPLETE",
                            "task_id": tid,
                            "patch_type": patch_type,
                            "detail": typed.get("detail"),
                        }
                    )
                    continue
            result["patch_type"] = patch_type
            validated.append(result)
        else:
            errors.append(result)

    if require_full_coverage:
        needs = {
            str(t.get("task_id") or "")
            for t in open_blocking_tasks(uo_root, current_run_id=current_run_id)
            if not can_auto_mark_missing(t) and str(t.get("task_id") or "").strip()
        }
        covered = {str(p.get("task_id") or "") for p in patches if isinstance(p, dict)}
        missing = sorted(needs - covered)
        if missing:
            errors.append(
                {
                    "ok": False,
                    "error": "incomplete_task_coverage",
                    "missing_task_ids": missing,
                }
            )

    if errors:
        return {
            "ok": False,
            "errors": errors,
            "validated": validated,
            "doc": doc,
            "missing_task_ids": next(
                (e.get("missing_task_ids") for e in errors if e.get("missing_task_ids")),
                [],
            ),
            "error": str(errors[0].get("error") or "validation_failed"),
        }
    return {
        "ok": True,
        "validated": validated,
        "doc": doc,
        "next_batches": next_batches,
    }


def commit_patches_batch(
    uo_root: Path,
    validated: list[dict[str, Any]],
    *,
    next_batches: int,
    current_run_id: str,
    workflow_id: str = "uo-init",
    phase: str = "",
    control_action_id: str = "adjudicate_llm_tasks",
    actor_id: str = "uo-semantic-resolve",
    role_id: str = "producer",
    action_session_id: str = "",
    lease_id: str = "",
) -> dict[str, Any]:
    """Atomically commit a pre-validated batch (one batch increment, one ledger save)."""
    from datetime import datetime, timezone

    from uo.scripts._ir_io import commit_semantic_artifacts
    from uo.scripts.semantic_patches import extract_typed_payload, validate_typed_patch
    from uo.scripts.semantic_resolution_ledger import load_ledger

    req = _require_current_run_id(current_run_id)
    if req is not None:
        return {**req, "applied_count": 0, "error_count": 1, "applied": [], "errors": [req]}

    doc = load_llm_tasks(uo_root)
    doc_check = assert_llm_tasks_document_run(doc, current_run_id, workflow_id=workflow_id)
    if not doc_check.get("ok") and not doc_check.get("empty"):
        return {
            **doc_check,
            "applied_count": 0,
            "error_count": 1,
            "applied": [],
            "errors": [doc_check],
        }
    doc = stamp_llm_tasks_identity(doc, run_id=current_run_id, workflow_id=workflow_id or "uo-init")
    by_id = {str(t.get("task_id")): t for t in (doc.get("tasks") or []) if isinstance(t, dict)}
    ledger = load_ledger(uo_root)
    ledger.setdefault("artifact_identity", {})
    if isinstance(ledger.get("artifact_identity"), dict):
        ledger["artifact_identity"] = {
            **dict(ledger.get("artifact_identity") or {}),
            "run_id": current_run_id,
            "workflow_id": workflow_id or "uo-init",
        }
    applied: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for item in validated:
        tid = str(item["task_id"])
        task = by_id.get(tid)
        if task is None or str(task.get("task_status") or task.get("status")) not in {
            "open",
            "rework_required",
        }:
            return {
                "ok": False,
                "error": "commit_race_task_not_open",
                "task_id": tid,
                "applied_count": 0,
                "error_count": 1,
                "applied": [],
                "errors": [{"ok": False, "error": "commit_race_task_not_open", "task_id": tid}],
            }
        task_err = _assert_task_run(task, current_run_id)
        if task_err is not None:
            return {
                **task_err,
                "applied_count": 0,
                "error_count": 1,
                "applied": [],
                "errors": [task_err],
            }
        task["task_attempts"] = int(item["next_attempts"])
        action = str(item["action"])
        patch = item["patch"]
        patch_type = str(item.get("patch_type") or _effective_patch_type(task, patch, action))
        typed = validate_typed_patch(patch, patch_type=patch_type)
        if not typed.get("ok") and action != "mark_missing" and patch_type not in {"edge_resolution", "mark_missing", ""}:
            return {
                "ok": False,
                "error": typed.get("error") or "TYPED_PATCH_PAYLOAD_INCOMPLETE",
                "task_id": tid,
                "applied_count": 0,
                "error_count": 1,
                "applied": [],
                "errors": [{"ok": False, "error": typed.get("error"), "task_id": tid, "detail": typed.get("detail")}],
            }
        typed_payload = typed.get("payload") if isinstance(typed.get("payload"), dict) else extract_typed_payload(patch, patch_type)
        accepted = list(item["accepted"])
        edge_id = _resolve_patch_edge_id(task, patch, accepted=accepted)
        if edge_id and _is_candidate_node_id(edge_id):
            return {
                "ok": False,
                "error": "LEDGER_TARGET_TYPE_MISMATCH",
                "task_id": tid,
                "applied_count": 0,
                "error_count": 1,
                "applied": [],
                "errors": [{"ok": False, "error": "LEDGER_TARGET_TYPE_MISMATCH", "task_id": tid}],
            }
        if action == "mark_missing":
            task["status"] = "adjudicated"
            task["task_status"] = "adjudicated"
            task["semantic_status"] = "unresolved"
            task["blocking"] = True
        elif action == "candidate_enrichment":
            nested = patch.get("payload") if isinstance(patch.get("payload"), dict) else {}
            new_cands = [
                c
                for c in (patch.get("candidates") or nested.get("candidates") or [])
                if isinstance(c, dict)
            ]
            existing = [c for c in (task.get("candidates") or []) if isinstance(c, dict)]
            by_id = {str(c.get("id") or ""): c for c in existing if str(c.get("id") or "").strip()}
            for c in new_cands:
                cid = str(c.get("id") or "").strip()
                if cid:
                    by_id[cid] = c
                else:
                    existing.append(c)
            merged = list(by_id.values()) if by_id else existing + new_cands
            if not merged:
                return {
                    "ok": False,
                    "error": "candidate_enrichment_empty",
                    "task_id": tid,
                    "applied_count": 0,
                    "error_count": 1,
                    "applied": [],
                    "errors": [{"ok": False, "error": "candidate_enrichment_empty", "task_id": tid}],
                }
            task["candidates"] = merged
            task["candidate_set_hash"] = candidate_set_hash(merged)
            task["status"] = "open"
            task["task_status"] = "open"
            task["semantic_status"] = "unresolved"
            task["blocking"] = True
            task["allowed_actions"] = sorted(
                set(list(task.get("allowed_actions") or []) + ["accept_edge", "choose_one", "mark_missing", "candidate_enrichment"])
            )
            # Category/route/eligibility owned by triage SSOT — never hand-write.
            from uo.scripts.semantic_task_triage import apply_triage_to_tasks

            apply_triage_to_tasks([task], uo_root=uo_root)
        elif action == "scope_expansion_request":
            nested = patch.get("payload") if isinstance(patch.get("payload"), dict) else {}
            proposed = list(patch.get("proposed_files") or nested.get("proposed_files") or [])
            req_doc = read_yaml(uo_root / "ir" / "scope_expansion_requests.yaml") or {
                "version": 1,
                "requests": [],
            }
            req_doc.setdefault("requests", []).append(
                {
                    "task_id": tid,
                    "run_id": current_run_id,
                    "missing_symbol": patch.get("missing_symbol") or nested.get("missing_symbol") or task.get("target"),
                    "proposed_files": proposed,
                    "evidence": patch.get("evidence") or nested.get("evidence") or [],
                    "evidence_windows": (
                        patch.get("evidence_windows")
                        or nested.get("evidence_windows")
                        or []
                    ),
                    "symbol_evidence": (
                        patch.get("symbol_evidence")
                        or nested.get("symbol_evidence")
                        or []
                    ),
                }
            )
            write_yaml(uo_root / "ir" / "scope_expansion_requests.yaml", req_doc)
            task["status"] = "adjudicated"
            task["task_status"] = "adjudicated"
            task["semantic_status"] = "unresolved"
            task["blocking"] = True
            task["pending_scope_expansion"] = True
        elif action in _ACCEPT_CLOSE_ACTIONS:
            task["status"] = "pending_materialization"
            task["task_status"] = "pending_materialization"
            task["semantic_status"] = "pending_materialization"
            task["blocking"] = True
        else:
            task["status"] = "pending_materialization"
            task["task_status"] = "pending_materialization"
            task["semantic_status"] = "pending_materialization"
            task["blocking"] = True
        task["resolution"] = {"action": action, "patch": patch}
        apply_status = "pending"
        if action == "candidate_enrichment":
            apply_status = "materialized"
        elif action == "scope_expansion_request":
            apply_status = "adjudicated_only"
        elif action == "mark_missing":
            apply_status = "adjudicated_only"
        record = {
            "task_id": tid,
            "run_id": current_run_id,
            "workflow_id": workflow_id or "uo-init",
            "phase": phase or "",
            "control_action_id": control_action_id or "adjudicate_llm_tasks",
            "actor_id": actor_id or "uo-semantic-resolve",
            "role_id": role_id or "producer",
            "action_session_id": action_session_id or "",
            "lease_id": lease_id or "",
            "patch_type": patch_type,
            "semantic_action": action,
            # Legacy mirror — production code must prefer semantic_action.
            "action": action,
            "edge_id": edge_id,
            "accepted_candidate_ids": accepted,
            "rejected_candidate_ids": list(item["rejected"]),
            "relation": patch.get("relation") or typed_payload.get("relation") or task.get("type"),
            "evidence": patch.get("evidence") or [],
            "source_snapshot_hash": task.get("source_snapshot_hash"),
            "candidate_set_hash": task.get("candidate_set_hash"),
            "verification_source": "llm",
            "confidence": "semantic_verified",
            "applied_at": now,
            "status": "active",
            "apply_status": apply_status,
            "payload": typed_payload,
        }
        for key, value in typed_payload.items():
            if key not in record or record[key] in (None, "", []):
                record[key] = value
        ledger.setdefault("semantic_patches", []).append(record)
        applied.append(
            {
                "ok": True,
                "task_id": tid,
                "task_attempts": task["task_attempts"],
                "total_semantic_batches": next_batches,
                "ledger_entry": record,
            }
        )

    doc["total_semantic_batches"] = next_batches
    commit_semantic_artifacts(uo_root, llm_tasks=doc, ledger=ledger)
    return {
        "ok": True,
        "applied_count": len(applied),
        "error_count": 0,
        "applied": applied,
        "errors": [],
        "total_semantic_batches": next_batches,
    }


def apply_task_patch(
    uo_root: Path,
    patch: dict[str, Any],
    *,
    current_run_id: str,
    current_source_hash: str | None = None,
    workflow_id: str = "uo-init",
    phase: str = "",
    control_action_id: str = "adjudicate_llm_tasks",
    actor_id: str = "uo-semantic-resolve",
    role_id: str = "producer",
    action_session_id: str = "",
    lease_id: str = "",
) -> dict[str, Any]:
    """Validate then commit a single patch as a one-patch transactional batch."""
    req = _require_current_run_id(current_run_id)
    if req is not None:
        return req
    enriched = normalize_patch_candidate_set_hash(patch)
    if not str(enriched.get("run_id") or "").strip():
        enriched["run_id"] = current_run_id
    doc = load_llm_tasks(uo_root)
    tid = str(enriched.get("task_id") or "")
    task = next((t for t in doc.get("tasks") or [] if t.get("task_id") == tid), None)
    if isinstance(task, dict):
        if not str(enriched.get("candidate_set_hash") or "").strip():
            enriched["candidate_set_hash"] = str(task.get("candidate_set_hash") or "")
        if not str(enriched.get("source_snapshot_hash") or "").strip():
            enriched["source_snapshot_hash"] = str(task.get("source_snapshot_hash") or "")
    batch = apply_patches_batch(
        uo_root,
        [enriched],
        current_run_id=current_run_id,
        current_source_hash=current_source_hash,
        workflow_id=workflow_id,
        phase=phase,
        control_action_id=control_action_id,
        actor_id=actor_id,
        role_id=role_id,
        action_session_id=action_session_id,
        lease_id=lease_id,
    )
    if batch.get("ok") and batch.get("applied"):
        return batch["applied"][0]
    if batch.get("errors"):
        return batch["errors"][0]
    return {"ok": False, "error": batch.get("error") or "apply_failed"}


def apply_patches_batch(
    uo_root: Path,
    patches: list[dict[str, Any]],
    *,
    current_run_id: str,
    current_source_hash: str | None = None,
    workflow_id: str = "uo-init",
    phase: str = "",
    control_action_id: str = "adjudicate_llm_tasks",
    actor_id: str = "uo-semantic-resolve",
    role_id: str = "producer",
    action_session_id: str = "",
    lease_id: str = "",
) -> dict[str, Any]:
    """Validate-all-then-commit: any failure leaves llm_tasks and ledger unchanged."""
    req = _require_current_run_id(current_run_id)
    if req is not None:
        return {**req, "applied_count": 0, "error_count": 1, "applied": [], "errors": [req]}
    if not patches:
        return {"ok": True, "applied_count": 0, "error_count": 0, "applied": [], "errors": []}
    stamped = []
    for p in patches:
        if not isinstance(p, dict):
            continue
        ep = dict(p)
        if not str(ep.get("run_id") or "").strip():
            ep["run_id"] = current_run_id
        stamped.append(ep)
    checked = validate_semantic_patch_set(
        uo_root,
        stamped,
        current_source_hash,
        current_run_id=current_run_id,
        require_full_coverage=False,
        mutate=False,
    )
    if not checked.get("ok"):
        return {
            "ok": False,
            "applied_count": 0,
            "error_count": len(checked.get("errors") or []),
            "applied": [],
            "errors": list(checked.get("errors") or []),
            "error": checked.get("error"),
        }
    return commit_patches_batch(
        uo_root,
        list(checked.get("validated") or []),
        next_batches=int(checked["next_batches"]),
        current_run_id=current_run_id,
        workflow_id=workflow_id,
        phase=phase,
        control_action_id=control_action_id,
        actor_id=actor_id,
        role_id=role_id,
        action_session_id=action_session_id,
        lease_id=lease_id,
    )


def assert_semantic_patches_document_run(
    doc: dict[str, Any],
    current_run_id: str,
    *,
    workflow_id: str = "",
) -> dict[str, Any]:
    """Fail-closed document identity for semantic_patches.yaml when present."""
    if not isinstance(doc, dict):
        return {"ok": True, "empty": True}
    identity = doc.get("artifact_identity") if isinstance(doc.get("artifact_identity"), dict) else {}
    doc_run = str(identity.get("run_id") or doc.get("run_id") or "").strip()
    patches = [p for p in (doc.get("patches") or []) if isinstance(p, dict)]
    if not doc_run and not patches:
        return {"ok": True, "empty": True}
    if not doc_run:
        return {"ok": False, "error": "SEMANTIC_DOCUMENT_RUN_ID_MISSING"}
    if doc_run != str(current_run_id):
        return {
            "ok": False,
            "error": "SEMANTIC_DOCUMENT_RUN_MISMATCH",
            "document_run_id": doc_run,
            "current_run_id": current_run_id,
        }
    if workflow_id:
        doc_wf = str(identity.get("workflow_id") or doc.get("workflow_id") or "").strip()
        if doc_wf and doc_wf != workflow_id:
            return {
                "ok": False,
                "error": "SEMANTIC_DOCUMENT_RUN_MISMATCH",
                "field": "workflow_id",
                "document_workflow_id": doc_wf,
                "current_workflow_id": workflow_id,
            }
    return {"ok": True}


def resolve_patches_for_apply(
    uo_root: Path,
    *,
    current_run_id: str,
    patches_doc: dict[str, Any] | None = None,
    workflow_id: str = "uo-init",
) -> dict[str, Any]:
    """Resolve patch list for deterministic apply.

    Prefers ``ir/semantic_patches.yaml``. Merges auto ``mark_missing`` for uncovered
    empty-candidate tasks. Tasks that still need LLM adjudication surface as
    ``SEMANTIC_PATCHES_REQUIRED``.
    """
    req = _require_current_run_id(current_run_id)
    if req is not None:
        return req
    open_blocking = open_blocking_tasks(uo_root, current_run_id=current_run_id)
    if not open_blocking:
        return {"ok": True, "patches": [], "skipped": True, "reason": "no_open_blocking"}

    patches: list[dict[str, Any]] = []
    if isinstance(patches_doc, dict):
        doc_check = assert_semantic_patches_document_run(
            patches_doc, current_run_id, workflow_id=workflow_id
        )
        if not doc_check.get("ok") and not doc_check.get("empty"):
            return doc_check
        raw = patches_doc.get("patches")
        if isinstance(raw, list):
            for p in raw:
                if not isinstance(p, dict):
                    continue
                ep = dict(p)
                if not str(ep.get("run_id") or "").strip():
                    # Producer omitted per-patch run_id — inherit document identity only
                    # when document run already validated; still fail if neither present.
                    ident = (
                        patches_doc.get("artifact_identity")
                        if isinstance(patches_doc.get("artifact_identity"), dict)
                        else {}
                    )
                    inherited = str(ident.get("run_id") or patches_doc.get("run_id") or "").strip()
                    if inherited:
                        ep["run_id"] = inherited
                patches.append(ep)

    covered = {str(p.get("task_id") or "") for p in patches}
    auto: list[dict[str, Any]] = []
    needs_llm: list[str] = []
    invalid_auto: list[dict[str, Any]] = []
    tasks_doc = load_llm_tasks(uo_root)
    for task in open_blocking:
        tid = str(task.get("task_id") or "")
        if tid in covered:
            continue
        if can_auto_mark_missing(task):
            candidate = {
                "task_id": tid,
                "run_id": current_run_id,
                "action": "mark_missing",
                "accepted_candidate_ids": [],
                "rejected_candidate_ids": [],
                "evidence": ["auto:validated_negative_evidence"],
                "negative_evidence": dict(task.get("negative_evidence") or {}),
                "source_snapshot_hash": str(task.get("source_snapshot_hash") or ""),
                "candidate_set_hash": str(task.get("candidate_set_hash") or ""),
            }
            # Auto patches must pass the same Gate as producer patches.
            validated = validate_task_patch(
                tasks_doc,
                candidate,
                current_source_hash=str(task.get("source_snapshot_hash") or "") or None,
                current_run_id=current_run_id,
                uo_root=uo_root,
            )
            if not validated.get("ok"):
                invalid_auto.append(
                    {
                        "task_id": tid,
                        "error": "AUTO_PATCH_CONTRACT_INVALID",
                        "detail": validated,
                    }
                )
                needs_llm.append(tid)
                continue
            auto.append(candidate)
        else:
            needs_llm.append(tid)

    if invalid_auto and not auto and not patches:
        return {
            "ok": False,
            "error": "AUTO_PATCH_CONTRACT_INVALID",
            "invalid_auto": invalid_auto,
            "needs_llm_task_ids": needs_llm,
        }

    if needs_llm:
        return {
            "ok": False,
            "error": "SEMANTIC_PATCHES_REQUIRED",
            "message": (
                "open blocking llm_tasks need producer adjudication; "
                "run `acp run-action adjudicate_llm_tasks` then re-run apply_semantic_patch"
            ),
            "needs_llm_task_ids": needs_llm,
            "auto_mark_missing_count": len(auto),
            "invalid_auto": invalid_auto,
        }

    merged = list(patches) + auto
    source = "semantic_patches.yaml" if patches else "auto_mark_missing"
    if patches and auto:
        source = "semantic_patches.yaml+auto_mark_missing"
    return {"ok": True, "patches": merged, "source": source}


def recheck_does_not_increment(uo_root: Path, *, current_run_id: str) -> dict[str, Any]:
    """Recheck helper — read budgets without mutating attempts."""
    req = _require_current_run_id(current_run_id)
    if req is not None:
        return req
    doc = load_llm_tasks(uo_root)
    gaps = blocking_gap_tasks(uo_root, current_run_id=current_run_id)
    return {
        "ok": True,
        "open_blocking": open_blocking_tasks(uo_root, current_run_id=current_run_id),
        "blocking_gaps": gaps,
        "blocking_gap_count": len(gaps),
        "total_semantic_batches": int(doc.get("total_semantic_batches") or 0),
        "tasks": _tasks_for_run(doc, current_run_id),
        **compute_semantic_stats(uo_root, current_run_id=current_run_id),
    }


def compute_semantic_stats(uo_root: Path, *, current_run_id: str) -> dict[str, Any]:
    """Aggregate semantic task / patch / ledger counters for the current run only."""
    from uo.scripts.semantic_resolution_ledger import load_ledger

    req = _require_current_run_id(current_run_id)
    if req is not None:
        return {**req, "task_total": 0, "blocking_gap_count": 0}

    tasks_doc = load_llm_tasks(uo_root)
    doc_check = assert_llm_tasks_document_run(tasks_doc, current_run_id)
    if not doc_check.get("ok") and not doc_check.get("empty"):
        return {
            **doc_check,
            "task_total": 0,
            "blocking_gap_count": 0,
            "producer_patch_count": 0,
            "auto_patch_count": 0,
            "accept_count": 0,
            "reject_count": 0,
            "mark_missing_count": 0,
            "materialized_patch_count": 0,
            "unconsumed_patch_count": 0,
            "total_semantic_batches": 0,
        }
    tasks = _tasks_for_run(tasks_doc, current_run_id)
    patches_doc = read_yaml(uo_root / "ir" / "semantic_patches.yaml") or {}
    patch_doc_check = assert_semantic_patches_document_run(patches_doc, current_run_id)
    if not patch_doc_check.get("ok") and not patch_doc_check.get("empty"):
        producer_patches: list[dict[str, Any]] = []
    else:
        producer_patches = []
        for p in patches_doc.get("patches") or []:
            if not isinstance(p, dict):
                continue
            if _assert_patch_run(p, current_run_id) is None:
                producer_patches.append(p)
            else:
                # Inherit document run when per-patch missing but doc validated.
                ident = (
                    patches_doc.get("artifact_identity")
                    if isinstance(patches_doc.get("artifact_identity"), dict)
                    else {}
                )
                inherited = str(ident.get("run_id") or patches_doc.get("run_id") or "").strip()
                if inherited == str(current_run_id) and not str(p.get("run_id") or "").strip():
                    producer_patches.append(p)
    ledger = load_ledger(uo_root)
    ledger_patches = []
    for p in ledger.get("semantic_patches") or []:
        if not isinstance(p, dict):
            continue
        if str(p.get("run_id") or "").strip() == str(current_run_id):
            ledger_patches.append(p)

    accept_count = 0
    reject_count = 0
    mark_missing_count = 0
    auto_patch_count = 0
    materialized_patch_count = 0
    unconsumed_patch_count = 0
    for p in ledger_patches:
        if p.get("status") == "stale":
            continue
        action = str(p.get("semantic_action") or p.get("action") or "")
        ev = p.get("evidence") or []
        if any(str(x).startswith("auto:") for x in ev):
            auto_patch_count += 1
        if action == "mark_missing":
            mark_missing_count += 1
        elif action in _ACCEPT_CLOSE_ACTIONS:
            accept_count += 1
        elif action == "reject_edge":
            reject_count += 1
        apply_st = str(p.get("apply_status") or "")
        if apply_st == "materialized":
            materialized_patch_count += 1
        elif apply_st == "unconsumed" and p.get("status") == "active":
            unconsumed_patch_count += 1

    return {
        "task_total": len(tasks),
        "producer_patch_count": len(producer_patches),
        "auto_patch_count": auto_patch_count,
        "accept_count": accept_count,
        "reject_count": reject_count,
        "mark_missing_count": mark_missing_count,
        "materialized_patch_count": materialized_patch_count,
        "unconsumed_patch_count": unconsumed_patch_count,
        "blocking_gap_count": len(blocking_gap_tasks(uo_root, current_run_id=current_run_id)),
        "total_semantic_batches": int(tasks_doc.get("total_semantic_batches") or 0),
        "active_run_id": current_run_id,
    }


_FAILURE_APPLY_STATUSES = frozenset(
    {"unconsumed", "invalid", "target_missing", "target_type_mismatch"}
)


def sync_tasks_from_materialization(
    uo_root: Path,
    ledger: dict[str, Any],
    *,
    current_run_id: str,
    mutate_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update llm_tasks from ledger apply_status after rebuild verification.

    - materialized → task_status=resolved, semantic_status=closed, blocking=false
    - unconsumed/invalid/target_* → rework_required + unresolved + blocking
    - mark_missing → remains adjudicated/unresolved/blocking
    """
    req = _require_current_run_id(current_run_id)
    if req is not None:
        return {**req, "doc": mutate_doc or {}, "closed_count": 0, "rework_count": 0}
    doc = mutate_doc if mutate_doc is not None else load_llm_tasks(uo_root)
    by_id = {str(t.get("task_id")): t for t in (doc.get("tasks") or []) if isinstance(t, dict)}
    closed = 0
    reopened = 0
    for patch in ledger.get("semantic_patches") or []:
        if not isinstance(patch, dict) or patch.get("status") == "stale":
            continue
        patch_run = str(patch.get("run_id") or "").strip()
        if not patch_run:
            return {
                "ok": False,
                "error": "LEDGER_RUN_ID_MISSING",
                "task_id": patch.get("task_id"),
                "doc": doc,
                "closed_count": closed,
                "rework_count": reopened,
            }
        if patch_run != str(current_run_id):
            continue
        tid = str(patch.get("task_id") or "")
        task = by_id.get(tid)
        if task is None:
            continue
        task_err = _assert_task_run(task, current_run_id)
        if task_err is not None:
            continue
        action = str(patch.get("semantic_action") or patch.get("action") or "")
        apply_st = str(patch.get("apply_status") or "")
        if action == "mark_missing" or str(patch.get("patch_type") or "") == "mark_missing":
            task["status"] = "adjudicated"
            task["task_status"] = "adjudicated"
            task["semantic_status"] = "unresolved"
            task["blocking"] = True
            continue
        if apply_st == "materialized":
            task["status"] = "resolved"
            task["task_status"] = "resolved"
            task["semantic_status"] = "closed"
            task["blocking"] = False
            task.pop("failure_code", None)
            task.pop("failure_detail", None)
            closed += 1
        elif apply_st in _FAILURE_APPLY_STATUSES:
            task["status"] = "rework_required"
            task["task_status"] = "rework_required"
            task["semantic_status"] = "unresolved"
            task["blocking"] = True
            code = str(patch.get("apply_error") or "")
            if apply_st == "unconsumed":
                code = code or "SEMANTIC_PATCH_UNCONSUMED"
            elif apply_st == "invalid":
                code = code or "SEMANTIC_PATCH_INVALID"
            elif apply_st == "target_missing":
                code = code or "SEMANTIC_TARGET_NOT_FOUND"
            elif apply_st == "target_type_mismatch":
                code = code or "SEMANTIC_TARGET_TYPE_MISMATCH"
            task["failure_code"] = code
            task["failure_detail"] = str(patch.get("apply_detail") or apply_st)
            reopened += 1
        elif apply_st in {"pending", "adjudicated_only"}:
            # Still waiting or mark_missing-equivalent.
            if _task_lifecycle(task) == "pending_materialization":
                pass
    return {
        "ok": True,
        "doc": doc,
        "closed_count": closed,
        "rework_count": reopened,
    }
