# -*- coding: utf-8 -*-
"""Inject TG_PROBE prints into a TG-owned sandbox copy. Never touch operator git."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_PROBE_LINE = 'printf("TG_PROBE {key}=%s\\n", ({key})); /* ascendc-tg-probe */\n'
_IDENT = re.compile(r"^[A-Za-z_]\w*$")


def required_fields(plan: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for row in plan.get("targets") or []:
        if not isinstance(row, dict):
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        if str(evidence.get("kind") or "") != "probe":
            continue
        field = str(evidence.get("field") or "").strip()
        if field:
            names.append(field.split(".")[-1])
    for row in plan.get("dimensions") or []:
        if not isinstance(row, dict):
            continue
        classifier = row.get("classifier") if isinstance(row.get("classifier"), dict) else {}
        for raw in classifier.get("requires") or []:
            field = str(raw or "").strip()
            if field.startswith("probe."):
                names.append(field.split(".", 1)[1])
    out: list[str] = []
    for name in names:
        if name and name not in out and _IDENT.match(name):
            out.append(name)
    return out


def missing_probe_fields(plan: dict[str, Any], observes: list[dict[str, Any]]) -> list[str]:
    need = required_fields(plan)
    if not need:
        return []
    seen: set[str] = set()
    for obs in observes:
        probe = obs.get("probe") if isinstance(obs.get("probe"), dict) else {}
        replay = obs.get("replay") if isinstance(obs.get("replay"), dict) else {}
        for key, blob in (("probe", probe), ("replay", replay)):
            del key
            for name in need:
                if name in blob or f"probe.{name}" in blob:
                    seen.add(name)
    return [n for n in need if n not in seen]


def inject_probes(ops_root: Path, fields: list[str]) -> dict[str, Any]:
    """Insert TG_PROBE prints next to assignments in a sandbox copy."""
    root = Path(ops_root)
    patched: list[str] = []
    missing: list[str] = []
    for field in fields:
        if not _IDENT.match(field):
            missing.append(field)
            continue
        hit = _find_assignment(root, field)
        if hit is None:
            missing.append(field)
            continue
        path, line_no, line = hit
        marker = f"TG_PROBE {field}="
        if marker in path.read_text(encoding="utf-8", errors="replace"):
            patched.append(str(path))
            continue
        indent = re.match(r"^\s*", line).group(0) if line else "  "
        probe = indent + _PROBE_LINE.format(key=field)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        lines.insert(line_no, probe)
        path.write_text("".join(lines), encoding="utf-8")
        patched.append(str(path))
    return {"ok": bool(patched) and not missing, "patched": patched, "missing": missing}


def _find_assignment(root: Path, field: str) -> tuple[Path, int, str] | None:
    pattern = re.compile(rf"\b{re.escape(field)}\s*=")
    for path in list(root.rglob("*.cpp")) + list(root.rglob("*.h")) + list(root.rglob("*.cc")):
        rel = path.as_posix()
        if "/.git/" in rel or "/build/" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(keepends=True)):
            if pattern.search(line) and "TG_PROBE" not in line:
                return path, i + 1, line
    return None
