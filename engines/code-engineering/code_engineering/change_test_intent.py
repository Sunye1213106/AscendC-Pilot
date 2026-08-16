"""Typed ChangeTestIntent: CE impact → TG targeted construct (machine-consumed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SCHEMA = "ce-change-test-intent/v1"


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def scenario_ids(doc: dict[str, Any]) -> set[str]:
    return {
        str(row.get("id") or "")
        for row in (doc.get("items") or [])
        if isinstance(row, dict) and row.get("id")
    }


def scenario_delta(planned: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    p = scenario_ids(planned)
    a = scenario_ids(actual)
    return {
        "schema": "ce-scenario-delta/v1",
        "planned_and_hit": sorted(p & a),
        "newly_discovered": sorted(a - p),
        "planned_but_not_impacted": sorted(p - a),
    }


def build_change_test_intent(
    *,
    impact: dict[str, Any],
    obligations: list[dict[str, Any]],
    uo_digest: str = "",
    source_fingerprint: str = "",
    change_revision: str = "",
) -> dict[str, Any]:
    """Map impact slice + risk obligations to typed replay targets."""
    targets: list[dict[str, Any]] = []
    keys = impact.get("affected_keys") or impact.get("affected_keys_sample") or []
    for idx, key in enumerate(keys):
        targets.append(
            {
                "obligation_id": f"CE-OBL-KEY-{idx}",
                "kind": "tiling_key",
                "expected_key": key,
                "predicate": {"tiling_key": key},
                "expected": {"tiling_key": key},
            }
        )
    for idx, row in enumerate(obligations):
        if not isinstance(row, dict):
            continue
        oid = str(row.get("id") or row.get("obligation_id") or f"CE-OBL-{idx}")
        kind = str(row.get("kind") or row.get("risk_class") or "host_branch")
        if kind.upper() in {"KERNEL", "KERNEL_PATH"}:
            kind = "kernel_path"
        elif kind.upper() in {"TILING", "TILING_KEY"}:
            kind = "tiling_key"
        else:
            kind = "host_branch"
        symbol = str(
            row.get("symbol")
            or row.get("callee")
            or (row.get("anchor") or {}).get("callee")
            or row.get("name")
            or ""
        )
        targets.append(
            {
                "obligation_id": oid,
                "kind": kind,
                "symbol": symbol,
                "predicate": dict(row.get("predicate") or {}),
                "expected": dict(row.get("expected") or {"risk_class": row.get("risk_class")}),
            }
        )
    return {
        "schema": SCHEMA,
        "change_revision": change_revision,
        "uo_digest": uo_digest,
        "source_fingerprint": source_fingerprint,
        "targets": targets,
    }


def write_yaml(path: Path, doc: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path
