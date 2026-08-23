# -*- coding: utf-8 -*-
"""Coverage ledger lives inside tg/worklog.md YAML fence — not a 4th product."""

from __future__ import annotations

import re
from typing import Any

LEDGER_SCHEMA = "tg-worklog/v2"
_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_OPEN_RE = re.compile(r"^open:\s*\[(.*?)\]\s*$", re.MULTILINE)
CLOSED_OK = frozenset({"CLOSED", "PROVED_UNREACHABLE"})
BLOCKING = frozenset({"UNKNOWN", "GUARD_LEAK"})


def parse_worklog_fence(text: str) -> dict[str, Any]:
    matches = list(_FENCE_RE.finditer(text or ""))
    if not matches:
        return {}
    body = matches[-1].group(1)
    try:
        import yaml

        doc = yaml.safe_load(body)
    except Exception:  # noqa: BLE001
        return {}
    return doc if isinstance(doc, dict) else {}


def seed_ledger(obligations: list[dict[str, Any]]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for row in obligations:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("id") or "").strip()
        if not oid:
            continue
        item = dict(row)
        item.setdefault("status", "OPEN")
        rows[oid] = item
    return {
        "schema": LEDGER_SCHEMA,
        "obligations": rows,
        "signatures": [],
        "recipe": {},
        "refinement": {},
    }


def upsert_obligation(ledger: dict[str, Any], oid: str, **fields: Any) -> dict[str, Any]:
    rows = ledger.get("obligations")
    if not isinstance(rows, dict):
        rows = {}
        ledger["obligations"] = rows
    cur = dict(rows.get(oid) or {})
    cur.update(fields)
    cur["id"] = oid
    rows[oid] = cur
    sig = fields.get("signature")
    if sig:
        seen = list(ledger.get("signatures") or [])
        if sig not in seen:
            seen.append(sig)
        ledger["signatures"] = seen
    return ledger


def open_ids(ledger: dict[str, Any]) -> list[str]:
    rows = ledger.get("obligations") if isinstance(ledger.get("obligations"), dict) else {}
    out: list[str] = []
    for oid, row in rows.items():
        status = str((row or {}).get("status") or "OPEN")
        if status in {"OPEN", "MISS", "UNKNOWN"}:
            out.append(str(oid))
    return out


def ledger_closed(ledger: dict[str, Any]) -> tuple[bool, list[str]]:
    rows = ledger.get("obligations") if isinstance(ledger.get("obligations"), dict) else {}
    if not rows:
        return False, ["ledger empty"]
    problems: list[str] = []
    for oid, row in rows.items():
        status = str((row or {}).get("status") or "OPEN")
        if status in BLOCKING:
            problems.append(f"{oid}:{status}")
        elif status not in CLOSED_OK:
            problems.append(f"{oid}:{status}")
    return (not problems), problems


def dump_worklog(ledger: dict[str, Any], *, prose: str = "") -> str:
    import yaml

    ids = open_ids(ledger)
    open_line = "open: [" + ", ".join(ids) + "]"
    fence = yaml.safe_dump(ledger, allow_unicode=True, sort_keys=False).rstrip()
    body = (prose or "").strip()
    parts = [open_line, ""]
    if body:
        parts.extend([body, ""])
    parts.extend(["```yaml", fence, "```", ""])
    return "\n".join(parts)


def merge_prose(existing: str, ledger: dict[str, Any], *, extra_prose: str = "") -> str:
    """Keep human prose; replace the last yaml fence with the ledger."""
    text = existing or ""
    matches = list(_FENCE_RE.finditer(text))
    prefix = text[: matches[-1].start()] if matches else text
    prefix = _OPEN_RE.sub("", prefix).strip()
    combined = "\n\n".join(p for p in (prefix, extra_prose.strip()) if p)
    return dump_worklog(ledger, prose=combined)
