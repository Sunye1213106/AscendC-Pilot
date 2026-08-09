# -*- coding: utf-8 -*-
"""CodeMap query engine — Agent-facing API over ``.uo`` / in-memory CodeMap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.reader import find_uo_product, read_codemap


@dataclass
class CodeMapQuery:
    codemap: CodeMap
    path: str = ""

    def find_symbol(self, name: str, *, kind: str | None = None) -> list[dict[str, Any]]:
        ents = self.codemap.by_name(name, kind=kind)
        if not ents:
            # substring fallback
            ents = [
                e
                for e in self.codemap.entities.values()
                if name in e.name and (kind is None or e.kind_name() == kind)
            ]
        return [e.to_dict() for e in ents]

    def definition(self, name: str) -> dict[str, Any] | None:
        hits = self.find_symbol(name)
        return hits[0] if hits else None

    def references(self, name: str) -> list[dict[str, Any]]:
        targets = {e["id"] for e in self.find_symbol(name)}
        out: list[dict[str, Any]] = []
        for rel in self.codemap.relations.values():
            if rel.kind_name() in {"REFERENCES", "READS", "WRITES", "CALLS"} and (
                rel.src in targets or rel.dst in targets
            ):
                out.append(rel.to_dict())
        return out

    def callers(self, name: str) -> list[dict[str, Any]]:
        return self._adj(name, RelationKind.CALLS, direction="in")

    def callees(self, name: str) -> list[dict[str, Any]]:
        return self._adj(name, RelationKind.CALLS, direction="out")

    def writers(self, name: str) -> list[dict[str, Any]]:
        return self._adj(name, RelationKind.WRITES, direction="in")

    def readers(self, name: str) -> list[dict[str, Any]]:
        return self._adj(name, RelationKind.READS, direction="in")

    def upstream(self, name: str, *, limit: int = 32) -> list[dict[str, Any]]:
        return self._walk(name, direction="in", limit=limit)

    def downstream(self, name: str, *, limit: int = 32) -> list[dict[str, Any]]:
        return self._walk(name, direction="out", limit=limit)

    def find_path(self, start: str, end: str | None = None, *, end_kind: str = "") -> list[dict[str, Any]]:
        start_ents = self.codemap.by_name(start)
        if not start_ents:
            # allow kind-qualified "input.query"
            start_ents = [
                e for e in self.codemap.entities.values() if e.name.endswith(start) or start in e.name
            ]
        if not start_ents:
            return []
        # Prefer INPUT / TILING_KEY roots over same-named VARIABLE shadows.
        rank = {
            "INPUT": 0,
            "TILING_KEY": 1,
            "FIELD": 2,
            "VARIABLE": 3,
        }
        start_ents = sorted(start_ents, key=lambda e: rank.get(e.kind_name(), 9))
        end_kinds = [end_kind] if end_kind else None
        end_id = None
        if end:
            end_ents = self.codemap.by_name(end)
            if end_ents:
                end_id = end_ents[0].id
            elif end.upper() in {k.value for k in EntityKind}:
                end_kinds = [end.upper()]
        kinds = end_kinds or (["KERNEL"] if not end else None)
        for ent in start_ents:
            path_ids = self.codemap.find_path(
                ent.id,
                end_id=end_id,
                end_kinds=kinds,
            )
            if path_ids:
                return [
                    self.codemap.entities[i].to_dict()
                    for i in path_ids
                    if i in self.codemap.entities
                ]
        return []

    def input_roots(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.codemap.by_kind(EntityKind.INPUT)]

    def guards(self, name: str) -> list[dict[str, Any]]:
        return self._adj(name, RelationKind.GUARDED_BY, direction="out") + self._adj(
            name, RelationKind.CONTROLS, direction="in"
        )

    def template_instance(self, name: str = "") -> list[dict[str, Any]]:
        if name:
            return self.find_symbol(name, kind="TEMPLATE_INSTANCE")
        return [e.to_dict() for e in self.codemap.by_kind(EntityKind.TEMPLATE_INSTANCE)]

    def template_bindings(self, instance_name: str) -> list[dict[str, Any]]:
        return self._adj(instance_name, RelationKind.BINDS, direction="out")

    def active_variant(self) -> dict[str, Any] | None:
        rows = [e.to_dict() for e in self.codemap.by_kind(EntityKind.BUILD_VARIANT)]
        return rows[0] if rows else None

    def available_arch(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.codemap.by_kind(EntityKind.ARCH)]

    def selected_kernel(self, key_name: str = "") -> list[dict[str, Any]]:
        if key_name:
            return self._adj(key_name, RelationKind.SELECTS, direction="out")
        return [e.to_dict() for e in self.codemap.by_kind(EntityKind.KERNEL)]

    def source(self, name: str) -> dict[str, Any] | None:
        ent = self.definition(name)
        if not ent:
            return None
        return {
            "name": ent.get("name"),
            "file": ent.get("file"),
            "line_start": ent.get("line_start"),
            "line_end": ent.get("line_end"),
        }

    def summary(self) -> dict[str, Any]:
        return self.codemap.summary()

    def _adj(
        self,
        name: str,
        kind: RelationKind,
        *,
        direction: str,
    ) -> list[dict[str, Any]]:
        ents = self.codemap.by_name(name)
        out: list[dict[str, Any]] = []
        for ent in ents:
            for _rel, other in self.codemap.neighbors(ent.id, kind=kind, direction=direction):
                out.append(other.to_dict())
        return out

    def _walk(self, name: str, *, direction: str, limit: int) -> list[dict[str, Any]]:
        ents = self.codemap.by_name(name)
        if not ents:
            return []
        seen: set[str] = {ents[0].id}
        frontier = [ents[0].id]
        ordered: list[Entity] = []
        while frontier and len(ordered) < limit:
            cur = frontier.pop(0)
            for _rel, other in self.codemap.neighbors(cur, direction=direction):
                if other.id in seen:
                    continue
                seen.add(other.id)
                ordered.append(other)
                frontier.append(other.id)
                if len(ordered) >= limit:
                    break
        return [e.to_dict() for e in ordered]


def open_codemap_query(
    op_root_or_uo: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
) -> CodeMapQuery:
    path = Path(op_root_or_uo).expanduser().resolve()
    if path.is_file() and path.suffix == ".uo":
        return CodeMapQuery(codemap=read_codemap(path), path=str(path))
    found = find_uo_product(path, op_name=op_name, architecture=architecture)
    if found is None:
        raise FileNotFoundError(f"no .uo product under {path}")
    if found.suffix == ".uo":
        return CodeMapQuery(codemap=read_codemap(found), path=str(found))
    # Legacy sqlite: empty CodeMap with note; caller may still use UoQuery.
    cm = CodeMap(op_name=op_name, architecture=architecture or "arch35")
    cm.meta["legacy_db"] = str(found)
    return CodeMapQuery(codemap=cm, path=str(found))
