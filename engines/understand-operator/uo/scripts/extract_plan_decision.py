"""Extract-plan decision worklist / decision_report / slim IR.

Separates run-scoped audit artifacts from compact canonical extract_plan.yaml.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from uo.scripts.extract_plan_autofill import (
    ALIAS_AUTO_ACCEPT_THRESHOLD,
    ALIAS_EVIDENCE_KINDS,
    stamp_candidate_ids,
)
from uo.scripts.extract_plan_io import HELPER_WRITER_NAMES, PROMOTED_WRITER_ROLES
from uo.scripts.role_evidence import validate_role_evidence

CANDIDATE_KINDS = frozenset(
    {
        "function_writer",
        "receiver_sink",
        "receiver_binding",
        "macro_binding",
        "key_dimension_source",
        "helper",
        "duplicate",
        "alias",
        "extra_entry",
        "non_sink_root",
    }
)

ALLOWED_DECISIONS = frozenset({"accept", "reject", "defer"})

# Audit-only fields stripped from canonical writers/receivers/aliases.
AUDIT_ITEM_KEYS = frozenset(
    {
        "evidence_snippet",
        "decision_reason",
        "score",
        "source_window",
        "evidence",
        "duplicate_of",
        "duplicate_explanation",
    }
)

# Top-level keys that belong in run decision_report, not canonical IR.
AUDIT_PLAN_KEYS = frozenset(
    {
        "rejected_candidates",
        "deferred_candidates",
        "accepted_candidates",
        "decision_report_ref",
    }
)

_COMMON_ASSIGN_NAME_RE = re.compile(r"(?:^|_)TILING_DATA_COMMON_ASSIGN$|COMMON_ASSIGN$")
_INIT_TILING_RE = re.compile(r"^InitTilingData$", re.IGNORECASE)

DECISION_REPORT_VERSION = 1
WORKLIST_VERSION = 1
SLIM_PLAN_VERSION = 2


def classify_candidate_kind(
    item: dict[str, Any],
    *,
    section: str = "",
    sibling_names: set[str] | None = None,
) -> str:
    """Assign semantic candidate_kind. Never treat macro/binding as 'not a function'."""
    if section == "alias_candidates":
        return "alias"
    if section == "receiver_binding_candidates":
        return "receiver_binding"
    if section == "non_sink_root_candidates":
        return "non_sink_root"
    if section == "extra_entry_candidates":
        return "extra_entry"
    if section == "receiver_candidates":
        return "receiver_sink"

    name = str(item.get("name") or "").strip()
    qn = str(item.get("qualified_name") or "").strip()
    role_sug = str(item.get("role_suggested") or "").strip()
    name_cf = name.casefold()

    if _COMMON_ASSIGN_NAME_RE.search(name) or "COMMON_ASSIGN" in name.upper():
        return "macro_binding"
    if _INIT_TILING_RE.match(name):
        return "receiver_binding"
    if role_sug == "key_dimension_source":
        return "key_dimension_source"
    if name_cf in HELPER_WRITER_NAMES or role_sug in {"ignore", "provenance_helper"}:
        if role_sug == "provenance_helper":
            return "helper"
        if name_cf in HELPER_WRITER_NAMES or role_sug == "ignore":
            return "helper"
    # Overlapping window / same start_line different name → likely duplicate label.
    if sibling_names and name and name in sibling_names:
        return "duplicate"
    if section == "writer_candidates":
        return "function_writer"
    return "function_writer"


def _alias_kinds(item: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for x in item.get("evidence") or []:
        s = str(x or "").strip()
        if s:
            out.add(s)
    return out


def _source_nav(item: dict[str, Any]) -> dict[str, Any]:
    sw = item.get("source_window") if isinstance(item.get("source_window"), dict) else {}
    text = str(sw.get("text") or "")
    sha = str(sw.get("sha256") or item.get("source_window_sha256") or "").strip()
    start = int(item.get("start_line") or sw.get("start_line") or 0)
    end = int(item.get("end_line") or sw.get("end_line") or 0)
    snippet = text[:800] if text else ""
    return {
        "file": str(item.get("file_path") or "").replace("\\", "/"),
        "start_line": start or None,
        "end_line": end or None,
        "window_sha256": sha or None,
        "snippet": snippet,
    }


def _roles_for_kind(kind: str, item: dict[str, Any]) -> list[str]:
    sug = str(item.get("role_suggested") or "").strip()
    if kind == "macro_binding":
        return [sug] if sug else ["tiling_writer"]
    if kind == "receiver_binding":
        return ["receiver_binding"]
    if kind == "receiver_sink":
        return ["tiling_sink"] if item.get("is_tiling_sink_suggested") else ["receiver"]
    if kind == "key_dimension_source":
        return ["key_dimension_source"]
    if kind == "helper":
        return ["ignore"]
    if kind == "alias":
        return ["alias"]
    if sug:
        return [sug]
    return ["tiling_writer"]


def _required_decision(item: dict[str, Any], kind: str, *, section: str) -> bool:
    score = float(item.get("score") or 0)
    if kind == "alias":
        kinds = _alias_kinds(item)
        return score >= ALIAS_AUTO_ACCEPT_THRESHOLD and bool(kinds & ALIAS_EVIDENCE_KINDS)
    if kind == "receiver_binding":
        return score >= 0.85
    if kind == "macro_binding":
        return score >= 0.7
    if kind in {"helper", "duplicate", "non_sink_root"}:
        return False
    if section == "writer_candidates":
        role = str(item.get("role_suggested") or "").strip()
        if role in PROMOTED_WRITER_ROLES or role == "key_dimension_source":
            return True
        return score >= 0.85
    if section == "receiver_candidates":
        return bool(item.get("is_tiling_sink_suggested")) and score >= 0.7
    return score >= 0.9


def build_decision_worklist(
    candidates: dict[str, Any],
    *,
    architecture: str = "",
    entrypoint_units: set[str] | None = None,
) -> dict[str, Any]:
    """Deterministic prepare artifact for producer decisions."""
    if isinstance(candidates, dict):
        stamp_candidate_ids(candidates)

    arch = str(architecture or candidates.get("architecture") or "").strip()
    units = {u.casefold() for u in (entrypoint_units or set()) if u}
    work_items: list[dict[str, Any]] = []

    section_map = [
        ("writer_candidates", "writer"),
        ("receiver_candidates", "receiver"),
        ("alias_candidates", "alias"),
        ("receiver_binding_candidates", "receiver_binding"),
        ("extra_entry_candidates", "extra_entry"),
        ("non_sink_root_candidates", "non_sink_root"),
    ]

    # Precompute overlapping writer windows for duplicate hints.
    writers = [c for c in (candidates.get("writer_candidates") or []) if isinstance(c, dict)]
    window_owners: dict[tuple[str, int], list[str]] = {}
    for w in writers:
        fp = str(w.get("file_path") or "").replace("\\", "/")
        start = int(w.get("start_line") or 0)
        name = str(w.get("name") or "").strip()
        if fp and start and name:
            window_owners.setdefault((fp, start), []).append(name)

    for section, _ot in section_map:
        rows = [r for r in (candidates.get(section) or []) if isinstance(r, dict)]
        for item in rows:
            cid = str(item.get("candidate_id") or "").strip()
            if not cid:
                continue
            siblings: set[str] = set()
            if section == "writer_candidates":
                fp = str(item.get("file_path") or "").replace("\\", "/")
                start = int(item.get("start_line") or 0)
                names = window_owners.get((fp, start)) or []
                self_name = str(item.get("name") or "").strip()
                siblings = {n for n in names if n != self_name}
            kind = classify_candidate_kind(item, section=section, sibling_names=siblings or None)
            item["candidate_kind"] = kind
            eu = str(
                item.get("extraction_unit")
                or item.get("class_or_namespace")
                or ""
            ).strip()
            reachable = True
            if units and eu:
                reachable = eu.casefold() in units
            elif units and arch:
                # Path heuristic fallback: arch folder must match when units empty for path.
                fp = str(item.get("file_path") or "").replace("\\", "/").casefold()
                if arch.casefold() == "arch35" and "/arch35/" not in fp and "arch35" in fp:
                    reachable = True
            nav = _source_nav(item)
            req = _required_decision(item, kind, section=section)
            work_items.append(
                {
                    "candidate_id": cid,
                    "candidate_kind": [kind],
                    "name": str(item.get("name") or item.get("local") or item.get("receiver") or ""),
                    "qualified_name": str(item.get("qualified_name") or ""),
                    "architecture": arch or None,
                    "extraction_unit": eu or None,
                    "template_family": str(item.get("template_family") or "") or None,
                    "path_family": str(item.get("path_family") or "") or None,
                    "role_candidates": _roles_for_kind(kind, item),
                    "score": item.get("score"),
                    "source": {
                        "file": nav["file"],
                        "start_line": nav["start_line"],
                        "end_line": nav["end_line"],
                        "window_sha256": nav["window_sha256"],
                    },
                    "evidence": {"snippet": nav["snippet"]},
                    "reachable": reachable,
                    "required_decision": req,
                    "allowed_decisions": sorted(ALLOWED_DECISIONS),
                    "section": section,
                }
            )

    return {
        "version": WORKLIST_VERSION,
        "architecture": arch,
        "counts": {
            "work_items": len(work_items),
            "required": sum(1 for w in work_items if w.get("required_decision")),
            "by_kind": _count_by(work_items, "candidate_kind"),
        },
        "work_items": work_items,
    }


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        val = it.get(key)
        if isinstance(val, list):
            for v in val:
                k = str(v or "?")
                out[k] = out.get(k, 0) + 1
        else:
            k = str(val or "?")
            out[k] = out.get(k, 0) + 1
    return out


def index_candidates_by_id(candidates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stamp_candidate_ids(candidates)
    out: dict[str, dict[str, Any]] = {}
    for section in (
        "writer_candidates",
        "receiver_candidates",
        "alias_candidates",
        "receiver_binding_candidates",
        "extra_entry_candidates",
        "non_sink_root_candidates",
    ):
        for item in candidates.get(section) or []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("candidate_id") or "").strip()
            if cid:
                row = dict(item)
                row["_section"] = section
                out[cid] = row
    return out


def validate_decision_report_schema(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["decision_report must be a mapping"]
    if int(report.get("version") or 0) not in {1, DECISION_REPORT_VERSION}:
        errors.append("decision_report.version must be 1")
    for key in ("accepted", "rejected", "deferred"):
        if key in report and not isinstance(report.get(key), list):
            errors.append(f"decision_report.{key} must be a list")
    for row in report.get("accepted") or []:
        if not isinstance(row, dict):
            errors.append("accepted entry must be mapping")
            continue
        if not str(row.get("candidate_id") or "").strip():
            errors.append("accepted entry missing candidate_id")
    for key in ("rejected", "deferred"):
        for row in report.get(key) or []:
            if not isinstance(row, dict):
                errors.append(f"{key} entry must be mapping")
                continue
            if not str(row.get("candidate_id") or "").strip():
                errors.append(f"{key} entry missing candidate_id")
    return errors


def validate_decision_coverage(
    report: dict[str, Any],
    worklist: dict[str, Any],
) -> list[str]:
    """All required_decision work items must be in accepted ∪ rejected ∪ deferred (exclusive)."""
    errors: list[str] = []
    required = {
        str(w.get("candidate_id") or "")
        for w in (worklist.get("work_items") or [])
        if isinstance(w, dict) and w.get("required_decision") and w.get("candidate_id")
    }
    if not required:
        return errors

    def _collect(key: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in report.get(key) or []:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("candidate_id") or "").strip()
            if not cid:
                errors.append(f"{key} has empty candidate_id")
                continue
            if cid in out:
                errors.append(f"duplicate candidate_id in {key}: {cid}")
            out[cid] = row
        return out

    accepted = _collect("accepted")
    rejected = _collect("rejected")
    deferred = _collect("deferred")

    # Also count receiver_binding_confirmations as accepted coverage.
    for row in report.get("receiver_binding_confirmations") or []:
        if isinstance(row, dict) and row.get("candidate_id"):
            accepted.setdefault(str(row["candidate_id"]), row)

    overlap_ar = set(accepted) & set(rejected)
    overlap_ad = set(accepted) & set(deferred)
    overlap_rd = set(rejected) & set(deferred)
    for cid in sorted(overlap_ar | overlap_ad | overlap_rd):
        errors.append(f"DECISION_COVERAGE: candidate {cid} appears in multiple buckets")

    covered = set(accepted) | set(rejected) | set(deferred)
    for cid in sorted(required - covered):
        errors.append(
            f"DECISION_COVERAGE: required candidate {cid} missing from "
            f"accepted/rejected/deferred"
        )
    return errors


def validate_candidate_architecture(
    report: dict[str, Any],
    worklist: dict[str, Any],
) -> list[str]:
    """Accepted items must be reachable per worklist (entrypoint_graph), not filename guess."""
    errors: list[str] = []
    by_id = {
        str(w.get("candidate_id") or ""): w
        for w in (worklist.get("work_items") or [])
        if isinstance(w, dict) and w.get("candidate_id")
    }
    for row in report.get("accepted") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("candidate_id") or "").strip()
        wi = by_id.get(cid)
        if not wi:
            continue
        if wi.get("reachable") is False:
            errors.append(
                f"ARCHITECTURE: candidate {cid} is not reachable from entrypoint_graph "
                f"— must defer, not accept"
            )
    return errors


def _binding_ref(binding: dict[str, Any], idx: int) -> str:
    existing = str(binding.get("binding_ref") or "").strip()
    if existing.startswith("RB_"):
        return existing
    return f"RB_{idx:03d}"


def materialize_plan_from_decision_report(
    report: dict[str, Any],
    candidates: dict[str, Any],
    *,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expand decision_report into a validate-ready extract_plan (pre-slim)."""
    by_id = index_candidates_by_id(candidates)
    plan: dict[str, Any] = {
        "version": 1,
        "writers": [],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
        "derived_roots": [],
        "extra_host_entries": [],
        "receiver_bindings": [],
        "accepted_candidates": [],
        "rejected_candidates": [],
        "deferred_candidates": [],
    }
    if identity:
        for k in ("actor_id", "run_id", "workflow_id", "candidates_sha256", "architecture"):
            if identity.get(k) is not None:
                plan[k] = identity[k]
    for k in ("actor_id", "run_id", "workflow_id", "candidates_sha256", "architecture"):
        if report.get(k) is not None and k not in plan:
            plan[k] = report[k]

    for row in report.get("accepted") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("candidate_id") or "").strip()
        cand = by_id.get(cid)
        if not cand:
            plan["accepted_candidates"].append({"candidate_id": cid, "reason_code": "unknown_candidate"})
            continue
        section = str(cand.get("_section") or "")
        role = str(row.get("role") or cand.get("role_suggested") or "").strip()
        kind = str(cand.get("candidate_kind") or classify_candidate_kind(cand, section=section))
        plan["accepted_candidates"].append(
            {"candidate_id": cid, "role": role, "kind": kind}
        )
        if section == "writer_candidates" or kind in {
            "function_writer",
            "macro_binding",
            "key_dimension_source",
            "helper",
        }:
            item = _writer_from_candidate(cand, role=role or "tiling_writer", kind=kind)
            plan["writers"].append(item)
        elif section == "receiver_candidates" or kind == "receiver_sink":
            item = _receiver_from_candidate(cand)
            plan["receivers"].append(item)
        elif section == "alias_candidates" or kind == "alias":
            plan["aliases"].append(
                {
                    "local": cand.get("local"),
                    "tdf_leaf": cand.get("tdf_leaf"),
                    "tdf_path": cand.get("tdf_path") or cand.get("tdf_leaf"),
                    "candidate_id": cid,
                    "file_path": cand.get("file_path"),
                    "start_line": cand.get("start_line"),
                }
            )
        elif section == "receiver_binding_candidates" or kind == "receiver_binding":
            b = dict(cand)
            b.pop("_section", None)
            plan["receiver_bindings"].append(b)

    # Binding confirmations
    for idx, row in enumerate(report.get("receiver_binding_confirmations") or [], start=1):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("candidate_id") or "").strip()
        cand = by_id.get(cid)
        if not cand:
            continue
        b = dict(cand)
        b.pop("_section", None)
        bref = str(row.get("binding_ref") or "").strip() or _binding_ref(b, idx)
        b["binding_ref"] = bref
        plan["receiver_bindings"].append(b)

    for row in report.get("rejected") or []:
        if isinstance(row, dict) and row.get("candidate_id"):
            plan["rejected_candidates"].append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "reason_code": row.get("reason_code") or row.get("reason") or "rejected",
                }
            )
    for row in report.get("deferred") or []:
        if isinstance(row, dict) and row.get("candidate_id"):
            plan["deferred_candidates"].append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "reason_code": row.get("reason_code") or row.get("reason") or "deferred",
                }
            )
    return plan


def _writer_from_candidate(cand: dict[str, Any], *, role: str, kind: str) -> dict[str, Any]:
    sw = cand.get("source_window") if isinstance(cand.get("source_window"), dict) else {}
    text = str(sw.get("text") or "")
    start = int(cand.get("start_line") or sw.get("start_line") or 0)
    end = int(cand.get("end_line") or sw.get("end_line") or start)
    fp = str(cand.get("file_path") or "").replace("\\", "/")
    item: dict[str, Any] = {
        "name": cand.get("name"),
        "qualified_name": cand.get("qualified_name"),
        "file_path": fp,
        "start_line": start,
        "role": role,
        "candidate_id": cand.get("candidate_id"),
        "candidate_kind": kind,
        "evidence_source": "source" if text else "candidate_only",
        "source_verified": bool(text),
        "evidence_files": [fp] if fp else [],
        "evidence_lines": [f"{start}-{end}"] if start else [],
        "evidence_snippet": text[:12000] if text else "",
        "evidence_window_sha256": str(sw.get("sha256") or ""),
        "decision_reason": f"decision_report accept as {role} ({kind})",
    }
    return item


def _receiver_from_candidate(cand: dict[str, Any]) -> dict[str, Any]:
    sw = cand.get("source_window") if isinstance(cand.get("source_window"), dict) else {}
    text = str(sw.get("text") or "")
    start = int(cand.get("start_line") or sw.get("start_line") or 0)
    end = int(cand.get("end_line") or sw.get("end_line") or start)
    fp = str(cand.get("file_path") or "").replace("\\", "/")
    return {
        "name": cand.get("name") or cand.get("receiver"),
        "file_path": fp,
        "start_line": start,
        "is_tiling_sink": bool(cand.get("is_tiling_sink_suggested", True)),
        "candidate_id": cand.get("candidate_id"),
        "candidate_kind": "receiver_sink",
        "evidence_source": "source" if text else "candidate_only",
        "source_verified": bool(text) or bool(cand.get("is_tiling_sink_suggested")),
        "evidence_files": [fp] if fp else [],
        "evidence_lines": [f"{start}-{end}"] if start else [],
        "evidence_snippet": text[:12000] if text else "",
        "evidence_window_sha256": str(sw.get("sha256") or ""),
        "decision_reason": "decision_report accept receiver",
    }


def is_decision_report(doc: dict[str, Any]) -> bool:
    if not isinstance(doc, dict):
        return False
    if "accepted" in doc or "receiver_binding_confirmations" in doc:
        # Distinguish from full plan which has writers list.
        if "writers" in doc and isinstance(doc.get("writers"), list) and doc.get("writers"):
            # Hybrid / legacy full plan
            return False
        return True
    return False


def validate_role_evidence_for_plan(
    plan: dict[str, Any],
    candidates: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Sufficiency gate for accepted writers/receivers/bindings."""
    _ = project_root
    errors: list[str] = []
    by_id = index_candidates_by_id(candidates)
    for item in plan.get("writers") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role in {"ignore"}:
            continue
        if role not in PROMOTED_WRITER_ROLES and role != "key_dimension_source":
            continue
        cid = str(item.get("candidate_id") or "").strip()
        cand = by_id.get(cid)
        kind = str(item.get("candidate_kind") or (cand or {}).get("candidate_kind") or "")
        result = validate_role_evidence(item, role=role, candidate=cand, candidate_kind=kind)
        if not result.get("sufficient"):
            errors.append(
                f"ROLE_EVIDENCE: writer {item.get('name') or cid} "
                f"{result.get('reason_code') or 'insufficient'}"
            )
    for item in plan.get("receivers") or []:
        if not isinstance(item, dict) or not item.get("is_tiling_sink"):
            continue
        cid = str(item.get("candidate_id") or "").strip()
        cand = by_id.get(cid)
        # Receivers often lack own windows; skip soft if no text and no candidate window.
        text_ok = bool(str(item.get("evidence_snippet") or "").strip())
        if not text_ok and cand:
            sw = cand.get("source_window") if isinstance(cand.get("source_window"), dict) else {}
            text_ok = bool(sw.get("text"))
        if not text_ok:
            # Sink receivers may be derived from writer context — do not hard-fail empty.
            continue
        result = validate_role_evidence(
            item, role="tiling_writer", candidate=cand, candidate_kind="receiver_sink"
        )
        if not result.get("sufficient"):
            errors.append(
                f"ROLE_EVIDENCE: receiver {item.get('name') or cid} "
                f"{result.get('reason_code') or 'insufficient'}"
            )
    return errors


def slim_extract_plan(
    plan: dict[str, Any],
    *,
    aliases_rel: str = "extract_plan_aliases.yaml",
    bindings_rel: str = "receiver_bindings.yaml",
    aliases_sha: str = "",
    bindings_sha: str = "",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (slim_plan, aliases_sidecar, bindings_sidecar)."""
    aliases_doc = {
        "version": 1,
        "aliases": {},
    }
    for a in plan.get("aliases") or []:
        if not isinstance(a, dict):
            continue
        local = str(a.get("local") or "").strip()
        leaf = str(a.get("tdf_leaf") or "").strip()
        if local and leaf:
            aliases_doc["aliases"][local] = leaf

    bindings_doc: dict[str, Any] = {"version": 1, "bindings": {}}
    for idx, b in enumerate(plan.get("receiver_bindings") or [], start=1):
        if not isinstance(b, dict):
            continue
        bref = _binding_ref(b, idx)
        owner = b.get("canonical_owner_key") if isinstance(b.get("canonical_owner_key"), dict) else {}
        bindings_doc["bindings"][bref] = {
            "receiver": b.get("receiver") or b.get("name"),
            "root_type": owner.get("root_type")
            or (list(b.get("root_tiling_types") or [None])[0]),
            "nested_field": b.get("nested_field") or owner.get("nested_path"),
            "member_type": b.get("member_type") or owner.get("member_type"),
            "source_candidate": b.get("candidate_id"),
        }

    recv_name_to_ref = {
        str(v.get("receiver") or ""): k
        for k, v in bindings_doc["bindings"].items()
        if v.get("receiver")
    }

    slim_writers = []
    for w in plan.get("writers") or []:
        if not isinstance(w, dict):
            continue
        slim_writers.append(
            {
                "id": w.get("candidate_id") or w.get("id"),
                "name": w.get("name"),
                "role": w.get("role"),
                "file_path": w.get("file_path"),
                "start_line": w.get("start_line"),
                "qualified_name": w.get("qualified_name"),
            }
        )

    slim_receivers = []
    for r in plan.get("receivers") or []:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()
        slim_receivers.append(
            {
                "id": r.get("candidate_id") or r.get("id"),
                "name": name,
                "is_tiling_sink": r.get("is_tiling_sink"),
                "file_path": r.get("file_path"),
                "binding_ref": recv_name_to_ref.get(name),
            }
        )

    slim: dict[str, Any] = {
        "version": SLIM_PLAN_VERSION,
        "architecture": plan.get("architecture"),
        "actor_id": plan.get("actor_id"),
        "run_id": plan.get("run_id"),
        "workflow_id": plan.get("workflow_id"),
        "candidates_sha256": plan.get("candidates_sha256"),
        "confirmed_by": plan.get("confirmed_by") or "llm",
        "writers": slim_writers,
        "receivers": slim_receivers,
        "non_sink_roots": [
            x for x in (plan.get("non_sink_roots") or []) if isinstance(x, str)
        ],
        "derived_roots": [
            x for x in (plan.get("derived_roots") or []) if isinstance(x, str)
        ],
        "extra_host_entries": list(plan.get("extra_host_entries") or []),
        "aliases_ref": {
            "path": aliases_rel,
            "sha256": aliases_sha,
            "count": len(aliases_doc["aliases"]),
        },
        "receiver_bindings_ref": {
            "path": bindings_rel,
            "sha256": bindings_sha,
            "count": len(bindings_doc["bindings"]),
        },
        # Keep slim inline copies for consumers that have not migrated yet.
        "aliases": [
            {"local": k, "tdf_leaf": v} for k, v in aliases_doc["aliases"].items()
        ],
        "receiver_bindings": [
            {
                "binding_ref": k,
                "receiver": v.get("receiver"),
                "root_type": v.get("root_type"),
                "nested_field": v.get("nested_field"),
                "member_type": v.get("member_type"),
                "candidate_id": v.get("source_candidate"),
                "canonical_owner_key": {
                    "root_type": v.get("root_type") or "",
                    "nested_path": v.get("nested_field") or "",
                    "member_type": v.get("member_type") or "",
                },
            }
            for k, v in bindings_doc["bindings"].items()
        ],
    }
    # Drop Nones
    slim = {k: v for k, v in slim.items() if v is not None}
    return slim, aliases_doc, bindings_doc


def hydrate_extract_plan(plan: dict[str, Any], uo_ir: Path) -> dict[str, Any]:
    """Merge sidecar aliases/bindings into plan for downstream consumers."""
    out = dict(plan)
    aref = plan.get("aliases_ref") if isinstance(plan.get("aliases_ref"), dict) else None
    if aref and aref.get("path"):
        ap = uo_ir / str(aref["path"])
        if ap.is_file():
            from uo.scripts._ir_io import read_yaml

            doc = read_yaml(ap) or {}
            aliases = doc.get("aliases") if isinstance(doc, dict) else None
            if isinstance(aliases, dict) and aliases:
                out["aliases"] = [
                    {"local": k, "tdf_leaf": v} for k, v in aliases.items()
                ]
    bref = (
        plan.get("receiver_bindings_ref")
        if isinstance(plan.get("receiver_bindings_ref"), dict)
        else None
    )
    if bref and bref.get("path"):
        bp = uo_ir / str(bref["path"])
        if bp.is_file():
            from uo.scripts._ir_io import read_yaml

            doc = read_yaml(bp) or {}
            bindings = doc.get("bindings") if isinstance(doc, dict) else None
            if isinstance(bindings, dict) and bindings:
                rows = []
                for k, v in bindings.items():
                    if not isinstance(v, dict):
                        continue
                    rows.append(
                        {
                            "binding_ref": k,
                            "receiver": v.get("receiver"),
                            "root_type": v.get("root_type"),
                            "nested_field": v.get("nested_field"),
                            "member_type": v.get("member_type"),
                            "candidate_id": v.get("source_candidate"),
                            "canonical_owner_key": {
                                "root_type": v.get("root_type") or "",
                                "nested_path": v.get("nested_field") or "",
                                "member_type": v.get("member_type") or "",
                            },
                        }
                    )
                out["receiver_bindings"] = rows
    # Normalize slim writer id → candidate_id for tooling.
    writers = []
    for w in out.get("writers") or []:
        if not isinstance(w, dict):
            writers.append(w)
            continue
        row = dict(w)
        if row.get("id") and not row.get("candidate_id"):
            row["candidate_id"] = row["id"]
        writers.append(row)
    out["writers"] = writers
    return out


def file_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def report_extract_plan_coverage(
    worklist: dict[str, Any],
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    """Structured coverage stats for acp inspect / scratch."""
    required = [
        str(w.get("candidate_id") or "")
        for w in (worklist.get("work_items") or [])
        if isinstance(w, dict) and w.get("required_decision")
    ]
    report = report or {}
    accepted = [
        str(r.get("candidate_id") or "")
        for r in (report.get("accepted") or [])
        if isinstance(r, dict)
    ]
    rejected = [
        str(r.get("candidate_id") or "")
        for r in (report.get("rejected") or [])
        if isinstance(r, dict)
    ]
    deferred = [
        str(r.get("candidate_id") or "")
        for r in (report.get("deferred") or [])
        if isinstance(r, dict)
    ]
    covered = set(accepted) | set(rejected) | set(deferred)
    missing = [c for c in required if c and c not in covered]
    dupes = []
    seen: set[str] = set()
    for cid in accepted + rejected + deferred:
        if cid and cid in seen:
            dupes.append(cid)
        seen.add(cid)
    return {
        "ok": not missing and not dupes,
        "work_items": len(worklist.get("work_items") or []),
        "required": len(required),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "deferred": len(deferred),
        "missing_required": missing,
        "duplicate_ids": dupes,
        "empty_candidate_ids": sum(
            1
            for key in ("accepted", "rejected", "deferred")
            for r in (report.get(key) or [])
            if isinstance(r, dict) and not str(r.get("candidate_id") or "").strip()
        ),
    }


def validate_extract_plan_staging(
    *,
    report: dict[str, Any] | None,
    worklist: dict[str, Any] | None,
    plan: dict[str, Any] | None = None,
    candidates: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> list[str]:
    """Finalize pre-check: schema → identity → coverage → role evidence → architecture."""
    errors: list[str] = []
    if report is not None:
        errors.extend(validate_decision_report_schema(report))
        if worklist:
            errors.extend(validate_decision_coverage(report, worklist))
            errors.extend(validate_candidate_architecture(report, worklist))
    if plan is not None and candidates is not None:
        errors.extend(
            validate_role_evidence_for_plan(plan, candidates, project_root=project_root)
        )
        # Canonical slim must not embed evidence snippets if version>=2 after slim —
        # checked separately by test_extract_plan_size / assert_canonical_slim.
    return errors


def assert_canonical_plan_slim(plan: dict[str, Any]) -> list[str]:
    """Gate: canonical IR must not carry audit blobs."""
    errors: list[str] = []
    for key in AUDIT_PLAN_KEYS:
        if key in plan and plan.get(key):
            # accepted/rejected/deferred must live in decision_report, not canonical.
            errors.append(f"CANONICAL_SLIM: forbidden audit key {key!r} in extract_plan.yaml")
    for section in ("writers", "receivers", "aliases"):
        for item in plan.get(section) or []:
            if not isinstance(item, dict):
                continue
            for bad in AUDIT_ITEM_KEYS:
                if item.get(bad):
                    errors.append(
                        f"CANONICAL_SLIM: {section} item carries audit field {bad!r}"
                    )
    return errors


__all__ = [
    "ALLOWED_DECISIONS",
    "CANDIDATE_KINDS",
    "assert_canonical_plan_slim",
    "build_decision_worklist",
    "classify_candidate_kind",
    "hydrate_extract_plan",
    "index_candidates_by_id",
    "is_decision_report",
    "materialize_plan_from_decision_report",
    "report_extract_plan_coverage",
    "slim_extract_plan",
    "validate_candidate_architecture",
    "validate_decision_coverage",
    "validate_decision_report_schema",
    "validate_extract_plan_staging",
    "validate_role_evidence_for_plan",
]
