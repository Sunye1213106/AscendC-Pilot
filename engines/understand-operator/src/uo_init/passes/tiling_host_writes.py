# -*- coding: utf-8 -*-
"""Resolve current-source Host writes to qualified TilingData fields.

This pass is intentionally independent from TilingKey def-use.  It builds a
small receiver-type index from Host declarations and TilingData nested members,
then accepts a ``set_field`` or direct member assignment only when the receiver
resolves to one concrete TilingData owner.  Ambiguous owners remain explicit
partial facts; short field names are never used to guess a write target.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.symbol_identity import normalize_symbol

_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_SETTER_RE = re.compile(
    r"(?P<receiver>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*)\s*"
    r"(?:\.|->)\s*set_(?P<field>[A-Za-z_]\w*)\s*\("
)
_DIRECT_RE = re.compile(
    r"(?P<lhs>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)+)\s*"
    r"(?<![=!<>])=(?!=)\s*(?P<rhs>[^;]+);",
    re.S,
)


def enrich_tiling_host_writes(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "arch35",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    host_dir = root / "op_host" / architecture
    if not host_dir.is_dir():
        return codemap

    types = {e.name: e for e in codemap.by_kind(EntityKind.TILING_DATA)}
    fields: dict[tuple[str, str], Entity] = {}
    nested_by_field: dict[str, set[str]] = defaultdict(set)
    for field in codemap.by_kind(EntityKind.TILING_FIELD):
        owner = str(field.attrs.get("owner") or "")
        fields[(owner, field.name)] = field
        nested = _base_type(str(field.attrs.get("cpp_type") or ""))
        if nested in types:
            nested_by_field[field.name].add(nested)

    texts: list[tuple[Path, str, str]] = []
    receiver_types: dict[str, set[str]] = defaultdict(set)
    type_names = sorted(types, key=len, reverse=True)
    if not type_names:
        return codemap
    type_alt = "|".join(re.escape(name) for name in type_names)
    declaration_re = re.compile(
        rf"\b(?P<type>{type_alt})\b\s*(?:const\s*)?[*&]*\s*(?P<name>[A-Za-z_]\w*)\b"
    )

    for path in sorted(host_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SUFFIXES:
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        masked = _mask_non_code(raw)
        texts.append((path, raw, masked))
        for match in declaration_re.finditer(masked):
            receiver_types[match.group("name")].add(match.group("type"))

    # Clear only facts owned by this verified pass so reruns are idempotent.
    remove_rel = {
        rid for rid, rel in codemap.relations.items()
        if str(rel.attrs.get("provenance") or "") == "source_tilingdata_host_write_verified"
    }
    remove_ent = {
        eid for eid, ent in codemap.entities.items()
        if str(ent.attrs.get("provenance") or "") in {
            "source_tilingdata_host_write_verified",
            "source_tilingdata_host_write_unresolved",
        }
    }
    for rid, rel in list(codemap.relations.items()):
        if rel.src in remove_ent or rel.dst in remove_ent:
            remove_rel.add(rid)
    for rid in remove_rel:
        codemap.relations.pop(rid, None)
    for eid in remove_ent:
        codemap.entities.pop(eid, None)

    sites = 0
    resolved = 0
    ambiguous = 0
    written_fields: set[str] = set()
    for path, raw, masked in texts:
        file = _rel(root, path)
        for match in _SETTER_RE.finditer(masked):
            close = _matching_paren(masked, match.end() - 1)
            if close < 0:
                continue
            sites += 1
            receiver = normalize_symbol(match.group("receiver"))
            field_name = match.group("field")
            owners = _receiver_owners(receiver, receiver_types, fields, nested_by_field, types)
            targets = [fields[(owner, field_name)] for owner in owners if (owner, field_name) in fields]
            targets = _unique(targets)
            line = _line(raw, match.start())
            expr = raw[match.end():close].strip()
            if len(targets) == 1:
                _write(codemap, targets[0], file, line, receiver, expr, "setter")
                written_fields.add(targets[0].id)
                resolved += 1
            else:
                _unresolved(codemap, file, line, receiver, field_name, expr, targets)
                ambiguous += 1

        for match in _DIRECT_RE.finditer(masked):
            lhs = normalize_symbol(match.group("lhs"))
            parts = [p for p in lhs.split(".") if p]
            if len(parts) < 2:
                continue
            receiver = ".".join(parts[:-1])
            field_name = parts[-1]
            owners = _receiver_owners(receiver, receiver_types, fields, nested_by_field, types)
            if not owners:
                continue
            targets = [fields[(owner, field_name)] for owner in owners if (owner, field_name) in fields]
            targets = _unique(targets)
            sites += 1
            line = _line(raw, match.start())
            expr = raw[match.start("rhs"):match.end("rhs")].strip()
            if len(targets) == 1:
                _write(codemap, targets[0], file, line, receiver, expr, "assignment")
                written_fields.add(targets[0].id)
                resolved += 1
            else:
                _unresolved(codemap, file, line, receiver, field_name, expr, targets)
                ambiguous += 1

    _attach_defaults(codemap, root, fields)
    closure = dict(codemap.meta.get("kernel_tiling_closure") or {})
    closure.update(
        {
            "tiling_host_writer_sites": sites,
            "tiling_resolved_host_writer_sites": resolved,
            "tiling_host_writer_fields": len(written_fields),
            "tiling_ambiguous_writer_sites": ambiguous,
            "tiling_host_writer_policy": "qualified-receiver/v1",
        }
    )
    codemap.meta["kernel_tiling_closure"] = closure
    return codemap


def _receiver_owners(
    receiver: str,
    receiver_types: dict[str, set[str]],
    fields: dict[tuple[str, str], Entity],
    nested_by_field: dict[str, set[str]],
    types: dict[str, Entity],
) -> set[str]:
    parts = [p for p in normalize_symbol(receiver).split(".") if p]
    if not parts:
        return set()
    owners = set(receiver_types.get(parts[0]) or ())
    # A receiver can itself be a nested TilingData field pointer assigned from
    # ``tilingData->nested`` even when its declaration is in a macro-expanded
    # class header.  The field name is still source-qualified by its cpp type.
    if not owners:
        owners.update(nested_by_field.get(parts[0]) or ())
    for segment in parts[1:]:
        next_owners: set[str] = set()
        if owners:
            for owner in owners:
                field = fields.get((owner, segment))
                if field is None:
                    continue
                nested = _base_type(str(field.attrs.get("cpp_type") or ""))
                if nested in types:
                    next_owners.add(nested)
        if not next_owners:
            next_owners.update(nested_by_field.get(segment) or ())
        owners = next_owners
    return owners


def _write(codemap: CodeMap, field: Entity, file: str, line: int, receiver: str, expr: str, mode: str) -> None:
    owner = str(field.attrs.get("owner") or "")
    node = codemap.upsert(
        EntityKind.PREDICATE,
        f"{owner}::{field.name} <- {expr[:120]}",
        eid=f"TDWRITEV::{file}::{line}::{owner}::{field.name}",
        attrs={
            "predicate_role": "tilingdata_writer",
            "owner": owner,
            "field": field.name,
            "receiver": receiver,
            "expression": expr[:600],
            "write_mode": mode,
            "provenance": "source_tilingdata_host_write_verified",
        },
        file=file,
        line=line,
        status="confirmed",
    )
    codemap.link(
        RelationKind.WRITES,
        node.id,
        field.id,
        attrs={
            "provenance": "source_tilingdata_host_write_verified",
            "file": file,
            "line": line,
            "mode": mode,
        },
        status="confirmed",
    )
    sites = field.attrs.setdefault("host_writer_sites", [])
    site = {"file": file, "line": line, "receiver": receiver, "expression": expr[:300], "mode": mode}
    if site not in sites:
        sites.append(site)
    field.attrs["host_writer_site_count"] = len(sites)


def _unresolved(
    codemap: CodeMap,
    file: str,
    line: int,
    receiver: str,
    field_name: str,
    expr: str,
    candidates: list[Entity],
) -> None:
    codemap.upsert(
        EntityKind.OTHER,
        f"{receiver}.set_{field_name}",
        eid=f"TDWRITEUNRES::{file}::{line}::{field_name}",
        attrs={
            "role": "tilingdata_writer_unresolved",
            "reason": "field_owner_ambiguous" if candidates else "field_owner_unknown",
            "receiver": receiver,
            "field": field_name,
            "expression": expr[:600],
            "candidate_fields": [f.attrs.get("qualified_name") for f in candidates],
            "provenance": "source_tilingdata_host_write_unresolved",
        },
        file=file,
        line=line,
        status="partial",
        confidence=0.5,
    )


def _attach_defaults(codemap: CodeMap, root: Path, fields: dict[tuple[str, str], Entity]) -> None:
    cache: dict[str, list[str]] = {}
    for field in fields.values():
        if not field.file or not field.line_start:
            continue
        if field.file not in cache:
            path = _resolve_file(root, field.file)
            cache[field.file] = path.read_text(encoding="utf-8", errors="replace").splitlines() if path else []
        lines = cache[field.file]
        line_no = int(field.line_start or 0)
        if not (1 <= line_no <= len(lines)):
            continue
        match = re.search(rf"\b{re.escape(field.name)}\b\s*=\s*([^;]+);", lines[line_no - 1])
        if match:
            field.attrs["default_initializer"] = match.group(1).strip()
            field.attrs["default_initializer_site"] = {"file": field.file, "line": line_no}


def _base_type(raw: str) -> str:
    text = re.sub(r"\b(?:const|volatile|typename|class|struct)\b", " ", raw or "")
    text = text.replace("*", " ").replace("&", " ").strip()
    text = re.sub(r"<.*>", "", text).strip()
    return text.split("::")[-1].strip().split()[-1] if text else ""


def _unique(items: list[Entity]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)
    return out


def _matching_paren(text: str, open_pos: int) -> int:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "(":
        return -1
    depth = 0
    for idx in range(open_pos, len(text)):
        if text[idx] == "(":
            depth += 1
        elif text[idx] == ")":
            depth -= 1
            if depth == 0:
                return idx
    return -1


def _mask_non_code(text: str) -> str:
    out = list(text)
    i = 0
    state = "code"
    quote = ""
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "line"
                continue
            if ch == "/" and nxt == "*":
                out[i] = out[i + 1] = " "
                i += 2
                state = "block"
                continue
            if ch in {'\"', "'"}:
                quote = ch
                out[i] = " "
                i += 1
                state = "string"
                continue
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                state = "code"
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "code"
            else:
                if ch != "\n":
                    out[i] = " "
                i += 1
            continue
        if state == "string":
            if ch == "\\" and i + 1 < len(text):
                out[i] = " "
                if text[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == quote:
                out[i] = " "
                i += 1
                state = "code"
            else:
                if ch != "\n":
                    out[i] = " "
                i += 1
    return "".join(out)


def _resolve_file(root: Path, raw: str) -> Path | None:
    rel = raw.replace("\\", "/").lstrip("./")
    candidates = [root.parent / rel, root / rel]
    if rel.startswith(root.name + "/"):
        candidates.append(root / rel[len(root.name) + 1:])
    for path in candidates:
        if path.is_file():
            return path
    return None


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1
