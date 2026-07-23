"""Hard isolation + KB fingerprint for TG↔UO boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .io import read_yaml, write_yaml

UO_MARKERS = (".ascendc-pilot", "uo")  # refuse writes under .../.ascendc-pilot/uo/...


class IsolationError(PermissionError):
    """Raised when TG attempts to write under UO_ROOT."""


def _is_uo_tree(resolved: Path) -> bool:
    parts = resolved.parts
    if ".ascendc-pilot" in parts:
        try:
            idx = parts.index(".ascendc-pilot")
        except ValueError:
            return False
        return idx + 1 < len(parts) and parts[idx + 1] == "uo"
    return False


def assert_tg_write_path(path: Path | str, *, out_root: Path | None = None) -> Path:
    """Refuse writes under UO graph. Optionally require under out_root."""
    resolved = Path(path).expanduser().resolve()
    if _is_uo_tree(resolved):
        raise IsolationError(
            f"TG isolation: refuse write under $UO_ROOT (.ascendc-pilot/uo): {resolved}. "
            "CSV mapping / bind artifacts must stay under $TG_ROOT (.ascendc-pilot/tg)."
        )
    if out_root is not None:
        root = Path(out_root).expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise IsolationError(
                f"TG isolation: write path {resolved} is outside OUT_ROOT {root}"
            ) from exc
    return resolved


def compute_kb_fingerprint(uo_root: Path) -> dict[str, Any]:
    """Stable fingerprint of a finalized UO KB (read-only)."""
    root = Path(uo_root).expanduser().resolve()
    hashes: dict[str, str] = {}
    artifact_path = root / "checks" / "artifact_hashes.yaml"
    if artifact_path.is_file():
        doc = read_yaml(artifact_path)
        if isinstance(doc, dict):
            raw = doc.get("hashes") or doc.get("files") or {}
            if isinstance(raw, dict):
                hashes = {str(k): str(v) for k, v in raw.items()}

    revision = ""
    manifest_path = root / "manifest.yaml"
    if manifest_path.is_file():
        manifest = read_yaml(manifest_path)
        if isinstance(manifest, dict):
            source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
            revision = str(source.get("revision") or manifest.get("revision") or "")

    integrity_status = ""
    integrity_path = root / "checks" / "integrity.yaml"
    if integrity_path.is_file():
        integrity = read_yaml(integrity_path)
        if isinstance(integrity, dict):
            integrity_status = str(integrity.get("status") or "")

    confidence_status = ""
    conf_path = root / "checks" / "confidence_gate.yaml"
    if conf_path.is_file():
        conf = read_yaml(conf_path)
        if isinstance(conf, dict):
            confidence_status = str(conf.get("status") or "")

    sqlite_sha = ""
    sqlite_path = root / "indexes" / "kb_graph.sqlite"
    if sqlite_path.is_file():
        h = hashlib.sha256()
        with sqlite_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        sqlite_sha = h.hexdigest()

    payload = {
        "artifact_hashes": dict(sorted(hashes.items())),
        "revision": revision,
        "integrity_status": integrity_status,
        "confidence_status": confidence_status,
        "kb_graph_sha256": sqlite_sha,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "version": 1,
        "uo_root": root.as_posix(),
        "digest": digest,
        "revision": revision,
        "integrity_status": integrity_status,
        "confidence_status": confidence_status,
        "kb_graph_sha256": sqlite_sha,
        "artifact_hash_count": len(hashes),
    }


def write_kb_fingerprint(out_root: Path, uo_root: Path) -> dict[str, Any]:
    """Write fingerprint under OUT_ROOT only (never touches UO)."""
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
