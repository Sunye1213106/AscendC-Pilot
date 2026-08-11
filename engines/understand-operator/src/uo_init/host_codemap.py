# -*- coding: utf-8 -*-
"""TG Host View: a disposable projection of HostIR facts for TG/CE search.

Authority lives in ``ir/operator_graph.yaml`` (KB). This module writes a
human-reviewable search projection (``ir/tg_host_view.yaml``) stamped with
``source.graph_fingerprint`` so freshness gates can detect drift.

Schema ``tg-host-view/v1`` surfaces:

  HostIR writes (+ one-level callee expansion)  → fields[].writers
  PredicateNormalizer / var roots               → fields[].reads + predicates[]
  kernel tiling-key header                      → declared_keys
  npuArch / SocVersion guards                   → platform_gates

The single SQLite product / authority is ``indexes/kb_graph.sqlite``. Legacy
``host_codemap.yaml`` / ``host_codemap.sqlite`` aliases are no longer written.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

# Durable projection (preferred name).
TG_HOST_VIEW_YAML = "ir/tg_host_view.yaml"
# Legacy read-only fallbacks for old on-disk caches. New writers must not
# create these; load_tg_host_view still accepts them when the preferred file
# is missing.
CODEMAP_YAML = "ir/host_codemap.yaml"  # legacy alias (read-only)
CODEMAP_SQLITE = "indexes/host_codemap.sqlite"  # legacy; unlinked when present
KB_GRAPH_SQLITE = "indexes/kb_graph.sqlite"
SCHEMA = "tg-host-view/v1"
COMPAT_SCHEMA = "codemap/v2"

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
    graph_fingerprint: str = "",
    source_revision: str = "",
    manifest_hash: str = "",
) -> dict[str, Any]:
    """Write the TG host view under ``uo_root`` and rebuild the query cache.

    Prefer :func:`export_tg_host_view` at call sites; this name is kept for
    older imports.
    """
    return export_tg_host_view(
        host_ir,
        uo_root,
        derive_fields=derive_fields,
        declared=declared,
        graph_fingerprint=graph_fingerprint,
        source_revision=source_revision,
        manifest_hash=manifest_hash,
    )


def export_tg_host_view(
    host_ir: Any,
    uo_root: str | Path,
    *,
    derive_fields: list[dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
    graph_fingerprint: str = "",
    source_revision: str = "",
    manifest_hash: str = "",
) -> dict[str, Any]:
    """Project HostIR into ``tg_host_view.yaml`` stamped with the KB fingerprint.

    Does not read ``.probe_cache/*.pkl``. Callers must supply a live HostIR
    (typically from the same in-process extract that fed ``export_kb``).
    """
    root = Path(uo_root)
    payload = host_ir_payload(
        host_ir,
        derive_fields=derive_fields,
        declared=declared,
        graph_fingerprint=graph_fingerprint,
        source_revision=source_revision,
        manifest_hash=manifest_hash,
    )
    view_path = root / TG_HOST_VIEW_YAML
    view_path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    view_path.write_text(text, encoding="utf-8")
    # No host_codemap.yaml alias — single authority is tg_host_view.yaml +
    # indexes/kb_graph.sqlite (W4b).
    summary = rebuild_codemap_index(root)
    kb_upsert: dict[str, Any] = {}
    try:
        from uo_init.kb_index import upsert_host_view_tables

        kb_upsert = upsert_host_view_tables(root, payload)
    except Exception as exc:  # noqa: BLE001
        kb_upsert = {"ok": False, "error": str(exc)[:200]}
    return {
        "ok": True,
        "schema": SCHEMA,
        "yaml": str(view_path),
        "alias_yaml": "",
        "fields": len(payload.get("fields") or []),
        "writers": sum(
            len(f.get("writers") or []) for f in payload.get("fields") or []
        ),
        "predicates": len(payload.get("predicates") or []),
        "graph_fingerprint": str(
            (payload.get("source") or {}).get("graph_fingerprint") or ""
        ),
        "kb_upsert": kb_upsert,
        **summary,
    }


def host_ir_payload(
    host_ir: Any,
    *,
    derive_fields: list[dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
    graph_fingerprint: str = "",
    source_revision: str = "",
    manifest_hash: str = "",
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
        "compat_schema": COMPAT_SCHEMA,
        "source": {
            "graph_fingerprint": graph_fingerprint or "",
            "manifest_hash": manifest_hash or "",
            "source_revision": source_revision or "",
            "generated_by": "export_tg_host_view",
            "authority": "uo/ir/operator_graph.yaml",
            "role": "tg_host_projection",
        },
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

    Full predicate normalisation stays in `uo_init.predicate.PredicateNormalizer`;
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
    """Load the TG host view.

    Preference order:
    1. Durable YAML (legacy / transition)
    2. ``view_blob`` inside ``.uo`` CodeMap product
    3. ``view_blob`` / host_view tables inside ``kb_graph.sqlite``
    """
    root = Path(uo_root)
    path = root / TG_HOST_VIEW_YAML
    if path.is_file():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Read-only fallback for older checkouts that still have the alias.
    legacy = root / CODEMAP_YAML
    if legacy.is_file():
        return yaml.safe_load(legacy.read_text(encoding="utf-8")) or {}

    # Prefer single-file ``.uo`` product (arch-neutral or beside op root).
    try:
        from uo_init.store.reader import find_uo_product, load_view_blob

        # uo_root is typically ``<op>/.ascendc-pilot/<arch>/uo`` → op = parents[2]
        # or ``<op>/.ascendc-pilot/uo`` → op = parents[1]
        if root.name == "uo" and root.parent.name == ".ascendc-pilot":
            op_root = root.parent.parent
        elif root.name == "uo":
            op_root = root.parents[2]
        else:
            op_root = root
        found = find_uo_product(op_root)
        if found is not None and found.suffix == ".uo":
            for key in ("ir/tg_host_view.yaml", "tg_host_view"):
                blob = load_view_blob(found, key)
                if isinstance(blob, dict) and blob:
                    return blob
    except Exception:
        pass

    # Legacy sqlite view_blob.
    db = root / KB_GRAPH_SQLITE
    if db.is_file():
        try:
            from uo_init.kb_index import load_view_blob as _kb_blob

            for key in ("ir/tg_host_view.yaml", "tg_host_view"):
                blob = _kb_blob(db, key)
                if isinstance(blob, dict) and blob:
                    return blob
        except Exception:
            pass
    return {}


def load_tg_host_view(uo_root: str | Path) -> dict[str, Any]:
    """TG shim: materialize host view from YAML or ``.uo`` (no new authority)."""
    return load_host_codemap(uo_root)


def rebuild_codemap_index(uo_root: str | Path) -> dict[str, Any]:
    """Ensure host-view rows live in ``kb_graph.sqlite`` (no second sqlite).

    Historically this wrote ``indexes/host_codemap.sqlite``. That dual
    authority is removed: we only upsert into kb_graph and report counts.
    """
    root = Path(uo_root)
    doc = load_host_codemap(root)
    fp = str((doc.get("source") or {}).get("graph_fingerprint") or "")
    kb_upsert: dict[str, Any] = {}
    try:
        from uo_init.kb_index import upsert_host_view_tables

        kb_upsert = upsert_host_view_tables(root, doc)
    except Exception as exc:  # noqa: BLE001
        kb_upsert = {"ok": False, "error": str(exc)[:200]}
    legacy = root / CODEMAP_SQLITE
    if legacy.is_file():
        try:
            legacy.unlink()
        except OSError:
            pass
    return {
        "ok": True,
        "mode": "kb_graph",
        "field_rows": len(doc.get("fields") or []),
        "predicate_rows": len(doc.get("predicates") or []),
        "graph_fingerprint": fp,
        "kb_upsert": kb_upsert,
    }


def _kb_has_host_view_tables(db: Path) -> bool:
    if not db.is_file():
        return False
    try:
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='field_writer'"
            ).fetchone()
            return bool(row)
    except sqlite3.Error:
        return False


@dataclass
class QueryResult:
    """Uniform Codemap query envelope: facts + completeness + evidence."""

    facts: list[Any] = field(default_factory=list)
    completeness: str = "unknown"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    fingerprint: str = ""
    scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": list(self.facts),
            "completeness": self.completeness,
            "evidence": list(self.evidence),
            "fingerprint": self.fingerprint,
            "scope": self.scope,
        }


def default_codemap_completeness(
    *,
    init_profile: str = "fast",
    closure_mode: str = "keypath",
) -> dict[str, Any]:
    """Profile-level completeness contract stored in KB meta / view blob."""
    profile = (init_profile or "fast").strip().lower()
    mode = (closure_mode or "keypath").strip().lower()
    host_complete = mode == "full" and profile == "full"
    return {
        "schema": "codemap-completeness/v1",
        "init_profile": profile,
        "closure_mode": mode,
        "host": {
            "functions": {
                "mode": mode,
                "entry_roots_complete": True,
                "call_closure": "complete" if host_complete else "partial",
            },
            "writes": "complete" if mode in {"full", "keypath"} else "partial",
            "reads": "complete" if mode in {"full", "keypath"} else "partial",
        },
        "kernel": {
            "completeness": "partial" if profile == "fast" else "complete",
            "dtype_variants": "fast_one" if profile == "fast" else "full",
        },
        "api": {"completeness": "skipped" if profile == "fast" else "partial"},
        "macros": {"completeness": "partial"},
        "lemma_certificate": {
            "assignment_sites_complete": host_complete,
            "call_closure_complete": host_complete,
            "alias_state_exact": False,
            "macro_context_complete": False,
        },
    }


class CodemapQuery:
    """Unified read API over ``indexes/kb_graph.sqlite`` (Host view + graph)."""

    def __init__(self, uo_root: str | Path):
        self.root = Path(uo_root)
        kb = self.root / KB_GRAPH_SQLITE
        if not _kb_has_host_view_tables(kb):
            rebuild_codemap_index(self.root)
        self.db = kb
        self._mode = "kb"
        self._fingerprint = self._load_fingerprint()
        self._completeness = self._load_completeness()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db))

    def _load_fingerprint(self) -> str:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key='graph_fingerprint'"
                ).fetchone()
                return str(row[0]) if row else ""
        except sqlite3.Error:
            return ""

    def _load_completeness(self) -> dict[str, Any]:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key='codemap_completeness'"
                ).fetchone()
                if row:
                    try:
                        payload = json.loads(row[0])
                        if isinstance(payload, dict):
                            return payload
                    except json.JSONDecodeError:
                        pass
                blob = conn.execute(
                    "SELECT data FROM view_blob WHERE name=?",
                    ("codemap/completeness.yaml",),
                ).fetchone()
                if blob:
                    try:
                        payload = json.loads(blob[0])
                        if isinstance(payload, dict):
                            return payload
                    except json.JSONDecodeError:
                        pass
        except sqlite3.Error:
            pass
        return default_codemap_completeness()

    def _result(
        self,
        facts: Iterable[Any],
        *,
        completeness: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        scope: str = "",
    ) -> QueryResult:
        return QueryResult(
            facts=list(facts),
            completeness=completeness or "unknown",
            evidence=list(evidence or []),
            fingerprint=self._fingerprint,
            scope=scope,
        )

    def completeness(self, scope: str = "") -> QueryResult:
        """Return the stored completeness contract (optionally scoped)."""
        payload: Any = self._completeness
        level = "partial"
        if scope:
            parts = scope.split(".")
            cur: Any = self._completeness
            for part in parts:
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    cur = None
                    break
            payload = cur
            if isinstance(cur, str):
                level = cur
            elif isinstance(cur, dict):
                level = str(cur.get("completeness") or cur.get("call_closure") or "partial")
        else:
            lemma = self._completeness.get("lemma_certificate") or {}
            if all(bool(lemma.get(k)) for k in (
                "assignment_sites_complete",
                "call_closure_complete",
                "alias_state_exact",
                "macro_context_complete",
            )):
                level = "complete"
            else:
                level = "partial"
        return self._result(
            [payload] if payload is not None else [],
            completeness=level,
            scope=scope or "codemap",
        )

    def fields(self) -> list[dict[str, Any]]:
        """All host-view fields with writers (and attached guards)."""
        with self._conn() as conn:
            metas = conn.execute(
                "SELECT name, kind, exactness, grade FROM field_meta ORDER BY name"
            ).fetchall()
            writers = conn.execute(
                "SELECT field, path, function, file, line, rhs, via FROM field_writer "
                "ORDER BY field, file, line"
            ).fetchall()
            guards = conn.execute(
                "SELECT file, line, guard FROM field_guard"
            ).fetchall()
        guard_map: dict[tuple[str, int], list[str]] = {}
        for file, line, guard in guards:
            if not guard:
                continue
            guard_map.setdefault((str(file), int(line or 0)), []).append(str(guard))
        by_field: dict[str, dict[str, Any]] = {}
        for name, kind, exactness, grade in metas:
            by_field[str(name)] = {
                "name": str(name),
                "kind": kind,
                "exactness": exactness,
                "grade": grade,
                "writers": [],
            }
        for field_name, path, function, file, line, rhs, via in writers:
            key = str(field_name or path or "")
            row = by_field.setdefault(
                key, {"name": key, "kind": "", "exactness": "", "grade": "", "writers": []}
            )
            g = guard_map.get((str(file), int(line or 0)), [])
            row["writers"].append(
                {
                    "path": path,
                    "function": function,
                    "file": file,
                    "line": line,
                    "rhs": rhs,
                    "via": via,
                    "guards": list(g),
                }
            )
        return list(by_field.values())

    def writers_of(self, symbol: str) -> list[dict[str, Any]]:
        table = "field_writer" if self._mode == "kb" else "writers"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT path, function, file, line, rhs, via FROM {table} "
                "WHERE path LIKE ? OR field LIKE ? ORDER BY file, line",
                (f"%{symbol}%", f"%{symbol}%"),
            ).fetchall()
        return [
            {"path": r[0], "function": r[1], "file": r[2], "line": r[3],
             "rhs": r[4], "via": r[5]}
            for r in rows
        ]

    def writers(self, symbol: str) -> QueryResult:
        host = (self._completeness.get("host") or {}).get("writes") or "partial"
        facts = self.writers_of(symbol)
        return self._result(facts, completeness=str(host), scope=f"writers:{symbol}")

    def guards_at(self, file: str, line: int) -> list[str]:
        table = "field_guard" if self._mode == "kb" else "guards"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT guard FROM {table} WHERE file LIKE ? AND line = ?",
                (f"%{file}%", int(line)),
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def guards(self, file: str, line: int) -> QueryResult:
        facts = [{"guard": g} for g in self.guards_at(file, line)]
        return self._result(facts, completeness="partial", scope=f"guards:{file}:{line}")

    def reads_of(self, field: str) -> list[dict[str, str]]:
        table = "field_read" if self._mode == "kb" else "reads"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT var, root FROM {table} WHERE field = ?", (field,),
            ).fetchall()
        return [{"var": r[0], "root": r[1]} for r in rows]

    def readers(self, field: str) -> QueryResult:
        host = (self._completeness.get("host") or {}).get("reads") or "partial"
        return self._result(
            self.reads_of(field), completeness=str(host), scope=f"reads:{field}"
        )

    def roots(self, field: str) -> QueryResult:
        roots = sorted({r.get("root") for r in self.reads_of(field) if r.get("root")})
        host = (self._completeness.get("host") or {}).get("reads") or "partial"
        return self._result(
            [{"root": r} for r in roots],
            completeness=str(host),
            scope=f"roots:{field}",
        )

    def predicates(self, *, feature_hint: str | None = None) -> list[dict[str, Any]]:
        table = "field_predicate" if self._mode == "kb" else "predicates"
        with self._conn() as conn:
            if feature_hint:
                rows = conn.execute(
                    f"SELECT id, file, line, function, condition, feature_hint "
                    f"FROM {table} WHERE feature_hint = ?",
                    (feature_hint,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT id, file, line, function, condition, feature_hint "
                    f"FROM {table}"
                ).fetchall()
        return [
            {"id": r[0], "file": r[1], "line": r[2], "function": r[3],
             "condition": r[4], "feature_hint": r[5]}
            for r in rows
        ]

    def _function_node_id(self, function: str) -> str | None:
        from uo_init.ids import named_id

        name = str(function or "").strip()
        if not name:
            return None
        return named_id("Function", name)

    def callers_of(self, function: str) -> list[dict[str, Any]]:
        """Callers of ``function`` from first-class ``calls`` edges."""
        # edges where function is the callee
        node_id = self._function_node_id(function)
        if not node_id:
            return []
        short = function.rsplit("::", 1)[-1]
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT e.src, e.dst, e.data, src.name, dst.name FROM edge e "
                "JOIN node src ON src.id = e.src "
                "JOIN node dst ON dst.id = e.dst "
                "WHERE e.kind = 'calls' AND "
                "(e.dst = ? OR dst.name = ? OR dst.name LIKE ?)",
                (node_id, function, f"%{short}"),
            ).fetchall()
        return _expand_call_rows(rows, want="caller")

    def callees_of(self, function: str) -> list[dict[str, Any]]:
        node_id = self._function_node_id(function)
        if not node_id:
            return []
        short = function.rsplit("::", 1)[-1]
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT e.src, e.dst, e.data, src.name, dst.name FROM edge e "
                "JOIN node src ON src.id = e.src "
                "JOIN node dst ON dst.id = e.dst "
                "WHERE e.kind = 'calls' AND "
                "(e.src = ? OR src.name = ? OR src.name LIKE ?)",
                (node_id, function, f"%{short}"),
            ).fetchall()
        return _expand_call_rows(rows, want="callee")

    def callers(self, function: str) -> QueryResult:
        host = (
            ((self._completeness.get("host") or {}).get("functions") or {}).get(
                "call_closure"
            )
            or "partial"
        )
        return self._result(
            self.callers_of(function), completeness=str(host), scope=f"callers:{function}"
        )

    def callees(self, function: str) -> QueryResult:
        host = (
            ((self._completeness.get("host") or {}).get("functions") or {}).get(
                "call_closure"
            )
            or "partial"
        )
        return self._result(
            self.callees_of(function), completeness=str(host), scope=f"callees:{function}"
        )

    def influence(self, symbol: str, *, limit: int = 64) -> QueryResult:
        """Bounded BFS over outbound edges from nodes matching ``symbol``."""
        with self._conn() as conn:
            seeds = [
                r[0]
                for r in conn.execute(
                    "SELECT id FROM node WHERE name LIKE ? OR id LIKE ? LIMIT 16",
                    (f"%{symbol}%", f"%{symbol}%"),
                ).fetchall()
            ]
            seen = set(seeds)
            frontier = list(seeds)
            facts: list[dict[str, Any]] = []
            while frontier and len(facts) < limit:
                cur = frontier.pop(0)
                rows = conn.execute(
                    "SELECT id, kind, src, dst, data FROM edge WHERE src = ?",
                    (cur,),
                ).fetchall()
                for eid, kind, src, dst, data_json in rows:
                    facts.append(
                        {
                            "edge_id": eid,
                            "kind": kind,
                            "src": src,
                            "dst": dst,
                        }
                    )
                    if dst not in seen and len(seen) < limit:
                        seen.add(dst)
                        frontier.append(dst)
                    if len(facts) >= limit:
                        break
        return self._result(facts, completeness="partial", scope=f"influence:{symbol}")

    def path(self, src: str, dst: str, *, limit: int = 32) -> QueryResult:
        """Shortest node path via edges (ids or name substrings)."""
        with self._conn() as conn:
            def resolve(token: str) -> str | None:
                row = conn.execute(
                    "SELECT id FROM node WHERE id = ? OR name = ? LIMIT 1",
                    (token, token),
                ).fetchone()
                if row:
                    return row[0]
                row = conn.execute(
                    "SELECT id FROM node WHERE name LIKE ? OR id LIKE ? LIMIT 1",
                    (f"%{token}%", f"%{token}%"),
                ).fetchone()
                return row[0] if row else None

            start = resolve(src)
            goal = resolve(dst)
            if not start or not goal:
                return self._result([], completeness="unknown", scope=f"path:{src}->{dst}")
            prev: dict[str, str | None] = {start: None}
            queue = [start]
            while queue and len(prev) < limit * 4:
                cur = queue.pop(0)
                if cur == goal:
                    break
                for (nxt,) in conn.execute(
                    "SELECT dst FROM edge WHERE src = ?", (cur,)
                ).fetchall():
                    if nxt not in prev:
                        prev[nxt] = cur
                        queue.append(nxt)
            if goal not in prev:
                return self._result([], completeness="partial", scope=f"path:{src}->{dst}")
            chain = []
            cur: str | None = goal
            while cur is not None:
                chain.append(cur)
                cur = prev.get(cur)
            chain.reverse()
        return self._result(
            [{"nodes": chain}],
            completeness="partial",
            scope=f"path:{src}->{dst}",
        )

    def search(self, text: str, *, limit: int = 32) -> QueryResult:
        q = f"%{text}%"
        with self._conn() as conn:
            nodes = conn.execute(
                "SELECT id, kind, name FROM node WHERE name LIKE ? OR id LIKE ? LIMIT ?",
                (q, q, limit),
            ).fetchall()
            try:
                fts = conn.execute(
                    "SELECT evidence_id, snippet FROM evidence_fts "
                    "WHERE evidence_fts MATCH ? LIMIT ?",
                    (text, limit),
                ).fetchall()
            except sqlite3.Error:
                fts = []
        facts = (
            [{"id": r[0], "kind": r[1], "name": r[2], "match": "node"} for r in nodes]
            + [
                {"id": r[0], "snippet": r[1], "match": "evidence"}
                for r in fts
            ]
        )
        return self._result(facts[:limit], completeness="partial", scope=f"search:{text}")

    def source(self, node_id: str) -> QueryResult:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT e.id, e.file, e.line_start, e.line_end, e.snippet "
                "FROM evidence e "
                "LEFT JOIN node_evidence ne ON ne.evidence_id = e.id "
                "WHERE e.node_id = ? OR ne.node_id = ? OR e.id = ?",
                (node_id, node_id, node_id),
            ).fetchall()
        facts = [
            {
                "id": r[0],
                "file": r[1],
                "line_start": r[2],
                "line_end": r[3],
                "snippet": r[4],
            }
            for r in rows
        ]
        return self._result(facts, completeness="partial", scope=f"source:{node_id}")


def _expand_call_rows(
    rows: list[tuple], *, want: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for src, dst, data_json, src_name, dst_name in rows:
        try:
            data = json.loads(data_json) if data_json else {}
        except json.JSONDecodeError:
            data = {}
        sites = data.get("sites") if isinstance(data.get("sites"), list) else None
        if not sites:
            sites = [data]
        for site in sites:
            if not isinstance(site, dict):
                continue
            out.append(
                {
                    "caller": src_name,
                    "callee": dst_name,
                    "file": site.get("file") or data.get("file") or "",
                    "line": int(site.get("line") or data.get("line") or 0),
                    "guards": list(site.get("guards") or data.get("guards") or []),
                    "args": list(site.get("args") or data.get("args") or []),
                    "receiver": site.get("receiver") or data.get("receiver") or "",
                    "peer": dst_name if want == "callee" else src_name,
                }
            )
    return out


def export_codemap_from_bundle(
    bundle_path: str | Path, uo_root: str | Path
) -> dict[str, Any]:
    """Legacy helper: load a pickled host bundle and export its HostIR.

    Production paths must not call this. Prefer live HostIR from
    ``extract_host_bundle`` / in-process ``_STORE``. Kept for migration
    scripts only.
    """
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
    return export_tg_host_view(
        host_ir, uo_root, derive_fields=derive, declared=declared)
