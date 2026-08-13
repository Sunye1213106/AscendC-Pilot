# -*- coding: utf-8 -*-
"""Canonical scenario ids and kind/callee → scenario mapping.

Keep this table aligned with skills/code-engineering/references/scenario-catalog.md.
"""

from __future__ import annotations

from typing import Any, Iterable

PRECISION_IDS = frozenset({
    "P-DTYPE", "P-CAST", "P-COPY-ALIGN", "P-QUEUE", "P-REDUCE-LONG",
    "P-OPTIONAL", "P-ILLEGAL", "P-TAIL",
})
PERF_IDS = frozenset({
    "F-SPLIT", "F-BUFFER", "F-SHAPE-TYPICAL", "F-SHAPE-TAIL", "F-DTYPE", "F-BALANCE",
})
LEGAL_IDS = PRECISION_IDS | PERF_IDS

_DEFAULT_BUDGET = {
    "P-DTYPE": {"max_cases": 4, "suite": "precision"},
    "P-CAST": {"max_cases": 4, "suite": "precision"},
    "P-COPY-ALIGN": {"max_cases": 4, "suite": "precision"},
    "P-QUEUE": {"max_cases": 2, "suite": "precision"},
    "P-REDUCE-LONG": {"max_cases": 2, "suite": "precision"},
    "P-OPTIONAL": {"max_cases": 4, "suite": "precision"},
    "P-ILLEGAL": {"max_cases": 0, "suite": "precision"},
    "P-TAIL": {"max_cases": 3, "suite": "precision"},
    "F-SPLIT": {"max_cases": 8, "suite": "perf"},
    "F-BUFFER": {"max_cases": 8, "suite": "perf"},
    "F-SHAPE-TYPICAL": {"max_cases": 8, "suite": "perf"},
    "F-SHAPE-TAIL": {"max_cases": 3, "suite": "perf"},
    "F-DTYPE": {"max_cases": 2, "suite": "perf"},
    "F-BALANCE": {"max_cases": 2, "suite": "perf"},
}

_COPY_OPS = frozenset({"DataCopy", "DataCopyPad"})
_QUEUE_OPS = frozenset({"EnQue", "DeQue"})
_SPLIT_NAME_HINTS = (
    "inner", "outer", "base", "tile", "core", "s1", "s2", "usedcore", "block",
)


def oracle_for(scenario_id: str) -> str:
    if scenario_id == "P-ILLEGAL":
        return "none"
    if scenario_id in PRECISION_IDS:
        return "only_grad"
    if scenario_id in PERF_IDS:
        return "profiler"
    return "host_replay"


def budget_for(scenario_id: str) -> dict[str, Any]:
    return dict(_DEFAULT_BUDGET.get(scenario_id) or {"max_cases": 4, "suite": "coverage"})


def risk_class_for(scenario_id: str) -> str:
    if scenario_id in PRECISION_IDS:
        return "precision"
    if scenario_id in PERF_IDS:
        return "perf"
    return "coverage"


def _callee(anchor: dict[str, Any]) -> str:
    facts = anchor.get("facts") if isinstance(anchor.get("facts"), dict) else {}
    return str(facts.get("callee") or anchor.get("callee") or anchor.get("name") or "")


def _kind(anchor: dict[str, Any]) -> str:
    return str(anchor.get("kind") or "").upper()


def scenarios_for_anchor(anchor: dict[str, Any]) -> tuple[str, ...]:
    """Deterministic kind/callee → scenario_id. Unknown anchors yield ()."""
    if not isinstance(anchor, dict):
        return ()
    kind = _kind(anchor)
    callee = _callee(anchor)
    name = str(anchor.get("name") or callee)
    ids: list[str] = []

    lowered = name.lower()
    if kind == "OPERATION":
        if callee == "Cast" or name.endswith("Cast"):
            ids.extend(("P-CAST", "P-DTYPE"))
        if callee in _COPY_OPS:
            ids.append("P-COPY-ALIGN")
        if callee in _QUEUE_OPS:
            ids.append("P-QUEUE")
        if any(token in lowered or token in callee.lower() for token in ("softmax", "reduce", "sum")):
            ids.append("P-REDUCE-LONG")
    if kind in {"INPUT", "OUTPUT"}:
        ids.append("P-DTYPE")
        if any(token in lowered for token in ("mask", "pse", "drop", "rope", "atten")):
            ids.append("P-OPTIONAL")
    if kind in {"TILING_FIELD", "TILING_DATA", "FIELD", "VARIABLE"}:
        if any(token in lowered for token in _SPLIT_NAME_HINTS):
            ids.extend(("F-SPLIT", "F-SHAPE-TYPICAL"))
        if "core" in lowered or "block" in lowered:
            ids.append("F-BALANCE")
    if kind in {"BUFFER", "QUEUE"}:
        ids.extend(("F-BUFFER", "F-SHAPE-TYPICAL"))
    if kind == "BRANCH":
        if any(token in lowered for token in ("tail", "empty", "remainder", "align")):
            ids.append("P-TAIL")
        if "tail" in lowered or "unalign" in lowered:
            ids.append("F-SHAPE-TAIL")
    if kind == "KERNEL" and not ids:
        ids.append("P-TAIL")
    if any(token in lowered for token in ("illegal", "invalid", "disable")):
        ids.append("P-ILLEGAL")
    # stable unique
    seen: list[str] = []
    for sid in ids:
        if sid in LEGAL_IDS and sid not in seen:
            seen.append(sid)
    return tuple(seen)


def scenarios_for_anchors(anchors: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    seen: list[str] = []
    for anchor in anchors:
        for sid in scenarios_for_anchor(anchor):
            if sid not in seen:
                seen.append(sid)
    return tuple(seen)
