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
        prefer_file_contains: str | None = None,
        qualified_contains: str | None = None,
        architecture: str | None = None,
        limit: int = 50,
    ) -> list[CbmSymbol]:
        """Search symbols.

        ``file_contains`` remains an optional hard SQL filter for callers that
        intentionally narrow. Prefer ``prefer_file_contains`` for ranking only
        (⑩) so confirmed-scope common files stay visible.
        """
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
        arch = (architecture or "").strip().replace("\\", "/").strip("/")
        prefer = (prefer_file_contains or "").replace("\\", "/").strip()
        order_parts: list[str] = []
        if prefer:
            order_parts.append(
                f"CASE WHEN file_path LIKE '%{prefer.replace(chr(39), '')}%' THEN 0 ELSE 1 END"
            )
        if arch:
            order_parts.append(
                f"""CASE
                WHEN file_path LIKE '%/{arch}/%' THEN 0
                WHEN file_path NOT LIKE '%/arch%' THEN 1
                ELSE 2
              END"""
            )
        order_parts.extend(
            [
                "length(COALESCE(qualified_name, name))",
                "file_path",
                "start_line",
                "id",
            ]
        )
        order = "ORDER BY " + ", ".join(order_parts)
        sql = f"""
            SELECT id, label, name, qualified_name, file_path, start_line, end_line
            FROM nodes
            WHERE {' AND '.join(clauses)}
            {order}
            LIMIT ?
        """
        params.append(limit)
        try:
            rows = con.execute(sql, params).fetchall()
        except sqlite3.Error:
            # Some CBM schemas use a different table name; fail soft.
            return []
        return [_row_to_symbol(row) for row in rows]

    def resolve_symbols(
        self,
        short_or_qn: str,
        *,
        file_contains: str | None = None,
        class_qn: str | None = None,
        prefer_file_contains: str | None = None,
        architecture: str | None = None,
        limit: int = 30,
    ) -> list[CbmSymbol]:
        """Return ranked symbol hits; never silently collapse ambiguity."""
        text = short_or_qn.strip()
        if not text:
            return []
        hits: list[CbmSymbol] = []
        if "." in text or "::" in text:
            short = text.split(".")[-1].split("::")[-1]
            hits = self.search_symbols(
                qualified_contains=short,
                file_contains=file_contains,
                prefer_file_contains=prefer_file_contains,
                architecture=architecture,
                limit=limit,
            )
            exact_qn = [
                h
                for h in hits
                if h.qualified_name == text
                or h.qualified_name.endswith("." + text)
                or h.qualified_name.endswith("::" + text)
            ]
            if exact_qn:
                hits = exact_qn
        else:
            name = text.split("::")[-1].split(".")[-1]
            hits = self.search_symbols(
                name_pattern=name,
                file_contains=file_contains,
                prefer_file_contains=prefer_file_contains,
                architecture=architecture,
                limit=limit,
            )
            if not hits:
                hits = self.search_symbols(
                    name_pattern=f"%{name}%",
                    file_contains=file_contains,
                    prefer_file_contains=prefer_file_contains,
                    architecture=architecture,
                    limit=limit,
                )
            exact = [h for h in hits if h.name == name]
            if exact:
                hits = exact
        if class_qn:
            cq = class_qn.strip()
            if cq:
                scoped = [
                    h
                    for h in hits
                    if h.qualified_name == cq
                    or h.qualified_name.startswith(cq + "::")
                    or h.qualified_name.startswith(cq + ".")
                    or cq in h.qualified_name
                ]
                if scoped:
                    hits = scoped
        return hits

    def resolve_qn(
        self,
        short_or_qn: str,
        *,
        file_contains: str | None = None,
        class_qn: str | None = None,
        prefer_file_contains: str | None = None,
        architecture: str | None = None,
        limit: int = 30,
    ) -> CbmSymbol | None:
        """Fail-closed: return the hit only when exactly one candidate matches."""
        hits = self.resolve_symbols(
            short_or_qn,
            file_contains=file_contains,
            class_qn=class_qn,
            prefer_file_contains=prefer_file_contains,
            architecture=architecture,
            limit=limit,
        )
        if len(hits) == 1:
            return hits[0]
        return None

    def resolve_qn_or_ambiguous(
        self,
        short_or_qn: str,
        *,
        file_contains: str | None = None,
        class_qn: str | None = None,
        prefer_file_contains: str | None = None,
        architecture: str | None = None,
        limit: int = 30,
    ) -> tuple[CbmSymbol | None, list[CbmSymbol]]:
        hits = self.resolve_symbols(
            short_or_qn,
            file_contains=file_contains,
            class_qn=class_qn,
            prefer_file_contains=prefer_file_contains,
            architecture=architecture,
            limit=limit,
        )
        if len(hits) == 1:
            return hits[0], []
        if len(hits) == 0:
            return None, []
        return None, hits

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
    from uo.scripts.source_path import resolve_repo_source_path

    path = resolve_repo_source_path(repo_root, file_path)
    if path is None:
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    lo = max(1, start_line - pad) - 1
    hi = min(len(lines), max(end_line, start_line) + pad)
    return "\n".join(lines[lo:hi])
