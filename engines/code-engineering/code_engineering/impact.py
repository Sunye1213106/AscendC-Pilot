# -*- coding: utf-8 -*-
"""Diff → affected tiling fields / keys, using the durable CodeMap ``.uo``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def _project_root_from_uo_root(uo_root: Path) -> Path | None:
    """``<op>/.ascendc-pilot/<arch>/uo`` → ``<op>``."""
    if uo_root.name == "uo" and uo_root.parent.name.startswith("arch"):
        return uo_root.parents[2]
    return None


def _as_packed_key(value: Any) -> int | None:
    """Packed tiling-key integers only. Dimension names never coerce."""
    if isinstance(value, bool) or isinstance(value, float):
        return None
    if isinstance(value, int):
        return value
    return None


def _load_host_view(
    project_root: Path | None,
    *,
    architecture: str = "",
) -> tuple[dict[str, Any], str]:
    """Load ``ir/tg_host_view.yaml`` from the arch-scoped ``.uo`` product."""
    try:
        from uo_init.store.reader import find_uo_product, load_view_blob_checked
    except ImportError as exc:
        return {}, f"uo_init unavailable: {exc}"

    if project_root is None:
        return {}, "missing project_root for find_uo_product"
    product = find_uo_product(project_root, architecture=architecture)
    if product is None or product.suffix != ".uo":
        return {}, "missing CodeMap .uo"
    checked = load_view_blob_checked(product, "ir/tg_host_view.yaml")
    if not checked.get("ok"):
        reason = str(checked.get("reason_code") or "VIEW_UNUSABLE")
        return {}, f"uo:{product.name}:{reason}"
    blob = checked.get("view")
    if isinstance(blob, dict) and blob:
        return blob, f"uo:{product.name}"
    return {}, f"uo:{product.name}:empty_host_view"


def impact_from_diff(
    diff_text: str,
    *,
    uo_root: str | Path | None = None,
    project_root: str | Path | None = None,
    architecture: str = "",
) -> ImpactReport:
    """Compute the tiling impact of a unified diff against the CodeMap."""
    proj = Path(project_root).expanduser().resolve() if project_root else None
    if proj is None and uo_root is not None:
        inferred = _project_root_from_uo_root(Path(uo_root))
        if inferred is not None:
            proj = inferred
    arch = str(architecture or "").strip()
    ranges = parse_diff_ranges(diff_text)
    report = ImpactReport(files=sorted(ranges))
    report.two_sided_spans = parse_two_sided_spans(diff_text)
    if not ranges:
        report.note = "no file hunks in diff"
        return report

    doc, source = _load_host_view(proj, architecture=arch)
    if not doc:
        try:
            from uo_init.store.reader import find_uo_product, read_codemap
            from uo_init.ir.entity import EntityKind

            if proj is None:
                report.note = source or "missing CodeMap .uo"
                return report
            product = find_uo_product(proj, architecture=arch)
            if product is None:
                report.note = source or "missing CodeMap .uo"
                return report
            cm = read_codemap(product)
            fields_hit: set[str] = set()
            for ent in cm.entities.values():
                if ent.kind_name() not in {
                    EntityKind.FIELD.value,
                    EntityKind.VARIABLE.value,
                    EntityKind.PREDICATE.value,
                    EntityKind.OPERATION.value,
                    EntityKind.BUFFER.value,
                    EntityKind.QUEUE.value,
                    EntityKind.BRANCH.value,
                    EntityKind.KERNEL.value,
                    EntityKind.TILING_FIELD.value,
                    EntityKind.INPUT.value,
                    EntityKind.OUTPUT.value,
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
                        elif ent.kind_name() in {
                            EntityKind.OPERATION.value,
                            EntityKind.BUFFER.value,
                            EntityKind.QUEUE.value,
                            EntityKind.BRANCH.value,
                            EntityKind.KERNEL.value,
                            EntityKind.INPUT.value,
                            EntityKind.OUTPUT.value,
                        }:
                            report.hit_writers.append(
                                {
                                    "field": ent.name,
                                    "file": wf,
                                    "line": line,
                                    "kind": ent.kind_name(),
                                    "function": ent.attrs.get("function") or ent.attrs.get("callee"),
                                    "callee": ent.attrs.get("callee") or ent.name,
                                }
                            )
                            fields_hit.add(ent.name)
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
                f"codemap-entity scan ({source}): {len(report.hit_writers)} writers, "
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
    packed: list[int] = []
    for raw in list(doc.get("keys") or []) + list(doc.get("packed_keys") or []):
        key = _as_packed_key(raw)
        if key is not None:
            packed.append(key)
    for f in doc.get("fields") or []:
        if str(f.get("name") or "") not in fields_hit:
            continue
        for candidate in (f.get("packed_key"), f.get("key")):
            key = _as_packed_key(candidate)
            if key is not None:
                packed.append(key)
    report.affected_keys = sorted(set(packed))
    report.note = (
        f"source={source}; {len(report.hit_writers)} writers, "
        f"{len(report.hit_predicates)} predicates, fields={report.fields}"
    )
    return report
