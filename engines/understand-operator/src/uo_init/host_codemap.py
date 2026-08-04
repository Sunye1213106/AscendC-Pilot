# -*- coding: utf-8 -*-
"""Persist HostIR as a queryable codemap (YAML authority + SQLite index).

The in-memory HostIR already answers `writes_to` / `calls_to` / `loop_at`.
This module is the durable form of those answers for later PR→test flows,
and for the coverage agent to ask "who writes X" without unpickling the
dev bundle every time.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

CODEMAP_YAML = "ir/host_codemap.yaml"
CODEMAP_SQLITE = "indexes/host_codemap.sqlite"


def export_host_codemap(host_ir: Any, uo_root: str | Path) -> dict[str, Any]:
    """Write a compact HostIR view under ``uo_root`` and rebuild the index."""
    root = Path(uo_root)
    payload = host_ir_payload(host_ir)
    path = root / CODEMAP_YAML
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    summary = rebuild_codemap_index(root)
    return {"ok": True, "yaml": str(path), "writes": len(payload.get("writes") or []),
            "calls": len(payload.get("calls") or []), **summary}


def host_ir_payload(host_ir: Any) -> dict[str, Any]:
    """Serialise the query surfaces the coverage agent needs."""
    writes = []
    for w in getattr(host_ir, "writes", ()) or ():
        writes.append({
            "path": getattr(w, "path", ""),
            "function": getattr(w, "function", ""),
            "file": getattr(w, "file", ""),
            "line": int(getattr(w, "line", 0) or 0),
            "rhs": str(getattr(w, "rhs", "") or "")[:200],
            "guards": list(getattr(w, "guards", lambda: [])() or [])[:12],
        })
    calls = []
    for c in getattr(host_ir, "call_sites", ()) or ():
        calls.append({
            "callee": getattr(c, "callee", ""),
            "caller": getattr(c, "caller", "") or getattr(c, "function", ""),
            "file": getattr(c, "file", ""),
            "line": int(getattr(c, "line", 0) or 0),
        })
    return {
        "schema": "host_codemap/v1",
        "writes": writes,
        "calls": calls,
        "functions": sorted({
            *(w["function"] for w in writes if w["function"]),
            *(c["caller"] for c in calls if c["caller"]),
            *(c["callee"] for c in calls if c["callee"]),
        }),
    }


def load_host_codemap(uo_root: str | Path) -> dict[str, Any]:
    path = Path(uo_root) / CODEMAP_YAML
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def rebuild_codemap_index(uo_root: str | Path) -> dict[str, Any]:
    root = Path(uo_root)
    doc = load_host_codemap(root)
    db = root / CODEMAP_SQLITE
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE writers (
                path TEXT, function TEXT, file TEXT, line INTEGER, rhs TEXT
            );
            CREATE TABLE guards (
                file TEXT, line INTEGER, function TEXT, guard TEXT
            );
            CREATE TABLE callers (
                callee TEXT, caller TEXT, file TEXT, line INTEGER
            );
            CREATE INDEX idx_writers_path ON writers(path);
            CREATE INDEX idx_guards_loc ON guards(file, line);
            CREATE INDEX idx_callers_callee ON callers(callee);
            """
        )
        for w in doc.get("writes") or []:
            conn.execute(
                "INSERT INTO writers VALUES (?,?,?,?,?)",
                (w.get("path"), w.get("function"), w.get("file"),
                 int(w.get("line") or 0), w.get("rhs")),
            )
            for g in w.get("guards") or []:
                conn.execute(
                    "INSERT INTO guards VALUES (?,?,?,?)",
                    (w.get("file"), int(w.get("line") or 0),
                     w.get("function"), str(g)),
                )
        for c in doc.get("calls") or []:
            conn.execute(
                "INSERT INTO callers VALUES (?,?,?,?)",
                (c.get("callee"), c.get("caller"), c.get("file"),
                 int(c.get("line") or 0)),
            )
        conn.commit()
    finally:
        conn.close()
    return {
        "sqlite": str(db),
        "writer_rows": len(doc.get("writes") or []),
        "caller_rows": len(doc.get("calls") or []),
    }


class CodemapQuery:
    """Read-only queries over the exported HostIR codemap."""

    def __init__(self, uo_root: str | Path):
        self.root = Path(uo_root)
        self.db = self.root / CODEMAP_SQLITE
        if not self.db.is_file():
            rebuild_codemap_index(self.root)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db))

    def writers_of(self, symbol: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT path, function, file, line, rhs FROM writers "
                "WHERE path LIKE ? ORDER BY file, line",
                (f"%{symbol}%",),
            ).fetchall()
        return [
            {"path": r[0], "function": r[1], "file": r[2], "line": r[3], "rhs": r[4]}
            for r in rows
        ]

    def guards_at(self, file: str, line: int) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT guard FROM guards WHERE file LIKE ? AND line = ?",
                (f"%{file}%", int(line)),
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def callers_of(self, function: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT callee, caller, file, line FROM callers "
                "WHERE callee = ? ORDER BY file, line",
                (function,),
            ).fetchall()
        return [
            {"callee": r[0], "caller": r[1], "file": r[2], "line": r[3]}
            for r in rows
        ]


def export_codemap_from_bundle(
    bundle_path: str | Path, uo_root: str | Path
) -> dict[str, Any]:
    """Load a pickled host bundle and export its HostIR."""
    import pickle

    path = Path(bundle_path)
    raw = pickle.loads(path.read_bytes())
    host_ir = raw.get("host_ir") if isinstance(raw, dict) else raw
    if host_ir is None:
        return {"ok": False, "error": "bundle has no host_ir"}
    return export_host_codemap(host_ir, uo_root)
