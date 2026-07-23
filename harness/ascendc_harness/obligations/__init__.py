"""Static + dynamic obligations normalized from domain artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_harness.paths import tg_root, uo_root
from ascendc_harness.workflows import get_workflow


def _load(path: Path) -> Any:
    if yaml is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _open_ids_from_yaml(path: Path) -> list[dict[str, str]]:
    doc = _load(path)
    out: list[dict[str, str]] = []
    if not isinstance(doc, dict):
        return out
    items = doc.get("items") or doc.get("gaps") or doc.get("open") or doc.get("obligations") or []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, str):
                out.append({"id": it, "source": path.as_posix(), "kind": "dynamic"})
            elif isinstance(it, dict):
                status = str(it.get("status") or it.get("state") or "open").lower()
                if status in {"closed", "resolved", "accepted", "done", "pass"}:
                    continue
                kid = str(it.get("id") or it.get("key") or it.get("target") or "")
                if kid:
                    out.append(
                        {
                            "id": kid,
                            "source": path.as_posix(),
                            "kind": "dynamic",
                            "label_zh": str(it.get("reason") or it.get("message") or kid)[:120],
                        }
                    )
    return out


def collect_obligations(project_root: Path, workflow_id: str) -> list[dict[str, Any]]:
    meta = get_workflow(workflow_id)
    out: list[dict[str, Any]] = []
    for row in meta.get("static_obligations") or []:
        if isinstance(row, dict) and row.get("id"):
            out.append(
                {
                    "id": str(row["id"]),
                    "kind": "static",
                    "label_zh": str(row.get("label_zh") or row["id"]),
                    "status": "open",
                }
            )

    uo = uo_root(project_root)
    tg = tg_root(project_root)
    for rel in meta.get("dynamic_obligation_sources") or []:
        rel_s = str(rel)
        # Support simple ** glob under tg/uo
        bases = [uo, tg, project_root / ".ascendc-agent"]
        matched: list[Path] = []
        if "**" in rel_s:
            for base in bases:
                matched.extend(base.glob(rel_s))
        else:
            for base in bases:
                candidate = base / rel_s
                if candidate.is_file():
                    matched.append(candidate)
        for path in matched:
            out.extend(_open_ids_from_yaml(path))

    # Dedupe by id, prefer first
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for row in out:
        kid = str(row.get("id") or "")
        if not kid or kid in seen:
            continue
        seen.add(kid)
        uniq.append(row)
    return uniq


def obligation_id_set(items: list[dict[str, Any]]) -> set[str]:
    return {str(it.get("id") or "") for it in items if it.get("id")}
