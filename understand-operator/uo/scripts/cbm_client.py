from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from uo._operator.cbm_metadata import load_index_meta


@dataclass(frozen=True)
class CbmSymbol:
    node_id: int
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path.replace("\\", "/"),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "label": self.label,
        }


class CbmClient:
    """Local SQLite-first CBM helper with MCP-compatible query conventions.

    Pitfalls encoded here:
    1. Always resolve short names to qualified_name before path tracing.
    2. Prefer (f) + WHERE file_path CONTAINS / LIKE over OR-ed Function|Method labels.
    3. Macro / bit layout / empty kernel graphs fall back to python file scans.
    """

    def __init__(self, uo_root: Path, *, db_path: Path | None = None, project: str | None = None) -> None:
        meta = load_index_meta(uo_root)
        self.project = project or str(meta.get("cbm_project") or "").strip()
        self.db_path = db_path or _db_from_meta(meta, self.project)
        self._con: sqlite3.Connection | None = None

    @property
    def available(self) -> bool:
        return bool(self.db_path and self.db_path.exists() and self.project)

    def connect(self) -> sqlite3.Connection:
        if not self.available:
            raise FileNotFoundError(f"CBM SQLite unavailable: project={self.project!r} db={self.db_path}")
        if self._con is None:
            uri = f"file:{self.db_path.as_posix()}?mode=ro"
            self._con = sqlite3.connect(uri, uri=True)
            self._con.row_factory = sqlite3.Row
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def search_symbols(
        self,
        *,
        name_pattern: str | None = None,
        file_contains: str | None = None,
        qualified_contains: str | None = None,
        limit: int = 50,
    ) -> list[CbmSymbol]:
        con = self.connect()
        clauses = ["project = ?"]
        params: list[Any] = [self.project]
        if name_pattern:
            clauses.append("(name LIKE ? OR qualified_name LIKE ?)")
            params.extend([name_pattern, name_pattern])
        if file_contains:
            clauses.append("file_path LIKE ?")
            params.append(f"%{file_contains.replace(chr(92), '/')}%")
        if qualified_contains:
            clauses.append("qualified_name LIKE ?")
            params.append(f"%{qualified_contains}%")
        sql = f"""
            SELECT id, label, name, qualified_name, file_path, start_line, end_line
            FROM nodes
            WHERE {' AND '.join(clauses)}
            ORDER BY
              CASE WHEN file_path LIKE '%/arch35/%' THEN 0 ELSE 1 END,
              length(COALESCE(qualified_name, name)),
              file_path, start_line, id
            LIMIT ?
        """
        params.append(limit)
        try:
            rows = con.execute(sql, params).fetchall()
        except sqlite3.Error:
            # Some CBM schemas use a different table name; fail soft.
            return []
        return [_row_to_symbol(row) for row in rows]

    def resolve_qn(self, short_or_qn: str, *, file_contains: str | None = None) -> CbmSymbol | None:
        text = short_or_qn.strip()
        if not text:
            return None
        if "." in text or "::" in text:
            hits = self.search_symbols(qualified_contains=text.split(".")[-1].split("::")[-1], file_contains=file_contains, limit=30)
            for hit in hits:
                if hit.qualified_name == text or hit.qualified_name.endswith("." + text) or hit.qualified_name.endswith("::" + text):
                    return hit
                if text in hit.qualified_name:
                    return hit
        name = text.split("::")[-1].split(".")[-1]
        hits = self.search_symbols(name_pattern=name, file_contains=file_contains, limit=30)
        if not hits:
            hits = self.search_symbols(name_pattern=f"%{name}%", file_contains=file_contains, limit=30)
        if not hits:
            return None
        exact = [h for h in hits if h.name == name]
        return (exact or hits)[0]

    def callers_callees(self, node_id: int, *, direction: str = "outbound", limit: int = 200) -> list[CbmSymbol]:
        con = self.connect()
        if direction == "inbound":
            sql = """
                SELECT n.id, n.label, n.name, n.qualified_name, n.file_path, n.start_line, n.end_line
                FROM edges e
                JOIN nodes n ON n.id = e.source_id
                WHERE e.project = ? AND e.target_id = ?
                LIMIT ?
            """
        else:
            sql = """
                SELECT n.id, n.label, n.name, n.qualified_name, n.file_path, n.start_line, n.end_line
                FROM edges e
                JOIN nodes n ON n.id = e.target_id
                WHERE e.project = ? AND e.source_id = ?
                LIMIT ?
            """
        try:
            rows = con.execute(sql, (self.project, node_id, limit)).fetchall()
        except sqlite3.Error:
            return []
        return [_row_to_symbol(row) for row in rows]

    def bounded_trace(
        self,
        root: CbmSymbol,
        *,
        keep_names: Iterable[str] | None = None,
        max_depth: int = 4,
        max_nodes: int = 80,
    ) -> list[CbmSymbol]:
        keep = {name.lower() for name in (keep_names or [])}
        seen: set[int] = {root.node_id}
        queue: list[tuple[CbmSymbol, int]] = [(root, 0)]
        out: list[CbmSymbol] = [root]
        while queue and len(out) < max_nodes:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for nxt in self.callers_callees(current.node_id, direction="outbound", limit=40):
                if nxt.node_id in seen:
                    continue
                seen.add(nxt.node_id)
                if keep and nxt.name.lower() not in keep and not any(k in nxt.name.lower() for k in keep):
                    # still expand through helpers one step if name partially matches keep set
                    if depth + 1 < max_depth and any(k in nxt.qualified_name.lower() for k in keep):
                        out.append(nxt)
                        queue.append((nxt, depth + 1))
                    continue
                out.append(nxt)
                queue.append((nxt, depth + 1))
        return out


def _db_from_meta(meta: dict[str, Any], project: str) -> Path | None:
    value = meta.get("cbm_db_path") or meta.get("db_path")
    if value:
        path = Path(str(value)).expanduser()
        if path.exists():
            return path
    if project:
        candidate = Path.home() / ".cache" / "codebase-memory-mcp" / f"{project}.db"
        if candidate.exists():
            return candidate
    return None


def _row_to_symbol(row: sqlite3.Row) -> CbmSymbol:
    return CbmSymbol(
        node_id=int(row["id"]),
        name=str(row["name"] or ""),
        qualified_name=str(row["qualified_name"] or row["name"] or ""),
        file_path=str(row["file_path"] or "").replace("\\", "/"),
        start_line=int(row["start_line"] or 0),
        end_line=int(row["end_line"] or 0),
        label=str(row["label"] or ""),
    )


def read_source_snippet(repo_root: Path, file_path: str, start_line: int, end_line: int, *, pad: int = 2) -> str:
    path = repo_root / file_path
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    lo = max(1, start_line - pad) - 1
    hi = min(len(lines), max(end_line, start_line) + pad)
    return "\n".join(lines[lo:hi])
