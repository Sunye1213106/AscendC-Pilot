"""UO semantic severity grading: uo_blocking / tg_resolvable / degraded.

Public SSOT for extract closure vs TG intake vs soft leftovers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml

RESOLUTION_UO_BLOCKING = "uo_blocking"
RESOLUTION_TG_RESOLVABLE = "tg_resolvable"
RESOLUTION_DEGRADED = "degraded"


def grade_task(task: dict[str, Any]) -> str:
    """Assign resolution_class for one llm_tasks entry."""
    cat = str(task.get("triage_category") or "")
    route = str(task.get("route") or "")
    necessity = str(task.get("necessity") or "")
    severity = str(task.get("severity") or "")

    if cat == "key_derivation_gap" or route == "uo-key-resolve":
        return RESOLUTION_TG_RESOLVABLE
    if cat in {"noncoverage_internal"} or severity in {"degraded", "informational"}:
        return RESOLUTION_DEGRADED
    if necessity == "auxiliary" and severity != "blocking":
        return RESOLUTION_DEGRADED
    if task.get("blocks_extract_advance") is False and task.get("blocks_workflow_complete"):
        return RESOLUTION_TG_RESOLVABLE
    if severity == "blocking" or task.get("blocking") is True:
        return RESOLUTION_UO_BLOCKING
    return RESOLUTION_DEGRADED


def annotate_resolution_class(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for t in tasks:
        if isinstance(t, dict):
            t["resolution_class"] = grade_task(t)
    return tasks


def input_derivable_closure(uo_root: Path) -> dict[str, Any]:
    """Machine check: Host→KEY loop closed for TG intake."""
    id_path = uo_root / "ir" / "input_derivable.yaml"
    if not id_path.is_file():
        return {
            "ok": False,
            "error": "INPUT_DERIVABLE_MISSING",
            "open_gaps": 0,
            "unsolved": 0,
            "message": "ir/input_derivable.yaml missing",
        }
    id_doc = read_yaml(id_path) or {}
    gaps_doc = read_yaml(uo_root / "ir" / "input_derivable_gaps.yaml") or {}
    keys = id_doc.get("keys") if isinstance(id_doc.get("keys"), dict) else {}
    # Vacuous close: explicit empty KEY product (no dimensions).
    if not keys:
        unsolved_stat = int((id_doc.get("stats") or {}).get("unsolved") or 0)
        open_gap_items = [
            g
            for g in (gaps_doc.get("gaps") or [])
            if isinstance(g, dict)
            and str(g.get("status") or "unresolved").casefold() in {"unresolved", "open", ""}
        ]
        ok = unsolved_stat == 0 and not open_gap_items
        return {
            "ok": ok,
            "unsolved": unsolved_stat,
            "unsolved_ids": [],
            "open_gaps": len(open_gap_items),
            "open_gap_ids": [],
            "bad_true": [],
            "true_count": 0,
            "false_count": 0,
            "message": "ok (no KEY dimensions)" if ok else "empty input_derivable still has open gaps",
        }
    unsolved = [
        kid
        for kid, entry in keys.items()
        if isinstance(entry, dict) and entry.get("input_derivable") == "unsolved"
    ]
    open_gaps: list[str] = []
    for g in gaps_doc.get("gaps") or []:
        if not isinstance(g, dict):
            continue
        st = str(g.get("status") or "unresolved").casefold()
        if st in {"unresolved", "open", ""}:
            open_gaps.append(str(g.get("id") or g.get("target") or "?"))
    # true keys must be TG-bindable (needs_binding implied by classify)
    bad_true = []
    for kid, entry in keys.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("input_derivable") is True:
            if not (entry.get("host_parent") or entry.get("derivation_roots")):
                bad_true.append(str(kid))
    ok = not unsolved and not open_gaps and not bad_true
    return {
        "ok": ok,
        "unsolved": len(unsolved),
        "unsolved_ids": unsolved[:16],
        "open_gaps": len(open_gaps),
        "open_gap_ids": open_gaps[:16],
        "bad_true": bad_true[:8],
        "true_count": sum(
            1 for e in keys.values() if isinstance(e, dict) and e.get("input_derivable") is True
        ),
        "false_count": sum(
            1 for e in keys.values() if isinstance(e, dict) and e.get("input_derivable") is False
        ),
        "message": "ok" if ok else "Host→KEY input_derivable loop not closed",
    }


def grade_summary(uo_root: Path, *, current_run_id: str = "") -> dict[str, Any]:
    """Aggregate resolution_class counts for observation / gates."""
    doc = read_yaml(uo_root / "ir" / "llm_tasks.yaml") or {}
    tasks = [t for t in (doc.get("tasks") or []) if isinstance(t, dict)]
    if current_run_id:
        tasks = [t for t in tasks if str(t.get("run_id") or "") == current_run_id]
    annotate_resolution_class(tasks)
    counts = {
        RESOLUTION_UO_BLOCKING: 0,
        RESOLUTION_TG_RESOLVABLE: 0,
        RESOLUTION_DEGRADED: 0,
    }
    open_by: dict[str, int] = {k: 0 for k in counts}
    for t in tasks:
        rc = str(t.get("resolution_class") or RESOLUTION_DEGRADED)
        counts[rc] = counts.get(rc, 0) + 1
        lifecycle = str(t.get("task_status") or t.get("status") or "")
        sem = str(t.get("semantic_status") or "")
        if lifecycle in {"open", "rework_required", "adjudicated", "provisional"} and sem != "closed":
            open_by[rc] = open_by.get(rc, 0) + 1
    id_close = input_derivable_closure(uo_root)
    return {
        "version": 1,
        "counts": counts,
        "open_by_class": open_by,
        "input_derivable": id_close,
    }
