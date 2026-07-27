from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def require_yaml() -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    return yaml


def _loader() -> Any:
    require_yaml()
    return getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _dumper() -> Any:
    require_yaml()
    return getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def _render_yaml(data: dict[str, Any]) -> str:
    require_yaml()
    return yaml.dump(
        data,
        Dumper=_dumper(),
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )


def _semantic_digest(data: dict[str, Any]) -> str:
    """Stable, cheap content key used only to avoid redundant YAML serialization.

    JSON-compatible IR payloads take the fast path. Unusual values fall back to a
    deterministic repr so callers never fail merely because caching is unavailable.
    The sidecar is trusted only while the destination file stat still matches.
    """

    try:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        raw = repr(data)
    return hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()


def _hash_sidecar(path: Path) -> Path:
    import os
    import tempfile

    root = Path(os.environ.get("ASCENDC_PILOT_CACHE_DIR") or tempfile.gettempdir())
    cache_dir = root / "ascendc-pilot" / "yaml-hashes"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(path.resolve()).encode("utf-8", errors="surrogatepass")).hexdigest()
    return cache_dir / f"{key}.json"


def _read_hash_sidecar(path: Path) -> dict[str, Any]:
    sidecar = _hash_sidecar(path)
    if not sidecar.is_file() or not path.is_file():
        return {}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        stat = path.stat()
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if int(payload.get("size") or -1) != int(stat.st_size):
        return {}
    if int(payload.get("mtime_ns") or -1) != int(stat.st_mtime_ns):
        return {}
    return payload


def _write_hash_sidecar(path: Path, digest: str) -> None:
    try:
        stat = path.stat()
        payload = {
            "version": 1,
            "digest": digest,
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
        sidecar = _hash_sidecar(path)
        sidecar.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except OSError:
        # Sidecars are an optimization only; artifact writes remain authoritative.
        pass


def _payload_unchanged(path: Path, data: dict[str, Any], digest: str | None = None) -> bool:
    if not path.is_file():
        return False
    digest = digest or _semantic_digest(data)
    cached = _read_hash_sidecar(path)
    return bool(cached and cached.get("digest") == digest)


def read_yaml(path: Path) -> dict[str, Any]:
    require_yaml()
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    # extract_plan / other IR with embedded code: sanitize `|` blocks first.
    name = path.name.lower()
    if name in {"extract_plan.yaml", "semantic_patches.yaml"} or name.endswith(
        "_plan.yaml"
    ):
        from uo.scripts.yaml_literal_sanitize import safe_load_yaml_text

        data = safe_load_yaml_text(text) or {}
    else:
        data = yaml.load(text, Loader=_loader()) or {}
    return data if isinstance(data, dict) else {}


def write_yaml_if_changed(path: Path, data: dict[str, Any]) -> bool:
    """Write YAML only when semantic content changed.

    Returns ``True`` when the file was replaced and ``False`` on a proven no-op.
    The stat-validated sidecar prevents stale cache hits after external edits.
    """

    require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = _semantic_digest(data)
    if _payload_unchanged(path, data, digest):
        return False
    rendered = _render_yaml(data)
    # Bootstrap compatibility for artifacts written before sidecars existed.
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == rendered:
                _write_hash_sidecar(path, digest)
                return False
        except OSError:
            pass
    path.write_text(rendered, encoding="utf-8")
    _write_hash_sidecar(path, digest)
    return True


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    write_yaml_if_changed(path, data)


def atomic_write_yaml(path: Path, data: dict[str, Any]) -> bool:
    """Write YAML via temp file + os.replace, skipping proven no-op payloads."""
    import os
    import tempfile

    require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = _semantic_digest(data)
    if _payload_unchanged(path, data, digest):
        return False
    text = _render_yaml(data)
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == text:
                _write_hash_sidecar(path, digest)
                return False
        except OSError:
            pass
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        _write_hash_sidecar(path, digest)
        return True
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_replace_files(replacements: list[tuple[Path, Path]]) -> None:
    """Atomically replace dest with prepared temp paths. On failure, leave dests untouched.

    ``replacements`` is a list of ``(temp_path, dest_path)``. All temps must already
    contain the final content. Uses os.replace per pair; if a later replace fails,
    earlier dests may already be updated — callers should stage ALL content first
    and prefer ``commit_semantic_artifacts`` for multi-file semantic tx.
    """
    import os

    for tmp, dest in replacements:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)


def commit_semantic_artifacts(
    uo_root: Path,
    *,
    llm_tasks: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    apply_report: dict[str, Any] | None = None,
) -> None:
    """Transactionally update changed semantic artifacts only.

    Unchanged members are excluded before staging. Changed members retain the prior
    all-or-nothing backup/restore behavior.
    """
    import os
    import shutil
    import tempfile

    require_yaml()
    ir = uo_root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    mapping = [
        (llm_tasks, ir / "llm_tasks.yaml"),
        (ledger, ir / "semantic_resolution_ledger.yaml"),
        (apply_report, ir / "semantic_apply_report.yaml"),
    ]
    changed: list[tuple[dict[str, Any], Path, str, str]] = []
    for payload, dest in mapping:
        if payload is None:
            continue
        digest = _semantic_digest(payload)
        if _payload_unchanged(dest, payload, digest):
            continue
        text = _render_yaml(payload)
        if dest.is_file():
            try:
                if dest.read_text(encoding="utf-8") == text:
                    _write_hash_sidecar(dest, digest)
                    continue
            except OSError:
                pass
        changed.append((payload, dest, text, digest))
    if not changed:
        return

    staged: list[tuple[Path, Path, str]] = []
    backups: list[tuple[Path, Path | None]] = []
    temps: list[Path] = []
    try:
        for _payload, dest, text, digest in changed:
            fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(ir))
            tmp_path = Path(tmp_name)
            temps.append(tmp_path)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            backup: Path | None = None
            if dest.is_file():
                fd_b, bak_name = tempfile.mkstemp(prefix=f".{dest.name}.bak.", suffix=".tmp", dir=str(ir))
                os.close(fd_b)
                backup = Path(bak_name)
                shutil.copy2(dest, backup)
                temps.append(backup)
            staged.append((tmp_path, dest, digest))
            backups.append((dest, backup))
        replaced: list[Path] = []
        try:
            for tmp_path, dest, _digest in staged:
                os.replace(tmp_path, dest)
                replaced.append(dest)
                temps = [t for t in temps if t != tmp_path]
        except Exception:
            for dest, backup in backups:
                if dest in replaced and backup is not None and backup.is_file():
                    os.replace(backup, dest)
                    temps = [t for t in temps if t != backup]
            raise
        for _tmp, dest, digest in staged:
            _write_hash_sidecar(dest, digest)
        for _, backup in backups:
            if backup is not None:
                try:
                    backup.unlink(missing_ok=True)
                except OSError:
                    pass
                temps = [t for t in temps if t != backup]
    except Exception:
        for t in temps:
            try:
                t.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def stable_id(prefix: str, *parts: str) -> str:
    text = "_".join(str(part) for part in parts if str(part).strip())
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_").upper()
    return f"{prefix}{cleaned or 'UNKNOWN'}"


def snippet(text: str, *, max_chars: int = 400) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."
