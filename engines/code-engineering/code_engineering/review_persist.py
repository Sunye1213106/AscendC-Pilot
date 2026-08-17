"""Copy session review parts into canonical ce/review reports when the user asks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _dump(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def persist_review_reports(
    project_root: Path | str,
    *,
    architecture: str,
    run_id: str = "",
    persist: bool = False,
) -> dict[str, Any]:
    """If persist, copy axis parts into ce/review/*.yaml. Always write persist.yaml."""
    root = Path(project_root).expanduser().resolve()
    arch = str(architecture or "").strip()
    ce = root / ".ascendc-pilot" / arch / "ce" / "review"
    ce.mkdir(parents=True, exist_ok=True)
    parts = root / ".ascendc-pilot" / arch / "runs" / str(run_id or "") / "actions" / "code_review" / "parts"
    copied: list[str] = []
    if persist:
        mapping = (
            ("spec.yaml", "functional_report.yaml"),
            ("standards.yaml", "bug_report.yaml"),
            ("scope.yaml", "index.yaml"),
        )
        for src_name, dest_name in mapping:
            src = _load(parts / src_name)
            if not src:
                continue
            dest = ce / dest_name
            existing = _load(dest)
            merged = dict(existing)
            merged.update(src)
            _dump(dest, merged)
            copied.append(dest_name)
    receipt = {
        "schema": "ce-review-persist/v1",
        "persisted": bool(persist),
        "copied": copied,
        "run_id": str(run_id or ""),
    }
    out = ce / "persist.yaml"
    _dump(out, receipt)
    return {"ok": True, "artifact": out.as_posix(), **receipt}
