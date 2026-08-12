# -*- coding: utf-8 -*-
"""Projection provenance: digest + counts + builder (fingerprint alone is insufficient)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.tg_views import graph_fingerprint

PROJECTION_SCHEMA = "uo-projection-provenance/v1"
PROJECTION_BUILDER = "uo_init.tg_views"
PROJECTION_BUILDER_VERSION = "1"

VIEW_STALE = "VIEW_STALE"


def canonical_counts(codemap: CodeMap) -> dict[str, int]:
    return {
        "entity_count": len(codemap.entities),
        "relation_count": len(codemap.relations),
    }


def canonical_graph_digest(codemap: CodeMap) -> str:
    """Stable digest over identity + totals + kind histograms (stronger than fingerprint alone)."""
    fp = graph_fingerprint(codemap)
    counts = canonical_counts(codemap)
    payload = {
        "fingerprint": fp,
        "entity_count": counts["entity_count"],
        "relation_count": counts["relation_count"],
        "op": codemap.op_name,
        "arch": codemap.architecture,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stamp_provenance(
    view: Any,
    codemap: CodeMap,
    *,
    builder: str = PROJECTION_BUILDER,
    builder_version: str = PROJECTION_BUILDER_VERSION,
    schema_version: str = PROJECTION_SCHEMA,
) -> Any:
    """Attach provenance block to a dict view; non-dicts returned unchanged."""
    if not isinstance(view, dict):
        return view
    counts = canonical_counts(codemap)
    fp = str(codemap.meta.get("graph_fingerprint") or graph_fingerprint(codemap))
    digest = canonical_graph_digest(codemap)
    revision = str(codemap.meta.get("canonical_revision") or digest[:16])
    out = dict(view)
    # Keep legacy fingerprint fields in sync with post-drop canonical.
    if "fingerprint" in out:
        out["fingerprint"] = fp
    source = out.get("source")
    if isinstance(source, dict):
        src = dict(source)
        src["graph_fingerprint"] = fp
        out["source"] = src
    out["provenance"] = {
        "schema": schema_version,
        "canonical_revision": revision,
        "canonical_graph_digest": digest,
        "graph_fingerprint": fp,
        "entity_count": counts["entity_count"],
        "relation_count": counts["relation_count"],
        "schema_version": schema_version,
        "projection_builder": builder,
        "projection_builder_version": builder_version,
    }
    # operator_graph convenience fields
    if out.get("schema") == "uo-operator-graph/v1":
        out["node_count"] = counts["entity_count"]
        out["edge_count"] = counts["relation_count"]
        out["fingerprint"] = fp
    return out


def stamp_all_views(views: dict[str, Any], codemap: CodeMap) -> dict[str, Any]:
    return {name: stamp_provenance(payload, codemap) for name, payload in views.items()}


def extract_provenance(view: Any) -> dict[str, Any] | None:
    if not isinstance(view, dict):
        return None
    prov = view.get("provenance")
    if isinstance(prov, dict) and prov.get("canonical_graph_digest"):
        return prov
    # Legacy: fingerprint / source.graph_fingerprint + optional counts
    fp = view.get("fingerprint")
    if not fp and isinstance(view.get("source"), dict):
        fp = view["source"].get("graph_fingerprint")
    if not fp:
        return None
    return {
        "graph_fingerprint": fp,
        "entity_count": view.get("node_count") or view.get("entity_count"),
        "relation_count": view.get("edge_count") or view.get("relation_count"),
        "canonical_graph_digest": None,
    }


def validate_view_against_codemap(view: Any, codemap: CodeMap) -> dict[str, Any]:
    """Return ``{ok, reason_code?, expected?, actual?}``.

    Non-dict blobs (raw jsonl lists) skip count checks; callers that need
    freshness should use dict wrappers with ``provenance``.
    """
    if not isinstance(view, dict):
        return {"ok": True, "reason_code": "", "skipped": "non_dict_view"}
    expected_fp = str(codemap.meta.get("graph_fingerprint") or graph_fingerprint(codemap))
    expected_digest = canonical_graph_digest(codemap)
    expected_counts = canonical_counts(codemap)
    prov = extract_provenance(view)
    if prov is None:
        # Opaque dict without fingerprint/counts — not a stamped projection.
        if "fingerprint" not in view and not (
            isinstance(view.get("source"), dict) and view["source"].get("graph_fingerprint")
        ):
            return {"ok": True, "reason_code": "", "skipped": "no_identity_fields"}
        return {
            "ok": False,
            "reason_code": VIEW_STALE,
            "message": "missing projection provenance",
            "expected": {
                "canonical_graph_digest": expected_digest,
                **expected_counts,
            },
        }
    actual_digest = prov.get("canonical_graph_digest")
    actual_fp = str(prov.get("graph_fingerprint") or "")
    actual_ec = prov.get("entity_count")
    actual_rc = prov.get("relation_count")
    mismatches: list[str] = []
    if actual_digest and actual_digest != expected_digest:
        mismatches.append("canonical_graph_digest")
    if actual_fp and actual_fp != expected_fp:
        mismatches.append("graph_fingerprint")
    if actual_ec is not None and int(actual_ec) != expected_counts["entity_count"]:
        mismatches.append("entity_count")
    if actual_rc is not None and int(actual_rc) != expected_counts["relation_count"]:
        mismatches.append("relation_count")
    # Legacy views with matching fingerprint but drifted edge/node counts
    if (
        not actual_digest
        and actual_fp == expected_fp
        and actual_rc is not None
        and int(actual_rc) != expected_counts["relation_count"]
    ):
        mismatches.append("relation_count")
    if mismatches:
        return {
            "ok": False,
            "reason_code": VIEW_STALE,
            "mismatches": mismatches,
            "expected": {
                "canonical_graph_digest": expected_digest,
                "graph_fingerprint": expected_fp,
                **expected_counts,
            },
            "actual": {
                "canonical_graph_digest": actual_digest,
                "graph_fingerprint": actual_fp,
                "entity_count": actual_ec,
                "relation_count": actual_rc,
            },
        }
    return {"ok": True, "reason_code": ""}
