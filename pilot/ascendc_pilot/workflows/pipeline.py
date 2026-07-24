"""Preferred action pipelines within a phase (Host must follow recommended_next)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Ordered extract pipeline for uo-init (producer → deterministic consumers).
UO_INIT_EXTRACT_PIPELINE: list[str] = [
    "detect_score_pre",
    "extract_plan",
    "detect_score_post",
    "adjudicate_llm_tasks",
    "apply_semantic_patch",
    "rebuild_from_ledger",
    "recheck_closure",
]

# resolve phase preferred order (producer before confidence_report)
UO_INIT_RESOLVE_PIPELINE: list[str] = [
    "key_triage",
    "key_resolution",
    "adjudicate_llm_tasks",
    "apply_semantic_patch",
    "rebuild_from_ledger",
    "recheck_closure",
    "confidence_report",
    "confidence_review",
]


def _uo_root(project_root: Path) -> Path:
    return project_root / ".ascendc-pilot" / "uo"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return {}
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _open_blocking(uo: Path) -> list[dict[str, Any]]:
    doc = _load_yaml(uo / "ir" / "llm_tasks.yaml")
    tasks = doc.get("tasks") if isinstance(doc, dict) else []
    return [
        t
        for t in (tasks or [])
        if isinstance(t, dict) and t.get("status") == "open" and t.get("severity") == "blocking"
    ]


def _can_auto_mark_missing(task: dict[str, Any]) -> bool:
    ttype = str(task.get("type") or "")
    cands = list(task.get("candidates") or [])
    allowed = {str(a) for a in (task.get("allowed_actions") or [])}
    if ttype == "mark_missing" and not cands:
        return True
    if not cands and "mark_missing" in allowed and "accept_edge" not in allowed and "choose_one" not in allowed:
        return True
    return False


def _patches_cover_open(uo: Path, open_blocking: list[dict[str, Any]]) -> bool:
    doc = _load_yaml(uo / "ir" / "semantic_patches.yaml")
    raw = doc.get("patches") if isinstance(doc, dict) else None
    if not isinstance(raw, list) or not raw:
        return False
    covered = {str(p.get("task_id") or "") for p in raw if isinstance(p, dict)}
    needed = {str(t.get("task_id") or "") for t in open_blocking}
    return bool(needed) and needed.issubset(covered)


def _action_done(project_root: Path, action_id: str) -> bool:
    """Artifact-based completion (receipts are nice-to-have, not required mid-pipeline)."""
    uo = _uo_root(project_root)
    ir = uo / "ir"
    if action_id == "detect_score_pre":
        return (ir / "score_report_pre.yaml").is_file() and (ir / "llm_tasks.yaml").is_file()
    if action_id == "extract_plan":
        return (ir / "extract_plan.yaml").is_file() and (ir / "host_subgraph.yaml").is_file()
    if action_id == "detect_score_post":
        return (ir / "score_report_post.yaml").is_file()
    if action_id == "adjudicate_llm_tasks":
        open_b = _open_blocking(uo)
        if not open_b:
            return True
        if all(_can_auto_mark_missing(t) for t in open_b):
            # Deterministic apply can auto mark_missing — producer optional.
            return True
        return _patches_cover_open(uo, open_b)
    if action_id == "apply_semantic_patch":
        open_b = _open_blocking(uo)
        if open_b:
            return False
        return True
    if action_id == "rebuild_from_ledger":
        if _open_blocking(uo):
            return False
        return (ir / "operator_graph.yaml").is_file() or (ir / "entrypoint_graph.yaml").is_file()
    if action_id == "recheck_closure":
        return not _open_blocking(uo)
    if action_id == "key_triage":
        return (ir / "key_triage.yaml").is_file() or not (ir / "input_derivable_gaps.yaml").is_file()
    if action_id == "key_resolution":
        gaps = _load_yaml(ir / "input_derivable_gaps.yaml")
        if str(gaps.get("status") or "") == "open":
            return (ir / "input_derivable_patch.yaml").is_file()
        return True
    if action_id == "confidence_report":
        return (uo / "checks" / "confidence_gate.yaml").is_file()
    if action_id == "confidence_review":
        return (uo / "review" / "confidence_reason_review.yaml").is_file()
    return False


def preferred_pipeline(workflow_id: str, phase: str) -> list[str]:
    if workflow_id == "uo-init" and phase == "extract":
        return list(UO_INIT_EXTRACT_PIPELINE)
    if workflow_id == "uo-init" and phase == "resolve":
        return list(UO_INIT_RESOLVE_PIPELINE)
    return []


def recommend_next_action(
    project_root: Path,
    *,
    workflow_id: str,
    phase: str,
    allowed_actions: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Pick the first incomplete preferred action that is also currently allowed."""
    allowed = [a for a in (allowed_actions or []) if isinstance(a, dict) and a.get("id")]
    if not allowed:
        return None
    by_id = {str(a["id"]): a for a in allowed}
    pipe = preferred_pipeline(workflow_id, phase)
    if not pipe:
        a0 = allowed[0]
        return {
            "id": str(a0.get("id")),
            "label_zh": str(a0.get("label_zh") or a0.get("id") or ""),
            "reason": "first_allowed",
        }
    for aid in pipe:
        if aid not in by_id:
            continue
        if not _action_done(project_root, aid):
            row = by_id[aid]
            return {
                "id": aid,
                "label_zh": str(row.get("label_zh") or aid),
                "reason": "pipeline_incomplete",
                "pipeline": pipe,
            }
    return {
        "id": None,
        "label_zh": "",
        "reason": "pipeline_complete",
        "pipeline": pipe,
        "hint_zh": "本阶段首选流水线已齐；可尝试 acp advance",
    }
