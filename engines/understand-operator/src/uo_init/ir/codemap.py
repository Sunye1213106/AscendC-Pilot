# -*- coding: utf-8 -*-
"""In-memory AscendC CodeMap — single graph for Host/Kernel/Tiling/compile-time."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind

# Legacy KB kind → CodeMap entity kind.
_KB_KIND_MAP: dict[str, EntityKind] = {
    "Variable": EntityKind.VARIABLE,
    "Field": EntityKind.FIELD,
    "Function": EntityKind.FUNCTION,
    "Method": EntityKind.METHOD,
    "File": EntityKind.FILE,
    "Type": EntityKind.TYPE,
    "Input": EntityKind.INPUT,
    "Output": EntityKind.OUTPUT,
    "Macro": EntityKind.MACRO,
    "CompileDefine": EntityKind.COMPILE_VAR,
    "CompileVar": EntityKind.COMPILE_VAR,
    "Template": EntityKind.TEMPLATE,
    "TemplateArg": EntityKind.TEMPLATE_ARG,
    "TemplateInstance": EntityKind.TEMPLATE_INSTANCE,
    "Branch": EntityKind.BRANCH,
    "Ctrl": EntityKind.BRANCH,
    "Predicate": EntityKind.PREDICATE,
    "TilingKey": EntityKind.TILING_KEY,
    "TilingKeyDim": EntityKind.TILING_KEY,
    "TilingField": EntityKind.TILING_FIELD,
    "TilingDataField": EntityKind.TILING_FIELD,
    "Kernel": EntityKind.KERNEL,
    "KernelBranch": EntityKind.BRANCH,
    "Arch": EntityKind.ARCH,
    "Architecture": EntityKind.ARCH,
    "BuildVariant": EntityKind.BUILD_VARIANT,
}

_KB_EDGE_MAP: dict[str, RelationKind] = {
    "DECLARES": RelationKind.DECLARES,
    "DEFINES": RelationKind.DEFINES,
    "REFERENCES": RelationKind.REFERENCES,
    "CALLS": RelationKind.CALLS,
    "READS": RelationKind.READS,
    "WRITES": RelationKind.WRITES,
    "DERIVES": RelationKind.DERIVES,
    "FLOWS_TO": RelationKind.FLOWS_TO,
    "CONTROLS": RelationKind.CONTROLS,
    "EXPANDS_TO": RelationKind.EXPANDS_TO,
    "GUARDED_BY": RelationKind.GUARDED_BY,
    "BINDS": RelationKind.BINDS,
    "INSTANTIATES": RelationKind.INSTANTIATES,
    "SPECIALIZES": RelationKind.SPECIALIZES,
    "SELECTS": RelationKind.SELECTS,
    "LAUNCHES": RelationKind.LAUNCHES,
    "AVAILABLE_ON": RelationKind.AVAILABLE_ON,
    "ACTIVE_UNDER": RelationKind.ACTIVE_UNDER,
    "SAVES": RelationKind.SAVES,
    "RESTORES": RelationKind.RESTORES,
    # Legacy KB edge names.
    "writes": RelationKind.WRITES,
    "reads": RelationKind.READS,
    "calls": RelationKind.CALLS,
    "controls": RelationKind.CONTROLS,
    "derives": RelationKind.DERIVES,
    "flows_to": RelationKind.FLOWS_TO,
    "selects": RelationKind.SELECTS,
    "binds": RelationKind.BINDS,
    "instantiates": RelationKind.INSTANTIATES,
    "guarded_by": RelationKind.GUARDED_BY,
}


def _eid(kind: str, name: str, *extra: str) -> str:
    raw = "|".join([kind, name, *extra])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"E_{kind}_{digest}"


def _rid(kind: str, src: str, dst: str) -> str:
    raw = f"{kind}|{src}|{dst}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"R_{kind}_{digest}"


@dataclass
class CodeMap:
    """Unified operator CodeMap (Host + Kernel + compile-time overlay)."""

    op_name: str = ""
    architecture: str = ""
    entities: dict[str, Entity] = field(default_factory=dict)
    relations: dict[str, Relation] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    # -- mutation ----------------------------------------------------------
    def add_entity(self, entity: Entity) -> Entity:
        existing = self.entities.get(entity.id)
        if existing is None:
            self.entities[entity.id] = entity
            return entity
        existing.attrs.update(entity.attrs)
        if entity.name and not existing.name:
            existing.name = entity.name
        if entity.file and not existing.file:
            existing.file = entity.file
            existing.line_start = entity.line_start
            existing.line_end = entity.line_end
        return existing

    def upsert(
        self,
        kind: EntityKind | str,
        name: str,
        *,
        eid: str | None = None,
        attrs: dict[str, Any] | None = None,
        file: str = "",
        line: int = 0,
        status: str = "extracted",
        confidence: float = 1.0,
    ) -> Entity:
        kind_name = kind.value if isinstance(kind, EntityKind) else str(kind)
        attrs_doc = dict(attrs or {})

        # The source-closure scanner first verifies the global kernel signature,
        # then performs a generic function-body scan.  Treating the second hit as
        # a fresh FUNCTION forks graph identity: CALLS edges originate from the
        # duplicate instead of the Kernel, so entry reachability and TilingData
        # consumption become false negatives.  Reuse the already verified Kernel
        # only for this exact provenance/name case; ordinary same-name functions
        # remain separate entities.
        if (
            eid is None
            and kind_name == EntityKind.FUNCTION.value
            and attrs_doc.get("provenance") == "source_kernel_definition"
        ):
            kernels = [
                ent
                for ent in self.by_name(name, kind=EntityKind.KERNEL)
                if ent.attrs.get("source_signature") is True
            ]
            if len(kernels) == 1:
                entity = kernels[0]
                entity.attrs.update(attrs_doc)
                if file:
                    entity.file = file
                    entity.line_start = int(line)
                    entity.line_end = int(line)
                entity.status = status
                entity.confidence = confidence
                return entity

        entity_id = eid or _eid(kind_name, name)
        return self.add_entity(
            Entity(
                id=entity_id,
                kind=kind,
                name=name,
                attrs=attrs_doc,
                file=file,
                line_start=int(line),
                line_end=int(line),
                status=status,
                confidence=confidence,
            )
        )

    def link(
        self,
        kind: RelationKind | str,
        src: str,
        dst: str,
        *,
        attrs: dict[str, Any] | None = None,
        status: str = "extracted",
        confidence: float = 1.0,
    ) -> Relation:
        kind_name = kind.value if isinstance(kind, RelationKind) else str(kind)
        rid = _rid(kind_name, src, dst)
        rel = Relation(
            id=rid,
            kind=kind,
            src=src,
            dst=dst,
            attrs=dict(attrs or {}),
            status=status,
            confidence=confidence,
        )
        self.relations.setdefault(rid, rel)
        return self.relations[rid]

    # -- query helpers -----------------------------------------------------
    def by_kind(self, kind: EntityKind | str) -> list[Entity]:
        name = kind.value if isinstance(kind, EntityKind) else str(kind)
        return [e for e in self.entities.values() if e.kind_name() == name]

    def by_name(self, name: str, *, kind: EntityKind | str | None = None) -> list[Entity]:
        kn = None
        if kind is not None:
            kn = kind.value if isinstance(kind, EntityKind) else str(kind)
        out: list[Entity] = []
        for e in self.entities.values():
            if e.name != name:
                continue
            if kn is not None and e.kind_name() != kn:
                continue
            out.append(e)
        return out

    def neighbors(
        self,
        entity_id: str,
        *,
        kind: RelationKind | str | None = None,
        direction: str = "out",
    ) -> list[tuple[Relation, Entity]]:
        kn = None
        if kind is not None:
            kn = kind.value if isinstance(kind, RelationKind) else str(kind)
        hits: list[tuple[Relation, Entity]] = []
        for rel in self.relations.values():
            if kn is not None and rel.kind_name() != kn:
                continue
            if direction in ("out", "both") and rel.src == entity_id:
                dst = self.entities.get(rel.dst)
                if dst is not None:
                    hits.append((rel, dst))
            if direction in ("in", "both") and rel.dst == entity_id:
                src = self.entities.get(rel.src)
                if src is not None:
                    hits.append((rel, src))
        return hits

    def find_path(
        self,
        start_id: str,
        *,
        end_kinds: Iterable[str] | None = None,
        end_id: str | None = None,
        max_depth: int = 32,
    ) -> list[str]:
        """BFS path of entity ids from start to end_id or first end_kind."""
        ends = {str(k) for k in (end_kinds or ())}
        adj: dict[str, list[str]] = defaultdict(list)
        for rel in self.relations.values():
            adj[rel.src].append(rel.dst)

        prev: dict[str, str | None] = {start_id: None}
        q: deque[str] = deque([start_id])
        found: str | None = None
        while q:
            cur = q.popleft()
            ent = self.entities.get(cur)
            if end_id and cur == end_id:
                found = cur
                break
            if ends and ent is not None and ent.kind_name() in ends:
                found = cur
                break
            if len(prev) > 1 and (len(prev) // 2) > max_depth * 64:
                break
            depth = 0
            walk = cur
            while prev.get(walk) is not None:
                depth += 1
                walk = prev[walk]  # type: ignore[assignment]
                if depth > max_depth:
                    break
            if depth > max_depth:
                continue
            for nxt in adj.get(cur, ()):
                if nxt in prev:
                    continue
                prev[nxt] = cur
                q.append(nxt)
        if found is None:
            return []
        path: list[str] = []
        cur2: str | None = found
        while cur2 is not None:
            path.append(cur2)
            cur2 = prev.get(cur2)
        path.reverse()
        return path

    def incoming(self, entity_id: str, *, kind: RelationKind | str | None = None) -> list[tuple[Relation, Entity]]:
        return self.neighbors(entity_id, kind=kind, direction="in")

    def outgoing(self, entity_id: str, *, kind: RelationKind | str | None = None) -> list[tuple[Relation, Entity]]:
        return self.neighbors(entity_id, kind=kind, direction="out")

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "uo-codemap/v1",
            "op_name": self.op_name,
            "architecture": self.architecture,
            "entities": [e.to_dict() for e in self.entities.values()],
            "relations": [r.to_dict() for r in self.relations.values()],
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CodeMap":
        cm = cls(
            op_name=str(data.get("op_name") or ""),
            architecture=str(data.get("architecture") or ""),
            meta=dict(data.get("meta") or {}),
        )
        for row in data.get("entities") or []:
            if isinstance(row, dict):
                cm.add_entity(Entity.from_dict(row))
        for row in data.get("relations") or []:
            if not isinstance(row, dict):
                continue
            rel = Relation.from_dict(row)
            cm.relations[rel.id] = rel
        return cm

    @classmethod
    def from_legacy(cls, legacy: dict[str, Any], *, op_name: str = "", architecture: str = "") -> "CodeMap":
        """Build a CodeMap from a legacy ``build_kb`` dictionary."""
        cm = cls(op_name=op_name, architecture=architecture)
        id_map: dict[str, str] = {}
        for row in legacy.get("nodes") or []:
            if not isinstance(row, dict):
                continue
            raw_kind = str(row.get("kind") or row.get("type") or "Other")
            kind = _KB_KIND_MAP.get(raw_kind, EntityKind.OTHER)
            raw_id = str(row.get("id") or "")
            name = str(row.get("name") or row.get("symbol") or raw_id or raw_kind)
            ent = cm.upsert(
                kind,
                name,
                eid=raw_id or None,
                attrs={
                    k: v
                    for k, v in row.items()
                    if k not in {"id", "kind", "type", "name", "symbol", "file", "line", "status", "confidence"}
                },
                file=str(row.get("file") or ""),
                line=int(row.get("line") or row.get("line_start") or 0),
                status=str(row.get("status") or "extracted"),
                confidence=float(row.get("confidence") or 1.0),
            )
            if raw_id:
                id_map[raw_id] = ent.id
        for row in legacy.get("edges") or []:
            if not isinstance(row, dict):
                continue
            raw_kind = str(row.get("kind") or row.get("type") or "REFERENCES")
            kind = _KB_EDGE_MAP.get(raw_kind, RelationKind.REFERENCES)
            src = id_map.get(str(row.get("src") or row.get("source") or ""), str(row.get("src") or row.get("source") or ""))
            dst = id_map.get(str(row.get("dst") or row.get("target") or ""), str(row.get("dst") or row.get("target") or ""))
            if not src or not dst or src not in cm.entities or dst not in cm.entities:
                continue
            rel = cm.link(
                kind,
                src,
                dst,
                attrs={
                    k: v
                    for k, v in row.items()
                    if k not in {"id", "kind", "type", "src", "source", "dst", "target", "status", "confidence"}
                },
                status=str(row.get("status") or "extracted"),
                confidence=float(row.get("confidence") or 1.0),
            )
            if row.get("id"):
                old_id = rel.id
                rel.id = str(row["id"])
                cm.relations.pop(old_id, None)
                cm.relations[rel.id] = rel
        return cm

    def iter_entities(self, kinds: Iterable[str] | None = None) -> Iterator[Entity]:
        allowed = set(kinds or ())
        for entity in self.entities.values():
            if allowed and entity.kind_name() not in allowed:
                continue
            yield entity

    def iter_relations(self, kinds: Iterable[str] | None = None) -> Iterator[Relation]:
        allowed = set(kinds or ())
        for relation in self.relations.values():
            if allowed and relation.kind_name() not in allowed:
                continue
            yield relation
