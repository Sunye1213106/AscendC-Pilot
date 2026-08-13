# -*- coding: utf-8 -*-
"""Build ce-scenario-set/v1 from CodeMap anchors (static or diff)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from code_engineering.scenarios.catalog import (
    LEGAL_IDS,
    budget_for,
    oracle_for,
    risk_class_for,
    scenarios_for_anchor,
)

SCHEMA = "ce-scenario-set/v1"


def anchors_from_slice(impact: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Collect OPERATION/BUFFER/KERNEL/FIELD anchors from a CE slice document."""
    doc = impact if isinstance(impact, dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("anchors", "hit_writers"):
        for item in doc.get(key) or []:
            if isinstance(item, dict):
                rows.append(_normalize_anchor(item))
    for side in ("forward", "backward"):
        block = doc.get(side) if isinstance(doc.get(side), dict) else {}
        for item in (block.get("nodes") or []):
            if isinstance(item, dict):
                rows.append(_normalize_anchor(item))
    return [row for row in rows if row.get("kind") or row.get("name") or row.get("id")]


def _normalize_anchor(anchor: dict[str, Any]) -> dict[str, Any]:
    facts = anchor.get("facts") if isinstance(anchor.get("facts"), dict) else {}
    callee = str(
        facts.get("callee")
        or anchor.get("callee")
        or anchor.get("function")
        or ""
    )
    kind = str(anchor.get("kind") or "").upper()
    name = str(anchor.get("name") or anchor.get("field") or callee or "")
    if not kind:
        if callee:
            kind = "OPERATION"
        elif anchor.get("field"):
            kind = "FIELD"
    return {
        "id": str(anchor.get("id") or name),
        "kind": kind,
        "name": name,
        "file": str(anchor.get("file") or facts.get("file") or ""),
        "line_start": int(anchor.get("line_start") or anchor.get("line") or 0),
        "callee": callee,
        "facts": {**facts, **({"callee": callee} if callee else {})},
        "evidence_tier": str(anchor.get("evidence_tier") or ""),
    }


def _anchor_ref(anchor: dict[str, Any]) -> dict[str, Any]:
    facts = anchor.get("facts") if isinstance(anchor.get("facts"), dict) else {}
    return {
        "id": str(anchor.get("id") or ""),
        "kind": str(anchor.get("kind") or ""),
        "name": str(anchor.get("name") or ""),
        "file": str(anchor.get("file") or facts.get("file") or ""),
        "line": int(anchor.get("line_start") or anchor.get("line") or 0),
        "callee": str(facts.get("callee") or ""),
    }


def infer_scenario_set(
    anchors: Iterable[dict[str, Any]],
    *,
    entry: str = "diff",
    fingerprint: str = "",
    origin: str = "inferred",
) -> dict[str, Any]:
    """Map anchors to catalog scenarios. Unknown ids are dropped."""
    grouped: dict[str, dict[str, Any]] = {}
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        ref = _anchor_ref(anchor)
        for sid in scenarios_for_anchor(anchor):
            if sid not in LEGAL_IDS:
                continue
            item = grouped.setdefault(
                sid,
                {
                    "id": sid,
                    "risk_class": risk_class_for(sid),
                    "anchors": [],
                    "knobs": {},
                    "budget": budget_for(sid),
                    "oracle": oracle_for(sid),
                    "origin": origin,
                    "retrieve_from": ["corpus"],
                },
            )
            if ref not in item["anchors"] and (ref.get("id") or ref.get("file")):
                item["anchors"].append(ref)
    return {
        "schema": SCHEMA,
        "entry": entry if entry in {"static", "diff"} else "diff",
        "fingerprint": fingerprint,
        "items": [grouped[key] for key in sorted(grouped)],
    }


def merge_knobs(skeleton: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    """Apply agent knob overlay; drop unknown scenario ids."""
    out = dict(skeleton)
    items = {str(row.get("id")): dict(row) for row in (skeleton.get("items") or []) if row.get("id")}
    for row in (overlay or {}).get("items") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "")
        if sid not in LEGAL_IDS or sid not in items:
            continue
        if isinstance(row.get("knobs"), dict):
            items[sid]["knobs"] = dict(row["knobs"])
        if isinstance(row.get("budget"), dict):
            items[sid]["budget"] = dict(row["budget"])
        if row.get("oracle") not in (None, ""):
            items[sid]["oracle"] = row["oracle"]
    out["items"] = [items[key] for key in sorted(items)]
    return out


def write_scenario_set(doc: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
