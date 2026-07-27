from __future__ import annotations

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
        data = yaml.safe_load(text) or {}
    return data if isinstance(data, dict) else {}


def _render_yaml(data: dict[str, Any]) -> str:
    require_yaml()
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def _content_hash_path(path: Path) -> Path:
    return path.with_name(path.name + ".content-hash")


def _invalidate_content_hash(path: Path) -> None:
    """Drop sidecar so write_yaml_if_changed cannot reuse a stale digest."""
    try:
        _content_hash_path(path).unlink(missing_ok=True)
    except OSError:
        pass


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_yaml(data), encoding="utf-8")
    _invalidate_content_hash(path)


def _stable_payload_hash(data: dict[str, Any]) -> str:
    import hashlib
    import json

    raw = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_content_hash_sidecar(hash_path: Path) -> dict[str, Any]:
    """Parse sidecar; supports legacy plain-digest and structured YAML."""
    require_yaml()
    try:
        text = hash_path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not text:
        return {}
    if "\n" not in text and ":" not in text and len(text) == 64:
        return {"desired_content_hash": text, "schema_version": 0}
    try:
        data = yaml.safe_load(text) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {"desired_content_hash": text.splitlines()[0].strip(), "schema_version": 0}


def write_yaml_if_changed(path: Path, data: dict[str, Any]) -> bool:
    """Write YAML only when structured content hash differs. Returns True if written.

    Crash-safe protocol:
    1. invalidate old sidecar
    2. write temp YAML + temp sidecar (desired_content_hash + actual_yaml_sha256)
    3. fsync
    4. os.replace YAML then sidecar

    Skip only when sidecar.actual_yaml_sha256 matches on-disk YAML SHA **and**
    desired_content_hash matches the incoming payload digest.
    """
    import os
    import tempfile

    digest = _stable_payload_hash(data)
    hash_path = _content_hash_path(path)
    if path.is_file() and hash_path.is_file():
        meta = _read_content_hash_sidecar(hash_path)
        desired = str(meta.get("desired_content_hash") or "").strip()
        actual = str(meta.get("actual_yaml_sha256") or "").strip()
        try:
            file_sha = _file_sha256(path)
        except OSError:
            file_sha = ""
        # Fail-closed: legacy sidecars without actual_yaml_sha256 never skip.
        if (
            desired == digest
            and actual
            and file_sha
            and actual == file_sha
            and int(meta.get("schema_version") or 0) >= 1
        ):
            return False

    text = _render_yaml(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    _invalidate_content_hash(path)

    fd_y, tmp_y = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    fd_h, tmp_h = tempfile.mkstemp(prefix=f".{hash_path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        import hashlib

        yaml_bytes = text.encode("utf-8")
        # Binary write avoids Windows text-mode newline translation skewing SHA.
        with os.fdopen(fd_y, "wb") as fh:
            fh.write(yaml_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        yaml_sha = hashlib.sha256(yaml_bytes).hexdigest()
        sidecar = {
            "schema_version": 1,
            "desired_content_hash": digest,
            "actual_yaml_sha256": yaml_sha,
        }
        side_bytes = _render_yaml(sidecar).encode("utf-8")
        with os.fdopen(fd_h, "wb") as fh:
            fh.write(side_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_y, path)
        os.replace(tmp_h, hash_path)
    except Exception:
        for tmp in (tmp_y, tmp_h):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise
    return True


def atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write YAML via temp file + os.replace (crash-safe single-file update)."""
    import os
    import tempfile

    require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        _invalidate_content_hash(path)
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
    """Transactionally update llm_tasks / ledger / apply_report (all-or-nothing).

    Stages all payloads to temp files, backups existing dests, then replaces.
    On mid-replace failure, restores from backups so no half-updated trio remains.
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
    staged: list[tuple[Path, Path]] = []
    backups: list[tuple[Path, Path | None]] = []
    temps: list[Path] = []
    try:
        for payload, dest in mapping:
            if payload is None:
                continue
            text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=120)
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
            staged.append((tmp_path, dest))
            backups.append((dest, backup))
        replaced: list[Path] = []
        try:
            for tmp_path, dest in staged:
                os.replace(tmp_path, dest)
                _invalidate_content_hash(dest)
                replaced.append(dest)
                temps = [t for t in temps if t != tmp_path]
        except Exception:
            # Restore any already-replaced dests from backups.
            for dest, backup in backups:
                if dest in replaced and backup is not None and backup.is_file():
                    os.replace(backup, dest)
                    temps = [t for t in temps if t != backup]
            raise
        # Success: drop backups.
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
