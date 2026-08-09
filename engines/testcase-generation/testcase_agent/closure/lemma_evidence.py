# -*- coding: utf-8 -*-
"""Collect source evidence for a lemma combo (Dim=Val,...).

Gathers assignment sites / guards / early returns for involved fields from
CodemapQuery, source regex, and optional UO evidence. Output is structured
JSON/YAML with stable entry IDs for certificate proof-check references.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from testcase_agent.closure import workspace as W


def parse_combo(text: str) -> dict[str, str]:
    """Parse ``Dim=Val,Dim2=Val2`` into a mapping."""
    out: dict[str, str] = {}
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"combo segment missing '=': {part!r}")
        dim, val = part.split("=", 1)
        out[dim.strip()] = val.strip()
    if not out:
        raise ValueError("empty combo")
    return out


def _entry_id(kind: str, file: str, line: int, snippet: str) -> str:
    raw = f"{kind}|{file}|{line}|{snippet[:80]}"
    return "EV_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _uo_root(ws: W.Workspace) -> Path | None:
    import os

    arch = (os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or "arch35").strip()
    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(ws.root, arch=arch)
    except Exception:
        cand = ws.root / ".ascendc-pilot" / arch / "uo"
        return cand if cand.is_dir() else None


def _from_codemap(uo: Path, fields: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        from uo_init.host_codemap import CodemapQuery

        q = CodemapQuery(uo)
        for fld in q.fields():
            name = str(fld.get("name") or "")
            if fields and name not in fields and not any(
                f.lower() in name.lower() for f in fields
            ):
                continue
            for w in fld.get("writers") or []:
                file = str(w.get("file") or "")
                line = int(w.get("line") or 0)
                snippet = str(w.get("rhs") or w.get("path") or "")[:200]
                eid = _entry_id("assignment", file, line, snippet)
                entries.append({
                    "id": eid,
                    "kind": "assignment",
                    "field": name,
                    "file": file,
                    "line": line,
                    "snippet": snippet,
                    "guards": list(w.get("guards") or [])[:8],
                    "source": "codemap",
                })
                for g in (w.get("guards") or [])[:8]:
                    gtext = str(g)
                    gid = _entry_id("guard", file, line, gtext)
                    entries.append({
                        "id": gid,
                        "kind": "guard",
                        "field": name,
                        "file": file,
                        "line": line,
                        "snippet": gtext[:200],
                        "source": "codemap",
                    })
        for pred in q.predicates():
            hint = str(pred.get("feature_hint") or "")
            cond = str(pred.get("condition") or "")
            if fields and not any(
                f.lower() in (hint + cond + str(pred.get("function") or "")).lower()
                for f in fields
            ):
                continue
            file = str(pred.get("file") or "")
            line = int(pred.get("line") or 0)
            eid = _entry_id("predicate", file, line, cond)
            entries.append({
                "id": eid,
                "kind": "predicate",
                "field": hint,
                "file": file,
                "line": line,
                "snippet": cond[:200],
                "source": "codemap",
            })
    except Exception:
        pass
    return entries


_EARLY_RETURN_RE = re.compile(
    r"\breturn\b[^;]{0,80};", re.MULTILINE
)
_ASSIGN_RE = re.compile(
    r"(\w+)\s*=\s*([^;]{1,120});"
)


def _from_source_regex(
    project_root: Path,
    fields: list[str],
    *,
    max_files: int = 40,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    patterns = [re.compile(re.escape(f), re.I) for f in fields if f]
    if not patterns:
        return entries
    roots = [
        project_root / "op_host",
        project_root / "op_kernel",
        project_root,
    ]
    seen_files: list[Path] = []
    for base in roots:
        if not base.is_dir():
            continue
        for path in base.rglob("*.cpp"):
            seen_files.append(path)
            if len(seen_files) >= max_files:
                break
        if len(seen_files) >= max_files:
            break
    for path in seen_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not any(p.search(text) for p in patterns):
            continue
        rel = str(path).replace("\\", "/")
        for i, line in enumerate(text.splitlines(), 1):
            if not any(p.search(line) for p in patterns):
                continue
            if _EARLY_RETURN_RE.search(line):
                eid = _entry_id("early_return", rel, i, line.strip())
                entries.append({
                    "id": eid,
                    "kind": "early_return",
                    "field": "",
                    "file": rel,
                    "line": i,
                    "snippet": line.strip()[:200],
                    "source": "regex",
                })
            for m in _ASSIGN_RE.finditer(line):
                name = m.group(1)
                if not any(p.search(name) or p.search(line) for p in patterns):
                    continue
                eid = _entry_id("assignment", rel, i, m.group(0))
                entries.append({
                    "id": eid,
                    "kind": "assignment",
                    "field": name,
                    "file": rel,
                    "line": i,
                    "snippet": m.group(0)[:200],
                    "source": "regex",
                })
    return entries


def collect(
    combo: Mapping[str, str] | str,
    ws: W.Workspace | None = None,
) -> dict[str, Any]:
    """Build an evidence pack for the combo."""
    ws = (ws or W.default_workspace()).ensure()
    when = parse_combo(combo) if isinstance(combo, str) else {
        str(k): str(v) for k, v in combo.items()
    }
    fields = list(when.keys())
    uo = _uo_root(ws)
    entries: list[dict[str, Any]] = []
    if uo is not None:
        entries.extend(_from_codemap(uo, fields))
    entries.extend(_from_source_regex(ws.root, fields))

    # Dedup by id
    by_id: dict[str, dict[str, Any]] = {}
    for e in entries:
        by_id[str(e["id"])] = e
    ordered = sorted(by_id.values(), key=lambda e: (e.get("kind"), e.get("file"), e.get("line")))

    pack = {
        "schema": "tg-lemma-evidence/v1",
        "combo": when,
        "fields": fields,
        "entry_count": len(ordered),
        "entries": ordered,
        "by_kind": {
            kind: sum(1 for e in ordered if e.get("kind") == kind)
            for kind in sorted({str(e.get("kind")) for e in ordered})
        },
        "review_template": {
            "when": when,
            "grade": "source_lemma",
            "proof": {
                "entry_branches_checked": False,
                "early_returns_checked": False,
                "all_writers_checked": False,
                "execution_order_checked": False,
                "exception_branches_checked": False,
                "evidence_entry_ids": [e["id"] for e in ordered[:32]],
            },
            "certificate": {
                "proof_scope": {
                    "target_dimensions": fields,
                    "relevant_functions": [],
                    "assignments": [
                        f"{e['file']}:{e['line']}"
                        for e in ordered if e.get("kind") == "assignment"
                    ][:20],
                    "guards": [
                        f"{e['file']}:{e['line']}"
                        for e in ordered if e.get("kind") == "guard"
                    ][:20],
                },
                "assumptions": [],
                "completeness_evidence": {
                    "assignment_sites_complete": False,
                    "call_closure_complete": False,
                    "alias_state_exact": False,
                    "macro_context_complete": False,
                },
                "counterexample_strategy": {},
                "evidence_entry_ids": [e["id"] for e in ordered[:32]],
            },
        },
    }

    out_dir = ws.state / "lemmas" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    label = "_".join(f"{k}-{v}" for k, v in when.items())
    yaml_path = out_dir / f"{label}.yaml"
    json_path = out_dir / f"{label}.json"
    yaml_path.write_text(
        yaml.safe_dump(pack, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "combo": when,
        "entry_count": len(ordered),
        "yaml": str(yaml_path),
        "json": str(json_path),
        "entry_ids": [e["id"] for e in ordered],
        "pack": pack,
    }
