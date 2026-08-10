"""Hard isolation + product fingerprint for the TG↔UO boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .io import read_yaml, write_yaml


class IsolationError(PermissionError):
    """Raised when TG attempts to write into either UO namespace."""


def _is_uo_tree(resolved: Path) -> bool:
    """Match both the formal product tree and the retired arch work tree."""
    parts = resolved.parts
    try:
        idx = parts.index(".ascendc-pilot")
    except ValueError:
        return False
    tail = parts[idx + 1 :]
    if not tail:
        return False
    # <op>/.ascendc-pilot/uo/**
    if tail[0] == "uo":
        return True
    # <op>/.ascendc-pilot/<arch>/uo/**
    return len(tail) >= 2 and tail[1] == "uo"


def assert_tg_write_path(path: Path | str, *, out_root: Path | None = None) -> Path:
    resolved = Path(path).expanduser().resolve()
    if _is_uo_tree(resolved):
        raise IsolationError(
            f"UO_ROOT: TG isolation refuses write under UO authority/work tree: {resolved}. "
            "TG artifacts must stay under .ascendc-pilot/<arch>/tg."
        )
    if out_root is not None:
        root = Path(out_root).expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise IsolationError(f"TG isolation: write path {resolved} is outside OUT_ROOT {root}") from exc
    return resolved


def _project_from_uo_hint(uo_hint: Path) -> tuple[Path | None, str]:
    """Recover operator root and arch from old/new UO path shapes."""
    root = Path(uo_hint).expanduser().resolve()
    parts = root.parts
    try:
        idx = parts.index(".ascendc-pilot")
    except ValueError:
        return None, ""
    project = Path(*parts[:idx]) if idx > 0 else Path(root.anchor)
    tail = parts[idx + 1 :]
    arch = ""
    if len(tail) >= 2 and tail[1] == "uo":
        arch = str(tail[0])
    return project, arch


def _product_fingerprint(uo_hint: Path) -> dict[str, Any] | None:
    project, arch = _project_from_uo_hint(uo_hint)
    if project is None:
        return None
    try:
        from testcase_agent import product_uo

        ident = product_uo.identity(project, architecture=arch)
    except Exception:
        return None
    sha = str(ident.get("sha256") or "")
    if not sha:
        return None
    # The product byte digest is the lock. Metadata is explanatory, not a
    # second mutable authority that can drift independently.
    return {
        "version": 2,
        "authority": "uo_product",
        "uo_product": str(ident.get("path") or ""),
        "digest": sha,
        "uo_sha256": sha,
        "revision": str(ident.get("revision") or ""),
        "graph_fingerprint": str(ident.get("graph_fingerprint") or ""),
        "op_name": str(ident.get("op_name") or ""),
        "architecture": str(ident.get("architecture") or arch),
    }


def _meta_from_sqlite(sqlite_path: Path) -> dict[str, str]:
    try:
        import sqlite3

        conn = sqlite3.connect(str(sqlite_path))
        try:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
            return {str(k): str(v) for k, v in rows}
        finally:
            conn.close()
    except Exception:
        return {}


def _view_blob_from_sqlite(sqlite_path: Path, name: str) -> dict[str, Any] | None:
    try:
        import sqlite3

        conn = sqlite3.connect(str(sqlite_path))
        try:
            row = conn.execute("SELECT data FROM view_blob WHERE name=?", (name,)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        payload = json.loads(row[0])
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _legacy_fingerprint(uo_root: Path) -> dict[str, Any]:
    """Compatibility fingerprint for old fixtures that predate ``.uo``."""
    root = Path(uo_root).expanduser().resolve()
    hashes: dict[str, str] = {}
    artifact_path = root / "checks" / "artifact_hashes.yaml"
    if artifact_path.is_file():
        doc = read_yaml(artifact_path)
        if isinstance(doc, dict):
            raw = doc.get("hashes") or doc.get("files") or {}
            if isinstance(raw, dict):
                hashes = {str(k): str(v) for k, v in raw.items()}

    revision = authority = graph_fingerprint = integrity_status = confidence_status = ""
    manifest_path = root / "manifest.yaml"
    if manifest_path.is_file():
        manifest = read_yaml(manifest_path)
        if isinstance(manifest, dict):
            source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
            revision = str(source.get("revision") or manifest.get("revision") or "")
            authority = str(manifest.get("authority") or "")
            graph_fingerprint = str(manifest.get("graph_fingerprint") or "")
    for rel, key in (("checks/integrity.yaml", "integrity"), ("checks/confidence_gate.yaml", "confidence")):
        doc = read_yaml(root / rel) if (root / rel).is_file() else {}
        if isinstance(doc, dict):
            if key == "integrity":
                integrity_status = str(doc.get("status") or "")
            else:
                confidence_status = str(doc.get("status") or "")

    sqlite_sha = ""
    sqlite_path = root / "indexes" / "kb_graph.sqlite"
    if sqlite_path.is_file():
        sqlite_sha = hashlib.sha256(sqlite_path.read_bytes()).hexdigest()
        meta = _meta_from_sqlite(sqlite_path)
        authority = authority or str(meta.get("authority") or "")
        graph_fingerprint = graph_fingerprint or str(meta.get("graph_fingerprint") or "")
        integrity_status = integrity_status or str(meta.get("integrity_status") or "")
        if not hashes:
            blob = _view_blob_from_sqlite(sqlite_path, "checks/artifact_hashes.yaml")
            if isinstance(blob, dict):
                raw = blob.get("hashes") or blob.get("files") or {}
                if isinstance(raw, dict):
                    hashes = {str(k): str(v) for k, v in raw.items()}
        revision = revision or str(meta.get("revision") or "")

    payload = {
        "artifact_hashes": dict(sorted(hashes.items())),
        "revision": revision,
        "integrity_status": integrity_status,
        "confidence_status": confidence_status,
        "kb_graph_sha256": sqlite_sha,
        "authority": authority,
        "graph_fingerprint": graph_fingerprint,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "version": 1,
        "authority": authority or "legacy_uo_export",
        "uo_root": root.as_posix(),
        "digest": digest,
        "revision": revision,
        "integrity_status": integrity_status,
        "confidence_status": confidence_status,
        "kb_graph_sha256": sqlite_sha,
        "graph_fingerprint": graph_fingerprint,
        "artifact_hash_count": len(hashes),
    }


def compute_kb_fingerprint(uo_root: Path) -> dict[str, Any]:
    """Fingerprint the formal ``.uo`` whenever one exists.

    ``uo_root`` remains an argument only for compatibility with the old TG API;
    it is treated as a project/arch hint, not as the production authority.
    An empty or absent tree yields ``digest=""`` so confirm can fail closed.
    """
    product = _product_fingerprint(Path(uo_root))
    if product is not None:
        return product
    root = Path(uo_root).expanduser().resolve()
    legacy = _legacy_fingerprint(root)
    has_authority = bool(
        legacy.get("kb_graph_sha256")
        or int(legacy.get("artifact_hash_count") or 0) > 0
        or (root / "manifest.yaml").is_file()
    )
    if has_authority:
        return legacy
    return {
        "version": 2,
        "authority": "missing",
        "digest": "",
        "uo_root": root.as_posix(),
        "reason": "no_uo_product_or_legacy_export",
    }


def write_kb_fingerprint(out_root: Path, uo_root: Path) -> dict[str, Any]:
    fp = compute_kb_fingerprint(uo_root)
    path = Path(out_root) / "init" / "kb_fingerprint.yaml"
    assert_tg_write_path(path, out_root=out_root)
    write_yaml(path, fp)
    return fp


def read_kb_fingerprint(out_root: Path) -> dict[str, Any]:
    path = Path(out_root) / "init" / "kb_fingerprint.yaml"
    if not path.is_file():
        return {}
    data = read_yaml(path)
    return data if isinstance(data, dict) else {}


def kb_fingerprint_matches(out_root: Path, uo_root: Path) -> tuple[bool, dict[str, Any]]:
    stored = read_kb_fingerprint(out_root)
    current = compute_kb_fingerprint(uo_root)
    if not stored or not stored.get("digest"):
        return False, {"stored": stored, "current": current, "reason": "missing_fingerprint"}
    ok = str(stored.get("digest")) == str(current.get("digest"))
    return ok, {"stored": stored, "current": current, "reason": "" if ok else "digest_mismatch"}
