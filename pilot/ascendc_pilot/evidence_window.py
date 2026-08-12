# -*- coding: utf-8 -*-
"""Disk source-window proof helper for uo-query high-confidence evidence."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


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
    """
    root = Path(project_root).expanduser().resolve()
    rel = str(path or "").replace("\\", "/").lstrip("./")
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return {
            "ok": False,
            "error": "bad_path",
            "message_zh": "path 须为算子仓下相对路径（如 op_host/arch35/foo.cpp）",
        }
    file_path = (root / rel).resolve()
    try:
        file_path.relative_to(root)
    except ValueError:
        return {
            "ok": False,
            "error": "path_outside_project",
            "message_zh": f"path 越出 project: {rel}",
        }
    if not file_path.is_file():
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

    all_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
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
