"""Two-tier memory: local operator + global agent (lightweight files)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.paths import ensure_agent_layout, global_memory_root, memory_root

KINDS = frozenset({"fact", "decision", "issue", "taste", "event", "verification", "next"})


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _looks_like_private_source(text: str) -> bool:
    # Heuristic: long code fences or absolute windows paths with .cpp/.h
    if "```" in text and len(text) > 400:
        return True
    if re.search(r"[A-Za-z]:\\[^\s]+\.(cpp|h|py|cc)", text):
        return True
    return False


def add_candidate(
    project_root: Path,
    *,
    topic: str,
    kind: str,
    content: str,
    source: str = "session",
    confidence: float = 0.4,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    ensure_agent_layout(project_root)
    entry = {
        "id": f"mem_{uuid.uuid4().hex[:12]}",
        "topic": topic,
        "kind": kind,
        "content": content.strip(),
        "source": source,
        "confidence": confidence,
        "freshness": _now(),
        "evidence_refs": list(evidence_refs or []),
        "tier": "candidate",
        "verified": False,
    }
    path = memory_root(project_root) / "candidate" / f"{entry['id']}.yaml"
    _dump(path, entry)
    return entry


def promote_stable(
    project_root: Path,
    entry_id: str,
    *,
    verified_by: str,
) -> dict[str, Any]:
    cand = memory_root(project_root) / "candidate" / f"{entry_id}.yaml"
    if not cand.is_file():
        raise FileNotFoundError(entry_id)
    entry = _load(cand)
    entry["tier"] = "stable"
    entry["verified"] = True
    entry["verified_by"] = verified_by
    entry["freshness"] = _now()
    entry["confidence"] = max(float(entry.get("confidence") or 0.4), 0.8)
    out = memory_root(project_root) / "stable" / f"{entry_id}.yaml"
    _dump(out, entry)
    cand.unlink(missing_ok=True)
    return entry


def search_local(project_root: Path, *, topic: str = "", limit: int = 5) -> list[dict[str, Any]]:
    root = memory_root(project_root)
    hits: list[dict[str, Any]] = []
    for tier in ("stable", "candidate"):
        base = root / tier
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
            entry = _load(path)
            if not entry:
                continue
            if topic and topic.lower() not in str(entry.get("topic") or "").lower() and topic.lower() not in str(entry.get("content") or "").lower():
                continue
            hits.append(entry)
            if len(hits) >= limit:
                return hits
    return hits


def propose_global_promote(project_root: Path, entry_id: str) -> dict[str, Any]:
    path = memory_root(project_root) / "stable" / f"{entry_id}.yaml"
    entry = _load(path)
    if not entry:
        raise FileNotFoundError(entry_id)
    content = str(entry.get("content") or "")
    if _looks_like_private_source(content):
        return {"ok": False, "error": "private_source_detected", "entry_id": entry_id}
    if not entry.get("verified"):
        return {"ok": False, "error": "not_verified", "entry_id": entry_id}
    gdir = global_memory_root() / "proposals"
    gdir.mkdir(parents=True, exist_ok=True)
    proposal = {
        "entry": entry,
        "from_project": str(Path(project_root).resolve()),
        "proposed_at": _now(),
        "status": "pending_approval",
    }
    out = gdir / f"{entry_id}.yaml"
    _dump(out, proposal)
    return {"ok": True, "proposal_path": out.as_posix()}


def approve_global(entry_id: str) -> dict[str, Any]:
    prop_path = global_memory_root() / "proposals" / f"{entry_id}.yaml"
    proposal = _load(prop_path)
    if not proposal:
        raise FileNotFoundError(entry_id)
    entry = dict(proposal.get("entry") or {})
    entry["tier"] = "global"
    out = global_memory_root() / "stable" / f"{entry_id}.yaml"
    _dump(out, entry)
    proposal["status"] = "approved"
    _dump(prop_path, proposal)
    return entry
