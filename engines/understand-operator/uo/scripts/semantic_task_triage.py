"""Deterministic triage of semantic llm_tasks → category / route / phase blocking."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.semantic_severity import annotate_resolution_class, grade_task

MACRO_MARKERS = (
    "REGISTER_TILING_TEMPLATE",
    "REGISTER_TILING_TEMPLATE_WITH_ARCH",
    "REG_OP",
    "IMPL_OP_OPTILING",
    "ASCENDC_TPL_ARGS",
    "GET_TPL_TILING_KEY",
    "GET_TILING_DATA",
)

KEY_MARKERS = (
    "tilingkey",
    "tiling_key",
    "GET_TPL_TILING_KEY",
    "ASCENDC_TPL",
    "key_schema",
    "tilingkey_binding",
    "tilingkey_schema",
)

# triage_category → authoritative effective_task_type (downstream must use this).
CATEGORY_TO_EFFECTIVE_TYPE: dict[str, str] = {
    "candidate_generation_required": "candidate_generation",
    "incomplete_scope_candidate": "evidence_enrichment",
    "identity_join_ambiguous": "choose_edge",
    "true_multi_candidate": "choose_edge",
    "source_proven_unique": "deterministic_accept",
    "macro_contract_resolvable": "macro_semantics",
    "key_derivation_gap": "key_derivation",
    "tilingdata_type_unknown": "typed_bridge_resolution",
}


def effective_task_type_for(task: dict[str, Any]) -> str:
    """Authoritative task type for route/apply/auto-missing decisions."""
    explicit = str(task.get("effective_task_type") or "").strip()
    if explicit:
        return explicit
    cat = str(task.get("triage_category") or task.get("category") or "").strip()
    if cat in CATEGORY_TO_EFFECTIVE_TYPE:
        return CATEGORY_TO_EFFECTIVE_TYPE[cat]
    return str(task.get("type") or "").strip()


def validate_semantic_task_contract(task: dict[str, Any]) -> dict[str, Any]:
    """Reject illegal effective_type / category / route / eligibility combinations.

    Uses effective_task_type (post-canonicalize / post-triage), not original declared
    type — a scoring hint of mark_missing that was remapped to candidate_generation
    must not raise SEMANTIC_TASK_CONTRACT_CONFLICT.
    """
    category = str(task.get("triage_category") or task.get("category") or "")
    effective = effective_task_type_for(task)
    route = str(task.get("route") or "")
    eligible = bool(task.get("eligible_for_adjudication"))
    conflicts: list[str] = []

    if effective == "mark_missing" and category == "candidate_generation_required":
        conflicts.append("mark_missing+candidate_generation_required")
        conflicts.append("category_effective_type_mismatch")
    if route == "uo-semantic-resolve" and not eligible and category == "true_multi_candidate":
        conflicts.append("multi_candidate_not_eligible")
    if effective == "macro_semantics" and route == "uo-semantic-resolve":
        conflicts.append("macro_semantics_on_llm_route")
    if effective == "key_derivation" and route == "uo-semantic-resolve":
        conflicts.append("key_derivation_on_extract_llm_route")

    if conflicts:
        return {
            "ok": False,
            "error": "SEMANTIC_TASK_CONTRACT_CONFLICT",
            "conflicts": conflicts,
            "triage_category": category,
            "effective_task_type": effective,
            "route": route,
            "eligible_for_adjudication": eligible,
            "task_id": task.get("task_id"),
        }
    return {"ok": True, "effective_task_type": effective}


def _task_text(task: dict[str, Any]) -> str:
    parts = [
        str(task.get("target") or ""),
        str(task.get("type") or ""),
        str(task.get("object_type") or ""),
        str(task.get("task_hint") or ""),
    ]
    for c in task.get("candidates") or []:
        if isinstance(c, dict):
            parts.append(str(c.get("symbol_ref") or ""))
            parts.append(str(c.get("snippet") or ""))
    return " ".join(parts)


def _is_macro_task(task: dict[str, Any]) -> bool:
    text = _task_text(task)
    return any(m in text for m in MACRO_MARKERS)


def _is_key_task(task: dict[str, Any]) -> bool:
    text = _task_text(task).casefold()
    ot = str(task.get("object_type") or "").casefold()
    ttype = str(task.get("type") or "").casefold()
    if ot in {"tilingkey_binding"} or "tilingkey" in ttype:
        return True
    return any(m.casefold() in text for m in KEY_MARKERS)


def _candidate_count(task: dict[str, Any]) -> int:
    return len([c for c in (task.get("candidates") or []) if isinstance(c, dict)])


def _has_strong_match(task: dict[str, Any]) -> bool:
    for c in task.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        if c.get("file_path") and (c.get("start_line") or c.get("line")):
            if c.get("symbol_ref") or c.get("snippet"):
                return True
    return False


def _scope_complete(uo_root: Path) -> bool:
    """Machine check via include_closure SSOT only (no multi-file dual-read)."""
    from uo.scripts.source_include_closure import include_closure_is_complete

    return include_closure_is_complete(uo_root)


def _score_phase(task: dict[str, Any]) -> str:
    """Resolve phase with explicit score_phase taking precedence over old checkpoint text."""
    explicit = str(task.get("score_phase") or "").strip()
    if explicit:
        return explicit
    checkpoint = str(task.get("checkpoint") or "")
    if "post_semantic" in checkpoint:
        return "post_semantic"
    if "pre_semantic" in checkpoint:
        return "pre_semantic"
    return ""


def _promote_post_semantic_task(task: dict[str, Any]) -> bool:
    """Promote a reused pre-semantic provisional task into the canonical post task."""
    if _score_phase(task) != "post_semantic":
        return False
    lifecycle = str(task.get("task_status") or task.get("status") or "")
    if lifecycle != "provisional":
        return False
    task["task_status"] = "open"
    if str(task.get("status") or "") in {"", "open", "provisional"}:
        task["status"] = "open"
    task["promoted_from_provisional"] = True
    return True


def classify_task(task: dict[str, Any], *, uo_root: Path | None = None) -> dict[str, Any]:
    """Return triage fields for one task."""
    score_phase = _score_phase(task)

    # KEY gaps first — some KEY macros overlap MACRO_MARKERS (GET_TPL_TILING_KEY).
    if _is_key_task(task):
        return {
            "task_id": task.get("task_id"),
            "category": "key_derivation_gap",
            "route": "uo-key-resolve",
            "blocking_scope": "workflow",
            "blocking_phase": "resolve",
            "blocks_extract_advance": False,
            "blocks_workflow_complete": True,
            "eligible_for_adjudication": False,
            "score_phase": score_phase or "post_semantic",
            "reason": "KEY / tiling-key derivation deferred to resolve",
        }

    if _is_macro_task(task):
        return {
            "task_id": task.get("task_id"),
            "category": "macro_contract_resolvable",
            "route": "macro_semantic_materializer",
            "blocking_scope": "extract",
            "blocking_phase": "extract",
            "blocks_extract_advance": True,
            "blocks_workflow_complete": True,
            "eligible_for_adjudication": False,
            "score_phase": score_phase or "pre_semantic",
            "reason": "contract-backed registration/template macro",
        }

    n_cand = _candidate_count(task)
    strong = _has_strong_match(task)
    scope_ok = _scope_complete(uo_root) if uo_root is not None else False

    if n_cand == 0:
        return {
            "task_id": task.get("task_id"),
            "category": "candidate_generation_required",
            "route": "uo-semantic-resolve",
            "blocking_scope": "extract",
            "blocking_phase": "extract",
            "blocks_extract_advance": True,
            "blocks_workflow_complete": True,
            "eligible_for_adjudication": score_phase != "pre_semantic",
            "score_phase": score_phase or "post_semantic",
            "reason": "no grounded candidates; generate or enrich candidates before adjudication",
        }

    if n_cand == 1 and strong and scope_ok:
        return {
            "task_id": task.get("task_id"),
            "category": "source_proven_unique",
            "route": "deterministic_accept",
            "blocking_scope": "extract",
            "blocking_phase": "extract",
            "blocks_extract_advance": True,
            "blocks_workflow_complete": True,
            "eligible_for_adjudication": False,
            "score_phase": score_phase or "post_semantic",
            "reason": "unique candidate with strong match and complete scope",
        }

    if n_cand == 1 and strong and not scope_ok:
        return {
            "task_id": task.get("task_id"),
            "category": "incomplete_scope_candidate",
            "route": "uo-semantic-resolve",
            "blocking_scope": "extract",
            "blocking_phase": "extract",
            "blocks_extract_advance": True,
            "blocks_workflow_complete": True,
            "eligible_for_adjudication": True,
            "score_phase": score_phase or "post_semantic",
            "reason": "unique candidate but scope/include closure not machine-complete",
        }

    if n_cand == 1 and not strong:
        return {
            "task_id": task.get("task_id"),
            "category": "identity_join_ambiguous",
            "route": "uo-semantic-resolve",
            "blocking_scope": "extract",
            "blocking_phase": "extract",
            "blocks_extract_advance": True,
            "blocks_workflow_complete": True,
            "eligible_for_adjudication": True,
            "score_phase": score_phase or "post_semantic",
            "reason": "single weak candidate — needs LLM disambiguation",
        }

    # n_cand >= 2
    if strong:
        return {
            "task_id": task.get("task_id"),
            "category": "true_multi_candidate",
            "route": "uo-semantic-resolve",
            "blocking_scope": "extract",
            "blocking_phase": "extract",
            "blocks_extract_advance": True,
            "blocks_workflow_complete": True,
            "eligible_for_adjudication": True,
            "score_phase": score_phase or "post_semantic",
            "reason": "multiple grounded candidates",
        }

    return {
        "task_id": task.get("task_id"),
        "category": "identity_join_ambiguous",
        "route": "uo-semantic-resolve",
        "blocking_scope": "extract",
        "blocking_phase": "extract",
        "blocks_extract_advance": True,
        "blocks_workflow_complete": True,
        "eligible_for_adjudication": True,
        "score_phase": score_phase or "post_semantic",
        "reason": "multi-candidate without strong identity join",
    }


def apply_triage_to_tasks(
    tasks: list[dict[str, Any]],
    *,
    uo_root: Path | None = None,
    score_phase_filter: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Annotate tasks in-place; return (tasks, triage_rows)."""
    rows: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        phase = _score_phase(task)
        if score_phase_filter:
            if score_phase_filter == "post_semantic" and phase != "post_semantic":
                # Still triage open tasks without phase for safety.
                if phase or task.get("status") not in {"open", "rework_required"}:
                    continue
        promoted = _promote_post_semantic_task(task)
        phase = _score_phase(task)
        row = classify_task(task, uo_root=uo_root)
        if promoted:
            row["promoted_from_provisional"] = True

        # Pre-semantic diagnostics are provisional and never adjudicable.
        if phase == "pre_semantic":
            row["eligible_for_adjudication"] = False
            row["score_phase"] = "pre_semantic"
            task["task_status"] = task.get("task_status") or "provisional"
            if task.get("status") == "open":
                task["task_status"] = "provisional"
        elif phase == "post_semantic" and row.get("blocks_extract_advance"):
            # Post-semantic blocking tasks must have an executable deterministic or LLM route.
            if not str(row.get("route") or "").strip() or row.get("route") == "none":
                row["route"] = "uo-semantic-resolve"
                row["eligible_for_adjudication"] = True

        task["triage_category"] = row["category"]
        task["route"] = row["route"]
        task["blocking_scope"] = row["blocking_scope"]
        task["blocking_phase"] = row["blocking_phase"]
        task["blocks_extract_advance"] = row["blocks_extract_advance"]
        task["blocks_workflow_complete"] = row["blocks_workflow_complete"]
        task["eligible_for_adjudication"] = row["eligible_for_adjudication"]
        if not task.get("original_task_type"):
            task["original_task_type"] = str(task.get("type") or "")
        effective = CATEGORY_TO_EFFECTIVE_TYPE.get(str(row["category"]), str(task.get("type") or ""))
        task["effective_task_type"] = effective
        row["effective_task_type"] = effective
        row["original_task_type"] = task.get("original_task_type")
        if not task.get("score_phase"):
            task["score_phase"] = row.get("score_phase")
        task["resolution_class"] = grade_task(task)
        row["resolution_class"] = task["resolution_class"]
        contract = validate_semantic_task_contract(task)
        if not contract.get("ok"):
            row["contract_error"] = contract
            task["contract_error"] = contract.get("error")
            task["eligible_for_adjudication"] = False
            row["eligible_for_adjudication"] = False
            task["blocks_extract_advance"] = True
            row["blocks_extract_advance"] = True
            task["blocking"] = True
        rows.append(row)
    annotate_resolution_class(tasks)
    return tasks, rows


def write_semantic_task_triage(
    uo_root: Path,
    *,
    tasks: list[dict[str, Any]] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """Classify tasks and write ``ir/semantic_task_triage.yaml``."""
    if tasks is None:
        doc = read_yaml(uo_root / "ir" / "llm_tasks.yaml") or {}
        tasks = [t for t in (doc.get("tasks") or []) if isinstance(t, dict)]
        if run_id:
            tasks = [t for t in tasks if str(t.get("run_id") or "") == run_id]
    triaged_tasks, rows = apply_triage_to_tasks(list(tasks), uo_root=uo_root)
    by_cat: dict[str, int] = {}
    for r in rows:
        cat = str(r.get("category") or "unknown")
        by_cat[cat] = by_cat.get(cat, 0) + 1
    payload = {
        "version": 1,
        "run_id": run_id,
        "tasks": rows,
        "stats": {
            "task_count": len(rows),
            "by_category": by_cat,
            "llm_eligible": sum(1 for r in rows if r.get("eligible_for_adjudication")),
            "blocks_extract": sum(1 for r in rows if r.get("blocks_extract_advance")),
            "post_semantic_provisional_count": sum(
                1
                for task in triaged_tasks
                if _score_phase(task) == "post_semantic"
                and str(task.get("task_status") or task.get("status") or "") == "provisional"
            ),
            "blocking_route_none_count": sum(
                1
                for task in triaged_tasks
                if task.get("blocks_extract_advance")
                and str(task.get("route") or "") in {"", "none"}
            ),
        },
    }
    write_yaml(uo_root / "ir" / "semantic_task_triage.yaml", payload)
    return payload
