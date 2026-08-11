# -*- coding: utf-8 -*-
"""Lemma field pins for branch-outcome evaluation.

A proved rule claims: under keys matching ``when``, field ``F`` can only hold
``value``. Evaluating a branch against an Env with that pin makes the condition
``key_determined`` when it only reads pinned fields and key dims — so the
opposite outcome enters E without inventing a second exclusion language.

Rules come from the same surface TG already uses for key lemmas
(``lemmas/active_rules.yaml`` or a probe ``lemmas.yaml`` + optional usable set).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def flat_leaf(name: str) -> str:
    """Leaf field name: ``preTilingData.flag`` / ``__td__x__flag`` → ``flag``."""
    if name.startswith("__td__"):
        return name[len("__td__"):].rsplit("__", 1)[-1]
    if "." in name:
        return name.rsplit(".", 1)[-1]
    return name


def matches_when(when: dict[str, Any] | None, dims: dict[str, Any]) -> bool:
    return all(str(dims.get(k)) == str(v) for k, v in (when or {}).items())


def load_pinned(
    dims: dict[str, Any],
    *,
    rules_path: str | Path | None = None,
    usable_path: str | Path | None = None,
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fields fixed for a key with these dimensions.

    Only rules whose ``when`` matches are applied. When ``usable_path`` (or a
    sibling ``lemma_check.json`` with ``usable``) is present, only listed rule
    ids are used — the same refutation gate the probe used before believing a pin.
    """
    loaded = list(rules or [])
    if not loaded and rules_path is not None:
        path = Path(rules_path)
        if path.is_file():
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            loaded = list(doc.get("rules") or doc.get("active_rules") or [])
            # active_rules.yaml may be a bare list
            if isinstance(doc, list):
                loaded = list(doc)

    usable: set[str] | None = None
    if usable_path is not None:
        up = Path(usable_path)
        if up.is_file():
            data = json.loads(up.read_text(encoding="utf-8"))
            usable = set(data.get("usable") or [])

    out: dict[str, Any] = {}
    for rule in loaded:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "")
        if usable is not None and rid and rid not in usable:
            continue
        field = str(rule.get("field") or "")
        if not field:
            continue
        if not matches_when(rule.get("when"), dims):
            continue
        value = rule.get("value")
        out[field] = value
        out[flat_leaf(field)] = value
    return out


def refute_pins(
    rules: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Try to refute each rule against decoded field observations.

    Each observation is ``{"dims": {...}, "fields": {...}}``. A rule that
    matches ``when`` but disagrees on ``field`` is refuted.
    """
    tested: dict[str, int] = {}
    refuted: dict[str, list] = {}
    for rule in rules:
        rid = str(rule.get("id") or "")
        fname = str(rule.get("field") or "")
        for obs in observations:
            dims = obs.get("dims") or {}
            fields = obs.get("fields") or {}
            if not matches_when(rule.get("when"), dims):
                continue
            if fname not in fields and flat_leaf(fname) not in fields:
                continue
            tested[rid] = tested.get(rid, 0) + 1
            got = fields.get(fname, fields.get(flat_leaf(fname)))
            want = rule.get("value")
            if not _same(got, want):
                refuted.setdefault(rid, []).append(
                    {"observed": got, "claimed": want, "dims": dict(dims)}
                )
    usable = [
        str(r.get("id")) for r in rules
        if str(r.get("id")) and tested.get(str(r.get("id")), 0) > 0
        and str(r.get("id")) not in refuted
    ]
    return {"tested": tested, "refuted": refuted, "usable": usable}


def _same(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b
