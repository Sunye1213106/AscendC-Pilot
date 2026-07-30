from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_index_meta(artifact_root: Path) -> dict[str, Any]:
    path = artifact_root / "cbm" / "index_meta.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_index_meta(artifact_root: Path, data: dict[str, Any]) -> None:
    path = artifact_root / "cbm" / "index_meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def summarize_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"kind": type(result).__name__}
    summary: dict[str, Any] = {}
    for key in ("count", "total", "matches", "nodes", "edges", "functions", "files"):
        if key in result:
            summary[key] = result[key]
    for key in ("results", "matches", "nodes", "items", "functions", "files", "paths"):
        value = result.get(key)
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    if not summary and result.get("text"):
        summary["text_preview"] = str(result["text"])[:200]
    return summary
