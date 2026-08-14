"""Preferred action pipelines within a phase (Host must follow recommended_next).

Completion is receipt-bound for the current run (fail-closed). Artifact presence
alone is never enough. Spec ``pipelines`` is the sole order authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot.workflows import phase_pipeline


def _not_applicable_proof(project_root: Path, action_id: str) -> bool:
    """Explicit N/A proof written under the current run's action session."""
    from ascendc_pilot.state import load_state
    from ascendc_pilot.paths import runs_root

    state = load_state(project_root)
    run_id = str((state or {}).get("run_id") or "")
    if not run_id:
        return False
    path = runs_root(project_root) / run_id / "actions" / action_id / "not_applicable.yaml"
    if not path.is_file():
        return False
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(data, dict):
        return False
    status = str(data.get("status") or "").lower()
    return status in {
        "not_applicable",
        "na",
        "n/a",
        "semantic_patch_not_applicable",
    } and str(data.get("action_id") or action_id) == action_id and str(
        data.get("run_id") or run_id
    ) == run_id


def action_receipt_ok(project_root: Path, action_id: str) -> bool:
    """True iff current run has a verified Pilot receipt for ``action_id``."""
    from ascendc_pilot.runs import verify_receipt

    verified = verify_receipt(
        project_root,
        action_id=action_id,
        require_pilot_issued=True,
        require_hashes=True,
        require_action_id=True,
        require_spec_hash=True,
    )
    return bool(verified.get("ok"))


def _action_done(
    project_root: Path,
    action_id: str,
    *,
    done_cache: dict[str, bool] | None = None,
) -> bool:
    """Receipt (or explicit not_applicable proof) — never file existence alone."""
    if done_cache is not None and action_id in done_cache:
        return done_cache[action_id]
    ok = action_receipt_ok(project_root, action_id) or _not_applicable_proof(project_root, action_id)
    if done_cache is not None:
        done_cache[action_id] = ok
    return ok


def preferred_pipeline(
    workflow_id: str,
    phase: str,
    *,
    project_root: Path | None = None,
    mode: str | None = None,
) -> list[str]:
    return phase_pipeline(workflow_id, phase, project_root=project_root, mode=mode)


def missing_phase_actions(
    project_root: Path,
    workflow_id: str,
    phase: str,
    *,
    done_cache: dict[str, bool] | None = None,
    mode: str | None = None,
) -> list[str]:
    """Pipeline actions not yet proven complete for the current run."""
    cache = done_cache if done_cache is not None else {}
    missing: list[str] = []
    for aid in preferred_pipeline(
        workflow_id, phase, project_root=project_root, mode=mode
    ):
        if not _action_done(project_root, aid, done_cache=cache):
            missing.append(aid)
    return missing


def recommend_next_action(
    project_root: Path,
    *,
    workflow_id: str,
    phase: str,
    allowed_actions: list[dict[str, Any]] | None,
    mode: str | None = None,
) -> dict[str, Any] | None:
    """Pick the first incomplete preferred action that is also currently allowed."""
    allowed = [a for a in (allowed_actions or []) if isinstance(a, dict) and a.get("id")]
    by_id = {str(a["id"]): a for a in allowed}
    pipe = preferred_pipeline(
        workflow_id, phase, project_root=project_root, mode=mode
    )
    if not pipe:
        next_phase = ""
        try:
            from ascendc_pilot.workflows import WORKFLOWS

            meta = WORKFLOWS.get(workflow_id) or {}
            for tr in meta.get("transitions") or []:
                if not isinstance(tr, dict):
                    continue
                if str(tr.get("kind") or "forward") != "forward":
                    continue
                if str(tr.get("from") or "") == phase:
                    next_phase = str(tr.get("to") or "").strip()
                    if next_phase:
                        break
        except Exception:  # noqa: BLE001
            next_phase = ""
        if next_phase:
            hint = (
                f"本阶段首选流水线已齐；请执行 `acp advance {next_phase}`"
                f"（禁止再 run-action 本阶段 Action）"
            )
        else:
            hint = "本阶段首选流水线已齐；请 `acp advance <next_phase>` 或 `acp complete`"
        return {
            "id": None,
            "label_zh": "",
            "reason": "pipeline_complete",
            "pipeline": pipe,
            "next_phase": next_phase or None,
            "hint_zh": hint,
        }
    if not allowed:
        return None
    # Single-pass completion index: never re-verify the whole pipeline twice.
    done_cache: dict[str, bool] = {}
    missing = missing_phase_actions(
        project_root,
        workflow_id,
        phase,
        done_cache=done_cache,
        mode=mode,
    )
    for aid in pipe:
        if aid not in by_id:
            continue
        if aid in missing:
            row = by_id[aid]
            return {
                "id": aid,
                "label_zh": str(row.get("label_zh") or aid),
                "reason": "pipeline_incomplete",
                "pipeline": pipe,
                "missing_actions": missing,
            }
    # Resolve the forward next phase so Host gets an exact advance command.
    next_phase = ""
    try:
        from ascendc_pilot.workflows import WORKFLOWS

        meta = WORKFLOWS.get(workflow_id) or {}
        for tr in meta.get("transitions") or []:
            if not isinstance(tr, dict):
                continue
            if str(tr.get("kind") or "forward") != "forward":
                continue
            if str(tr.get("from") or "") == phase:
                next_phase = str(tr.get("to") or "").strip()
                if next_phase:
                    break
    except Exception:  # noqa: BLE001
        next_phase = ""
    if next_phase:
        hint = (
            f"本阶段首选流水线已齐；请执行 `acp advance {next_phase}`"
            f"（禁止再 run-action 本阶段 Action）"
        )
    else:
        hint = "本阶段首选流水线已齐；请 `acp advance <next_phase>` 或 `acp complete`"
    return {
        "id": None,
        "label_zh": "",
        "reason": "pipeline_complete",
        "pipeline": pipe,
        "next_phase": next_phase or None,
        "hint_zh": hint,
        "recommended_command": f"acp advance {next_phase}" if next_phase else "acp complete",
    }
