# -*- coding: utf-8 -*-
"""Promote staged CE feature drafts to canonical feature_decomposition.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _scope_root(project_root: Path | str, architecture: str) -> Path:
    root = Path(project_root).expanduser().resolve() / ".ascendc-pilot"
    return root / architecture if architecture else root


def _feature_rows(doc: Any) -> list[dict[str, Any]]:
    if isinstance(doc, dict):
        for key in ("features", "items", "accepted"):
            rows = doc.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    if isinstance(doc, list):
        return [row for row in doc if isinstance(row, dict)]
    return []


def _staging_features(scope: Path, run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    roots: list[Path] = []
    if run_id:
        roots.append(scope / "runs" / run_id / "actions" / "feature_decompose")
    else:
        roots.extend(sorted(scope.glob("runs/*/actions/feature_decompose")))
    for root in roots:
        rows.extend(_feature_rows(_load_yaml(root / "staging.yaml")))
        for part in sorted(root.glob("parts/*.yaml")):
            rows.extend(_feature_rows(_load_yaml(part)))
    return rows


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("name") or "").strip()


def promote_feature_decomposition(
    project_root: Path | str,
    *,
    architecture: str,
    run_id: str = "",
) -> dict[str, Any]:
    """Write canonical features from plan_review accepted list (+ staging fallback)."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "feature_promote", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    scope = _scope_root(project_root, arch)
    review = _load_yaml(scope / "ce" / "intent" / "plan_review.yaml")
    status = str(review.get("status") or "").strip().lower()
    if status not in {"pass", "accepted", "ok", "approve"}:
        return {
            "ok": False,
            "engine": "feature_promote",
            "error": "plan_review_not_accepted",
            "status": status or "missing",
        }
    accepted = review.get("accepted")
    if isinstance(accepted, list) and accepted and all(isinstance(row, dict) for row in accepted):
        features = [row for row in accepted if isinstance(row, dict)]
    else:
        wanted = {str(item).strip() for item in (accepted or []) if str(item).strip()}
        staged = _staging_features(scope, run_id)
        if wanted:
            features = [row for row in staged if _row_id(row) in wanted]
        else:
            features = staged
    if not features:
        return {
            "ok": False,
            "engine": "feature_promote",
            "error": "no_accepted_features",
            "status": status,
        }
    doc = {
        "schema": "ce-feature-decomposition/v1",
        "status": "accepted",
        "review_status": status,
        "features": features,
        "source": "plan_review",
    }
    out = scope / "ce" / "intent" / "feature_decomposition.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {
        "ok": True,
        "engine": "feature_promote",
        "artifact": out.as_posix(),
        "feature_count": len(features),
        **doc,
    }
