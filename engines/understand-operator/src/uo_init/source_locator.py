# -*- coding: utf-8 -*-
"""Source locator API over the UO KB SQLite product (file:line + snippets)."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Location:
    entity_id: str
    kind: str
    file: str
    line_start: int
    line_end: int
    snippet: str = ""
    window_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _window_sha(snippet: str) -> str | None:
    text = str(snippet or "")
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SourceLocator:
    """Locate KB entities and evidence spans inside ``kb_graph.sqlite``."""

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

    def locate(
        self,
        query: str,
        *,
        kinds: Iterable[str] | None = None,
        limit: int = 20,
    ) -> list[Location]:
        """Search nodes/evidence by id, name, data JSON, or snippet substring."""
        needle = str(query or "").strip()
        if not needle:
            return []
        kinds_list = [str(k) for k in (kinds or ()) if str(k)]
        like = f"%{needle}%"
        kind_filter = ""
        params: list[Any] = [needle, needle, like, like, like]
        if kinds_list:
            placeholders = ",".join("?" for _ in kinds_list)
            kind_filter = f" AND n.kind IN ({placeholders})"
            params.extend(kinds_list)
        params.extend([needle, needle, int(limit)])
        sql = f"""
            SELECT DISTINCT
              n.id AS entity_id,
              n.kind AS kind,
              IFNULL(ev.file, '') AS file,
              IFNULL(ev.line_start, 0) AS line_start,
              IFNULL(ev.line_end, 0) AS line_end,
              IFNULL(ev.snippet, '') AS snippet
            FROM node n
            LEFT JOIN node_evidence ne ON ne.node_id = n.id
            LEFT JOIN evidence ev ON ev.id = ne.evidence_id
            WHERE n.id = ?
               OR IFNULL(n.name, '') = ?
               OR n.id LIKE ?
               OR IFNULL(n.name, '') LIKE ?
               OR n.data LIKE ?
               {kind_filter}
            ORDER BY
              CASE WHEN n.id = ? OR IFNULL(n.name, '') = ? THEN 0 ELSE 1 END,
              n.kind, n.id, ev.line_start
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [
            Location(
                entity_id=str(row["entity_id"]),
                kind=str(row["kind"] or ""),
                file=str(row["file"] or ""),
                line_start=int(row["line_start"] or 0),
                line_end=int(row["line_end"] or row["line_start"] or 0),
                snippet=str(row["snippet"] or ""),
                window_sha256=_window_sha(str(row["snippet"] or "")),
            )
            for row in rows
        ]

    def locate_dim(self, name: str, *, limit: int = 20) -> list[Location]:
        return self.locate(name, kinds=("TilingKeyDim",), limit=limit)

    def locate_branch(self, branch_id: str, *, limit: int = 20) -> list[Location]:
        needle = str(branch_id or "").strip()
        if not needle:
            return []
        hits = self.locate(
            needle,
            kinds=("HostBranch", "KernelBranch", "Predicate"),
            limit=limit,
        )
        # Prefer exact id matches first (already ordered), keep as-is.
        return hits

    def locate_field(self, name: str, *, limit: int = 20) -> list[Location]:
        needle = str(name or "").strip()
        if not needle:
            return []
        # Prefer graph TilingDataField nodes; fall back to host-view writers.
        hits = self.locate(needle, kinds=("TilingDataField",), limit=limit)
        if hits:
            return hits
        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT field, file, line, function, rhs
                    FROM field_writer
                    WHERE field = ? OR field LIKE ?
                    ORDER BY field, file, line
                    LIMIT ?
                    """,
                    (needle, f"%{needle}%", int(limit)),
                ).fetchall()
            except sqlite3.Error:
                return []
        out: list[Location] = []
        for row in rows:
            snippet = str(row["rhs"] or row["function"] or "")
            out.append(
                Location(
                    entity_id=str(row["field"] or needle),
                    kind="TilingDataField",
                    file=str(row["file"] or ""),
                    line_start=int(row["line"] or 0),
                    line_end=int(row["line"] or 0),
                    snippet=snippet,
                    window_sha256=_window_sha(snippet),
                )
            )
        return out


def open_locator(uo_root: str | Path) -> SourceLocator:
    return SourceLocator(Path(uo_root) / "indexes" / "kb_graph.sqlite")


def locate(
    uo_root: str | Path,
    query: str,
    *,
    kinds: Iterable[str] | None = None,
    limit: int = 20,
) -> list[Location]:
    return open_locator(uo_root).locate(query, kinds=kinds, limit=limit)
