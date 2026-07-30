# -*- coding: utf-8 -*-
"""Fixed, parameterized query patterns over the derived UO SQLite index."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


class UoQuery:
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
        for key in ("data", "smt", "values_json"):
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

    def entities_in_files(
        self, files: Iterable[str]
    ) -> list[dict[str, Any]]:
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

    def impact_of(
        self, file: str, line_range: tuple[int, int]
    ) -> list[dict[str, Any]]:
        start, end = sorted((int(line_range[0]), int(line_range[1])))
        return self._all(
            """
            WITH RECURSIVE hit(id) AS (
              SELECT DISTINCT ne.node_id
              FROM evidence ev
              JOIN node_evidence ne ON ne.evidence_id=ev.id
              WHERE replace(ev.file, '\\', '/')=replace(?, '\\', '/')
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
            (file, start, end),
        )

    def _reachable(
        self, start_id: str, kinds: set[str]
    ) -> list[dict[str, Any]]:
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


def open_query(uo_root: str | Path) -> UoQuery:
    return UoQuery(Path(uo_root) / "indexes" / "kb_graph.sqlite")

