"""Safe TG artifact compaction for full TilingKey closure.

Only products that are reconstructible from the reviewed ``.uo`` and approved
``target_set.yaml`` are removed. Replay witnesses, R/E ledgers, lemma evidence,
audit reports and certificates are never compacted here.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def _remove(path: Path, removed: list[str]) -> None:
    if path.is_dir():
        shutil.rmtree(path)
        removed.append(path.as_posix())
    elif path.is_file():
        path.unlink()
        removed.append(path.as_posix())


def compact_after_plan_approve(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    try:
        from ascendc_pilot.paths import tg_root
        from ascendc_pilot.workflows import resolve_tg_mode

        mode = resolve_tg_mode(root)
        tg = tg_root(root)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}

    if mode != "tilingkey_full_coverage":
        return {"ok": True, "skipped": "non_full_mode", "mode": mode}

    # Approval is the point after which these are no longer authorities:
    # target_set.yaml embeds the .uo identity + declared/target hashes and the
    # solve precheck re-derives D directly from the product.
    candidates = [
        tg / "intake",
        tg / "snapshot",
        tg / "plan" / "coverage_obligations.yaml",  # duplicate of level copy
        tg / "init" / "uo_ready.yaml",              # superseded by status/fingerprint
        tg / "realization" / "llm_bind_prompt_bundle.yaml",  # consumed prompt, not evidence
    ]
    removed: list[str] = []
    errors: list[str] = []
    for path in candidates:
        try:
            _remove(path, removed)
        except OSError as exc:
            errors.append(f"{path}:{exc}")

    return {
        "ok": not errors,
        "mode": mode,
        "compacted": bool(removed),
        "removed": removed,
        "errors": errors,
        "preserved": [
            "tg/plan/levels/*/target_set.yaml",
            "tg/plan/levels/*/human_supplement.yaml",
            "tg/init/status.yaml",
            "tg/init/kb_fingerprint.yaml",
            "tg/closure/**",
            "tg/replay/**",
        ],
    }
