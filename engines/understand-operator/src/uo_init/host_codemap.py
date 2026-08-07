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

The single SQLite authority is ``indexes/kb_graph.sqlite``. Legacy
``host_codemap.yaml`` / ``host_codemap.sqlite`` aliases are no longer written.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

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
    """Load the TG host view (``tg_host_view.yaml`` only)."""
    root = Path(uo_root)
    path = root / TG_HOST_VIEW_YAML
    if path.is_file():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Read-only fallback for older checkouts that still have the alias.
    legacy = root / CODEMAP_YAML
    if legacy.is_file():
        return yaml.safe_load(legacy.read_text(encoding="utf-8")) or {}
    return {}


def load_tg_host_view(uo_root: str | Path) -> dict[str, Any]:
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


class CodemapQuery:
    """Read-only queries over the TG host-view projection in kb_graph.sqlite."""

    def __init__(self, uo_root: str | Path):
        self.root = Path(uo_root)
        kb = self.root / KB_GRAPH_SQLITE
        if not _kb_has_host_view_tables(kb):
            rebuild_codemap_index(self.root)
        self.db = kb
        self._mode = "kb"

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db))

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

    def guards_at(self, file: str, line: int) -> list[str]:
        table = "field_guard" if self._mode == "kb" else "guards"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT guard FROM {table} WHERE file LIKE ? AND line = ?",
                (f"%{file}%", int(line)),
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def reads_of(self, field: str) -> list[dict[str, str]]:
        table = "field_read" if self._mode == "kb" else "reads"
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT var, root FROM {table} WHERE field = ?", (field,),
            ).fetchall()
        return [{"var": r[0], "root": r[1]} for r in rows]

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

    def callers_of(self, function: str) -> list[dict[str, Any]]:
        """Deprecated in v2: call graph lives in the navigation layer.

        Kept as an empty list so old call sites do not crash; use UO graph queries.
        """
        del function
        return []


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
