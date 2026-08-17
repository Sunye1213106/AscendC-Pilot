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


def _parse_int_keys(raw: Any) -> list[int]:
    out: list[int] = []
    values = raw if isinstance(raw, (list, tuple, set)) else []
    for value in values:
        try:
            key = int(str(value).strip(), 0)
        except (TypeError, ValueError):
            continue
        if key not in out:
            out.append(key)
    return out


def build_tg_plan_intent(
    *,
    impact: dict[str, Any],
    architecture: str = "",
    op_name: str = "",
    source: str = "ce-impact",
) -> dict[str, Any]:
    """CE → tg-plan: ``tg-plan-intent/v1`` with keys/dims, never silent T=D."""
    keys = _parse_int_keys(
        impact.get("affected_keys") or impact.get("affected_keys_sample") or []
    )
    dim_names: list[str] = []
    raw_dims = impact.get("target_dimensions") or impact.get("key_dims") or impact.get("fields") or []
    if isinstance(raw_dims, dict):
        target_dimensions = {
            str(name): [str(v) for v in (values if isinstance(values, (list, tuple, set)) else [values]) if str(v)]
            for name, values in raw_dims.items()
            if str(name).strip()
        }
        target_dimensions = {k: v for k, v in target_dimensions.items() if v}
    else:
        dim_names = [str(name).strip() for name in raw_dims if str(name).strip()]
        target_dimensions = {}
    if keys:
        target_mode = "explicit_keys"
    elif target_dimensions:
        target_mode = "dimension_filter"
    else:
        target_mode = "explicit_keys"
    return {
        "schema": "tg-plan-intent/v1",
        "mode": "ce_change_scoped",
        "source": source,
        "target_mode": target_mode,
        "target_keys": keys,
        "target_dimensions": target_dimensions,
        "dimension_names": dim_names,
        "architecture": architecture,
        "op_name": op_name,
        "do_not_widen_to_declared_set": True,
    }
