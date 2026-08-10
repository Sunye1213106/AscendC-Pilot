# -*- coding: utf-8 -*-
"""Semantic gap helpers — only unresolved ambiguities reach the agent."""

from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def list_gaps(codemap: CodeMap) -> list[dict[str, Any]]:
    """Return deterministic structural/semantic gaps using the strict audit.

    The historical implementation used ``CodeMap.host_kernel_path_exists()``,
    whose compatibility fallback could treat node presence as connectivity.
    Gap production must use the same evidence-backed semantics as build, query,
    dump and review.
    """
    from uo_init.diagnostics.audit import audit_codemap

    audit = audit_codemap(codemap)
    gaps: list[dict[str, Any]] = []
    code_map = {
        "MISSING_KERNEL": "missing_kernel",
        "MISSING_TILING_KEY": "missing_tiling_key",
        "MISSING_TILING_DATA": "missing_tiling_data",
        "MISSING_INPUT": "missing_input",
        "MISSING_OUTPUT": "missing_output",
        "MISSING_EVIDENCE_BACKED_HOST_KERNEL_PATH": "missing_host_kernel_path",
        "MISSING_INPUT_TILINGKEY_KERNEL_PATH": "missing_input_tilingkey_kernel_path",
        "MISSING_TILINGDATA_KERNEL_PATH": "missing_tilingdata_kernel_path",
        "MISSING_INPUT_OUTPUT_PATH": "missing_input_output_path",
        "TILING_KEY_CARDINALITY_MISMATCH": "tiling_key_cardinality_mismatch",
        "SUSPICIOUS_CARTESIAN_KEY_KERNEL": "suspicious_cartesian_key_kernel",
    }
    for item in audit.get("blocking") or []:
        raw = str(item.get("code") or "")
        gaps.append(
            {
                "code": code_map.get(raw, raw.lower() or "audit_blocking"),
                "message": str(item.get("detail") or raw),
                "audit_code": raw,
                **{k: v for k, v in item.items() if k not in {"code", "detail"}},
            }
        )

    for ent in codemap.entities.values():
        if str(ent.status).lower() in {"unresolved", "partial", "not_extracted", "unknown"}:
            gaps.append(
                {
                    "code": "entity_status",
                    "entity_id": ent.id,
                    "name": ent.name,
                    "status": ent.status,
                    "reason": ent.attrs.get("reason"),
                    "resolution_blocker": ent.attrs.get("resolution_blocker"),
                }
            )
    return gaps


def merge_resolutions(codemap: CodeMap, patches: list[dict[str, Any]]) -> CodeMap:
    """Apply agent gap patches as entities/relations (non-authoritative until commit)."""
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        kind = patch.get("entity_kind") or patch.get("kind")
        name = str(patch.get("name") or "")
        if kind and name:
            ent = codemap.upsert(str(kind), name, attrs=dict(patch.get("attrs") or {}))
            ent.status = str(patch.get("status") or "extracted")
        rel = patch.get("relation") or {}
        if rel.get("kind") and rel.get("src") and rel.get("dst"):
            codemap.link(
                str(rel["kind"]),
                str(rel["src"]),
                str(rel["dst"]),
                attrs=dict(rel.get("attrs") or {}),
            )
        if patch.get("derives_from") and patch.get("name"):
            src = codemap.upsert(EntityKind.INPUT, str(patch["derives_from"]))
            dst = codemap.upsert(EntityKind.TILING_KEY, name)
            codemap.link(
                RelationKind.DERIVES,
                src.id,
                dst.id,
                attrs={"provenance": "semantic_gap_patch"},
            )
    return codemap
