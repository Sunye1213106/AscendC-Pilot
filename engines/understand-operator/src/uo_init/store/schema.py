# -*- coding: utf-8 -*-
"""SQLite schema for the AscendC CodeMap ``.uo`` product."""

from __future__ import annotations

SCHEMA_VERSION = "codemap-uo/v3"
SCHEMA_COMPAT = ("codemap-uo/v1", "codemap-uo/v2", "codemap-uo/v3")

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file(
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  sha256 TEXT,
  role TEXT
);

CREATE TABLE IF NOT EXISTS build_variant(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  architecture TEXT,
  data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity(
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT,
  status TEXT NOT NULL,
  confidence REAL NOT NULL,
  file TEXT,
  line_start INTEGER,
  line_end INTEGER,
  data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relation(
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence REAL NOT NULL,
  data TEXT NOT NULL,
  FOREIGN KEY(src) REFERENCES entity(id),
  FOREIGN KEY(dst) REFERENCES entity(id)
);

CREATE TABLE IF NOT EXISTS source_span(
  id TEXT PRIMARY KEY,
  entity_id TEXT,
  file TEXT NOT NULL,
  line_start INTEGER NOT NULL,
  line_end INTEGER NOT NULL,
  snippet TEXT,
  FOREIGN KEY(entity_id) REFERENCES entity(id)
);

CREATE TABLE IF NOT EXISTS legal_key(
  id INTEGER PRIMARY KEY,
  packed TEXT,
  hex TEXT,
  sel_group TEXT,
  status TEXT
);

CREATE TABLE IF NOT EXISTS legal_key_dim(
  key_id INTEGER NOT NULL,
  dim TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY(key_id, dim),
  FOREIGN KEY(key_id) REFERENCES legal_key(id)
);

CREATE TABLE IF NOT EXISTS view_blob(
  name TEXT PRIMARY KEY,
  schema_id TEXT,
  data TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_uo_entity_kind ON entity(kind);
CREATE INDEX IF NOT EXISTS idx_uo_entity_name ON entity(name);
CREATE INDEX IF NOT EXISTS idx_uo_rel_src ON relation(src, kind);
CREATE INDEX IF NOT EXISTS idx_uo_rel_dst ON relation(dst, kind);
CREATE INDEX IF NOT EXISTS idx_span_entity ON source_span(entity_id);
CREATE INDEX IF NOT EXISTS idx_span_file_line ON source_span(file, line_start, line_end);
CREATE INDEX IF NOT EXISTS idx_entity_file_line ON entity(file, line_start, line_end);
CREATE INDEX IF NOT EXISTS idx_entity_kind_name_nocase ON entity(kind, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_legal_key_dim_value ON legal_key_dim(dim, value, key_id);
CREATE INDEX IF NOT EXISTS idx_legal_key_dim_key ON legal_key_dim(key_id);
"""
