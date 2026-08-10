# -*- coding: utf-8 -*-
"""Project TG-facing view blobs from a CodeMap (disposable, stamped projections)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def graph_fingerprint(codemap: CodeMap) -> str:
    """Stable identity for the current CodeMap closure (not full dump)."""
    ent_kinds = sorted(Counter(e.kind_name() for e in codemap.entities.values()).items())
    rel_kinds = sorted(Counter(r.kind_name() for r in codemap.relations.values()).items())
    key_names = sorted(
        e.name for e in codemap.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")
    )
    payload = {
        "op": codemap.op_name,
        "arch": codemap.architecture,
        "entities": ent_kinds,
        "relations": rel_kinds,
        "tiling_keys": key_names,
        "legal_key_count": int(codemap.meta.get("legal_key_count") or 0),
        "args_sel_group_count": int(codemap.meta.get("args_sel_group_count") or 0),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def project_operator_graph(codemap: CodeMap, *, fingerprint: str = "") -> dict[str, Any]:
    fp = fingerprint or graph_fingerprint(codemap)
    entities_by_kind = dict(Counter(e.kind_name() for e in codemap.entities.values()))
    relations_by_kind = dict(Counter(r.kind_name() for r in codemap.relations.values()))
    return {
        "schema": "uo-operator-graph/v1",
        "fingerprint": fp,
        "op_name": codemap.op_name,
        "architecture": codemap.architecture,
        "node_count": len(codemap.entities),
        "edge_count": len(codemap.relations),
        "entities_by_kind": entities_by_kind,
        "relations_by_kind": relations_by_kind,
        "closure": {
            "legal_key_count": int(codemap.meta.get("legal_key_count") or 0),
            "args_sel_group_count": int(codemap.meta.get("args_sel_group_count") or 0),
            "tiling_key_host_packing": codemap.meta.get("host_tiling_key_packing") or {},
            "has_strict_kernel_tiling_closure": bool(
                codemap.meta.get("has_strict_kernel_tiling_closure")
            ),
        },
        # Slim — TG identity check, not a second full graph dump.
        "nodes": [],
        "edges": [],
    }


def project_tg_host_view(codemap: CodeMap, *, fingerprint: str = "") -> dict[str, Any]:
    """Host packing / producer / predicate surface for TG construct + bind."""
    fp = fingerprint or graph_fingerprint(codemap)
    keys = sorted(
        codemap.by_kind(EntityKind.TILING_KEY),
        key=lambda e: int(e.attrs.get("decl_order") or 0),
    )
    fields: list[dict[str, Any]] = []
    predicates: list[dict[str, Any]] = []
    declared_keys: dict[str, Any] = {}
    incoming: dict[str, list[Any]] = {}
    for rel in codemap.relations.values():
        incoming.setdefault(rel.dst, []).append(rel)

    for key in keys:
        packing = list(key.attrs.get("host_packing_expressions") or [])
        declared_keys[key.name] = {
            "decl_order": key.attrs.get("decl_order"),
            "bit_offset": key.attrs.get("bit_offset"),
            "bit_width": key.attrs.get("bit_width") or key.attrs.get("bw"),
            "allowed_values": list(key.attrs.get("allowed_values") or key.attrs.get("value_domain") or []),
            "packing": packing,
        }
        # Host symbols that feed this key (DERIVES into packing expr / field).
        host_syms = _host_symbols_for_key(codemap, key, incoming)
        for sym in host_syms:
            writers = list(sym.attrs.get("producer_sites") or [])
            field_preds = _predicates_for_entity(codemap, sym, incoming)
            for p in field_preds:
                predicates.append(p)
            fields.append(
                {
                    "name": sym.name,
                    "kind": "key_dim_host",
                    "tiling_key": key.name,
                    "exactness": sym.attrs.get("exactness") or "",
                    "writers": writers,
                    "reads": _read_roots(codemap, sym, incoming),
                    "packing": packing,
                    "rooted": bool(sym.attrs.get("rooted_by_current_source")),
                    "entity_id": sym.id,
                }
            )
        if not host_syms and packing:
            fields.append(
                {
                    "name": key.name,
                    "kind": "key_dim",
                    "tiling_key": key.name,
                    "exactness": "",
                    "writers": [],
                    "reads": [],
                    "packing": packing,
                    "rooted": False,
                    "entity_id": key.id,
                }
            )

    return {
        "schema": "tg-host-view/v1",
        "compat_schema": "codemap/v2",
        "source": {
            "graph_fingerprint": fp,
            "generated_by": "uo_init.tg_views.project_tg_host_view",
            "authority": "uo_codemap",
            "role": "tg_host_projection",
        },
        "fields": fields,
        "predicates": predicates,
        "declared_keys": declared_keys,
        "platform_gates": [],
    }


def finalize_tg_views(
    codemap: CodeMap,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge TPL blobs with host/graph projections; stamp fingerprints."""
    views = dict(existing or {})
    fp = graph_fingerprint(codemap)
    codemap.meta["graph_fingerprint"] = fp

    if "tiling/exhaustive_key_space.yaml" in views and isinstance(
        views["tiling/exhaustive_key_space.yaml"], dict
    ):
        views["tiling/exhaustive_key_space.yaml"]["fingerprint"] = fp

    views["ir/operator_graph.yaml"] = project_operator_graph(codemap, fingerprint=fp)
    views["ir/tg_host_view.yaml"] = project_tg_host_view(codemap, fingerprint=fp)
    return views


def _host_symbols_for_key(
    codemap: CodeMap, key: Any, incoming: dict[str, list[Any]]
) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    # Prefer entities marked as host_key_argument that share packing symbol names.
    packing = [str(x) for x in (key.attrs.get("host_packing_expressions") or [])]
    tokens: set[str] = set()
    for expr in packing:
        for tok in _extract_symbols(expr):
            tokens.add(tok)

    # Pre-index mid-nodes that DERIVE into this key so we never scan the full
    # relation table per candidate entity (that was O(|E|·|R|) per key).
    mid_ids = {
        rel.src
        for rel in incoming.get(key.id, [])
        if rel.kind_name() == RelationKind.DERIVES.value
    }

    for ent in codemap.entities.values():
        if ent.kind_name() not in {
            EntityKind.FIELD.value,
            EntityKind.VARIABLE.value,
        }:
            continue
        if not (
            ent.attrs.get("host_key_argument")
            or ent.attrs.get("producer_sites")
            or ent.name in tokens
            or any(ent.name.endswith(t) or t.endswith(ent.name) for t in tokens)
        ):
            continue
        # Keep symbols that derive into this key or are packing args for it.
        related = False
        if ent.attrs.get("host_key_argument") and (
            str(ent.attrs.get("tiling_key") or "") == key.name
            or key.name in str(ent.attrs.get("host_key_dims") or "")
        ):
            related = True
        for rel in incoming.get(key.id, []):
            if rel.kind_name() == RelationKind.DERIVES.value and rel.src == ent.id:
                related = True
                break
        if not related and mid_ids:
            for mid in mid_ids:
                for r2 in incoming.get(mid, []):
                    if r2.src == ent.id:
                        related = True
                        break
                if related:
                    break
        if related or (
            ent.attrs.get("host_key_argument")
            and tokens
            and any(t in ent.name or ent.name in t for t in tokens)
        ):
            if ent.id not in seen:
                seen.add(ent.id)
                out.append(ent)
    return out


def _predicates_for_entity(
    codemap: CodeMap, ent: Any, incoming: dict[str, list[Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel in incoming.get(ent.id, []):
        if rel.kind_name() != RelationKind.DERIVES.value:
            continue
        src = codemap.entities.get(rel.src)
        if src is None or src.kind_name() != EntityKind.PREDICATE.value:
            continue
        out.append(
            {
                "id": src.id,
                "file": rel.attrs.get("file") or src.file,
                "line": rel.attrs.get("line") or src.line_start,
                "function": rel.attrs.get("function") or src.attrs.get("function"),
                "condition": src.name,
                "fields": [ent.name],
                "lhs": src.attrs.get("lhs"),
                "guards": list(src.attrs.get("guards") or []),
            }
        )
    return out


def _read_roots(
    codemap: CodeMap, ent: Any, incoming: dict[str, list[Any]]
) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    for rel in incoming.get(ent.id, []):
        if rel.kind_name() not in {RelationKind.DERIVES.value, RelationKind.FLOWS_TO.value}:
            continue
        src = codemap.entities.get(rel.src)
        if src is None:
            continue
        if src.kind_name() in {
            EntityKind.INPUT.value,
            EntityKind.COMPILE_VAR.value,
            EntityKind.MACRO.value,
        }:
            roots.append(
                {
                    "root": src.name,
                    "kind": src.kind_name(),
                    "entity_id": src.id,
                    "provenance": rel.attrs.get("provenance") or "",
                }
            )
    return roots


def _extract_symbols(expr: str) -> list[str]:
    import re

    # static_cast<...>(foo.bar) or bare ident
    out: list[str] = []
    for m in re.finditer(r"\b([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+)\b", expr):
        out.append(m.group(1))
    for m in re.finditer(r"\b([A-Za-z_][\w]*)\b", expr):
        tok = m.group(1)
        if tok in {"static_cast", "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int"}:
            continue
        out.append(tok)
    return out
