# -*- coding: utf-8 -*-
"""Read CodeMap / views from a ``.uo`` SQLite product."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

_SHARED_LOCK = threading.Lock()
_SHARED_CONN: OrderedDict[str, sqlite3.Connection] = OrderedDict()
_SHARED_CONN_MAX = 1


def _configure_readonly(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Bound SQLite RAM: no mmap of the whole .uo, ~2MB page cache."""
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = 1")
        conn.execute("PRAGMA cache_size = -2000")
        conn.execute("PRAGMA mmap_size = 0")
        conn.execute("PRAGMA temp_store = MEMORY")
    except sqlite3.Error:
        pass
    return conn


def _connect_readonly(path: str | Path) -> sqlite3.Connection:
    db = Path(path).expanduser().resolve()
    if not db.is_file():
        raise FileNotFoundError(f"missing .uo product: {db}")
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    return _configure_readonly(conn)


def shared_uo(path: str | Path) -> sqlite3.Connection:
    """One live read-only connection per process (evict others).

    Opening a 80MB ``.uo`` per query was the Windows freeze: each connect
    remapped the file and cover queries did that several times per hop.
    """
    key = str(Path(path).expanduser().resolve())
    with _SHARED_LOCK:
        hit = _SHARED_CONN.get(key)
        if hit is not None:
            _SHARED_CONN.move_to_end(key)
            return hit
        while len(_SHARED_CONN) >= _SHARED_CONN_MAX:
            _, old = _SHARED_CONN.popitem(last=False)
            try:
                old.close()
            except sqlite3.Error:
                pass
        conn = _connect_readonly(key)
        _SHARED_CONN[key] = conn
        return conn


def close_uo_connections(path: str | Path | None = None) -> None:
    """Drop the shared query connection(s). Tests and eval harness call this."""
    with _SHARED_LOCK:
        if path is None:
            keys = list(_SHARED_CONN)
        else:
            keys = [str(Path(path).expanduser().resolve())]
        for key in keys:
            conn = _SHARED_CONN.pop(key, None)
            if conn is None:
                continue
            try:
                conn.close()
            except sqlite3.Error:
                pass

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.evidence import (
    SOURCE_UNSPECIFIED,
    STATE_RESOLVED,
    TRUST_LEGACY_UNKNOWN,
)
from uo_init.ir.relation import Relation, RelationKind


def _legacy_trust_attrs(attrs: dict[str, Any], *, legacy: bool) -> dict[str, Any]:
    """v1 products: missing trust is unknown, not lexical. v2 keeps stored fields."""
    if not legacy:
        return attrs
    if str(attrs.get("trust") or "") in {TRUST_LEGACY_UNKNOWN, "authoritative", "derived", "advisory"}:
        return attrs
    attrs["trust"] = TRUST_LEGACY_UNKNOWN
    attrs.setdefault("evidence_source", SOURCE_UNSPECIFIED)
    attrs.setdefault("semantic_state", STATE_RESOLVED)
    return attrs


def open_uo(path: str | Path) -> sqlite3.Connection:
    """Exclusive short-lived connection. Caller must ``close()``."""
    return _connect_readonly(path)


def read_meta(path: str | Path) -> dict[str, str]:
    conn = shared_uo(path)
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    return {str(r["key"]): str(r["value"]) for r in rows}


def read_codemap(path: str | Path) -> CodeMap:
    conn = open_uo(path)
    try:
        meta = {str(r["key"]): str(r["value"]) for r in conn.execute("SELECT key, value FROM meta")}
        cm = CodeMap(
            op_name=meta.get("op_name") or "",
            architecture=meta.get("architecture") or "",
        )
        cm.meta = {k[3:]: _maybe_json(v) for k, v in meta.items() if k.startswith("cm_")}
        schema = str(meta.get("schema") or "")
        legacy = schema != "codemap-uo/v2"
        if legacy:
            cm.meta["trust_model"] = "legacy_unknown"
        for row in conn.execute(
            "SELECT id, kind, name, status, confidence, file, line_start, line_end, data FROM entity"
        ):
            data = json.loads(row["data"] or "{}")
            attrs = {
                k: v
                for k, v in data.items()
                if k
                not in {
                    "id",
                    "kind",
                    "name",
                    "status",
                    "confidence",
                    "file",
                    "line_start",
                    "line_end",
                }
            }
            kind_name = str(row["kind"])
            try:
                kind: EntityKind | str = EntityKind(kind_name)
            except ValueError:
                kind = kind_name
            cm.add_entity(
                Entity(
                    id=str(row["id"]),
                    kind=kind,
                    name=str(row["name"] or ""),
                    attrs=_legacy_trust_attrs(attrs, legacy=legacy),
                    file=str(row["file"] or ""),
                    line_start=int(row["line_start"] or 0),
                    line_end=int(row["line_end"] or 0),
                    status=str(row["status"] or "extracted"),
                    confidence=float(row["confidence"] or 1.0),
                )
            )
        for row in conn.execute(
            "SELECT id, kind, src, dst, status, confidence, data FROM relation"
        ):
            data = json.loads(row["data"] or "{}")
            attrs = {
                k: v
                for k, v in data.items()
                if k not in {"id", "kind", "src", "dst", "status", "confidence"}
            }
            kind_name = str(row["kind"])
            try:
                rkind: RelationKind | str = RelationKind(kind_name)
            except ValueError:
                rkind = kind_name
            cm.relations[str(row["id"])] = Relation(
                id=str(row["id"]),
                kind=rkind,
                src=str(row["src"]),
                dst=str(row["dst"]),
                attrs=_legacy_trust_attrs(attrs, legacy=legacy),
                status=str(row["status"] or "extracted"),
                confidence=float(row["confidence"] or 1.0),
            )
        return cm
    finally:
        conn.close()


def load_view_blob(
    path: str | Path,
    name: str,
    *,
    expand_legal_keys: bool = True,
) -> Any | None:
    conn = shared_uo(path)
    row = conn.execute(
        "SELECT data FROM view_blob WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        return None
    blob = json.loads(row["data"])
    if (
        expand_legal_keys
        and name == "tiling/legal_key_index.jsonl"
        and isinstance(blob, dict)
    ):
        from uo_init.query.legal_key_cache import expand_legal_key_rows

        blob = dict(blob)
        blob["rows"] = expand_legal_key_rows(blob)
    return blob


def load_production_view(path: str | Path, name: str) -> Any | None:
    """Load a view for production callers. Stale blobs are never returned."""
    checked = load_view_blob_checked(path, name)
    if checked.get("ok"):
        return checked.get("view")
    return None


def _architecture_from_uo_name(path: Path) -> str:
    from uo_init.source_layout import is_product_architecture

    name = path.name
    if not name.endswith(".uo"):
        return ""
    stem = name[: -len(".uo")]
    parts = stem.rsplit(".", 1)
    if len(parts) == 2 and is_product_architecture(parts[1]):
        return parts[1]
    return ""


def load_view_blob_checked(
    path: str | Path,
    name: str,
    *,
    codemap: CodeMap | None = None,
    fallback_canonical: bool = True,
    expand_legal_keys: bool = True,
) -> dict[str, Any]:
    """Load a projection with fail-closed provenance validation.

    A stale/legacy blob is never returned as the usable ``view``.  Known
    projections are rebuilt from the canonical CodeMap engine-side; unknown
    projections return ``view=None`` so callers cannot accidentally consume an
    unverifiable shortcut.  ``stale_blob`` is retained only for diagnostics.
    """
    from uo_init.projection_provenance import (
        LEGACY_VIEW_UNVERIFIED,
        VIEW_STALE,
        validate_view_against_codemap,
    )
    from uo_init.tg_views import (
        finalize_tg_views,
        project_kernel_view,
        project_operator_graph,
        project_tilingdata_view,
        project_tg_host_view,
    )

    blob = load_view_blob(path, name, expand_legal_keys=expand_legal_keys)
    if blob is None:
        return {"ok": False, "reason_code": "VIEW_MISSING", "name": name, "view": None}
    stored_digest = str(_maybe_json(read_meta(path).get("cm_canonical_graph_digest") or "") or "")
    prov = blob.get("provenance") if isinstance(blob, dict) else None
    actual_digest = str((prov or {}).get("canonical_graph_digest") or "") if isinstance(prov, dict) else ""
    if stored_digest and actual_digest and stored_digest == actual_digest:
        return {"ok": True, "reason_code": "", "name": name, "view": blob}
    if codemap is None and not fallback_canonical:
        return {
            "ok": False,
            "reason_code": VIEW_STALE if actual_digest else LEGACY_VIEW_UNVERIFIED,
            "name": name,
            "view": None,
            "stale_blob": blob,
            "check": {
                "ok": False,
                "reason_code": "DIGEST_META_MISMATCH",
                "expected": {"canonical_graph_digest": stored_digest},
                "actual": {"canonical_graph_digest": actual_digest},
            },
        }
    cm = codemap if codemap is not None else read_codemap(path)
    check = validate_view_against_codemap(blob, cm)
    if check.get("ok"):
        return {"ok": True, "reason_code": "", "name": name, "view": blob}
    result: dict[str, Any] = {
        "ok": False,
        "reason_code": check.get("reason_code") or VIEW_STALE,
        "name": name,
        "view": None,
        "stale_blob": blob,
        "check": check,
    }
    if not fallback_canonical:
        return result
    rebuilt: Any = None
    if name == "ir/operator_graph.yaml":
        rebuilt = project_operator_graph(cm)
    elif name == "ir/tg_host_view.yaml":
        rebuilt = project_tg_host_view(cm)
    elif name == "views/kernel.yaml":
        rebuilt = project_kernel_view(cm)
    elif name == "views/tilingdata.yaml":
        rebuilt = project_tilingdata_view(cm)
    elif name == "summary":
        rebuilt = {
            "entity_count": len(cm.entities),
            "relation_count": len(cm.relations),
            "graph_fingerprint": cm.meta.get("graph_fingerprint"),
        }
    if rebuilt is not None:
        from uo_init.projection_provenance import stamp_provenance

        # Ensure fingerprint meta exists for stamp.
        if not cm.meta.get("graph_fingerprint"):
            finalize_tg_views(cm, existing={})
        result["ok"] = True
        result["fallback"] = "canonical"
        result["view"] = stamp_provenance(rebuilt, cm)
    return result


def list_views(path: str | Path) -> list[str]:
    conn = shared_uo(path)
    return [str(r["name"]) for r in conn.execute("SELECT name FROM view_blob ORDER BY name")]


def find_uo_product(
    op_root: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
) -> Path | None:
    """Locate the CodeMap product ``.ascendc-pilot/<arch>/uo/<op>.<arch>.uo``.

    Production authority is arch-scoped ``*.<arch>.uo`` only. Top-level
    ``.ascendc-pilot/uo/*.uo`` and ``indexes/kb_graph.sqlite`` are not products.

    Without ``architecture``, only a unique arch among candidates is accepted.
    Multiple arches never return ``candidates[0]`` (arch22 would sort first).
    """
    from uo_init.store.writer import uo_product_dir, uo_product_path

    root = Path(op_root).expanduser().resolve()
    if root.is_file() and root.suffix == ".uo":
        arch = (architecture or "").strip()
        if arch and not root.name.endswith(f".{arch}.uo"):
            return None
        if op_name and not root.name.startswith(f"{op_name}."):
            return None
        return root

    search_dirs: list[Path] = []
    arch = (architecture or "").strip()

    def _add_dir(path: Path) -> None:
        if path not in search_dirs:
            search_dirs.append(path)

    from uo_init.source_layout import is_product_architecture

    if root.is_dir():
        # Already standing in a uo product directory or an arch / default slot.
        if root.name == "uo" or is_product_architecture(root.name):
            _add_dir(root)
        if is_product_architecture(root.name) and (root / "uo").is_dir():
            _add_dir(root / "uo")

    if op_name and arch:
        try:
            p = uo_product_path(root, op_name, arch)
            if p.is_file():
                return p
        except Exception:
            pass

    if arch:
        try:
            _add_dir(uo_product_dir(root, architecture=arch))
        except Exception:
            _add_dir(root / ".ascendc-pilot" / arch / "uo")
        _add_dir(root / ".ascendc-pilot" / arch / "uo")

    pilot = root / ".ascendc-pilot"
    if not pilot.is_dir() and root.name == "uo" and is_product_architecture(root.parent.name):
        # ``<op>/.ascendc-pilot/<arch|default>/uo`` → climb to op root's pilot dir.
        maybe_pilot = root.parent.parent
        if maybe_pilot.name == ".ascendc-pilot":
            pilot = maybe_pilot
            root = maybe_pilot.parent
    if not pilot.is_dir() and root.name == ".ascendc-pilot":
        pilot = root

    if pilot.is_dir():
        for child in sorted(pilot.iterdir()):
            if child.is_dir() and is_product_architecture(child.name):
                _add_dir(child / "uo")
        # Intentionally skip legacy top-level ``.ascendc-pilot/uo/``.

    candidates: list[Path] = []
    seen: set[Path] = set()
    for product_dir in search_dirs:
        if not product_dir.is_dir():
            continue
        for p in sorted(product_dir.glob("*.uo")):
            if p.is_file() and p not in seen:
                seen.add(p)
                candidates.append(p)

    if arch:
        narrowed = [c for c in candidates if c.name.endswith(f".{arch}.uo")]
        if narrowed:
            if op_name:
                for c in narrowed:
                    if c.name.startswith(f"{op_name}."):
                        return c
            if len(narrowed) == 1:
                return narrowed[0]
            # Same arch can leave both snake_case and CamelCase products after
            # discover() spelling changes. The newest commit is the authority.
            return max(narrowed, key=lambda p: p.stat().st_mtime)
        return None
    by_arch: dict[str, list[Path]] = {}
    for c in candidates:
        a = _architecture_from_uo_name(c)
        if not a:
            continue
        by_arch.setdefault(a, []).append(c)
    if len(by_arch) != 1:
        return None
    arch_candidates = next(iter(by_arch.values()))
    if op_name:
        for c in arch_candidates:
            if c.name.startswith(f"{op_name}."):
                return c
        return None
    if len(arch_candidates) == 1:
        return arch_candidates[0]
    return None


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text
