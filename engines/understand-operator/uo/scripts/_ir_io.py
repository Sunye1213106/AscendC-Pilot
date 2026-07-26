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


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


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
