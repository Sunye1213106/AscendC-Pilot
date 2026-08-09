# -*- coding: utf-8 -*-
"""Semantic gap helpers — only unresolved ambiguities reach the agent."""

from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def list_gaps(codemap: CodeMap) -> list[dict[str, Any]]:
    """Structural gaps a deterministic Pass could not close."""
    gaps: list[dict[str, Any]] = []
    if not codemap.by_kind(EntityKind.KERNEL):
        gaps.append({"code": "missing_kernel", "message": "no KERNEL entity"})
    if not codemap.by_kind(EntityKind.TILING_KEY):
        gaps.append({"code": "missing_tiling_key", "message": "no TILING_KEY entity"})
    if not codemap.host_kernel_path_exists():
        gaps.append(
            {
                "code": "missing_host_kernel_path",
                "message": "no INPUT/VARIABLE → TILING_KEY/KERNEL path",
            }
        )
    for ent in codemap.entities.values():
        if ent.status in {"unresolved", "partial", "not_extracted"}:
            gaps.append(
                {
                    "code": "entity_status",
                    "entity_id": ent.id,
                    "name": ent.name,
                    "status": ent.status,
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
        # Convenience: bind input root → key
        if patch.get("derives_from") and patch.get("name"):
            src = codemap.upsert(EntityKind.INPUT, str(patch["derives_from"]))
            dst = codemap.upsert(EntityKind.TILING_KEY, name)
            codemap.link(RelationKind.DERIVES, src.id, dst.id)
    return codemap
