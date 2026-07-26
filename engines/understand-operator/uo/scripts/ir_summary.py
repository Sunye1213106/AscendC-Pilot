"""Public large-IR summary helpers (``*.summary.yaml`` + ``section_lines``).

Prepare emitters for oversized candidates / IR should:
1. Write a compact ``*.summary.yaml`` sidecar (counts + ``section_lines`` + ``must``).
2. List that summary ahead of the full IR in dispatch ``read`` paths.
3. Rely on Host stub ``MUST_READ_ORDER`` (injected when ``*.summary.yaml`` is in read).

Action-specific field shapes (sinks, key_writer, …) stay in the Action builder;
this module owns only the shared envelope and YAML section line scan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_LARGE_IR_MUST = (
    "MUST Read this summary (+ any *.rework_hints.yaml if present) "
    "BEFORE the full source IR. Use section_lines for targeted Read windows. "
    "Do NOT offset-hunt / Grep-scan the entire file first."
)

DEFAULT_LARGE_IR_NOTE = (
    "Public pattern: large IR prepare emits *.summary.yaml. "
    "apply/gate still validate against the full source file."
)


def scan_yaml_section_lines(
    path: Path | str,
    section_keys: Sequence[str],
) -> dict[str, dict[str, int]]:
    """1-based inclusive line ranges for top-level YAML keys (list/map sections)."""
    p = Path(path)
    if not p.is_file() or not section_keys:
        return {}
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    keys = [str(k).strip() for k in section_keys if str(k).strip()]
    starts: dict[str, int] = {}
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        for key in keys:
            if stripped == f"{key}:" or stripped.startswith(f"{key}:"):
                starts[key] = i
                break
    if not starts:
        return {}
    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    out: dict[str, dict[str, int]] = {}
    for idx, (key, start) in enumerate(ordered):
        end = (ordered[idx + 1][1] - 1) if idx + 1 < len(ordered) else len(lines)
        if end < start:
            end = start
        out[key] = {"start_line": start, "end_line": end}
    return out


def attach_large_ir_meta(
    summary: dict[str, Any],
    *,
    section_lines: dict[str, dict[str, int]] | None = None,
    source_line_count: int | None = None,
    must: str | None = None,
    note: str | None = None,
    source_sha256_key: str = "candidates_sha256",
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Merge public large-IR meta onto an Action-shaped summary dict."""
    out = dict(summary)
    if source_sha256 is not None:
        out[source_sha256_key] = str(source_sha256 or "").strip()
    out["section_lines"] = section_lines if section_lines is not None else (out.get("section_lines") or {})
    if source_line_count is not None:
        out["candidates_line_count"] = source_line_count
    out["must"] = str(must or out.get("must") or DEFAULT_LARGE_IR_MUST)
    out["note"] = str(note or out.get("note") or DEFAULT_LARGE_IR_NOTE)
    out.setdefault("version", 1)
    return out


def count_file_lines(path: Path | str) -> int | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return len(p.read_text(encoding="utf-8").splitlines())
    except OSError:
        return None


def iter_summary_basenames(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in paths:
        name = Path(str(raw).replace("\\", "/")).name
        low = name.lower()
        if low.endswith(".summary.yaml") or low.endswith(".summary.yml"):
            out.append(name)
    return out
