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
    lifecycle = _task_lifecycle(task)
    if lifecycle in {"resolved"} and _semantic_status(task) == "closed":
        return False
    # pending_materialization / rework_required / adjudicated / open all count as gaps
    if lifecycle in _LIFECYCLE_GAP or _semantic_status(task) in _SEMANTIC_OPEN:
        return True
    return _semantic_status(task) != "closed"


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
    ttype = str(task.get("type") or "")
    obj = str(task.get("object_type") or "")
    if obj == "tilingdata_bridge" or ttype == "tilingdata_bridge":
        return "tilingdata_bridge_resolution"
    if obj == "entrypoint_node":
        return "entrypoint_node_resolution"
    if obj == "call_edge":
        # Legacy choose_edge patches without typed payload stay edge_resolution.
        return "call_edge_resolution"
    if obj in {"entrypoint_dispatch_bind"} or obj in {"registration_edge"}:
        return "entrypoint_dispatch_resolution"
    if ttype == "choose_edge":
        return "edge_resolution"
    return "edge_resolution"


def _effective_patch_type(task: dict[str, Any], patch: dict[str, Any], action: str) -> str:
    """Prefer explicit patch_type; downgrade typed types to edge_resolution when payload incomplete."""
    explicit = str(patch.get("patch_type") or "").strip()
    inferred = explicit or _infer_patch_type(task, action)
    if inferred == "call_edge_resolution":
        if not (patch.get("caller_function_id") and patch.get("callee_function_id")):
            return "edge_resolution"
    if inferred == "entrypoint_dispatch_resolution":
        if not (patch.get("source_node_id") and patch.get("target_node_id")):
            return "edge_resolution"
    if inferred == "tilingdata_bridge_resolution":
        if not (patch.get("host_field_id") and patch.get("kernel_field_id")):
            return "edge_resolution"
    if inferred == "template_instance_resolution":
        if not (
            patch.get("tilingkey_value_id")
            and patch.get("template_instance_id")
            and patch.get("kernel_entry_id")
        ):
            return "edge_resolution"
    if inferred == "entrypoint_node_resolution":
        if not (patch.get("node_id") or patch.get("candidate_id")):
            # May still resolve via accepted candidate ids as node ids.
            return inferred
    return inferred


def _resolve_patch_edge_id(task: dict[str, Any], patch: dict[str, Any], *, accepted: list[str]) -> str | None:
    raw = patch.get("edge_id") or task.get("target")
    if _is_real_edge_id(raw):
        return str(raw)
    for cid in accepted:
        if _is_real_edge_id(cid):
            return str(cid)
    return None


def blocking_gap_tasks(uo_root: Path) -> list[dict[str, Any]]:
    """Blocking semantic gaps — shared SSOT for Gate / Engine / recheck."""
    doc = load_llm_tasks(uo_root)
    return [t for t in doc.get("tasks") or [] if isinstance(t, dict) and _semantic_gap_open(t)]


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
        object_type = str(item.get("object_type") or "")
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

        target = str(item.get("target_id") or item.get("role") or item.get("edge_type") or "unknown")
        candidates = item.get("candidates") or _default_candidates(item)
        if not candidates and (hint == "choose_edge" or object_type == "tilingdata_bridge" or task_type == "tilingdata_bridge"):
            if object_type == "tilingdata_bridge" and not _bridge_identity_complete(item):
                task_type = "evidence_enrichment"
                hint = "evidence_enrichment"
            elif object_type in {"call_edge", "registration_edge", "entrypoint_node"} or task_type == "entrypoint_dispatch_bind":
                task_type = "candidate_generation"
                hint = "candidate_generation"
            else:
                task_type = "evidence_enrichment"
                hint = "evidence_enrichment"
        elif not candidates and hint == "choose_edge":
            task_type = "candidate_generation"
            hint = "candidate_generation"
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
        if existing and existing.get("status") in {"resolved", "rejected", "adjudicated"}:
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
        task = {
            "task_id": tid,
            "status": "open",
            "task_status": "open",
            "run_id": run_id,
            "checkpoint": checkpoint,
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
        by_id[tid] = task
        created += 1

    doc["tasks"] = list(by_id.values())
    save_llm_tasks(uo_root, doc)
    return {
        "task_count": len(doc["tasks"]),
        "open_blocking": sum(
            1
            for t in doc["tasks"]
            if t.get("status") == "open" and _task_is_blocking(t) and _semantic_status(t) != "closed"
        ),
        "blocking_gap_count": sum(
            1 for t in doc["tasks"] if _task_is_blocking(t) and _semantic_status(t) != "closed"
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
    """Tasks that still need patch adjudication (open or rework_required)."""
    doc = load_llm_tasks(uo_root)
    out: list[dict[str, Any]] = []
    for t in doc.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        lifecycle = _task_lifecycle(t)
        if lifecycle not in {"open", "rework_required"}:
            continue
        if not _task_is_blocking(t):
            continue
        if _semantic_status(t) == "closed":
            continue
        out.append(t)
    return out


def can_auto_mark_missing(task: dict[str, Any]) -> bool:
    """Shared auto mark_missing predicate (Gate / pipeline / apply)."""
    ttype = str(task.get("type") or "")
    cands = list(task.get("candidates") or [])
    if ttype in {"evidence_enrichment", "candidate_generation"}:
        return False
    if ttype == "mark_missing" and not cands:
        return True
    return False


# Back-compat alias
_can_auto_mark_missing = can_auto_mark_missing


def validate_task_patch(
    doc: dict[str, Any],
    patch: dict[str, Any],
    *,
    current_source_hash: str | None = None,
) -> dict[str, Any]:
    """Pure validation for one patch against an in-memory llm_tasks doc. No I/O."""
    task_id = str(patch.get("task_id") or "")
    task = next((t for t in doc.get("tasks") or [] if t.get("task_id") == task_id), None)
    if task is None:
        return {"ok": False, "error": "unknown_task_id", "task_id": task_id}
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
        return {"ok": False, "error": "patch_candidate_set_hash_missing", "task_id": task_id}
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
    allowed = {str(a) for a in (task.get("allowed_actions") or [])}
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
    if action in accept_actions:
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


def validate_patches_batch(
    uo_root: Path,
    patches: list[dict[str, Any]],
    *,
    current_source_hash: str | None = None,
) -> dict[str, Any]:
    """Validate an entire batch with zero side effects."""
    return validate_semantic_patch_set(
        uo_root,
        patches,
        current_source_hash,
        require_full_coverage=False,
        mutate=False,
    )


def validate_semantic_patch_set(
    uo_root: Path,
    patches: list[dict[str, Any]],
    current_source_hash: str | None,
    *,
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

    doc = load_llm_tasks(uo_root)
    if not patches:
        if require_full_coverage:
            needs = [
                str(t.get("task_id") or "")
                for t in open_blocking_tasks(uo_root)
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
        result = validate_task_patch(doc, patch, current_source_hash=current_source_hash)
        if result.get("ok"):
            validated.append(result)
        else:
            errors.append(result)

    if require_full_coverage:
        needs = {
            str(t.get("task_id") or "")
            for t in open_blocking_tasks(uo_root)
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
) -> dict[str, Any]:
    """Atomically commit a pre-validated batch (one batch increment, one ledger save)."""
    from datetime import datetime, timezone

    from uo.scripts._ir_io import commit_semantic_artifacts
    from uo.scripts.semantic_patches import extract_typed_payload, validate_typed_patch
    from uo.scripts.semantic_resolution_ledger import load_ledger

    doc = load_llm_tasks(uo_root)
    by_id = {str(t.get("task_id")): t for t in (doc.get("tasks") or []) if isinstance(t, dict)}
    ledger = load_ledger(uo_root)
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
        task["task_attempts"] = int(item["next_attempts"])
        action = str(item["action"])
        patch = item["patch"]
        patch_type = _effective_patch_type(task, patch, action)
        typed = validate_typed_patch(patch, patch_type=patch_type)
        if not typed.get("ok") and action != "mark_missing":
            return {
                "ok": False,
                "error": typed.get("error") or "SEMANTIC_PATCH_INVALID",
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
        elif action in _ACCEPT_CLOSE_ACTIONS:
            # Do NOT close until rebuild confirms materialization.
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
        record = {
            "task_id": tid,
            "patch_type": patch_type,
            "edge_id": edge_id,
            "accepted_candidate_ids": accepted,
            "rejected_candidate_ids": list(item["rejected"]),
            "relation": patch.get("relation") or typed_payload.get("relation") or task.get("type"),
            "evidence": patch.get("evidence") or [],
            "source_snapshot_hash": task.get("source_snapshot_hash"),
            "candidate_set_hash": task.get("candidate_set_hash"),
            "verification_source": "llm",
            "confidence": "semantic_verified",
            "action": action,
            "applied_at": now,
            "status": "active",
            "apply_status": "pending",
            "payload": typed_payload,
        }
        # Flatten typed payload onto record so rebuild never drops fields.
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
    # Transactional: llm_tasks + ledger together (no apply_report yet — that comes from rebuild).
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
    current_source_hash: str | None = None,
) -> dict[str, Any]:
    """Validate then commit a single patch as a one-patch transactional batch."""
    enriched = dict(patch)
    doc = load_llm_tasks(uo_root)
    tid = str(enriched.get("task_id") or "")
    task = next((t for t in doc.get("tasks") or [] if t.get("task_id") == tid), None)
    if isinstance(task, dict):
        if not str(enriched.get("candidate_set_hash") or "").strip():
            enriched["candidate_set_hash"] = str(task.get("candidate_set_hash") or "")
        if not str(enriched.get("source_snapshot_hash") or "").strip():
            enriched["source_snapshot_hash"] = str(task.get("source_snapshot_hash") or "")
    batch = apply_patches_batch(uo_root, [enriched], current_source_hash=current_source_hash)
    if batch.get("ok") and batch.get("applied"):
        return batch["applied"][0]
    if batch.get("errors"):
        return batch["errors"][0]
    return {"ok": False, "error": batch.get("error") or "apply_failed"}


def apply_patches_batch(
    uo_root: Path,
    patches: list[dict[str, Any]],
    *,
    current_source_hash: str | None = None,
) -> dict[str, Any]:
    """Validate-all-then-commit: any failure leaves llm_tasks and ledger unchanged."""
    if not patches:
        return {"ok": True, "applied_count": 0, "error_count": 0, "applied": [], "errors": []}
    checked = validate_semantic_patch_set(
        uo_root,
        patches,
        current_source_hash,
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
    )


def resolve_patches_for_apply(
    uo_root: Path,
    *,
    patches_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve patch list for deterministic apply.

    Prefers ``ir/semantic_patches.yaml``. Merges auto ``mark_missing`` for uncovered
    empty-candidate tasks. Tasks that still need LLM adjudication surface as
    ``SEMANTIC_PATCHES_REQUIRED``.
    """
    open_blocking = open_blocking_tasks(uo_root)
    if not open_blocking:
        return {"ok": True, "patches": [], "skipped": True, "reason": "no_open_blocking"}

    patches: list[dict[str, Any]] = []
    if isinstance(patches_doc, dict):
        raw = patches_doc.get("patches")
        if isinstance(raw, list):
            patches = [p for p in raw if isinstance(p, dict)]

    covered = {str(p.get("task_id") or "") for p in patches}
    auto: list[dict[str, Any]] = []
    needs_llm: list[str] = []
    for task in open_blocking:
        tid = str(task.get("task_id") or "")
        if tid in covered:
            continue
        if can_auto_mark_missing(task):
            auto.append(
                {
                    "task_id": tid,
                    "action": "mark_missing",
                    "accepted_candidate_ids": [],
                    "rejected_candidate_ids": [],
                    "evidence": ["auto:empty_candidate_mark_missing"],
                    "source_snapshot_hash": str(task.get("source_snapshot_hash") or ""),
                    "candidate_set_hash": str(task.get("candidate_set_hash") or ""),
                }
            )
        else:
            needs_llm.append(tid)

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
        }

    merged = list(patches) + auto
    source = "semantic_patches.yaml" if patches else "auto_mark_missing"
    if patches and auto:
        source = "semantic_patches.yaml+auto_mark_missing"
    return {"ok": True, "patches": merged, "source": source}


def recheck_does_not_increment(uo_root: Path) -> dict[str, Any]:
    """Recheck helper — read budgets without mutating attempts."""
    doc = load_llm_tasks(uo_root)
    gaps = blocking_gap_tasks(uo_root)
    return {
        "ok": True,
        "open_blocking": open_blocking_tasks(uo_root),
        "blocking_gaps": gaps,
        "blocking_gap_count": len(gaps),
        "total_semantic_batches": int(doc.get("total_semantic_batches") or 0),
        "tasks": doc.get("tasks") or [],
        **compute_semantic_stats(uo_root),
    }


def compute_semantic_stats(uo_root: Path) -> dict[str, Any]:
    """Aggregate semantic task / patch / ledger counters for closure engines."""
    from uo.scripts.semantic_resolution_ledger import load_ledger

    tasks_doc = load_llm_tasks(uo_root)
    tasks = [t for t in (tasks_doc.get("tasks") or []) if isinstance(t, dict)]
    patches_doc = read_yaml(uo_root / "ir" / "semantic_patches.yaml") or {}
    producer_patches = [
        p for p in (patches_doc.get("patches") or []) if isinstance(p, dict)
    ]
    ledger = load_ledger(uo_root)
    ledger_patches = [p for p in (ledger.get("semantic_patches") or []) if isinstance(p, dict)]

    accept_count = 0
    reject_count = 0
    mark_missing_count = 0
    auto_patch_count = 0
    materialized_patch_count = 0
    unconsumed_patch_count = 0
    for p in ledger_patches:
        if p.get("status") == "stale":
            continue
        action = str(p.get("action") or "")
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
        "blocking_gap_count": len(blocking_gap_tasks(uo_root)),
    }


_FAILURE_APPLY_STATUSES = frozenset(
    {"unconsumed", "invalid", "target_missing", "target_type_mismatch"}
)


def sync_tasks_from_materialization(
    uo_root: Path,
    ledger: dict[str, Any],
    *,
    mutate_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update llm_tasks from ledger apply_status after rebuild verification.

    - materialized → task_status=resolved, semantic_status=closed, blocking=false
    - unconsumed/invalid/target_* → rework_required + unresolved + blocking
    - mark_missing → remains adjudicated/unresolved/blocking
    """
    doc = mutate_doc if mutate_doc is not None else load_llm_tasks(uo_root)
    by_id = {str(t.get("task_id")): t for t in (doc.get("tasks") or []) if isinstance(t, dict)}
    closed = 0
    reopened = 0
    for patch in ledger.get("semantic_patches") or []:
        if not isinstance(patch, dict) or patch.get("status") == "stale":
            continue
        tid = str(patch.get("task_id") or "")
        task = by_id.get(tid)
        if task is None:
            continue
        action = str(patch.get("action") or "")
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
