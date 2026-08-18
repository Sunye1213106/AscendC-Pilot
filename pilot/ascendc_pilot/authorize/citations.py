# -*- coding: utf-8 -*-
"""Persist uo-query card citations so truncated-window Reads can be authorized."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

CITATIONS_NAME = "uo-query-citations.yaml"
WINDOW_LIMIT_MAX = 80
LINE_PAD = 40
_WINDOW_RE = re.compile(
    r"offset\s*=\s*(\d+)\s+limit\s*=\s*(\d+)",
    re.I,
)
_ELLIPSIS = ("…", "...", "truncated", "(truncated)")


def citations_path(project_root: Path, *, arch: str | None = None) -> Path:
    from ascendc_pilot.paths import agent_root, discover_arch
    from ascendc_pilot.state import load_state

    root = Path(project_root).expanduser().resolve()
    resolved_arch = (arch or "").strip()
    if not resolved_arch:
        st = load_state(root) or {}
        resolved_arch = str(st.get("architecture") or "").strip()
    if not resolved_arch:
        try:
            resolved_arch = discover_arch(root)
        except Exception:  # noqa: BLE001
            resolved_arch = "arch35"
    return agent_root(root, resolved_arch) / CITATIONS_NAME


def _norm_path(path_s: str) -> str:
    return str(path_s or "").replace("\\", "/").lstrip("./").lower()


def _snippet_truncated(snippet: str, *, payload_truncated: bool) -> bool:
    if payload_truncated:
        return True
    text = str(snippet or "")
    if not text.strip():
        return True
    low = text.lower()
    return any(mark in text or mark in low for mark in _ELLIPSIS)


def _iter_payload_spans(payload: dict[str, Any]) -> list[dict[str, Any]]:
    truncated_global = bool(payload.get("truncated"))
    spans: list[dict[str, Any]] = []

    def _add(path: Any, line: Any, snippet: Any = "") -> None:
        p = str(path or "").strip()
        try:
            n = int(line or 0)
        except (TypeError, ValueError):
            n = 0
        if not p or n <= 0:
            return
        spans.append(
            {
                "path": p.replace("\\", "/"),
                "line": n,
                "truncated": _snippet_truncated(str(snippet or ""), payload_truncated=truncated_global),
            }
        )

    for card in payload.get("cards") or []:
        if not isinstance(card, dict):
            continue
        _add(card.get("file"), card.get("line") or card.get("line_start"), card.get("snippet"))
        extras = card.get("extras") if isinstance(card.get("extras"), dict) else {}
        definition = extras.get("definition") if isinstance(extras.get("definition"), dict) else {}
        _add(definition.get("file"), definition.get("line"), definition.get("snippet"))

    for loc in payload.get("locations") or []:
        if isinstance(loc, dict):
            _add(loc.get("file") or loc.get("path"), loc.get("line") or loc.get("line_start"), loc.get("snippet"))

    files = payload.get("files")
    if isinstance(files, dict):
        for path, rows in files.items():
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        _add(path, row.get("line") or row.get("line_start"), row.get("snippet"))
            elif isinstance(rows, dict):
                _add(path, rows.get("line") or rows.get("line_start"), rows.get("snippet"))
    return spans


def record_from_payload(
    project_root: Path,
    payload: dict[str, Any] | None,
    *,
    file: str = "",
    line: int = 0,
    arch: str | None = None,
) -> list[dict[str, Any]]:
    """Merge card citations from a uo-query payload onto disk."""
    spans = _iter_payload_spans(payload if isinstance(payload, dict) else {})
    if str(file or "").strip() and int(line or 0) > 0:
        spans.append(
            {
                "path": str(file).replace("\\", "/"),
                "line": int(line),
                "truncated": True,
            }
        )
    path = citations_path(project_root, arch=arch)
    existing = load_spans(project_root, arch=arch)
    merged = _merge_spans(existing + spans)
    body = {"schema": "uo-query-citations/v1", "spans": merged}
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml is not None:
        path.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def load_spans(project_root: Path, *, arch: str | None = None) -> list[dict[str, Any]]:
    path = citations_path(project_root, arch=arch)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        return []
    rows = data.get("spans") or []
    return [r for r in rows if isinstance(r, dict)]


def _merge_spans(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        path = str(row.get("path") or "").replace("\\", "/")
        try:
            line = int(row.get("line") or 0)
        except (TypeError, ValueError):
            line = 0
        if not path or line <= 0:
            continue
        key = (_norm_path(path), line)
        prev = by_key.get(key)
        truncated = bool(row.get("truncated")) or bool(prev and prev.get("truncated"))
        by_key[key] = {"path": path, "line": line, "truncated": truncated}
    return list(by_key.values())[-64:]


def parse_read_window(command: str) -> tuple[int, int] | None:
    m = _WINDOW_RE.search(str(command or ""))
    if not m:
        return None
    offset = int(m.group(1))
    limit = int(m.group(2))
    if offset <= 0 or limit <= 0:
        return None
    return offset, limit


def cited_window_allows(
    project_root: Path | None,
    path_s: str,
    *,
    command: str = "",
    arch: str | None = None,
) -> bool:
    if project_root is None:
        return False
    window = parse_read_window(command)
    if window is None:
        return False
    offset, limit = window
    if limit > WINDOW_LIMIT_MAX:
        return False
    want = _norm_path(path_s)
    root_n = _norm_path(str(project_root))
    if want.startswith(root_n + "/"):
        want = want[len(root_n) + 1 :]
    start = offset
    end = offset + limit - 1
    for span in load_spans(project_root, arch=arch):
        if not span.get("truncated"):
            continue
        cited_path = _norm_path(str(span.get("path") or ""))
        if cited_path.endswith(want) or want.endswith(cited_path) or cited_path == want:
            line = int(span.get("line") or 0)
            if line <= 0:
                continue
            if start - LINE_PAD <= line <= end + LINE_PAD:
                return True
    return False
