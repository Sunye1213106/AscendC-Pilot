"""Deterministic extract_plan auto-fill: aliases, receiver bindings, tri-state coverage."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from uo.scripts.receiver_binding import (
    binding_candidate_id,
    extract_receiver_bindings_from_text,
    index_bindings_by_receiver,
)

ALIAS_AUTO_ACCEPT_THRESHOLD = 0.85
ALIAS_EVIDENCE_KINDS = frozenset({"tdf_assign", "kernel_tdf_assign"})


def stable_candidate_id(
    *,
    object_type: str,
    identity_key: str = "",
    extraction_unit: str = "",
    file_path: str = "",
    start_line: int = 0,
    source_window_sha256: str = "",
    extra: str = "",
) -> str:
    raw = "|".join(
        [
            str(object_type or ""),
            str(identity_key or ""),
            str(extraction_unit or ""),
            str(file_path or "").replace("\\", "/"),
            str(int(start_line or 0)),
            str(source_window_sha256 or ""),
            str(extra or ""),
        ]
    )
    return "CAND_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def stamp_candidate_ids(candidates: dict[str, Any]) -> dict[str, Any]:
    """Ensure every candidate row has a stable candidate_id."""
    if not isinstance(candidates, dict):
        return candidates

    def _stamp(rows: list[Any], object_type: str) -> None:
        for item in rows:
            if not isinstance(item, dict):
                continue
            if str(item.get("candidate_id") or "").startswith("CAND_"):
                continue
            sw = item.get("source_window") if isinstance(item.get("source_window"), dict) else {}
            identity = str(item.get("identity_key") or "")
            if not identity:
                if object_type == "alias":
                    identity = f"{item.get('local')}|{item.get('tdf_leaf')}|{item.get('tdf_path')}"
                elif object_type == "receiver_binding":
                    identity = f"{item.get('receiver')}|{item.get('nested_field')}"
                else:
                    identity = str(item.get("qualified_name") or item.get("name") or "")
            item["candidate_id"] = stable_candidate_id(
                object_type=object_type,
                identity_key=identity,
                extraction_unit=str(item.get("class_or_namespace") or item.get("extraction_unit") or ""),
                file_path=str(item.get("file_path") or ""),
                start_line=int(item.get("start_line") or 0),
                source_window_sha256=str(sw.get("sha256") or item.get("source_window_sha256") or ""),
            )

    _stamp(list(candidates.get("writer_candidates") or []), "writer")
    _stamp(list(candidates.get("receiver_candidates") or []), "receiver")
    _stamp(list(candidates.get("alias_candidates") or []), "alias")
    _stamp(list(candidates.get("non_sink_root_candidates") or []), "non_sink_root")
    _stamp(list(candidates.get("extra_entry_candidates") or []), "extra_entry")
    _stamp(list(candidates.get("receiver_binding_candidates") or []), "receiver_binding")
    return candidates


def _alias_evidence_kinds(item: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for x in item.get("evidence") or []:
        s = str(x or "").strip()
        if s:
            out.add(s)
    return out


def detect_alias_conflicts(alias_candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """local → list of distinct tdf_leaf mappings (conflicts when >1 leaf)."""
    by_local: dict[str, dict[str, dict[str, Any]]] = {}
    for item in alias_candidates or []:
        if not isinstance(item, dict):
            continue
        local = str(item.get("local") or "").strip()
        leaf = str(item.get("tdf_leaf") or "").strip()
        if not local or not leaf:
            continue
        by_local.setdefault(local, {})
        by_local[local][leaf] = item
    return {k: list(v.values()) for k, v in by_local.items() if len(v) > 1}


def auto_merge_high_confidence_aliases(
    plan: dict[str, Any],
    candidates: dict[str, Any],
    *,
    project_root: Path | None = None,
    threshold: float = ALIAS_AUTO_ACCEPT_THRESHOLD,
) -> dict[str, Any]:
    """Merge high-confidence alias candidates into plan; conflicts → deferred.

    Must run before plan_aliases() dict collapse (which silently overwrites).
    """
    _ = project_root  # reserved for future window verification hooks
    report: dict[str, Any] = {
        "accepted": [],
        "deferred": [],
        "skipped_low_score": 0,
        "skipped_existing": 0,
    }
    plan.setdefault("aliases", [])
    plan.setdefault("accepted_candidates", [])
    plan.setdefault("rejected_candidates", [])
    plan.setdefault("deferred_candidates", [])

    alias_rows = [a for a in (candidates.get("alias_candidates") or []) if isinstance(a, dict)]
    conflicts = detect_alias_conflicts(alias_rows)
    conflict_locals = set(conflicts.keys())

    existing_pairs: set[tuple[str, str]] = set()
    existing_locals: dict[str, str] = {}
    for a in plan.get("aliases") or []:
        if not isinstance(a, dict):
            continue
        local = str(a.get("local") or "").strip()
        leaf = str(a.get("tdf_leaf") or "").strip()
        if local and leaf:
            existing_pairs.add((local, leaf))
            existing_locals[local] = leaf

    deferred_ids = {
        str(x.get("candidate_id") or "")
        for x in (plan.get("deferred_candidates") or [])
        if isinstance(x, dict)
    }
    rejected_ids = {
        str(x.get("candidate_id") or "")
        for x in (plan.get("rejected_candidates") or [])
        if isinstance(x, dict)
    }
    accepted_ids = {
        str(x.get("candidate_id") or "")
        for x in (plan.get("accepted_candidates") or [])
        if isinstance(x, dict)
    }

    for item in alias_rows:
        cid = str(item.get("candidate_id") or "")
        local = str(item.get("local") or "").strip()
        leaf = str(item.get("tdf_leaf") or "").strip()
        score = float(item.get("score") or 0)
        kinds = _alias_evidence_kinds(item)
        if score < float(threshold) or not (kinds & ALIAS_EVIDENCE_KINDS):
            report["skipped_low_score"] += 1
            continue
        if not local or not leaf:
            continue
        if cid and (cid in deferred_ids or cid in rejected_ids or cid in accepted_ids):
            report["skipped_existing"] += 1
            continue
        if local in conflict_locals:
            entry = {
                "candidate_id": cid,
                "reason_code": "conflicting_alias_mapping",
                "conflict_with": [
                    str(x.get("candidate_id") or f"{x.get('local')}:{x.get('tdf_leaf')}")
                    for x in conflicts.get(local) or []
                ],
                "evidence": list(item.get("evidence") or []),
                "local": local,
                "tdf_leaf": leaf,
            }
            plan["deferred_candidates"].append(entry)
            deferred_ids.add(cid)
            report["deferred"].append(cid or f"{local}:{leaf}")
            continue
        if local in existing_locals and existing_locals[local] != leaf:
            entry = {
                "candidate_id": cid,
                "reason_code": "conflicting_alias_mapping",
                "conflict_with": [f"plan:{local}:{existing_locals[local]}"],
                "evidence": list(item.get("evidence") or []),
                "local": local,
                "tdf_leaf": leaf,
            }
            plan["deferred_candidates"].append(entry)
            deferred_ids.add(cid)
            report["deferred"].append(cid or f"{local}:{leaf}")
            continue
        if (local, leaf) in existing_pairs:
            if cid and cid not in accepted_ids:
                plan["accepted_candidates"].append(
                    {"candidate_id": cid, "reason_code": "already_in_plan", "kind": "alias"}
                )
                accepted_ids.add(cid)
            report["skipped_existing"] += 1
            continue
        # Accept
        plan["aliases"].append(
            {
                "local": local,
                "tdf_leaf": leaf,
                "tdf_path": item.get("tdf_path") or leaf,
                "file_path": item.get("file_path"),
                "start_line": item.get("start_line"),
                "candidate_id": cid,
                "score": score,
                "evidence": list(item.get("evidence") or []),
                "decision_reason": "deterministic_auto_accept_alias",
            }
        )
        existing_pairs.add((local, leaf))
        existing_locals[local] = leaf
        if cid:
            plan["accepted_candidates"].append(
                {
                    "candidate_id": cid,
                    "reason_code": "deterministic_auto_accept",
                    "kind": "alias",
                }
            )
            accepted_ids.add(cid)
        report["accepted"].append(cid or f"{local}:{leaf}")
    return report


def merge_receiver_bindings_into_plan(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> dict[str, Any]:
    """Attach receiver_bindings from candidates (or empty) onto plan."""
    report = {"merged": 0, "from_candidates": 0}
    plan.setdefault("receiver_bindings", [])
    existing = index_bindings_by_receiver(
        [b for b in (plan.get("receiver_bindings") or []) if isinstance(b, dict)]
    )
    rows = [
        b
        for b in (candidates.get("receiver_binding_candidates") or [])
        if isinstance(b, dict)
    ]
    report["from_candidates"] = len(rows)
    for b in rows:
        recv = str(b.get("receiver") or "").strip()
        if not recv:
            continue
        if recv not in existing:
            if not b.get("candidate_id"):
                b = dict(b)
                b["candidate_id"] = binding_candidate_id(b)
            plan["receiver_bindings"].append(b)
            existing[recv] = b
            report["merged"] += 1
            cid = str(b.get("candidate_id") or "")
            if cid:
                plan.setdefault("accepted_candidates", []).append(
                    {
                        "candidate_id": cid,
                        "reason_code": "deterministic_receiver_binding",
                        "kind": "receiver_binding",
                    }
                )
    return report


def required_high_confidence_candidate_ids(
    candidates: dict[str, Any],
    *,
    alias_threshold: float = ALIAS_AUTO_ACCEPT_THRESHOLD,
) -> list[str]:
    """Candidate IDs that must appear in accepted ∪ rejected ∪ deferred."""
    required: list[str] = []
    for item in candidates.get("alias_candidates") or []:
        if not isinstance(item, dict):
            continue
        score = float(item.get("score") or 0)
        kinds = _alias_evidence_kinds(item)
        if score >= alias_threshold and (kinds & ALIAS_EVIDENCE_KINDS):
            cid = str(item.get("candidate_id") or "")
            if cid:
                required.append(cid)
    for item in candidates.get("receiver_binding_candidates") or []:
        if not isinstance(item, dict):
            continue
        if float(item.get("score") or 0) >= 0.85:
            cid = str(item.get("candidate_id") or "")
            if cid:
                required.append(cid)
    # Preserve order, unique
    seen: set[str] = set()
    out: list[str] = []
    for cid in required:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def validate_tri_state_coverage(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> list[str]:
    """Gate: required high-confidence IDs ⊆ accepted ∪ rejected ∪ deferred."""
    required = set(required_high_confidence_candidate_ids(candidates))
    if not required:
        return []

    def _ids(key: str) -> set[str]:
        out: set[str] = set()
        for row in plan.get(key) or []:
            if isinstance(row, dict):
                cid = str(row.get("candidate_id") or "").strip()
                if cid:
                    out.add(cid)
            elif isinstance(row, str) and row.startswith("CAND_"):
                out.add(row)
        return out

    covered = (
        _ids("accepted_candidates")
        | _ids("rejected_candidates")
        | _ids("deferred_candidates")
    )
    # Also treat aliases / receiver_bindings with candidate_id as accepted coverage.
    for a in plan.get("aliases") or []:
        if isinstance(a, dict) and a.get("candidate_id"):
            covered.add(str(a["candidate_id"]))
    for b in plan.get("receiver_bindings") or []:
        if isinstance(b, dict) and b.get("candidate_id"):
            covered.add(str(b["candidate_id"]))

    missing = sorted(required - covered)
    errors: list[str] = []
    for cid in missing:
        errors.append(
            f"TRI_STATE_COVERAGE: high-confidence candidate {cid} must be "
            f"accepted, rejected, or deferred"
        )
    return errors


def collect_bindings_from_source_files(
    file_texts: dict[str, str],
    *,
    class_or_namespace: str = "",
) -> list[dict[str, Any]]:
    """file_path → text → binding candidates."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fp, text in (file_texts or {}).items():
        for b in extract_receiver_bindings_from_text(
            text,
            file_path=fp,
            class_or_namespace=class_or_namespace,
        ):
            cid = binding_candidate_id(b)
            b["candidate_id"] = cid
            if cid in seen:
                continue
            seen.add(cid)
            out.append(b)
    return out


__all__ = [
    "ALIAS_AUTO_ACCEPT_THRESHOLD",
    "ALIAS_EVIDENCE_KINDS",
    "auto_merge_high_confidence_aliases",
    "collect_bindings_from_source_files",
    "detect_alias_conflicts",
    "merge_receiver_bindings_into_plan",
    "required_high_confidence_candidate_ids",
    "stable_candidate_id",
    "stamp_candidate_ids",
    "validate_tri_state_coverage",
]
