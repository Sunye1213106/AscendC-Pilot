# -*- coding: utf-8 -*-
"""Seven deterministic risk classes and their verification obligations."""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from code_engineering.evidence_tier import Tier, path_tier

_REQUIREMENTS = {
    "contract": "prove API, layout, and input/output contract compatibility",
    "dispatch": "exercise every affected dispatch and tiling-key branch",
    "coverage": "provide a witness for every affected reachable path",
    "shape": "verify boundary, rank, dtype, and format shape behavior",
    "sync": "prove synchronization ordering and memory-scope safety",
    "precision": "compare numerical output against declared tolerances",
    "perf": "show no unacceptable latency or resource regression",
}
_VERDICTS = {
    "contract": "static", "dispatch": "runtime", "coverage": "runtime",
    "shape": "runtime", "sync": "runtime", "precision": "external",
    "perf": "external",
}


def _bounded_verdict(risk_class: str, tier: Tier) -> str:
    """Cap the strongest verdict by the weakest evidence on the anchor path."""
    if tier == "C":
        return "open_only"
    if tier == "B":
        return "review_only"
    return _VERDICTS[risk_class]


def _spans(anchor: dict[str, Any]) -> list[dict[str, Any]]:
    spans = anchor.get("source_spans")
    if isinstance(spans, list):
        return [value for value in spans if isinstance(value, dict)]
    if anchor.get("file"):
        return [{
            "file": anchor.get("file"),
            "start": int(anchor.get("line_start") or 0),
            "end": int(anchor.get("line_end") or anchor.get("line_start") or 0),
        }]
    return []


def _rule(risk_class: str, anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not anchors:
        return []
    anchor_ids = sorted(str(a.get("id") or a.get("name") or "") for a in anchors)
    tiers: list[Tier] = [
        str(a.get("evidence_tier") or "C")  # type: ignore[list-item]
        for a in anchors
        if str(a.get("evidence_tier") or "C") in {"A", "B", "C"}
    ]
    tier = path_tier(tiers)
    digest = hashlib.sha256(
        (risk_class + "\0" + "\0".join(anchor_ids)).encode("utf-8")
    ).hexdigest()[:16]
    return [{
        "id": f"ce-{risk_class}-{digest}",
        "risk_class": risk_class,
        "anchors": anchor_ids,
        "evidence_tier": tier,
        "max_verdict": _bounded_verdict(risk_class, tier),
        "exclusion_eligible": tier == "A",
        "closure_requirement": _REQUIREMENTS[risk_class],
        "source_spans": [
            span for anchor in anchors for span in _spans(anchor)
        ],
    }]


def contract(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate interface and data-layout obligations."""
    return _rule("contract", anchors)


def dispatch(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate host/kernel dispatch obligations."""
    return _rule("dispatch", anchors)


def coverage(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate reachable-path coverage obligations."""
    return _rule("coverage", anchors)


def shape(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate shape and format obligations."""
    return _rule("shape", anchors)


def sync(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate synchronization obligations."""
    return _rule("sync", anchors)


def precision(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate numerical precision obligations."""
    return _rule("precision", anchors)


def perf(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate performance obligations."""
    return _rule("perf", anchors)


RISK_RULES: dict[str, Callable[[list[dict[str, Any]]], list[dict[str, Any]]]] = {
    "contract": contract,
    "dispatch": dispatch,
    "coverage": coverage,
    "shape": shape,
    "sync": sync,
    "precision": precision,
    "perf": perf,
}


_KIND_RISKS: dict[str, tuple[str, ...]] = {
    "TILING_KEY": ("dispatch",),
    "TEMPLATE": ("dispatch",),
    "PREDICATE": ("dispatch",),
    "BRANCH": ("coverage",),
    "KERNEL": ("coverage",),
    "TILING_FIELD": ("contract", "shape"),
    "TILING_DATA": ("contract", "shape"),
    "BUFFER": ("sync", "perf"),
    "REGISTER": ("sync",),
    "QUEUE": ("sync",),
    "PIPE": ("sync",),
    "EVENT": ("sync",),
    "INPUT": ("contract",),
    "OUTPUT": ("contract",),
}
_SYNC_OPS = {
    "AllocTensor", "FreeTensor", "EnQue", "DeQue",
    "SetFlag", "WaitFlag", "CrossCoreSetFlag", "CrossCoreWaitFlag",
    "PipeBarrier", "InitBuffer",
}
_PRECISION_OPS = {"Cast", "DataCopy", "DataCopyPad"}


def _classes_for_anchor(anchor: dict[str, Any]) -> tuple[str, ...]:
    kind = str(anchor.get("kind") or "").upper()
    facts = anchor.get("facts") if isinstance(anchor.get("facts"), dict) else {}
    name = str(facts.get("callee") or anchor.get("name") or "")
    if kind == "OPERATION":
        out: list[str] = []
        if name in _SYNC_OPS:
            out.append("sync")
        if name in _PRECISION_OPS:
            out.append("precision")
        return tuple(out) or ("coverage",)
    return _KIND_RISKS.get(kind, ())


def evaluate_risks(
    anchors: list[dict[str, Any]], risk_classes: list[str] | None = None
) -> list[dict[str, Any]]:
    """Evaluate selected risks per anchor so a weak peer cannot cap others.

    Kind routing still applies: BUFFER only yields sync/perf, not dispatch.
    Unknown kinds stay unattached unless the caller **explicitly** passes
    ``risk_classes``. That opt-in is not a silent default.
    """
    selected = set(risk_classes or RISK_RULES)
    explicit = risk_classes is not None
    rows: list[dict[str, Any]] = []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        classes = _classes_for_anchor(anchor)
        if not classes and explicit:
            classes = tuple(name for name in RISK_RULES if name in selected)
        for name, rule in RISK_RULES.items():
            if name in selected and name in classes:
                rows.extend(rule([anchor]))
    return rows
