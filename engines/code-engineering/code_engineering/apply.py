# -*- coding: utf-8 -*-
"""CE apply gates: confirmed intent + anchors, then diff ⊆ anchor files."""

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


def _scope(project_root: Path | str, architecture: str) -> Path:
    return Path(project_root).expanduser().resolve() / ".ascendc-pilot" / architecture


def apply_gate(project_root: Path | str, *, architecture: str) -> dict[str, Any]:
    """Fail closed unless intent is confirmed and anchors exist."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "apply_gate", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    ce = _scope(project_root, arch) / "ce"
    confirm = _load(ce / "intent" / "confirmation.yaml")
    anchors = _load(ce / "intent" / "anchors.yaml")
    status = str(confirm.get("status") or confirm.get("decision") or "").strip().lower()
    rows = anchors.get("anchors") if isinstance(anchors.get("anchors"), list) else []
    ok = status in {"confirmed", "confirm", "ok"} and bool(rows)
    doc = {
        "schema": "ce-apply-gate/v1",
        "ok": ok,
        "intent_confirmed": status in {"confirmed", "confirm", "ok"},
        "anchor_count": len(rows),
    }
    out = ce / "apply" / "gate.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": ok, "engine": "apply_gate", "artifact": out.as_posix(), **doc}


def _anchor_files(anchors: dict[str, Any]) -> set[str]:
    files: set[str] = set()
    rows = anchors.get("anchors") if isinstance(anchors.get("anchors"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("file", "path", "relpath"):
            raw = str(row.get(key) or "").replace("\\", "/").strip()
            if raw:
                files.add(raw.lstrip("./"))
        for span in row.get("spans") or []:
            if isinstance(span, dict):
                raw = str(span.get("file") or span.get("path") or "").replace("\\", "/").strip()
                if raw:
                    files.add(raw.lstrip("./"))
    return files


def _path_allowed(path: str, allowed: set[str]) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    for raw in allowed:
        a = raw.replace("\\", "/").lstrip("./")
        if p == a or p.endswith("/" + a) or a.endswith("/" + p):
            return True
        if a and (p.startswith(a.rstrip("/") + "/") or a.startswith(p.rstrip("/") + "/")):
            return True
    return False


def patch_guard(project_root: Path | str, *, architecture: str) -> dict[str, Any]:
    """Changed files from capture must sit in the located anchor file set."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "patch_guard", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    ce = _scope(project_root, arch) / "ce"
    capture = _load(ce / "apply" / "change_capture.yaml") or _load(ce / "impact" / "change_capture.yaml")
    anchors = _load(ce / "intent" / "anchors.yaml")
    allowed = _anchor_files(anchors)
    changed = sorted(str(p).replace("\\", "/").lstrip("./") for p in (capture.get("diff_spans") or {}))
    extra = [p for p in changed if not _path_allowed(p, allowed)]
    ok = bool(changed) and bool(allowed) and not extra
    doc = {
        "schema": "ce-apply-patch-guard/v1",
        "ok": ok,
        "changed_files": changed,
        "extra_files": extra,
        "anchor_file_count": len(allowed),
        "reason_code": "" if ok else ("PATCH_OUT_OF_ANCHORS" if extra else "PATCH_EMPTY_OR_UNANCHORED"),
    }
    out = ce / "apply" / "patch_report.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": ok, "engine": "patch_guard", "artifact": out.as_posix(), **doc}
