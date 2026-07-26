"""Public large-IR read-order helpers for Host task stubs.

When prepare lists ``*.summary.yaml`` in dispatch ``read``, the stub injects
``MUST_READ_ORDER`` so producers follow ``code-access`` (summary → hints → windows).
Action-specific evidence / sha rules stay in ``runtime._build_task_prompt_stub``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence


def _norm(path: str) -> str:
    return str(path or "").replace("\\", "/").strip()


def _basename(path: str) -> str:
    return Path(_norm(path)).name


def classify_large_ir_read_paths(
    read_paths: Sequence[str] | None,
) -> dict[str, list[str]]:
    """Split dispatch read paths into summary / hints / full-IR companions."""
    summaries: list[str] = []
    hints: list[str] = []
    full_ir: list[str] = []
    for raw in read_paths or []:
        p = _norm(raw)
        if not p:
            continue
        name = _basename(p).lower()
        if name.endswith(".summary.yaml") or name.endswith(".summary.yml"):
            summaries.append(p)
            continue
        if "rework_hints" in name or name.endswith(".hints.yaml"):
            hints.append(p)
            continue
        if "candidates" in name and (name.endswith(".yaml") or name.endswith(".yml")):
            if not name.endswith(".sha256"):
                full_ir.append(p)
    return {"summaries": summaries, "hints": hints, "full_ir": full_ir}


def large_ir_must_read_order_lines(read_paths: Sequence[str] | None) -> list[str]:
    """Stub lines for any Action whose dispatch read includes ``*.summary.yaml``."""
    parts = classify_large_ir_read_paths(read_paths)
    summaries = parts["summaries"]
    if not summaries:
        return []
    hint_names = [_basename(p) for p in parts["hints"]]
    full_names = [_basename(p) for p in parts["full_ir"]]
    summary_names = ", ".join(_basename(p) for p in summaries)
    hint_clause = (
        f"(2) {', '.join(hint_names)} if present "
        if hint_names
        else "(2) any *.rework_hints.yaml if present "
    )
    full_clause = (
        f"(3) only then windows of {', '.join(full_names)} — "
        if full_names
        else "(3) only then targeted windows of the full IR — "
    )
    return [
        f"MUST_READ_ORDER: (1) {summary_names} "
        f"(use section_lines for targeted Read) "
        f"{hint_clause}"
        f"{full_clause}"
        "FORBIDDEN to offset-hunt / Grep-scan the entire candidates/IR file first.",
        "readonly_search: OpenCode Grep/Read and bash grep|rg|Select-String "
        "are allowed for locate-only; still not high-confidence evidence.",
    ]


def has_large_ir_summary(read_paths: Iterable[str] | None) -> bool:
    return bool(classify_large_ir_read_paths(list(read_paths or []))["summaries"])
