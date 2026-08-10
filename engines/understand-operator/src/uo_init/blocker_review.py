# -*- coding: utf-8 -*-
"""Static review of unresolved UO blockers.

This review is intentionally conservative. It labels why a blocker is hard to
model so TG can route work, but it never patches derivations and never proves a
tiling key unreachable.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


_LOOP = re.compile(r"\b(for|while)\s*\(|\bdo\s*\{")
_TEMPLATE = re.compile(r"\b(template|constexpr|decltype|std::|lambda|operator<)\b")
_CALL = re.compile(r"\b(call|callee|helper|function|return value)\b")


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _source_root(ops_root: str | Path | None, project_root: str | Path | None) -> Path | None:
    for raw in (project_root, ops_root):
        if raw:
            root = Path(raw).expanduser().resolve()
            if root.exists():
                return root
    return None


def _read_context(file_name: str, line: int, *, root: Path | None) -> str:
    if not file_name or root is None:
        return ""
    path = Path(file_name)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    idx = max(0, int(line or 1) - 1)
    lo = max(0, idx - 8)
    hi = min(len(lines), idx + 9)
    return "\n".join(lines[lo:hi])


def _evidence_context(blocker: dict[str, Any], *, root: Path | None) -> str:
    chunks: list[str] = []
    for ev in blocker.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        chunks.append(str(ev.get("snippet") or ev.get("text") or ""))
        chunks.append(_read_context(str(ev.get("file") or ""), int(ev.get("line") or 0), root=root))
    return "\n".join(x for x in chunks if x)


def classify_blocker(blocker: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    bid = str(blocker.get("id") or blocker.get("blocker_id") or "")
    reason_code = str(blocker.get("reason_code") or "")
    text = "\n".join(
        str(blocker.get(k) or "")
        for k in ("reason", "text", "snippet", "readable_vars", "affected_nodes")
    )
    context = _evidence_context(blocker, root=root)
    haystack = f"{reason_code}\n{text}\n{context}"
    lower = haystack.lower()

    if "loop" in lower or _LOOP.search(haystack):
        cls = "loop_or_data_dependent"
        action = "source_lemma_or_series_evidence"
    elif (
        "unmapped" in lower
        or "unsupported" in lower
        or "normalize" in lower
        or "unwritten" in lower
        or "initial_value" in lower
    ):
        cls = "static_script_gap_candidate"
        action = "inspect_static_resolver_before_mining_lemma"
    elif _TEMPLATE.search(haystack):
        cls = "template_or_parser_gap"
        action = "improve_static_parser_or_add_source_lemma"
    elif _CALL.search(haystack):
        cls = "cross_function_or_helper"
        action = "trace_helper_then_source_lemma"
    else:
        cls = "source_lemma_required"
        action = "read_source_and_mine_bounded_lemma"

    return {
        "blocker_id": bid,
        "classification": cls,
        "reason_code": reason_code,
        "affected_nodes": len(blocker.get("affected_nodes") or []),
        "evidence_count": len(blocker.get("evidence") or []),
        "recommended_action": action,
        "has_source_context": bool(context),
    }


def build_review(
    unresolved: dict[str, Any],
    *,
    ops_root: str | Path | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = _source_root(ops_root, project_root)
    rows = [
        classify_blocker(row, root=root)
        for row in (unresolved.get("blockers") or [])
        if isinstance(row, dict)
    ]
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("classification") or "")
        counts[key] = counts.get(key, 0) + 1
    rows.sort(
        key=lambda r: (
            str(r.get("classification") or ""),
            -int(r.get("affected_nodes") or 0),
            str(r.get("blocker_id") or ""),
        )
    )
    return {
        "schema": "uo-static-blocker-review/v1",
        "status": "observation_only",
        "reviewer": "codex_static_blocker_classifier",
        "blocker_count": len(rows),
        "classification_counts": counts,
        "blockers": rows,
        "note": (
            "Routing aid only. A blocker still needs source proof before UO "
            "derivation changes or TG exclusion rules."
        ),
    }


def write_review(
    uo_root: str | Path,
    *,
    ops_root: str | Path | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    uo = Path(uo_root)
    unresolved = _load(uo / "ir" / "unresolved.yaml")
    doc = build_review(unresolved, ops_root=ops_root, project_root=project_root)
    path = uo / "review" / "static_blockers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "path": str(path), "blocker_count": doc["blocker_count"]}
