# -*- coding: utf-8 -*-
"""Query-acceleration side tables for a committed ``.uo``.

The agent-facing name lookup used to be ``e.name = ? COLLATE NOCASE OR
e.name LIKE '%::' || ?``.  A leading wildcard plus ``OR`` makes SQLite drop
every index on ``entity``, so each hop scanned all rows.  These tables turn
that into an indexed equality probe.

Everything here is derived from ``entity`` / ``source_span`` and can be
rebuilt at any time; ``.uo`` files without it still answer correctly through
the legacy path.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

ACCEL_VERSION = "uo-accel/v2"
_SEL_MACRO_RE = re.compile(r"ASCENDC_TPL_ARGS_SEL\s*\(")

KEEP_QUERY_BLOBS = (
    "tiling/template_blocks.yaml",
    "tiling/tpl_schema.yaml",
    "tiling/legal_key_index.jsonl",
    "summary",
)

TEMPLATE_BLOCK_SQL = """
CREATE TABLE IF NOT EXISTS template_block(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  sel_group_index INTEGER,
  file TEXT,
  line_start INTEGER,
  line_end INTEGER,
  product_count INTEGER,
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS template_block_dim(
  block_id INTEGER NOT NULL,
  dim TEXT NOT NULL,
  value TEXT NOT NULL,
  is_fixed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tbd_dim_value ON template_block_dim(dim, value, block_id);
CREATE INDEX IF NOT EXISTS idx_tbd_block ON template_block_dim(block_id);
CREATE INDEX IF NOT EXISTS idx_tb_name ON template_block(name);
"""

ACCEL_SQL = """
CREATE TABLE IF NOT EXISTS entity_name_leaf(
  leaf TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  is_ascendc INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_name_leaf ON entity_name_leaf(leaf, is_ascendc);
CREATE INDEX IF NOT EXISTS idx_name_leaf_entity ON entity_name_leaf(entity_id);
"""

# Recall fallback scans source text with LIKE. An FTS5 index answers faster but
# needs a full copy of the text (+6 MB) and its tokenizer silently misses
# identifiers like `kernel_deter` that a substring scan finds. Substring
# matching is also the semantics the agent expects, because it is what grep does.
#
# `source_span` only holds entity definition snippets, so scanning it can only
# recall names the graph already knows. `source_line` holds every line of the
# operator tree, which makes the fallback a real grep and lets a card report an
# exact total instead of a sample.
SOURCE_LINE_SQL = """
CREATE TABLE IF NOT EXISTS source_line(
  path TEXT NOT NULL,
  line INTEGER NOT NULL,
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_line_path ON source_line(path, line);
"""

SOURCE_SUFFIXES = (".h", ".hpp", ".cpp", ".cc", ".c", ".cuh")


def _leaf_variants(name: str) -> list[str]:
    """Lowercased full name plus its ``::`` / ``.`` qualified leaf."""
    low = str(name or "").strip().lower()
    if not low:
        return []
    out = [low]
    for sep in ("::", "."):
        if sep in low:
            leaf = low.rsplit(sep, 1)[-1].strip()
            if leaf and leaf not in out:
                out.append(leaf)
    return out


def has_accel(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entity_name_leaf' LIMIT 1"
    ).fetchone()
    return row is not None


def build_name_leaf(conn: sqlite3.Connection) -> int:
    """(Re)build the leaf-name inverted index. Returns row count."""
    conn.executescript(ACCEL_SQL)
    conn.execute("DELETE FROM entity_name_leaf")
    rows: list[tuple[str, str, int]] = []
    for eid, name, data in conn.execute(
        "SELECT id, name, IFNULL(data,'') FROM entity WHERE name IS NOT NULL AND name <> ''"
    ):
        is_ascendc = 1 if '"catalog": "ascendc"' in data or '"catalog":"ascendc"' in data else 0
        for leaf in _leaf_variants(name):
            rows.append((leaf, eid, is_ascendc))
    conn.executemany(
        "INSERT INTO entity_name_leaf(leaf, entity_id, is_ascendc) VALUES (?,?,?)", rows
    )
    return len(rows)


def has_source_line(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_line' LIMIT 1"
    ).fetchone()
    return row is not None


def build_source_line(
    conn: sqlite3.Connection, op_root: Path, *, architecture: str = ""
) -> tuple[int, int]:
    """Index every source line under the operator tree. Returns (files, lines).

    A `.uo` is built per architecture, so lines under a foreign `archNN/` are
    skipped: they cannot be a valid citation for this product, and they roughly
    halve the index.
    """
    conn.executescript(SOURCE_LINE_SQL)
    conn.execute("DELETE FROM source_line")
    root = Path(op_root)
    arch = str(architecture or "").strip().lower()
    files = 0
    rows: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts
        # The operator tree itself often lives under `.ascendc-pr`, so only
        # generated artifacts *below* the root are excluded.
        if any(part.startswith(".ascendc-") for part in rel_parts):
            continue
        if arch and any(
            part.lower().startswith("arch") and part.lower() != arch
            for part in rel_parts
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        files += 1
        for no, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                rows.append((rel, no, line))
    conn.executemany(
        "INSERT INTO source_line(path, line, text) VALUES (?,?,?)", rows
    )
    return files, len(rows)


def has_template_block(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='template_block' LIMIT 1"
    ).fetchone()
    return row is not None


def _load_template_block_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    row = conn.execute(
        "SELECT data FROM view_blob WHERE name = ?",
        ("tiling/template_blocks.yaml",),
    ).fetchone()
    if row is None:
        return []
    try:
        blob = json.loads(row[0] or "{}")
    except json.JSONDecodeError:
        return []
    if not isinstance(blob, dict):
        return []
    for key in ("groups", "blocks", "rows", "template_blocks"):
        rows = blob.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def sel_lines_from_header(path: Path) -> list[int]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [text.count("\n", 0, m.start()) + 1 for m in _SEL_MACRO_RE.finditer(text)]


def _resolve_sel_header(conn: sqlite3.Connection, op_root: Path | None) -> Path | None:
    row = conn.execute(
        "SELECT file FROM entity WHERE kind = 'TEMPLATE' AND name LIKE 'ARGS_SEL%' "
        "AND IFNULL(file,'') <> '' LIMIT 1"
    ).fetchone()
    if row is None or not op_root:
        return None
    rel = str(row[0] or "").replace("\\", "/")
    candidates = [op_root / rel, op_root / Path(rel).name]
    if "/" in rel:
        candidates.append(op_root / rel.split("/", 1)[1])
    for cand in candidates:
        if cand.is_file():
            return cand
    name = Path(rel).name
    if name:
        hits = list(op_root.rglob(name))
        if hits:
            return hits[0]
    return None


def patch_sel_lines(conn: sqlite3.Connection, op_root: Path | None) -> int:
    """Write ARGS_SEL file:line onto TEMPLATE entities. Returns rows updated."""
    header = _resolve_sel_header(conn, op_root)
    if header is None:
        return 0
    lines = sel_lines_from_header(header)
    if not lines:
        return 0
    rel = header.as_posix()
    if op_root:
        try:
            rel = header.relative_to(op_root).as_posix()
        except ValueError:
            pass
    updated = 0
    for index, start in enumerate(lines):
        end = (lines[index + 1] - 1) if index + 1 < len(lines) else start + 24
        name = f"ARGS_SEL_{index}"
        cur = conn.execute(
            "UPDATE entity SET file = ?, line_start = ?, line_end = ? "
            "WHERE kind = 'TEMPLATE' AND name = ?",
            (rel, int(start), int(end), name),
        )
        updated += int(cur.rowcount or 0)
    return updated


def build_template_blocks(conn: sqlite3.Connection) -> int:
    """Materialize SEL blocks as relational rows. Returns block count."""
    conn.executescript(TEMPLATE_BLOCK_SQL)
    conn.execute("DELETE FROM template_block_dim")
    conn.execute("DELETE FROM template_block")
    rows = _load_template_block_rows(conn)
    dim_rows: list[tuple[Any, ...]] = []
    for index, row in enumerate(rows):
        name = str(row.get("name") or f"ARGS_SEL_{index}")
        loc = conn.execute(
            "SELECT file, line_start, line_end FROM entity "
            "WHERE kind = 'TEMPLATE' AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        file = str((loc[0] if loc else "") or "")
        line_start = int((loc[1] if loc else 0) or 0)
        line_end = int((loc[2] if loc else 0) or 0)
        conn.execute(
            "INSERT INTO template_block("
            "id, name, sel_group_index, file, line_start, line_end, product_count, data"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                index,
                name,
                row.get("sel_group_index"),
                file,
                line_start,
                line_end,
                int(row.get("product_count") or 0),
                json.dumps(row, ensure_ascii=False, default=str),
            ),
        )
        fixed = row.get("fixed_fields") if isinstance(row.get("fixed_fields"), dict) else {}
        domains = row.get("field_domains") if isinstance(row.get("field_domains"), dict) else {}
        for dim, value in fixed.items():
            dim_rows.append((index, str(dim), str(value), 1))
        for dim, domain in domains.items():
            values = domain if isinstance(domain, (list, tuple, set)) else [domain]
            for value in values:
                dim_rows.append((index, str(dim), str(value), 0))
    if dim_rows:
        conn.executemany(
            "INSERT INTO template_block_dim(block_id, dim, value, is_fixed) VALUES (?,?,?,?)",
            dim_rows,
        )
    return len(rows)


def build_source_fts(conn: sqlite3.Connection) -> bool:
    """Trigram FTS over source_line. Returns False if FTS5 is unavailable."""
    if not has_source_line(conn):
        return False
    try:
        conn.execute("DROP TABLE IF EXISTS source_fts")
        conn.execute(
            "CREATE VIRTUAL TABLE source_fts USING fts5("
            "path UNINDEXED, line UNINDEXED, text, tokenize='trigram')"
        )
        conn.execute(
            "INSERT INTO source_fts(path, line, text) SELECT path, line, text FROM source_line"
        )
    except sqlite3.OperationalError:
        return False
    return True


def has_source_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_fts' LIMIT 1"
    ).fetchone()
    return row is not None


def prune_view_blobs(conn: sqlite3.Connection, keep: Iterable[str]) -> int:
    """Drop view blobs the agent query path never reads. Returns bytes freed."""
    keep_set = {str(k) for k in keep}
    freed = 0
    victims: list[str] = []
    for name, size in conn.execute(
        "SELECT name, LENGTH(IFNULL(data,'')) FROM view_blob"
    ):
        if name not in keep_set:
            victims.append(name)
            freed += int(size or 0)
    for name in victims:
        conn.execute("DELETE FROM view_blob WHERE name = ?", (name,))
    return freed


def upgrade(
    path: str | Path,
    *,
    op_root: str | Path | None = None,
    architecture: str = "",
    prune: Iterable[str] | None = KEEP_QUERY_BLOBS,
    vacuum: bool = True,
) -> dict[str, Any]:
    """Add acceleration tables to an existing ``.uo`` in place."""
    db = Path(path).expanduser().resolve()
    before = db.stat().st_size
    conn = sqlite3.connect(str(db))
    root = Path(op_root).expanduser().resolve() if op_root is not None else None
    stats: dict[str, Any] = {"product": str(db), "size_before": before}
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        stats["name_leaf_rows"] = build_name_leaf(conn)
        stats["sel_lines_patched"] = patch_sel_lines(conn, root)
        stats["template_blocks"] = build_template_blocks(conn)
        if root is not None:
            files, lines = build_source_line(
                conn, root, architecture=architecture
            )
            stats["source_files"] = files
            stats["source_lines"] = lines
            stats["source_fts"] = False
            # LIKE over ~35k lines is only used on identifier miss. FTS5
            # trigram would copy the text again and grew this product by 16 MB.
        if prune is not None:
            stats["view_blob_bytes_freed"] = prune_view_blobs(conn, prune)
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
            ("accel_version", ACCEL_VERSION),
        )
        conn.commit()
        if vacuum:
            conn.execute("VACUUM")
            conn.commit()
    finally:
        conn.close()
    stats["size_after"] = db.stat().st_size
    stats["saved_mb"] = round((before - stats["size_after"]) / 1048576, 2)
    return stats
