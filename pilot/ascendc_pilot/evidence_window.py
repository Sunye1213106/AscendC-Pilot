# -*- coding: utf-8 -*-
"""Disk source-window proof helper for uo-query high-confidence evidence."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

# First ``relative/path.with.ext:N`` or ``:N-M`` in free-form evidence.
# Do not use rpartition(":") — prose often has later colons (``other.cpp:2068``)
# and Windows treats ``file.h:105`` as an NTFS stream / invalid path.
_EVIDENCE_LOC_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_][A-Za-z0-9_./\\-]*?)\.[A-Za-z][A-Za-z0-9]*)"
    r":(?P<lines>\d+(?:-\d+)?)\b"
)


def parse_lines_spec(spec: str) -> tuple[int, int]:
    """Parse ``A-B`` or ``A`` (1-based inclusive)."""
    raw = str(spec or "").strip().replace(" ", "")
    if not raw:
        raise ValueError("lines spec required (e.g. 790-814)")
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", raw)
    if not m:
        raise ValueError(f"invalid lines spec: {spec!r}")
    start = int(m.group(1))
    end = int(m.group(2) or start)
    if start < 1 or end < start:
        raise ValueError(f"invalid line range: {start}-{end}")
    return start, end


def first_evidence_locator(evidence: str) -> tuple[str, str] | None:
    """Return ``(relative_path, lines_spec)`` from bind-mapping evidence prose.

    Bind writers put citations in running text:
    ``op_kernel/arch35/foo.h:105 TILING_FIELD b; other.cpp:2068``.
    Only the first ``file.ext:N[-M]`` is used.
    """
    raw = str(evidence or "").replace("\\", "/").replace("\r", "\n")
    match = _EVIDENCE_LOC_RE.search(raw)
    if not match:
        return None
    rel = match.group("path").strip().lstrip("./")
    spec = match.group("lines").strip()
    if not rel or ":" in rel or ".." in rel.split("/"):
        return None
    if rel.startswith("/"):
        return None
    return rel, spec


def disk_window_proof(
    project_root: Path | str,
    *,
    path: str,
    lines: str,
    max_lines: int = 400,
) -> dict[str, Any]:
    """Return sha256 + continuous snippet for an exact pad=0 line window.

    Hash input is the UTF-8 encoding of the selected lines joined by ``\\n``
    (no trailing newline after the last line unless the file line itself had
    content only — we use ``splitlines()`` then ``\"\\n\".join``).

    Never raises ``OSError`` / ``FileNotFoundError``: Windows ``Path.resolve``
    and ``read_text`` can throw on missing files, ``:\\r`` in the name, or
    NTFS ``file.h:105`` stream syntax. Callers (bind_promote) must stay JSON.
    """
    try:
        root = Path(project_root).expanduser().resolve()
    except OSError as exc:
        return {"ok": False, "error": "bad_path", "message_zh": str(exc)[:300]}
    rel = (
        str(path or "")
        .replace("\\", "/")
        .replace("\r", "")
        .replace("\n", "")
        .strip()
        .lstrip("./")
    )
    if not rel or rel.startswith("/") or ":" in rel or ".." in rel.split("/"):
        return {
            "ok": False,
            "error": "bad_path",
            "message_zh": "path 须为算子仓下相对路径（如 op_host/arch35/foo.cpp）",
        }
    try:
        file_path = (root / rel).resolve()
    except OSError as exc:
        return {
            "ok": False,
            "error": "missing_file",
            "path": rel,
            "message_zh": f"文件不存在: {rel} ({exc})",
        }
    try:
        file_path.relative_to(root)
    except ValueError:
        return {
            "ok": False,
            "error": "path_outside_project",
            "message_zh": f"path 越出 project: {rel}",
        }
    try:
        is_file = file_path.is_file()
    except OSError:
        is_file = False
    if not is_file:
        return {
            "ok": False,
            "error": "missing_file",
            "path": rel,
            "message_zh": f"文件不存在: {rel}",
        }
    try:
        start, end = parse_lines_spec(lines)
    except ValueError as exc:
        return {"ok": False, "error": "bad_lines", "message_zh": str(exc)}

    span = end - start + 1
    if span > int(max_lines):
        return {
            "ok": False,
            "error": "window_too_large",
            "message_zh": f"窗口 {span} 行超过上限 {max_lines}；缩小 --lines",
        }

    try:
        all_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {
            "ok": False,
            "error": "missing_file",
            "path": rel,
            "message_zh": f"无法读取: {rel} ({exc})",
        }
    if start > len(all_lines):
        return {
            "ok": False,
            "error": "line_out_of_range",
            "message_zh": f"起始行 {start} 超出文件行数 {len(all_lines)}",
        }
    end_eff = min(end, len(all_lines))
    window_lines = all_lines[start - 1 : end_eff]
    text = "\n".join(window_lines)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "project": str(root),
        "path": rel,
        "lines": f"{start}-{end_eff}",
        "line_start": start,
        "line_end": end_eff,
        "evidence_window_sha256": digest,
        "evidence_snippet": text,
        "char_count": len(text),
        "line_count": len(window_lines),
        "pad": 0,
        "note": (
            "Paste evidence_window_sha256 + a continuous evidence_snippet "
            "substring into kb-answer-v1 for confidence: high / source_verified."
        ),
    }
