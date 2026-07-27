"""Canonicalize score items into semantic obligations before llm_tasks upsert.

Bridge obligation identity excludes gap_kind; gap kinds accumulate in payload.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

_LEAF_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def _norm(s: Any) -> str:
    return str(s or "").strip()


def _norm_cf(s: Any) -> str:
    return _norm(s).casefold()


def field_leaf(field_path: str) -> str:
    fp = _norm(field_path)
    if not fp:
        return ""
    if "." in fp:
        return fp.rsplit(".", 1)[-1]
    m = _LEAF_RE.search(fp)
    return m.group(0) if m else fp


def bridge_obligation_id(
    *,
    owner_identity: str,
    field_path: str,
    architecture: str = "",
    template_family: str = "",
    path_family: str = "",
) -> str:
    raw = "|".join(
        [
            "tilingdata_bridge",
            _norm_cf(owner_identity),
            _norm_cf(field_path),
            _norm_cf(architecture),
            _norm_cf(template_family),
            _norm_cf(path_family),
        ]
    )
    return "OBL_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def bridge_task_id(*, obligation_id: str, source_snapshot_hash: str) -> str:
    raw = f"tilingdata_bridge|{obligation_id}|{source_snapshot_hash or ''}"
    return "TASK_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def candidate_content_hash(candidate: dict[str, Any]) -> str:
    """Content-level hash so snippet/line/sha changes invalidate shard parts."""
    sw = candidate.get("source_window") if isinstance(candidate.get("source_window"), dict) else {}
    snippet = str(candidate.get("snippet") or sw.get("text") or "")
    snippet_sha = hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16] if snippet else ""
    raw = "|".join(
        [
            str(candidate.get("candidate_id") or candidate.get("id") or ""),
            str(candidate.get("file_path") or sw.get("file_path") or "").replace("\\", "/"),
            str(candidate.get("symbol_ref") or candidate.get("qualified_name") or ""),
            str(candidate.get("start_line") or sw.get("start_line") or 0),
            str(candidate.get("end_line") or sw.get("end_line") or 0),
            str(candidate.get("source_window_sha256") or sw.get("sha256") or ""),
            snippet_sha,
            str(candidate.get("owning_type") or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def candidate_set_content_hash(candidates: list[Any] | None) -> str:
    parts: list[str] = []
    for c in candidates or []:
        if isinstance(c, dict):
            parts.append(candidate_content_hash(c))
        else:
            parts.append(hashlib.sha256(str(c).encode("utf-8")).hexdigest()[:16])
    raw = ",".join(sorted(parts))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _owner_from_item(item: dict[str, Any]) -> str:
    for key in (
        "normalized_owner_identity",
        "owner_identity",
        "canonical_owner_identity",
        "owning_type",
        "canonical_type",
    ):
        v = _norm(item.get(key))
        if v and v.casefold() != "unknowntype":
            return v
    cok = item.get("canonical_owner_key")
    if isinstance(cok, dict):
        root = _norm(cok.get("root_type"))
        nested = _norm(cok.get("nested_path"))
        if root and nested:
            return f"{root}::{nested}"
        if _norm(cok.get("member_type")):
            return str(cok.get("member_type"))
    return _norm(item.get("owning_type")) or "UnknownType"


def _field_from_item(item: dict[str, Any]) -> str:
    for key in ("normalized_field_path", "field_path", "field", "tdf_leaf"):
        v = _norm(item.get(key))
        if v:
            return v
    target = _norm(item.get("target_id") or "")
    # bridge_gap:{code}:{field}
    if target.startswith("bridge_gap:"):
        parts = target.split(":")
        if len(parts) >= 3:
            return parts[-1]
    return field_leaf(target)


def _gap_kind_from_item(item: dict[str, Any]) -> str:
    for key in ("gap_kind", "code", "classification"):
        v = _norm(item.get(key))
        if v:
            return v
    target = _norm(item.get("target_id") or "")
    if target.startswith("bridge_gap:"):
        parts = target.split(":")
        if len(parts) >= 2:
            return parts[1]
    return "bridge_gap"


def _is_bridge_item(item: dict[str, Any]) -> bool:
    ot = _norm_cf(item.get("object_type"))
    if ot in {"tilingdata_bridge", "bridge_gap", "tilingdata"}:
        return True
    target = _norm(item.get("target_id"))
    return target.startswith("bridge_gap:") or "tilingdata" in ot


def canonicalize_score_items(
    items: list[dict[str, Any]],
    *,
    architecture: str = "",
    source_snapshot_hash: str = "",
) -> list[dict[str, Any]]:
    """Group Bridge gaps/candidates into one obligation per semantic field.

    Non-bridge items pass through unchanged (with content hash enrichment).
    """
    out: list[dict[str, Any]] = []
    bridge_groups: dict[str, dict[str, Any]] = {}

    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        # Enrich candidates with content hashes
        cands = item.get("candidates")
        if isinstance(cands, list):
            item["candidate_set_hash"] = candidate_set_content_hash(cands)

        if not _is_bridge_item(item):
            out.append(item)
            continue

        owner = _owner_from_item(item)
        field = _field_from_item(item)
        arch = _norm(item.get("architecture") or architecture)
        template_family = _norm(item.get("template_family") or item.get("template") or "")
        path_family = _norm(item.get("path_family") or item.get("path") or "")
        obl_id = bridge_obligation_id(
            owner_identity=owner,
            field_path=field,
            architecture=arch,
            template_family=template_family,
            path_family=path_family,
        )
        gap = _gap_kind_from_item(item)
        snap = _norm(item.get("source_snapshot_hash") or source_snapshot_hash)

        group = bridge_groups.get(obl_id)
        if group is None:
            group = {
                **item,
                "object_type": "tilingdata_bridge",
                "obligation_id": obl_id,
                "canonical_obligation_id": obl_id,
                "normalized_owner_identity": owner,
                "normalized_field_path": field,
                "architecture": arch,
                "template_family": template_family,
                "path_family": path_family,
                "target_id": f"bridge_obl:{obl_id}",
                "gap_kinds": [],
                "host_writer_ids": [],
                "kernel_reader_ids": [],
                "evidence_windows": [],
                "candidates": [],
                "source_snapshot_hash": snap,
            }
            # Effective task type stays in payload; not part of stable id.
            bridge_groups[obl_id] = group

        gk = list(group.get("gap_kinds") or [])
        if gap and gap not in gk:
            gk.append(gap)
        group["gap_kinds"] = gk

        for key_src, key_dst in (
            ("host_writer_ids", "host_writer_ids"),
            ("kernel_reader_ids", "kernel_reader_ids"),
            ("evidence_windows", "evidence_windows"),
        ):
            bucket = list(group.get(key_dst) or [])
            for v in item.get(key_src) or []:
                if v not in bucket:
                    bucket.append(v)
            # Also accept singular ids
            singular = key_src[:-1] if key_src.endswith("_ids") else ""
            if singular and item.get(singular) and item.get(singular) not in bucket:
                bucket.append(item.get(singular))
            group[key_dst] = bucket

        # Merge candidates
        merged_cands = list(group.get("candidates") or [])
        seen_c = {candidate_content_hash(c) if isinstance(c, dict) else str(c) for c in merged_cands}
        for c in item.get("candidates") or []:
            h = candidate_content_hash(c) if isinstance(c, dict) else str(c)
            if h not in seen_c:
                seen_c.add(h)
                merged_cands.append(c)
        group["candidates"] = merged_cands
        group["candidate_set_hash"] = candidate_set_content_hash(merged_cands)

        # Severity: keep worst (blocking > degraded > informational)
        sev_rank = {"blocking": 3, "degraded": 2, "informational": 1, "none": 0}
        cur = sev_rank.get(_norm_cf(group.get("severity")), 0)
        nxt = sev_rank.get(_norm_cf(item.get("severity")), 0)
        if nxt >= cur:
            group["severity"] = item.get("severity") or group.get("severity")
        if item.get("disposition") == "llm_task":
            group["disposition"] = "llm_task"
        # Prefer typed resolution hint when unknown type present
        if "unknown_type" in gk or "tilingdata_type_unknown" in gk:
            group["task_hint"] = item.get("task_hint") or group.get("task_hint") or "evidence_enrichment"

        if snap and not group.get("source_snapshot_hash"):
            group["source_snapshot_hash"] = snap

    for obl_id, group in bridge_groups.items():
        snap = _norm(group.get("source_snapshot_hash") or source_snapshot_hash)
        group["stable_task_id_override"] = bridge_task_id(
            obligation_id=obl_id, source_snapshot_hash=snap
        )
        out.append(group)

    return out


__all__ = [
    "bridge_obligation_id",
    "bridge_task_id",
    "candidate_content_hash",
    "candidate_set_content_hash",
    "canonicalize_score_items",
    "field_leaf",
]
