# -*- coding: utf-8 -*-
"""Expand impact anchors across deterministic risk classes."""

from __future__ import annotations

from typing import Any

from code_engineering.risk.rules import RISK_RULES


def expand_obligations(
    impact: dict[str, Any] | Any,
    risk_classes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return one obligation for each anchor/risk-class pair."""
    if isinstance(impact, dict):
        anchors = impact.get("anchors")
        if anchors is None:
            anchors = list(impact.get("hit_writers") or []) + list(
                impact.get("hit_predicates") or []
            )
    else:
        anchors = getattr(impact, "anchors", None)
        if anchors is None:
            anchors = list(getattr(impact, "hit_writers", []) or []) + list(
                getattr(impact, "hit_predicates", []) or []
            )
    normalized = [anchor for anchor in (anchors or []) if isinstance(anchor, dict)]
    selected = set(risk_classes or RISK_RULES)
    return [
        obligation
        for anchor in normalized
        for name, rule in RISK_RULES.items()
        if name in selected
        for obligation in rule([anchor])
    ]
