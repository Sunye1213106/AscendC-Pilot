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
    """Machine check: prefer include-closure / scope artifacts over model claims."""
    for rel in (
        "ir/source_scope.yaml",
        "ir/include_closure.yaml",
    ):
        data = read_yaml(uo_root / rel) or {}
        status = str(
            data.get("include_closure_status")
            or data.get("status")
            or data.get("closure_status")
            or ""
        ).casefold()
        if status in {"complete", "closed", "ok"}:
            return True
    # Confirmed scope present counts as usable but not proven-complete.
    runs = uo_root / "runs"
    if runs.is_dir() and any(runs.glob("*/scope/scope_confirmed.yaml")):
        return False
    return False


def classify_task(task: dict[str, Any], *, uo_root: Path | None = None) -> dict[str, Any]:
    """Return triage fields for one task."""
    score_phase = str(task.get("score_phase") or "")
    if not score_phase:
        ck = str(task.get("checkpoint") or "")
        if "pre_semantic" in ck:
            score_phase = "pre_semantic"
        elif "post_semantic" in ck:
            score_phase = "post_semantic"

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
            "category": "incomplete_scope_candidate",
            "route": "none",
            "blocking_scope": "extract",
            "blocking_phase": "extract",
            "blocks_extract_advance": True,
            "blocks_workflow_complete": True,
            "eligible_for_adjudication": False,
            "score_phase": score_phase or "post_semantic",
            "reason": "no grounded candidates",
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
        if score_phase_filter:
            sp = str(task.get("score_phase") or "")
            ck = str(task.get("checkpoint") or "")
            if score_phase_filter == "post_semantic" and "post_semantic" not in sp and "post_semantic" not in ck:
                # Still triage open tasks without phase for safety.
                if task.get("status") not in {"open", "rework_required"}:
                    continue
        row = classify_task(task, uo_root=uo_root)
        # Pre-semantic tasks are never adjudicable.
        if str(task.get("score_phase") or "") == "pre_semantic" or "pre_semantic" in str(
            task.get("checkpoint") or ""
        ):
            row["eligible_for_adjudication"] = False
            row["score_phase"] = "pre_semantic"
            task["task_status"] = task.get("task_status") or "provisional"
            if task.get("status") == "open":
                task["task_status"] = "provisional"
        task["triage_category"] = row["category"]
        task["route"] = row["route"]
        task["blocking_scope"] = row["blocking_scope"]
        task["blocking_phase"] = row["blocking_phase"]
        task["blocks_extract_advance"] = row["blocks_extract_advance"]
        task["blocks_workflow_complete"] = row["blocks_workflow_complete"]
        task["eligible_for_adjudication"] = row["eligible_for_adjudication"]
        if not task.get("score_phase"):
            task["score_phase"] = row.get("score_phase")
        task["resolution_class"] = grade_task(task)
        row["resolution_class"] = task["resolution_class"]
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
    _, rows = apply_triage_to_tasks(list(tasks), uo_root=uo_root)
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
        },
    }
    write_yaml(uo_root / "ir" / "semantic_task_triage.yaml", payload)
    return payload
