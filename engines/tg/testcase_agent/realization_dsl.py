from __future__ import annotations

from typing import Any

from .realization_contract import REALIZATION_MAP_VERSION


def normalize_realization_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return empty_realization_map("realization map is not a mapping")
    out = dict(value)
    out["version"] = REALIZATION_MAP_VERSION
    out.setdefault("consumer", {})
    out.setdefault("csv_variables", [])
    out.setdefault("derived_variables", [])
    out.setdefault("branch_mappings", [])
    out.setdefault("abstract_branches", [])
    out.setdefault("emit", {})
    out.setdefault("alignment_report", {})
    out["csv_variables"] = [item for item in out["csv_variables"] if isinstance(item, dict)]
    out["derived_variables"] = [item for item in out["derived_variables"] if isinstance(item, dict)]
    out["branch_mappings"] = [item for item in out["branch_mappings"] if isinstance(item, dict)]
    out["abstract_branches"] = [item for item in out["abstract_branches"] if isinstance(item, dict)]
    return out


def empty_realization_map(reason: str = "") -> dict[str, Any]:
    return {
        "version": REALIZATION_MAP_VERSION,
        "status": "fallback",
        "consumer": {"columns": []},
        "csv_variables": [],
        "derived_variables": [],
        "branch_mappings": [],
        "abstract_branches": [],
        "alignment_report": {},
        "emit": {},
        "warnings": [reason] if reason else [],
    }


def realization_report(realization_map: dict[str, Any]) -> dict[str, Any]:
    branch_mappings = realization_map.get("branch_mappings") or []
    abstract = realization_map.get("abstract_branches") or []
    derived = realization_map.get("derived_variables") or []
    csv_vars = realization_map.get("csv_variables") or []
    alignment = realization_map.get("alignment_report") if isinstance(realization_map.get("alignment_report"), dict) else {}
    return {
        "version": 1,
        "status": realization_map.get("status", "ok"),
        "consumer_root": (realization_map.get("consumer") or {}).get("root", ""),
        "csv_column_count": len((realization_map.get("consumer") or {}).get("columns") or []),
        "csv_variable_count": len(csv_vars),
        "derived_variable_count": len(derived),
        "mapped_branch_count": len(branch_mappings),
        "abstract_branch_count": len(abstract),
        "mapped_branch_examples": branch_mappings[:20],
        "abstract_branch_examples": abstract[:20],
        "alignment_report": alignment,
        "warnings": realization_map.get("warnings") or [],
    }
