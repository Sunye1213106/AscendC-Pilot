# -*- coding: utf-8 -*-
"""CE closure certificate generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from code_engineering.ledger import Ledger, compute_open


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _scope_root(project_root: Path | str, architecture: str) -> Path:
    pilot = Path(project_root).expanduser().resolve() / ".ascendc-pilot"
    return pilot / architecture if architecture else pilot


def _blind_spots(impact: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for anchor in impact.get("anchors") or []:
        if isinstance(anchor, dict) and anchor.get("evidence_tier") == "C":
            rows.append({
                "kind": "anchor",
                "id": str(anchor.get("id") or ""),
                "file": str(anchor.get("file") or ""),
                "reason": "tier_c_anchor",
            })
    for direction in ("forward", "backward"):
        section = impact.get(direction) or {}
        if not isinstance(section, dict):
            continue
        if section.get("truncated"):
            rows.append({"kind": "slice", "direction": direction, "reason": "budget_truncated"})
        for relation in section.get("relations") or []:
            if isinstance(relation, dict) and relation.get("evidence_tier") == "C":
                rows.append({
                    "kind": "relation",
                    "direction": direction,
                    "id": str(relation.get("id") or ""),
                    "reason": "tier_c_relation",
                })
    return {
        "count": len(rows),
        "items": rows,
        "truncated": any(
            isinstance(impact.get(direction), dict)
            and bool((impact.get(direction) or {}).get("truncated"))
            for direction in ("forward", "backward")
        ),
    }


def _intent_drift(scope: Path, impact: dict[str, Any]) -> dict[str, Any]:
    predicted_doc = _load_yaml(scope / "ce" / "intent" / "anchors.yaml")
    predicted = {
        str(row.get("id"))
        for row in (predicted_doc.get("anchors") or [])
        if isinstance(row, dict) and row.get("id")
    }
    actual = {
        str(row.get("id"))
        for row in (impact.get("anchors") or [])
        if isinstance(row, dict) and row.get("id")
    }
    if not predicted:
        return {
            "status": "unavailable",
            "drift": False,
            "predicted_count": 0,
            "actual_count": len(actual),
            "missing_from_actual": [],
            "new_in_actual": sorted(actual),
        }
    missing = predicted - actual
    added = actual - predicted
    return {
        "status": "compared",
        "drift": bool(missing or added),
        "predicted_count": len(predicted),
        "actual_count": len(actual),
        "missing_from_actual": sorted(missing),
        "new_in_actual": sorted(added),
    }


def _analyzability(
    project_root: Path | str,
    architecture: str,
    scope: Path,
) -> dict[str, Any]:
    capture = _load_yaml(scope / "ce" / "impact" / "change_capture.yaml")
    files = sorted(str(name) for name in (capture.get("diff_spans") or {}))
    if not files:
        return {"max_verdict": "blind", "files": {}, "status": "no_changed_files"}
    try:
        from code_engineering.analyzability import file_analyzability

        result = file_analyzability(project_root, files, architecture=architecture)
        return {"status": "measured", **result}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "max_verdict": "blind",
            "files": {},
            "error": str(exc)[:300],
        }


def certificate(
    obligations: Iterable[str],
    verified: Iterable[str],
    excepted: Iterable[str],
    *,
    residual: dict[str, Any] | None = None,
    blind_spots: dict[str, Any] | None = None,
    analyzability: dict[str, Any] | None = None,
    intent_drift: dict[str, Any] | None = None,
    closure_evidence: dict[str, Any] | None = None,
    freshness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic closure certificate."""
    o, v, x = set(obligations), set(verified), set(excepted)
    opened = compute_open(o, v, x)
    return {
        "schema": "ce-change-certificate/v2",
        "O": sorted(o),
        "V": sorted(v),
        "X": sorted(x),
        "Open": sorted(opened),
        "closed": not opened,
        "residual": residual or {"open_obligations": sorted(opened)},
        "blind_spots": blind_spots or {"count": 0, "items": [], "truncated": False},
        "analyzability": analyzability or {"status": "unavailable"},
        "intent_drift": intent_drift or {"status": "unavailable", "drift": False},
        "closure_evidence": closure_evidence or {},
        "freshness": freshness or {},
    }


def write_certificate(
    project_root: Path | str,
    ledger: Ledger,
    *,
    architecture: str = "",
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Write an arch-scoped evidence-rich closure certificate."""
    scope = _scope_root(project_root, architecture)
    impact = _load_yaml(scope / "ce" / "impact" / "impact_slice.yaml")
    freshness = _load_yaml(scope / "ce" / "impact" / "freshness.yaml")
    residual_doc = _load_yaml(scope / "ce" / "verify" / "residual.yaml")
    residual = {
        "open_obligations": sorted(ledger.Open),
        "prior_residual": residual_doc.get("Open") or residual_doc.get("open") or [],
    }
    doc = certificate(
        ledger.O,
        ledger.V,
        ledger.X,
        residual=residual,
        blind_spots=_blind_spots(impact),
        analyzability=_analyzability(project_root, architecture, scope),
        intent_drift=_intent_drift(scope, impact),
        closure_evidence=ledger.closure_evidence,
        freshness=freshness,
    )
    doc["transition_audit"] = ledger.transition_audit
    target = Path(path) if path is not None else (
        scope / "ce" / "impact" / "certificate.yaml"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    doc["path"] = str(target)
    return doc
