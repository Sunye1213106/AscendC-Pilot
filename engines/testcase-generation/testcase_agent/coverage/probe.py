# -*- coding: utf-8 -*-
"""Inject TG_PROBE prints into a TG-owned sandbox copy. Never touch operator git."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .predicate import predicate_fields

_PROBE_LINE = 'printf("TG_PROBE {key}=%s\\n", ({key})); /* ascendc-tg-probe */\n'
_IDENT = re.compile(r"^[A-Za-z_]\w*$")


def _add_probe_name(names: list[str], field: str) -> None:
    text = str(field or "").strip()
    if not text:
        return
    if text.startswith("probe."):
        text = text.split(".", 1)[1]
    elif "." in text:
        return
    if text and text not in names and _IDENT.match(text):
        names.append(text)


def required_fields(plan: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for row in plan.get("targets") or []:
        if not isinstance(row, dict):
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        if str(evidence.get("kind") or "") == "probe":
            _add_probe_name(names, str(evidence.get("field") or ""))
        pred = evidence.get("predicate") if evidence.get("predicate") is not None else evidence.get("expr")
        for field in predicate_fields(pred):
            _add_probe_name(names, field)
    for row in plan.get("dimensions") or []:
        if not isinstance(row, dict):
            continue
        classifier = row.get("classifier") if isinstance(row.get("classifier"), dict) else {}
        for raw in classifier.get("requires") or []:
            _add_probe_name(names, str(raw or ""))
        for part in row.get("partitions") or []:
            if not isinstance(part, dict):
                continue
            for field in predicate_fields(part.get("predicate")):
                _add_probe_name(names, field)
    for row in plan.get("guards") or []:
        if not isinstance(row, dict):
            continue
        for field in predicate_fields(row.get("predicate")):
            _add_probe_name(names, field)
    for row in plan.get("constraints") or []:
        if not isinstance(row, dict):
            continue
        pred = row.get("predicate") if row.get("predicate") is not None else row.get("expr")
        for field in predicate_fields(pred):
            _add_probe_name(names, field)
    return names


def missing_probe_fields(plan: dict[str, Any], observes: list[dict[str, Any]]) -> list[str]:
    need = required_fields(plan)
    if not need:
        return []
    seen: set[str] = set()
    for obs in observes:
        probe = obs.get("probe") if isinstance(obs.get("probe"), dict) else {}
        replay = obs.get("replay") if isinstance(obs.get("replay"), dict) else {}
        for blob in (probe, replay):
            for name in need:
                if name in blob or f"probe.{name}" in blob:
                    seen.add(name)
    return [n for n in need if n not in seen]


def inject_probes(
    ops_root: Path,
    fields: list[str],
    *,
    scope: list[str] | None = None,
) -> dict[str, Any]:
    """Insert TG_PROBE prints next to assignments in a sandbox copy."""
    root = Path(ops_root)
    patched: list[str] = []
    missing: list[str] = []
    ambiguous: list[dict[str, Any]] = []
    for field in fields:
        if not _IDENT.match(field):
            missing.append(field)
            continue
        hits, amb = _find_assignments(root, field, scope=scope)
        if amb:
            ambiguous.append({"field": field, "candidates": [str(p) for p, _, _ in hits]})
            continue
        if not hits:
            missing.append(field)
            continue
        path, line_no, line = hits[0]
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
    ok = bool(patched) and not missing and not ambiguous
    out: dict[str, Any] = {"ok": ok, "patched": patched, "missing": missing}
    if ambiguous:
        out["ambiguous"] = ambiguous
        out["error"] = "PROBE_AMBIGUOUS"
    return out


def _scope_files(root: Path, scope: list[str] | None) -> list[Path]:
    if not scope:
        return []
    found: list[Path] = []
    seen: set[str] = set()
    for raw in scope:
        text = str(raw or "").strip().replace("\\", "/")
        if not text:
            continue
        cand = Path(text)
        matches: list[Path] = []
        if cand.is_absolute() and cand.is_file():
            matches.append(cand)
        else:
            direct = root / text
            if direct.is_file():
                matches.append(direct)
            else:
                name = Path(text).name
                for path in _iter_sources(root):
                    rel = path.relative_to(root).as_posix()
                    if rel == text or rel.endswith("/" + text) or path.name == name and text.endswith(path.name):
                        matches.append(path)
        for path in matches:
            key = str(path)
            if key not in seen:
                seen.add(key)
                found.append(path)
    return found


def _iter_sources(root: Path):
    for path in list(root.rglob("*.cpp")) + list(root.rglob("*.h")) + list(root.rglob("*.cc")):
        rel = path.as_posix()
        if "/.git/" in rel or "/build/" in rel:
            continue
        yield path


def _scan_assignment(paths: list[Path], field: str) -> list[tuple[Path, int, str]]:
    pattern = re.compile(rf"\b{re.escape(field)}\s*=")
    hits: list[tuple[Path, int, str]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(keepends=True)):
            if pattern.search(line) and "TG_PROBE" not in line:
                hits.append((path, i + 1, line))
    return hits


def _find_assignments(
    root: Path,
    field: str,
    *,
    scope: list[str] | None = None,
) -> tuple[list[tuple[Path, int, str]], bool]:
    scoped = _scope_files(root, scope)
    if scoped:
        hits = _scan_assignment(scoped, field)
        if len(hits) == 1:
            return hits, False
        if len(hits) > 1:
            return hits, True
    hits = _scan_assignment(list(_iter_sources(root)), field)
    if len(hits) > 1:
        return hits, True
    return hits, False


def _find_assignment(
    root: Path,
    field: str,
    scope: list[str] | None = None,
) -> tuple[Path, int, str] | None:
    hits, amb = _find_assignments(root, field, scope=scope)
    if amb or not hits:
        return None
    return hits[0]
