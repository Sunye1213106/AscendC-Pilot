# -*- coding: utf-8 -*-
"""Diff → affected tiling fields / keys, using the durable CodeMap ``.uo``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

_HUNK = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
_DIFF_FILE = re.compile(r"^\+\+\+\s+b/(.+)$|^\+\+\+\s+(.+)$")
_OLD_FILE = re.compile(r"^---\s+a/(.+)$|^---\s+(.+)$")


@dataclass
class ImpactReport:
    files: list[str] = field(default_factory=list)
    hit_writers: list[dict[str, Any]] = field(default_factory=list)
    hit_predicates: list[dict[str, Any]] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    key_dims: list[str] = field(default_factory=list)
    affected_keys: list[int] = field(default_factory=list)
    two_sided_spans: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "hit_writers": self.hit_writers,
            "hit_predicates": self.hit_predicates,
            "fields": self.fields,
            "key_dims": self.key_dims,
            "affected_key_count": len(self.affected_keys),
            "affected_keys_sample": self.affected_keys[:50],
            "two_sided_spans": self.two_sided_spans,
            "note": self.note,
        }


def parse_diff_ranges(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Map path → list of (start_line, end_line) for new-file hunks."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        fm = _DIFF_FILE.match(line)
        if fm:
            current = (fm.group(1) or fm.group(2) or "").strip()
            if current == "/dev/null":
                current = None
            continue
        hm = _HUNK.match(line)
        if hm and current:
            start = int(hm.group(3))
            count = int(hm.group(4) or "1")
            end = start + max(count, 1) - 1
            ranges.setdefault(current, []).append((start, end))
    return ranges


def parse_two_sided_spans(diff_text: str) -> list[dict[str, Any]]:
    """Preserve both old/new hunk spans and add/delete/modify/rename status."""
    rows: list[dict[str, Any]] = []
    old_path = ""
    new_path = ""
    for line in diff_text.splitlines():
        old = _OLD_FILE.match(line)
        if old:
            old_path = (old.group(1) or old.group(2) or "").strip()
            continue
        new = _DIFF_FILE.match(line)
        if new:
            new_path = (new.group(1) or new.group(2) or "").strip()
            continue
        hunk = _HUNK.match(line)
        if not hunk:
            continue
        old_start, old_count = int(hunk.group(1)), int(hunk.group(2) or "1")
        new_start, new_count = int(hunk.group(3)), int(hunk.group(4) or "1")
        if old_path == "/dev/null":
            status = "add"
        elif new_path == "/dev/null":
            status = "delete"
        elif old_path and new_path and old_path != new_path:
            status = "rename"
        else:
            status = "modify"
        rows.append({
            "status": status,
            "old": {"file": old_path or None, "start": old_start, "end": old_start + max(old_count, 1) - 1},
            "new": {"file": new_path or None, "start": new_start, "end": new_start + max(new_count, 1) - 1},
        })
    return rows


def _path_matches(writer_file: str, diff_path: str) -> bool:
    wf = writer_file.replace("\\", "/")
    dp = diff_path.replace("\\", "/")
    return wf.endswith(dp) or dp.endswith(wf.split("/")[-1])


def _load_host_view(
    uo_root: Path, project_root: Path | None
) -> tuple[dict[str, Any], str]:
    """Prefer ``.uo`` tg_host_view; fall back to legacy host_codemap.yaml."""
    try:
        from uo_init.store.reader import find_uo_product, load_view_blob

        root = project_root
        if root is None:
            # uo_root may be <op>/.ascendc-pilot/uo or <op>/.ascendc-pilot/<arch>/uo
            if uo_root.name == "uo" and uo_root.parent.name == ".ascendc-pilot":
                root = uo_root.parent.parent
            elif uo_root.name == "uo":
                root = uo_root.parents[2]
        if root is not None:
            product = find_uo_product(root)
            if product is not None and product.suffix == ".uo":
                blob = load_view_blob(product, "ir/tg_host_view.yaml")
                if isinstance(blob, dict) and blob:
                    return blob, f"uo:{product.name}"
    except Exception:
        pass

    for rel in ("ir/tg_host_view.yaml", "ir/host_codemap.yaml"):
        path = uo_root / rel
        if path.is_file():
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(doc, dict) and doc:
                return doc, path.as_posix()
    return {}, ""


def impact_from_diff(
    diff_text: str,
    *,
    uo_root: str | Path | None = None,
    project_root: str | Path | None = None,
) -> ImpactReport:
    """Compute the tiling impact of a unified diff against the CodeMap."""
    proj = Path(project_root).expanduser().resolve() if project_root else None
    root = Path(uo_root) if uo_root else (
        (proj / ".ascendc-pilot" / "uo") if proj else Path(".ascendc-pilot") / "uo"
    )
    ranges = parse_diff_ranges(diff_text)
    report = ImpactReport(files=sorted(ranges))
    report.two_sided_spans = parse_two_sided_spans(diff_text)
    if not ranges:
        report.note = "no file hunks in diff"
        return report

    doc, source = _load_host_view(root, proj)
    if not doc:
        # Last resort: scan CodeMap entities directly when only .uo exists.
        try:
            from uo_init.store.reader import find_uo_product, read_codemap
            from uo_init.ir.entity import EntityKind

            product = find_uo_product(proj or root)
            if product is None:
                report.note = "missing CodeMap .uo and host_codemap.yaml"
                return report
            cm = read_codemap(product)
            fields_hit: set[str] = set()
            for ent in cm.entities.values():
                if ent.kind_name() not in {
                    EntityKind.FIELD.value,
                    EntityKind.VARIABLE.value,
                    EntityKind.PREDICATE.value,
                }:
                    continue
                wf = str(ent.file or "")
                line = int(ent.line_start or 0)
                for dp, spans in ranges.items():
                    if not _path_matches(wf, dp):
                        continue
                    if any(a <= line <= b for a, b in spans):
                        if ent.kind_name() == EntityKind.PREDICATE.value:
                            report.hit_predicates.append(
                                {
                                    "file": wf,
                                    "line": line,
                                    "condition": ent.name,
                                    "fields": [],
                                }
                            )
                        else:
                            report.hit_writers.append(
                                {
                                    "field": ent.name,
                                    "file": wf,
                                    "line": line,
                                    "function": ent.attrs.get("function"),
                                }
                            )
                            fields_hit.add(ent.name)
            report.fields = sorted(fields_hit)
            report.key_dims = sorted(
                n
                for n in fields_hit
                if n[:1].isupper() and (len(n) == 1 or n[1:2].islower() or "_" not in n[:1])
            )
            report.note = (
                f"codemap-entity scan: {len(report.hit_writers)} writers, "
                f"{len(report.hit_predicates)} predicates, fields={report.fields}"
            )
            return report
        except Exception as exc:  # noqa: BLE001
            report.note = f"missing host view ({exc})"[:200]
            return report

    fields_hit: set[str] = set()
    for f in doc.get("fields") or []:
        name = str(f.get("name") or "")
        writers = list(f.get("writers") or [])
        if not writers and f.get("entity_id"):
            # tg_host_view from CodeMap may only stamp producer_sites as writers
            writers = list(f.get("writers") or [])
        for w in writers:
            if not isinstance(w, dict):
                continue
            wf = str(w.get("file") or "")
            line = int(w.get("line") or 0)
            for dp, spans in ranges.items():
                if not _path_matches(wf, dp):
                    continue
                if any(a <= line <= b for a, b in spans):
                    report.hit_writers.append({
                        "field": name, **{k: w.get(k) for k in
                        ("file", "line", "function", "rhs", "via")}
                    })
                    fields_hit.add(name)
                    if f.get("tiling_key"):
                        report.key_dims.append(str(f.get("tiling_key")))
    for p in doc.get("predicates") or []:
        pf = str(p.get("file") or "")
        line = int(p.get("line") or 0)
        for dp, spans in ranges.items():
            if not _path_matches(pf, dp):
                continue
            if any(a <= line <= b for a, b in spans):
                report.hit_predicates.append(p)
                for fld in p.get("fields") or []:
                    if fld:
                        fields_hit.add(str(fld))

    report.fields = sorted(fields_hit)
    key_dims = list(report.key_dims)
    for f in doc.get("fields") or []:
        name = str(f.get("name") or "")
        if name not in fields_hit:
            continue
        if f.get("kind") in {"key_dim", "key_dim_host"} or (
            name[:1].isupper() and name[1:2].islower()
        ):
            key_dims.append(str(f.get("tiling_key") or name))
    report.key_dims = sorted(set(key_dims))
    report.affected_keys = []
    report.note = (
        f"source={source}; {len(report.hit_writers)} writers, "
        f"{len(report.hit_predicates)} predicates, fields={report.fields}"
    )
    return report
