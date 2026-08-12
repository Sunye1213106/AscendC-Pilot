# -*- coding: utf-8 -*-
"""Static analyzability limits derived from operation entities."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from code_engineering.product_uo import product


def _matches(stored: str, requested: str) -> bool:
    left, right = stored.replace("\\", "/"), requested.replace("\\", "/")
    return left == right or left.endswith("/" + right) or right.endswith("/" + left)


def file_analyzability(
    project_root: Path | str, files: list[str], *, architecture: str = ""
) -> dict[str, Any]:
    """Measure operation reachability and lexical dependence for each file."""
    result: dict[str, Any] = {"max_verdict": "blind", "files": {}}
    p = product(project_root, architecture=architecture)
    if not p.is_file():
        for name in files:
            result["files"][name] = {
                "total": 0, "reached": 0, "orphan": 0, "lexical_ratio": 0.0,
                "score": 0.0, "max_verdict": "blind",
            }
        return result

    conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, file, status, data FROM entity WHERE upper(kind) = 'OPERATION'"
        ).fetchall()
    finally:
        conn.close()

    rank = {"blind": 0, "limited": 1, "static": 2}
    verdicts: list[str] = []
    for name in files:
        selected = [row for row in rows if _matches(str(row["file"] or ""), name)]
        reached = orphan = lexical = 0
        for row in selected:
            try:
                data = json.loads(row["data"] or "{}")
            except (TypeError, json.JSONDecodeError):
                data = {}
            is_reached = str(data.get("root_status") or "").upper() == "REACHED"
            reached += int(is_reached)
            orphan += int(not is_reached)
            lexical += int("lexical_source_calls" in str(data.get("provenance") or ""))
        total = len(selected)
        score = reached / total if total else 0.0
        verdict = "blind" if reached == 0 else ("limited" if orphan or lexical else "static")
        verdicts.append(verdict)
        result["files"][name] = {
            "total": total,
            "reached": reached,
            "orphan": orphan,
            "lexical_ratio": round(lexical / total, 6) if total else 0.0,
            "score": round(score, 6),
            "max_verdict": verdict,
        }
    result["max_verdict"] = min(verdicts, key=rank.get) if verdicts else "blind"
    return result
