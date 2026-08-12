# -*- coding: utf-8 -*-
"""Compatibility facade exposing legacy UO-query methods over a unified .uo.

The public Agent contract stays stable while storage moves from the legacy
``kb_graph.sqlite`` schema to the CodeMap ``.uo`` product.  This module never
issues raw SQL; all navigation is performed on the typed CodeMap graph.
"""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.query.engine import CodeMapQuery
from uo_init.store.reader import read_codemap

_LEGACY_KIND_MAP: dict[str, set[str]] = {
    "Variable": {"VARIABLE", "COMPILE_VAR", "MACRO"},
    "Input": {"INPUT"},
    "OptionalInput": {"INPUT"},
    "Output": {"OUTPUT"},
    "TilingDataField": {"TILING_FIELD"},
    "HostBranch": {"BRANCH"},
    "KernelBranch": {"BRANCH"},
    "TemplateBinding": {"TEMPLATE", "TEMPLATE_ARG", "TEMPLATE_INSTANCE"},
}


def _kind_names(kinds: Iterable[str]) -> set[str]:
    out: set[str] = set()
    valid = {k.value for k in EntityKind}
    for raw in kinds:
        text = str(raw or "").strip()
        if not text:
            continue
        if text in _LEGACY_KIND_MAP:
            out.update(_LEGACY_KIND_MAP[text])
        upper = text.upper()
        if upper in valid:
            out.add(upper)
    return out


def _entity_row(ent: Entity, *, distance: int | None = None) -> dict[str, Any]:
    row = ent.to_dict()
    row["data"] = dict(ent.attrs)
    if distance is not None:
        row["distance"] = int(distance)
    row.setdefault("evidence_refs", [])
    return row


def _template_block_rows(blob: Any) -> list[dict[str, Any]]:
    if not isinstance(blob, dict):
        return []
    for key in ("groups", "blocks", "rows", "template_blocks"):
        rows = blob.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _value_matches_domain(value: str, domain: Any) -> bool:
    want = str(value)
    if isinstance(domain, (list, tuple, set)):
        return any(str(v) == want for v in domain)
    return str(domain) == want


def _template_block_matches(row: dict[str, Any], filters: dict[str, str]) -> bool:
    fixed = row.get("fixed_fields") or {}
    domains = row.get("field_domains") or {}
    if not isinstance(fixed, dict):
        fixed = {}
    if not isinstance(domains, dict):
        domains = {}
    for name, value in filters.items():
        if name in fixed:
            if str(fixed[name]) != str(value):
                return False
            continue
        if name in domains:
            if not _value_matches_domain(str(value), domains[name]):
                return False
            continue
        return False
    return True


class CodeMapUoQuery:
    """Legacy-compatible query API backed by a committed ``.uo`` CodeMap."""

    backend = "codemap"

    def __init__(self, product: str | Path):
        self.product = Path(product).expanduser().resolve()
        if not self.product.is_file() or self.product.suffix != ".uo":
            raise FileNotFoundError(self.product)
        self.database = self.product  # compatibility for callers that display the path
        self.codemap = read_codemap(self.product)
        self.query = CodeMapQuery(self.codemap, path=str(self.product))

    # ---- legacy navigation -------------------------------------------------

    def search(
        self, pattern: str, *, kinds: Iterable[str] = (), limit: int = 50
    ) -> list[dict[str, Any]]:
        needle = str(pattern or "").lower()
        allowed = _kind_names(kinds)
        rows: list[Entity] = []
        for ent in self.codemap.entities.values():
            if allowed and ent.kind_name() not in allowed:
                continue
            hay = "\n".join(
                (
                    ent.id,
                    ent.name,
                    ent.kind_name(),
                    json.dumps(ent.attrs, ensure_ascii=False, sort_keys=True, default=str),
                )
            ).lower()
            if needle in hay:
                rows.append(ent)
        rows.sort(key=lambda e: (e.kind_name(), e.name, e.id))
        return [_entity_row(e) for e in rows[: max(0, int(limit))]]

    def neighbors(
        self, entity_id: str, *, depth: int = 1, limit: int = 100
    ) -> list[dict[str, Any]]:
        start = self._entity(entity_id)
        if start is None:
            return []
        max_depth = max(1, min(int(depth), 8))
        seen = {start.id}
        queue: deque[tuple[str, int]] = deque([(start.id, 0)])
        out: list[dict[str, Any]] = []
        while queue and len(out) < int(limit):
            cur, dist = queue.popleft()
            ent = self.codemap.entities.get(cur)
            if ent is not None:
                out.append(_entity_row(ent, distance=dist))
            if dist >= max_depth:
                continue
            for _rel, other in self.codemap.neighbors(cur, direction="both"):
                if other.id in seen:
                    continue
                seen.add(other.id)
                queue.append((other.id, dist + 1))
        return out[: int(limit)]

    def edges_of(
        self, entity_id: str, *, kind: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        ent = self._entity(entity_id)
        if ent is None:
            return []
        wanted = str(kind or "").upper()
        rows = [
            rel.to_dict()
            for rel in self.codemap.relations.values()
            if (rel.src == ent.id or rel.dst == ent.id)
            and (not wanted or rel.kind_name().upper() == wanted)
        ]
        rows.sort(key=lambda r: (str(r.get("kind")), str(r.get("src")), str(r.get("dst"))))
        return rows[: int(limit)]

    def constraints_for(self, entity_id: str) -> list[dict[str, Any]]:
        ent = self._entity(entity_id)
        if ent is None:
            return []
        ids = {ent.id}
        for rel, other in self.codemap.neighbors(ent.id, direction="both"):
            if rel.kind_name() in {
                RelationKind.GUARDED_BY.value,
                RelationKind.CONTROLS.value,
                RelationKind.DERIVES.value,
                RelationKind.BINDS.value,
            }:
                ids.add(other.id)
        return [
            _entity_row(e)
            for eid in ids
            if (e := self.codemap.entities.get(eid)) is not None
            and e.kind_name() == EntityKind.PREDICATE.value
        ]

    def branches_for_key(self, key_id: str) -> list[dict[str, Any]]:
        return self._reachable_kinds(key_id, {EntityKind.BRANCH.value})

    def templates_for_key(self, key_id: str) -> list[dict[str, Any]]:
        return self._reachable_kinds(
            key_id,
            {
                EntityKind.TEMPLATE.value,
                EntityKind.TEMPLATE_ARG.value,
                EntityKind.TEMPLATE_INSTANCE.value,
            },
        )

    def affected_shapes(self, entity_id: str) -> list[dict[str, Any]]:
        return self._reachable_kinds(
            entity_id,
            {EntityKind.INPUT.value, EntityKind.FIELD.value, EntityKind.TILING_FIELD.value},
        )

    def controllability_of(self, branch_id: str) -> list[dict[str, Any]]:
        branch = self._entity(branch_id)
        if branch is None:
            return []
        rows: list[dict[str, Any]] = []
        for rel, other in self.codemap.neighbors(branch.id, direction="both"):
            if rel.kind_name() in {
                RelationKind.CONTROLS.value,
                RelationKind.GUARDED_BY.value,
                RelationKind.DERIVES.value,
            } or other.kind_name() in {
                EntityKind.PREDICATE.value,
                EntityKind.TILING_KEY.value,
                EntityKind.INPUT.value,
            }:
                rows.append(_entity_row(other))
        return rows

    def entities_in_files(self, files: Iterable[str]) -> list[dict[str, Any]]:
        normalized = {str(p).replace("\\", "/").lstrip("./") for p in files}
        if not normalized:
            return []
        rows = []
        for ent in self.codemap.entities.values():
            file = str(ent.file or "").replace("\\", "/").lstrip("./")
            if any(file == p or file.endswith("/" + p) or p.endswith("/" + file) for p in normalized):
                rows.append(_entity_row(ent))
        return sorted(rows, key=lambda r: (str(r.get("kind")), str(r.get("id"))))

    def impact_of(self, file: str, line_range: tuple[int, int]) -> list[dict[str, Any]]:
        start, end = sorted((int(line_range[0]), int(line_range[1])))
        needle = str(file or "").replace("\\", "/").lstrip("./")
        seeds: list[Entity] = []
        for ent in self.codemap.entities.values():
            current = str(ent.file or "").replace("\\", "/").lstrip("./")
            if not (current == needle or current.endswith("/" + needle) or needle.endswith("/" + current)):
                continue
            lo = int(ent.line_start or 0)
            hi = int(ent.line_end or lo)
            if not lo or not hi or (hi >= start and lo <= end):
                seeds.append(ent)
        seen: dict[str, int] = {e.id: 0 for e in seeds}
        queue: deque[tuple[str, int]] = deque((e.id, 0) for e in seeds)
        while queue:
            cur, dist = queue.popleft()
            if dist >= 2:
                continue
            for _rel, other in self.codemap.neighbors(cur, direction="both"):
                if other.id in seen:
                    continue
                seen[other.id] = dist + 1
                queue.append((other.id, dist + 1))
        rows = [
            _entity_row(self.codemap.entities[eid], distance=dist)
            for eid, dist in seen.items()
            if eid in self.codemap.entities
        ]
        return sorted(rows, key=lambda r: (int(r.get("distance") or 0), str(r.get("kind")), str(r.get("id"))))

    def tiling_field(self, name_or_id: str) -> list[dict[str, Any]]:
        key = str(name_or_id or "").strip().lower()
        if not key:
            return []
        rows = [
            e for e in self.codemap.by_kind(EntityKind.TILING_FIELD)
            if key in e.id.lower()
            or key == e.name.lower()
            or key in str(e.attrs.get("qualified_name") or "").lower()
        ]
        return [_entity_row(e) for e in rows]

    def field_impact(self, name_or_id: str) -> dict[str, Any]:
        fields = self.tiling_field(name_or_id)
        if not fields:
            return {"ok": False, "error": "tiling_field_not_found", "query": name_or_id}
        primary = fields[0]
        fid = str(primary["id"])
        edges = self.edges_of(fid, limit=300)
        readers = []
        writers = []
        for rel in edges:
            src = self.codemap.entities.get(str(rel.get("src") or ""))
            dst = self.codemap.entities.get(str(rel.get("dst") or ""))
            if rel.get("kind") == RelationKind.READS.value and dst and dst.id == fid and src:
                readers.append(_entity_row(src))
            if rel.get("kind") in {RelationKind.WRITES.value, RelationKind.DERIVES.value} and dst and dst.id == fid and src:
                writers.append(_entity_row(src))
        return {
            "ok": True,
            "field": primary,
            "fields_matched": len(fields),
            "writers": writers,
            "readers": readers,
            "edges": edges,
            "neighbors": self.neighbors(fid, depth=2, limit=120),
        }

    def constant(self, name: str) -> list[dict[str, Any]]:
        needle = str(name or "").lower()
        rows = [
            e for e in self.codemap.entities.values()
            if e.kind_name() in {EntityKind.COMPILE_VAR.value, EntityKind.MACRO.value}
            and needle in e.name.lower()
        ]
        return [_entity_row(e) for e in rows[:20]]

    def locate(
        self, query: str, *, kinds: Iterable[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self.search(query, kinds=kinds or (), limit=limit)
        return [self._location(row) for row in rows if row.get("file")]

    def locate_dim(self, name: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = [
            _entity_row(e)
            for e in self.codemap.by_name(name, kind=EntityKind.TILING_KEY)
        ]
        return [self._location(row) for row in rows[:limit] if row.get("file")]

    def locate_branch(self, branch_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        ent = self._entity(branch_id)
        if ent is None or ent.kind_name() != EntityKind.BRANCH.value:
            return []
        return [self._location(_entity_row(ent))][:limit]

    def locate_field(self, name: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return [self._location(row) for row in self.tiling_field(name)[:limit] if row.get("file")]

    # ---- new unified CodeMap API ------------------------------------------

    def operator_api(self) -> dict[str, Any]:
        return self.query.operator_api()

    def input_roots(self) -> list[dict[str, Any]]:
        return self.query.input_roots()

    def output_roots(self) -> list[dict[str, Any]]:
        return self.query.output_roots()

    def tiling_keys(self) -> list[dict[str, Any]]:
        return self.query.tiling_keys()

    def tiling_data(self, name: str = "") -> list[dict[str, Any]]:
        return self.query.tiling_data(name)

    def tiling_fields(self, owner: str = "") -> list[dict[str, Any]]:
        return self.query.tiling_fields(owner)

    def tiling_registrations(self) -> list[dict[str, Any]]:
        return self.query.tiling_registrations()

    def unresolved(self) -> list[dict[str, Any]]:
        return self.query.unresolved()

    def audit(self) -> dict[str, Any]:
        return self.query.audit()

    def summary(self) -> dict[str, Any]:
        return self.query.summary()

    def slice_forward(
        self,
        seed_ids: Iterable[str],
        *,
        edge_kinds: Iterable[str] | None = None,
        depth: int = 3,
        budget: int = 500,
    ) -> dict[str, Any]:
        return self.query.slice_forward(
            list(seed_ids),
            edge_kinds=list(edge_kinds) if edge_kinds is not None else None,
            depth=depth,
            budget=budget,
        )

    def slice_backward(
        self,
        seed_ids: Iterable[str],
        *,
        edge_kinds: Iterable[str] | None = None,
        depth: int = 3,
        budget: int = 500,
    ) -> dict[str, Any]:
        return self.query.slice_backward(
            list(seed_ids),
            edge_kinds=list(edge_kinds) if edge_kinds is not None else None,
            depth=depth,
            budget=budget,
        )

    def find_path(self, start: str, end: str | None = None, *, end_kind: str = "") -> list[dict[str, Any]]:
        return self.query.find_path(start, end, end_kind=end_kind)

    def selected_kernel(self, key_name: str = "") -> list[dict[str, Any]]:
        return self.query.selected_kernel(key_name)

    def available_arch(self) -> list[dict[str, Any]]:
        return self.query.available_arch()

    # ---- aggregate Explore modes ------------------------------------------

    def aggregate_tiling_key(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        """Return the key itself and its already-extracted semantic attributes.

        Legal-key enumeration is intentionally *not* implicit.  Combination
        reachability is a separate claim and must use ``legal_key`` explicitly.
        """
        needle = str(pattern or "").strip()
        keys = self.tiling_keys()
        if needle:
            low = needle.lower()
            keys = [
                k
                for k in keys
                if low in str(k.get("name") or "").lower()
                or low in str(k.get("id") or "").lower()
            ]
        keys = keys[: max(0, int(limit))]
        return {
            "ok": True,
            "mode": "tiling_key",
            "pattern": needle,
            "keys": keys,
            "count": len(keys),
        }

    def aggregate_tiling_data(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        if needle:
            fields = self.tiling_field(needle)[: int(limit)]
            impact = self.field_impact(needle) if fields else {"ok": False}
            data = self.tiling_data(needle)
        else:
            fields = self.tiling_fields()[: int(limit)]
            impact = {}
            data = self.tiling_data()
        return {
            "ok": True,
            "mode": "tiling_data",
            "pattern": needle,
            "tiling_data": data[: int(limit)],
            "fields": fields,
            "impact": impact,
            "count": len(fields),
        }

    def aggregate_kernel_branch(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        branches = self.branches_for_key(needle) if needle else [
            _entity_row(e) for e in self.codemap.by_kind(EntityKind.BRANCH)
        ]
        kernels = self.selected_kernel(needle) if needle else [
            _entity_row(e) for e in self.codemap.by_kind(EntityKind.KERNEL)
        ]
        overview = self.query.kernel_overview()
        return {
            "ok": True,
            "mode": "kernel_branch",
            "pattern": needle,
            "branches": branches[: int(limit)],
            "kernels": kernels[: int(limit)],
            "overview": overview,
            "count": len(branches),
        }

    def aggregate_template_match(
        self,
        pattern: str = "",
        *,
        filters: dict[str, str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Match graph templates and, when requested, stamped template blocks."""
        needle = str(pattern or "").strip()
        structured = {
            str(k).strip(): str(v).strip()
            for k, v in dict(filters or {}).items()
            if str(k).strip() and str(v).strip()
        }
        templates = self.templates_for_key(needle) if needle else [
            _entity_row(e)
            for e in self.codemap.entities.values()
            if e.kind_name()
            in {
                EntityKind.TEMPLATE.value,
                EntityKind.TEMPLATE_ARG.value,
                EntityKind.TEMPLATE_INSTANCE.value,
            }
        ]
        macros = self.constant(needle) if needle else [
            _entity_row(e)
            for e in self.codemap.entities.values()
            if e.kind_name() in {EntityKind.MACRO.value, EntityKind.COMPILE_VAR.value}
        ]

        block_matches: list[dict[str, Any]] = []
        block_status: dict[str, Any] = {"ok": True, "reason_code": "", "used": False}
        if structured:
            from uo_init.store.reader import load_view_blob_checked

            checked = load_view_blob_checked(
                self.product,
                "tiling/template_blocks.yaml",
                codemap=self.codemap,
                fallback_canonical=False,
            )
            block_status = {
                "ok": bool(checked.get("ok")),
                "reason_code": str(checked.get("reason_code") or ""),
                "used": bool(checked.get("ok")),
            }
            if checked.get("ok"):
                block_matches = [
                    row
                    for row in _template_block_rows(checked.get("view"))
                    if _template_block_matches(row, structured)
                ][: int(limit)]

        return {
            "ok": bool(block_status.get("ok")) if structured else True,
            "mode": "template_match",
            "pattern": needle,
            "filters": structured,
            "templates": templates[: int(limit)],
            "macros_compile_vars": macros[: int(limit)],
            "template_blocks": block_matches,
            "template_projection": block_status,
            "count": len(block_matches) if structured else len(templates),
        }

    def aggregate_buffer(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        rows = self.query.buffer(needle) if needle else self.query.buffers()
        return {
            "ok": True,
            "mode": "buffer",
            "pattern": needle,
            "buffers": rows[: int(limit)],
            "count": min(len(rows), int(limit)),
            "total": len(rows),
        }

    def aggregate_gaps(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip().lower()
        rows = self.unresolved()
        if needle:
            rows = [
                r
                for r in rows
                if needle in json.dumps(r, ensure_ascii=False, default=str).lower()
            ]
        return {
            "ok": True,
            "mode": "gaps",
            "pattern": needle,
            "gaps": rows[: int(limit)],
            "count": min(len(rows), int(limit)),
            "total": len(rows),
        }

    def legal_key_query(
        self,
        *,
        pattern: str = "",
        dim: str = "",
        value: str = "",
        filters: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        from uo_init.query.legal_key_cache import query_legal_keys

        return query_legal_keys(
            self.product,
            pattern=pattern,
            dim=dim,
            value=value,
            filters=filters,
            limit=limit,
            offset=offset,
        )

    # ---- internals ---------------------------------------------------------

    def _entity(self, name_or_id: str) -> Entity | None:
        key = str(name_or_id or "")
        if key in self.codemap.entities:
            return self.codemap.entities[key]
        hits = self.codemap.by_name(key)
        return hits[0] if hits else None

    def _reachable_kinds(self, start_id: str, kinds: set[str]) -> list[dict[str, Any]]:
        start = self._entity(start_id)
        if start is None:
            return []
        seen = {start.id}
        queue = deque([start.id])
        out: list[dict[str, Any]] = []
        while queue:
            cur = queue.popleft()
            for _rel, other in self.codemap.neighbors(cur, direction="both"):
                if other.id in seen:
                    continue
                seen.add(other.id)
                queue.append(other.id)
                if other.kind_name() in kinds:
                    out.append(_entity_row(other))
        return out

    @staticmethod
    def _location(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "kind": row.get("kind"),
            "name": row.get("name"),
            "file": row.get("file"),
            "line_start": row.get("line_start"),
            "line_end": row.get("line_end"),
            "snippet": (row.get("data") or {}).get("snippet") if isinstance(row.get("data"), dict) else "",
        }
