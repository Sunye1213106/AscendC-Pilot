# -*- coding: utf-8 -*-
"""Persist HostIR as a queryable codemap (YAML authority + SQLite index).

Schema ``codemap/v2`` is the confluence of three producers that used to talk
past each other:

  HostIR writes (+ one-level callee expansion)  → fields[].writers
  PredicateNormalizer / var roots               → fields[].reads + predicates[]
  kernel tiling-key header                      → declared_keys
  npuArch / SocVersion guards                   → platform_gates

The v1 surface (flat writes/calls/functions) is gone: calls belong to the
navigation layer (CBM), and the 84% of functions with no writes were noise.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

CODEMAP_YAML = "ir/host_codemap.yaml"
CODEMAP_SQLITE = "indexes/host_codemap.sqlite"
SCHEMA = "codemap/v2"

#: RHS length for writer rows. v1 capped at 200 and already overflowed.
RHS_LIMIT = 800
#: Guard strings kept per writer.
GUARD_LIMIT = 16

_PLATFORM_RE = re.compile(
    r"\b(npuArch|socVersion|NpuArch|SocVersion|DAV_\w+|Ascend\d+)\b"
)
_CMP_HINTS = (
    ("bn1s1s2", re.compile(r"\bb\b.*\bn1\b.*\bs1\b.*\bs2\b|\bbn1s1s2\b", re.I)),
    ("qkv_bytes", re.compile(r"qkv|dtypeBytes|GetSize|l2Size|L2", re.I)),
    ("s1_mod128", re.compile(r"%\s*128|s1\s*%", re.I)),
    ("band", re.compile(r"preTokens|nextTokens|s1Token|s2Token|pre_tokens", re.I)),
    ("dtype_is_fp32", re.compile(r"DT_FLOAT\b|queryType\s*==\s*.*FLOAT", re.I)),
)


def export_host_codemap(
    host_ir: Any,
    uo_root: str | Path,
    *,
    derive_fields: list[dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the codemap under ``uo_root`` and rebuild the index."""
    root = Path(uo_root)
    payload = host_ir_payload(
        host_ir, derive_fields=derive_fields, declared=declared)
    path = root / CODEMAP_YAML
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    summary = rebuild_codemap_index(root)
    return {
        "ok": True,
        "schema": SCHEMA,
        "yaml": str(path),
        "fields": len(payload.get("fields") or []),
        "writers": sum(len(f.get("writers") or []) for f in payload.get("fields") or []),
        "predicates": len(payload.get("predicates") or []),
        **summary,
    }


def host_ir_payload(
    host_ir: Any,
    *,
    derive_fields: list[dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialise the query surfaces the coverage / CE agents need."""
    writers = _writer_rows(host_ir)
    fields = _fields_from_writers(writers, derive_fields or [])
    predicates = _predicates_from_writers(writers)
    platform_gates = [
        p for p in predicates
        if _PLATFORM_RE.search(str(p.get("condition") or p.get("lhs") or ""))
    ]
    return {
        "schema": SCHEMA,
        "fields": fields,
        "predicates": predicates,
        "declared_keys": declared or {},
        "platform_gates": platform_gates,
    }


def _writer_rows(host_ir: Any) -> list[dict[str, Any]]:
    expand = getattr(host_ir, "expand_callee_writers", None)
    events = expand() if callable(expand) else list(getattr(host_ir, "writes", ()) or ())
    rows = []
    for w in events:
        guards = list(getattr(w, "guards", lambda: [])() or [])[:GUARD_LIMIT]
        rows.append({
            "path": getattr(w, "path", ""),
            "function": getattr(w, "function", ""),
            "file": getattr(w, "file", ""),
            "line": int(getattr(w, "line", 0) or 0),
            "rhs": str(getattr(w, "rhs", "") or "")[:RHS_LIMIT],
            "guards": guards,
            "via": str(getattr(w, "via", "") or ""),
        })
    return rows


def _leaf(path: str) -> str:
    return path.rsplit(".", 1)[-1] if path else ""


def _fields_from_writers(
    writers: list[dict[str, Any]],
    derive_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_leaf: dict[str, dict[str, Any]] = {}
    for w in writers:
        leaf = _leaf(w["path"])
        if not leaf:
            continue
        slot = by_leaf.setdefault(leaf, {
            "name": leaf,
            "kind": "host_state",
            "writers": [],
            "reads": [],
            "state_deps": [],
            "exactness": "",
            "note": "",
            "grade": "",
            "domain": [],
        })
        slot["writers"].append({
            "file": w["file"],
            "line": w["line"],
            "function": w["function"],
            "rhs": w["rhs"],
            "guards": w["guards"],
            "via": w["via"] or "direct",
            "path": w["path"],
        })

    # Overlay lightweight metadata from derive_key_fields when provided.
    for f in derive_fields:
        name = str(f.get("name") or "")
        if not name:
            continue
        # Key dims are often PascalCase; writers use camelCase field names.
        leaf = name[0].lower() + name[1:] if name[:2].isupper() is False else name
        # Prefer exact name match against writer leaves, else the dim name itself.
        slot = by_leaf.get(name) or by_leaf.get(leaf) or by_leaf.setdefault(name, {
            "name": name,
            "kind": "key_dim",
            "writers": [],
            "reads": [],
            "state_deps": [],
            "exactness": "",
            "note": "",
            "grade": "",
            "domain": [],
        })
        slot["kind"] = "key_dim"
        slot["exactness"] = str(f.get("exactness") or "")
        slot["note"] = str(f.get("note") or "")
        slot["domain"] = list(f.get("domain") or [])
        roots = f.get("var_roots") or {}
        if isinstance(roots, dict):
            slot["reads"] = [
                {"var": str(v), "root": str(r)} for v, r in roots.items()
            ]
        elif isinstance(roots, list):
            slot["reads"] = [{"var": str(v), "root": ""} for v in roots]
        state = f.get("state_targets") or {}
        if isinstance(state, dict):
            deps = []
            for vals in state.values():
                deps.extend(str(x) for x in (vals or []))
            slot["state_deps"] = sorted(set(deps))
        exact = slot["exactness"]
        if exact in ("exact", "constant"):
            slot["grade"] = "exact_static"
        elif exact == "overapproximated" or str(f.get("status")) == "partial":
            slot["grade"] = "empirical"
        elif slot["state_deps"]:
            slot["grade"] = "observed_exact"

    return [by_leaf[k] for k in sorted(by_leaf)]


def _feature_hint(text: str) -> str:
    for name, pat in _CMP_HINTS:
        if pat.search(text):
            return name
    return ""


def _predicates_from_writers(writers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lift guard strings into predicate rows with a feature_hint when possible.

    Full SMT normalisation stays in `uo_init.predicate.PredicateNormalizer`;
    here we keep a durable, queryable projection for TG feature engineering.
    """
    seen: set[tuple] = set()
    out = []
    for w in writers:
        for g in w.get("guards") or []:
            text = str(g).strip()
            if not text:
                continue
            key = (w.get("file"), w.get("line"), text)
            if key in seen:
                continue
            seen.add(key)
            hint = _feature_hint(text)
            out.append({
                "id": f"P{len(out):04d}",
                "file": w.get("file"),
                "line": w.get("line"),
                "function": w.get("function"),
                "condition": text,
                "fields": [_leaf(w.get("path") or "")],
                "feature_hint": hint,
            })
    return out


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
                path TEXT, function TEXT, file TEXT, line INTEGER,
                rhs TEXT, via TEXT, field TEXT
            );
            CREATE TABLE guards (
                file TEXT, line INTEGER, function TEXT, guard TEXT
            );
            CREATE TABLE fields (
                name TEXT PRIMARY KEY, kind TEXT, exactness TEXT, grade TEXT
            );
            CREATE TABLE reads (
                field TEXT, var TEXT, root TEXT
            );
            CREATE TABLE predicates (
                id TEXT, file TEXT, line INTEGER, function TEXT,
                condition TEXT, feature_hint TEXT
            );
            CREATE INDEX idx_writers_path ON writers(path);
            CREATE INDEX idx_writers_field ON writers(field);
            CREATE INDEX idx_guards_loc ON guards(file, line);
            CREATE INDEX idx_preds_hint ON predicates(feature_hint);
            """
        )
        for f in doc.get("fields") or []:
            conn.execute(
                "INSERT OR REPLACE INTO fields VALUES (?,?,?,?)",
                (f.get("name"), f.get("kind"), f.get("exactness"), f.get("grade")),
            )
            for r in f.get("reads") or []:
                conn.execute(
                    "INSERT INTO reads VALUES (?,?,?)",
                    (f.get("name"), r.get("var"), r.get("root")),
                )
            for w in f.get("writers") or []:
                conn.execute(
                    "INSERT INTO writers VALUES (?,?,?,?,?,?,?)",
                    (w.get("path"), w.get("function"), w.get("file"),
                     int(w.get("line") or 0), w.get("rhs"),
                     w.get("via") or "direct", f.get("name")),
                )
                for g in w.get("guards") or []:
                    conn.execute(
                        "INSERT INTO guards VALUES (?,?,?,?)",
                        (w.get("file"), int(w.get("line") or 0),
                         w.get("function"), str(g)),
                    )
        for p in doc.get("predicates") or []:
            conn.execute(
                "INSERT INTO predicates VALUES (?,?,?,?,?,?)",
                (p.get("id"), p.get("file"), int(p.get("line") or 0),
                 p.get("function"), p.get("condition"), p.get("feature_hint")),
            )
        conn.commit()
    finally:
        conn.close()
    return {
        "sqlite": str(db),
        "field_rows": len(doc.get("fields") or []),
        "predicate_rows": len(doc.get("predicates") or []),
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
                "SELECT path, function, file, line, rhs, via FROM writers "
                "WHERE path LIKE ? OR field LIKE ? ORDER BY file, line",
                (f"%{symbol}%", f"%{symbol}%"),
            ).fetchall()
        return [
            {"path": r[0], "function": r[1], "file": r[2], "line": r[3],
             "rhs": r[4], "via": r[5]}
            for r in rows
        ]

    def guards_at(self, file: str, line: int) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT guard FROM guards WHERE file LIKE ? AND line = ?",
                (f"%{file}%", int(line)),
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def reads_of(self, field: str) -> list[dict[str, str]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT var, root FROM reads WHERE field = ?", (field,),
            ).fetchall()
        return [{"var": r[0], "root": r[1]} for r in rows]

    def predicates(self, *, feature_hint: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if feature_hint:
                rows = conn.execute(
                    "SELECT id, file, line, function, condition, feature_hint "
                    "FROM predicates WHERE feature_hint = ?",
                    (feature_hint,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, file, line, function, condition, feature_hint "
                    "FROM predicates"
                ).fetchall()
        return [
            {"id": r[0], "file": r[1], "line": r[2], "function": r[3],
             "condition": r[4], "feature_hint": r[5]}
            for r in rows
        ]

    def callers_of(self, function: str) -> list[dict[str, Any]]:
        """Deprecated in v2: call graph lives in the navigation layer.

        Kept as an empty list so old call sites do not crash; prefer CBM.
        """
        del function
        return []


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
    derive = None
    if isinstance(raw, dict):
        hd = raw.get("host_derivation") or {}
        derive = hd.get("fields") if isinstance(hd, dict) else None
    declared = None
    try:
        from testcase_agent.closure import workspace as WS
        sch = WS.schema()
        declared = {
            "count": len(WS.declared()),
            "dims": [
                {"name": d.name, "bw": getattr(d, "bw", 0),
                 "domain": list(getattr(d, "value_domain", []) or [])}
                for d in sch.dims
            ],
        }
    except Exception:
        declared = None
    return export_host_codemap(
        host_ir, uo_root, derive_fields=derive, declared=declared)
