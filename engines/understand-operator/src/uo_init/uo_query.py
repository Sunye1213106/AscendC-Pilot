# -*- coding: utf-8 -*-
"""Agent-facing UO query facade.

The unified ``.uo`` CodeMap is the only query authority. ``UoQuery`` below
is a migrate/test helper over ``kb_graph.sqlite``; production callers must
use :func:`open_query`, which fail-closes when no ``.uo`` product exists
and queries SQLite indexes without hydrating the full graph.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


class UoQuery:
    """Legacy read-only query backend over ``indexes/kb_graph.sqlite``."""

    backend = "legacy-sqlite"

    def __init__(self, database: str | Path):
        self.database = Path(database).expanduser().resolve()
        if not self.database.is_file():
            raise FileNotFoundError(self.database)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{self.database.as_posix()}?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        for key in ("data", "expr", "values_json"):
            value = out.get(key)
            if isinstance(value, str):
                try:
                    out[key] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        refs = out.get("evidence_refs")
        if isinstance(refs, str):
            out["evidence_refs"] = [item for item in refs.split(",") if item]
        return out

    def _all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [self._decode(row) for row in connection.execute(sql, tuple(params))]

    def constraints_for(self, entity_id: str) -> list[dict[str, Any]]:
        return self._all(
            """
            SELECT p.*, group_concat(ne.evidence_id) AS evidence_refs
            FROM predicate p
            LEFT JOIN node_evidence ne ON ne.node_id=p.id
            WHERE p.owner_id=? OR p.id IN (
              SELECT e.src FROM edge e WHERE e.kind='guards' AND e.dst=?
            )
            GROUP BY p.id ORDER BY p.id
            """,
            (entity_id, entity_id),
        )

    def branches_for_key(self, key_id: str) -> list[dict[str, Any]]:
        return self._reachable(key_id, {"HostBranch", "KernelBranch"})

    def templates_for_key(self, key_id: str) -> list[dict[str, Any]]:
        return self._reachable(key_id, {"TemplateBinding"})

    def affected_shapes(self, entity_id: str) -> list[dict[str, Any]]:
        rows = self._reachable(entity_id, {"Variable", "Input", "OptionalInput"})
        return [
            row for row in rows
            if row.get("kind") != "Variable"
            or str(row.get("id", "")).startswith("VAR_SHAPE_")
        ]

    def controllability_of(self, branch_id: str) -> list[dict[str, Any]]:
        return self._all(
            """
            SELECT p.*, group_concat(ne.evidence_id) AS evidence_refs
            FROM predicate p
            LEFT JOIN node_evidence ne ON ne.node_id=p.id
            WHERE p.owner_id=?
            GROUP BY p.id ORDER BY p.polarity DESC, p.id
            """,
            (branch_id,),
        )

    def entities_in_files(self, files: Iterable[str]) -> list[dict[str, Any]]:
        normalized = sorted({str(path).replace("\\", "/") for path in files})
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        return self._all(
            f"""
            SELECT n.*, group_concat(ne.evidence_id) AS evidence_refs
            FROM node n
            JOIN node_evidence ne ON ne.node_id=n.id
            JOIN evidence ev ON ev.id=ne.evidence_id
            WHERE replace(ev.file, '\\', '/') IN ({placeholders})
            GROUP BY n.id ORDER BY n.id
            """,
            normalized,
        )

    def impact_of(self, file: str, line_range: tuple[int, int]) -> list[dict[str, Any]]:
        start, end = sorted((int(line_range[0]), int(line_range[1])))
        return self._all(
            """
            WITH RECURSIVE hit(id) AS (
              SELECT DISTINCT ne.node_id
              FROM evidence ev
              JOIN node_evidence ne ON ne.evidence_id=ev.id
              WHERE replace(ev.file, '\\', '/') LIKE '%' || replace(?, '\\', '/')
                AND ev.line_end>=? AND ev.line_start<=?
              UNION
              SELECT e.dst FROM edge e JOIN hit ON e.src=hit.id
              UNION
              SELECT e.src FROM edge e JOIN hit ON e.dst=hit.id
            )
            SELECT n.*, group_concat(ne.evidence_id) AS evidence_refs
            FROM node n JOIN hit ON hit.id=n.id
            LEFT JOIN node_evidence ne ON ne.node_id=n.id
            GROUP BY n.id ORDER BY n.kind, n.id
            """,
            (file.replace("\\", "/"), start, end),
        )

    def search(
        self, pattern: str, *, kinds: Iterable[str] = (), limit: int = 50
    ) -> list[dict[str, Any]]:
        needle = f"%{pattern}%"
        kind_filter = ""
        params: list[Any] = [needle, needle, needle, needle]
        kinds_list = [str(k) for k in kinds if str(k)]
        if kinds_list:
            placeholders = ",".join("?" for _ in kinds_list)
            kind_filter = f" AND n.kind IN ({placeholders})"
            params.extend(kinds_list)
        params.append(int(limit))
        return self._all(
            f"""
            SELECT DISTINCT n.*, group_concat(ne.evidence_id) AS evidence_refs
            FROM node n
            LEFT JOIN node_evidence ne ON ne.node_id=n.id
            LEFT JOIN evidence ev ON ev.id=ne.evidence_id
            WHERE n.id LIKE ?
               OR IFNULL(n.name,'') LIKE ?
               OR n.data LIKE ?
               OR IFNULL(ev.snippet,'') LIKE ?
               {kind_filter}
            GROUP BY n.id
            ORDER BY n.kind, n.id
            LIMIT ?
            """,
            params,
        )

    def neighbors(
        self, entity_id: str, *, depth: int = 1, limit: int = 100
    ) -> list[dict[str, Any]]:
        depth = max(1, min(int(depth), 4))
        return self._all(
            """
            WITH RECURSIVE reach(id, dist) AS (
              SELECT ?, 0
              UNION
              SELECT e.dst, r.dist+1 FROM edge e JOIN reach r ON e.src=r.id
               WHERE r.dist < ?
              UNION
              SELECT e.src, r.dist+1 FROM edge e JOIN reach r ON e.dst=r.id
               WHERE r.dist < ?
            )
            SELECT n.*, r.dist AS distance,
                   group_concat(ne.evidence_id) AS evidence_refs
            FROM node n
            JOIN reach r ON r.id=n.id
            LEFT JOIN node_evidence ne ON ne.node_id=n.id
            GROUP BY n.id
            ORDER BY r.dist, n.kind, n.id
            LIMIT ?
            """,
            (entity_id, depth, depth, int(limit)),
        )

    def edges_of(
        self, entity_id: str, *, kind: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        if kind:
            return self._all(
                """
                SELECT * FROM edge
                WHERE (src=? OR dst=?) AND kind=?
                ORDER BY kind, src, dst LIMIT ?
                """,
                (entity_id, entity_id, kind, int(limit)),
            )
        return self._all(
            """
            SELECT * FROM edge
            WHERE src=? OR dst=?
            ORDER BY kind, src, dst LIMIT ?
            """,
            (entity_id, entity_id, int(limit)),
        )

    def tiling_field(self, name_or_id: str) -> list[dict[str, Any]]:
        key = str(name_or_id or "").strip()
        if not key:
            return []
        return self._all(
            """
            SELECT n.*, group_concat(ne.evidence_id) AS evidence_refs
            FROM node n
            LEFT JOIN node_evidence ne ON ne.node_id=n.id
            WHERE n.kind='TilingDataField'
              AND (n.id=? OR n.name=? OR n.id LIKE ? OR n.data LIKE ?)
            GROUP BY n.id ORDER BY n.id
            """,
            (
                key,
                key,
                f"%{key.upper().replace('.', '_')}%",
                f'%"{key}"%',
            ),
        )

    def field_impact(self, name_or_id: str) -> dict[str, Any]:
        fields = self.tiling_field(name_or_id)
        if not fields:
            return {"ok": False, "error": "tiling_field_not_found", "query": name_or_id}
        primary = fields[0]
        fid = str(primary["id"])
        edges = self.edges_of(fid, limit=200)
        neighbors = self.neighbors(fid, depth=2, limit=80)
        data = primary.get("data") if isinstance(primary.get("data"), dict) else {}
        if not data:
            data = {
                k: primary.get(k)
                for k in (
                    "struct",
                    "ctype",
                    "writers",
                    "readers",
                    "defect",
                    "writer_count",
                    "reader_count",
                    "qualified",
                )
                if k in primary
            }
        return {
            "ok": True,
            "field": primary,
            "fields_matched": len(fields),
            "writers": data.get("writers") or [],
            "readers": data.get("readers") or [],
            "defect": data.get("defect"),
            "edges": edges,
            "neighbors": neighbors,
        }

    def constant(self, name: str) -> list[dict[str, Any]]:
        return self.search(name, kinds=("Variable",), limit=20)

    def locate(
        self,
        query: str,
        *,
        kinds: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        from uo_init.source_locator import SourceLocator

        return [
            loc.to_dict()
            for loc in SourceLocator(self.database).locate(query, kinds=kinds, limit=limit)
        ]

    def locate_dim(self, name: str, *, limit: int = 20) -> list[dict[str, Any]]:
        from uo_init.source_locator import SourceLocator

        return [
            loc.to_dict()
            for loc in SourceLocator(self.database).locate_dim(name, limit=limit)
        ]

    def locate_branch(self, branch_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        from uo_init.source_locator import SourceLocator

        return [
            loc.to_dict()
            for loc in SourceLocator(self.database).locate_branch(branch_id, limit=limit)
        ]

    def locate_field(self, name: str, *, limit: int = 20) -> list[dict[str, Any]]:
        from uo_init.source_locator import SourceLocator

        return [
            loc.to_dict()
            for loc in SourceLocator(self.database).locate_field(name, limit=limit)
        ]

    def _reachable(self, start_id: str, kinds: set[str]) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in kinds)
        return self._all(
            f"""
            WITH RECURSIVE reach(id) AS (
              SELECT ?
              UNION
              SELECT e.dst FROM edge e JOIN reach r ON e.src=r.id
              UNION
              SELECT e.src FROM edge e JOIN reach r ON e.dst=r.id
            )
            SELECT n.*, group_concat(ne.evidence_id) AS evidence_refs
            FROM node n JOIN reach r ON r.id=n.id
            LEFT JOIN node_evidence ne ON ne.node_id=n.id
            WHERE n.kind IN ({placeholders})
            GROUP BY n.id ORDER BY n.id
            """,
            (start_id, *sorted(kinds)),
        )


def open_query(
    uo_root: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
):
    """Open the unified ``.uo`` SQL query backend.

    Fail-closed: no product means no query. sqlite / YAML are not fallbacks.
    """
    from uo_init.store.reader import find_uo_product
    from uo_init.query.sql import UoSqlQuery

    root = Path(uo_root).expanduser().resolve()
    product = find_uo_product(root, op_name=op_name, architecture=architecture)
    if product is None or product.suffix != ".uo":
        arch = architecture or "<arch>"
        raise FileNotFoundError(
            f"no .uo product under {root}; expected "
            f".ascendc-pilot/{arch}/uo/<op>.{arch}.uo. "
            "Run /uo-init or answer from source. Do not Glob or Grep for .uo."
        )
    return UoSqlQuery(product)
