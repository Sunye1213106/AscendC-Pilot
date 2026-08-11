# -*- coding: utf-8 -*-
"""Kernel Root Trace — source-rooted graph symmetric with Host UO.

Algorithm (no execution analysis):

  1. Collect source facts (Clang walks + lexical fallback)
  2. Build complete type / alias / member / call graph
  3. Seed AscendC / CANN terminal roots (+ known framework wrapper contracts)
  4. Single reverse fixed-point over WRAPS / ALIASES / CALLS
  5. Mark REACHED / UNRESOLVED / EXTERNAL with auditable gaps

Does **not** compute exec_rank, RAW/WAR/WAW, sync pairing, pipeline,
buffer lifecycle, or engine scheduling.
"""

from __future__ import annotations

import os
import re
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from uo_init.ids import buffer_site_id, make_id, operation_site_id, register_site_id
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes import kernel_scan as kscan
from uo_init.passes.source_text_cache import read_text
from uo_init.semantics import registry as semreg
from uo_init.semantics.ascendc_storage import (
    ASCENDC_BUFFER_TYPES,
    ASCENDC_REGISTER_TYPES,
    ASCENDC_STORAGE_WRAPPER_TYPES,
    MUTEX_BUFFER_METHOD_BRIDGES,
    is_non_storage_type,
    is_storage_type_text,
    is_storage_wrapper_type,
    is_valid_storage_name,
    memory_space_from_type_text,
    register_class_from_type,
    resolve_buffer_decl,
    storage_root_kind_from_space,
)
from uo_init.semantics.ascendc_sync import SYNC_MECHANISM

# ---------------------------------------------------------------------------
# Reason codes (auditable gaps)
# ---------------------------------------------------------------------------

REASON_NO_ASCENDC_ROOT = "NO_ASCENDC_ROOT_REACHED"
REASON_TYPE_UNRESOLVED = "TYPE_CANONICALIZATION_FAILED"
REASON_CALL_UNRESOLVED = "NO_ASCENDC_ROOT_REACHED"
REASON_EXTERNAL = "EXTERNAL_DECL_UNAVAILABLE"

_ROOT_KIND_BY_CATEGORY: dict[str, str] = {
    "memory_transfer": "MEMORY_API",
    "memory_init": "MEMORY_API",
    "buffer_init": "MEMORY_API",
    "buffer_acquire": "MEMORY_API",
    "buffer_release": "MEMORY_API",
    "buffer_view": "MEMORY_API",
    "queue_enqueue": "MEMORY_API",
    "queue_dequeue": "MEMORY_API",
    "sync_signal": "SYNC",
    "sync_wait": "SYNC",
    "sync_barrier": "SYNC",
    "reg_load": "REGISTER",
    "reg_store": "REGISTER",
    "reg_compute": "REGISTER",
    "vector": "COMPUTE_API",
    "cube": "COMPUTE_API",
    "cube_compute": "COMPUTE_API",
    "cube_load": "COMPUTE_API",
    "cube_store": "COMPUTE_API",
    "memory_atomic": "MEMORY_API",
}

# AscendC / CANN terminal API spellings used as catalog roots (not project names).
_ASCENDC_API_ROOTS: frozenset[str] = frozenset(
    set(ASCENDC_BUFFER_TYPES)
    | set(ASCENDC_REGISTER_TYPES)
    | set(SYNC_MECHANISM)
    | {
        "DataCopy",
        "DataCopyPad",
        "InitBuffer",
        "AllocTensor",
        "FreeTensor",
        "EnQue",
        "DeQue",
        "Get",
        "GetTensor",
        "SetAtomicAdd",
        "SetAtomicNone",
        "SetAtomicType",
        "Mmad",
        "LoadData",
        "Fixpipe",
        "Matmul",
    }
)

_CLASS_RE = re.compile(r"\b(?:class|struct)\s+(?P<name>[A-Za-z_]\w*)\b")
_USING_RE = re.compile(
    r"\busing\s+(?P<alias>[A-Za-z_]\w*)\s*=\s*(?P<target>[^;{]{1,400})\s*;"
)
_TYPEDEF_RE = re.compile(
    r"\btypedef\s+(?P<target>[\w:<>,\s*&]+?)\s+(?P<alias>[A-Za-z_]\w*)\s*;"
)
_MEMBER_RE = re.compile(
    r"(?P<type>(?:[\w:<>,\s*&]+?))\s+(?P<name>[A-Za-z_]\w*)\s*;"
)
_CONTINUATION_NAME_RE = re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\s*;\s*$")
_CXX_SKIP_BASE = frozenset(
    {
        "public",
        "private",
        "protected",
        "return",
        "if",
        "for",
        "while",
        "switch",
        "int",
        "float",
        "double",
        "bool",
        "char",
        "void",
        "auto",
        "size_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "half",
        "bfloat16_t",
    }
)


def _budget_s() -> float:
    raw = str(os.environ.get("UO_KERNEL_ROOT_TRACE_BUDGET_S") or "25").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 25.0


def _enabled() -> bool:
    raw = str(os.environ.get("UO_KERNEL_ROOT_TRACE") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _norm_file(path: str, root: str = "") -> str:
    return kscan.norm_file(path, root)


def _base_type_name(type_text: str) -> str:
    text = str(type_text or "").strip()
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|template)\b", " ", text)
    text = text.replace("&", " ").replace("*", " ")
    no_tpl = text.split("<", 1)[0].strip()
    token = no_tpl.split("::")[-1].strip()
    return token if token.isidentifier() else ""


def _is_ascendc_root_spelling(name: str) -> bool:
    return name in _ASCENDC_API_ROOTS or name in ASCENDC_BUFFER_TYPES or name in ASCENDC_REGISTER_TYPES


def _root_entity_id(spelling: str) -> str:
    return make_id("Root", "ascendc", spelling)


def _ensure_ascendc_root(codemap: CodeMap, spelling: str, *, root_kind: str) -> str:
    eid = _root_entity_id(spelling)
    codemap.upsert(
        EntityKind.TYPE,
        f"AscendC::{spelling}",
        eid=eid,
        attrs={
            "root_status": "REACHED",
            "root_kind": root_kind,
            "root": f"AscendC::{spelling}",
            "catalog": "ascendc",
            "spelling": spelling,
        },
        status="extracted",
        confidence=1.0,
    )
    return eid


def _category_root_kind(category: str, callee: str) -> str:
    if callee in SYNC_MECHANISM or category.startswith("sync_"):
        return "SYNC"
    if callee in ASCENDC_REGISTER_TYPES or category.startswith("reg_"):
        return "REGISTER"
    if category in _ROOT_KIND_BY_CATEGORY:
        return _ROOT_KIND_BY_CATEGORY[category]
    if callee in ASCENDC_BUFFER_TYPES or is_storage_wrapper_type(callee):
        return "STORAGE"
    return "COMPUTE_API"


def _decl_fields(decl: Any) -> tuple[str, str, str, str, int]:
    if isinstance(decl, dict):
        return (
            str(decl.get("type_text") or decl.get("type") or ""),
            str(decl.get("name") or ""),
            str(decl.get("function") or decl.get("scope") or ""),
            str(decl.get("file") or ""),
            int(decl.get("line") or 0),
        )
    return (
        str(getattr(decl, "type_text", "") or getattr(decl, "type", "") or ""),
        str(getattr(decl, "name", "") or ""),
        str(getattr(decl, "function", "") or getattr(decl, "scope", "") or ""),
        str(getattr(decl, "file", "") or ""),
        int(getattr(decl, "line", 0) or 0),
    )


# ---------------------------------------------------------------------------
# Source scanners (complete graph — not storage-filtered)
# ---------------------------------------------------------------------------


def _scan_type_aliases(files: list[Path], *, root: str, deadline: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        nfile = _norm_file(str(path), root)
        for i, line in enumerate(text.splitlines(), start=1):
            for m in _USING_RE.finditer(line):
                out.append(
                    {
                        "alias": m.group("alias"),
                        "target": m.group("target").strip(),
                        "file": nfile,
                        "line": i,
                    }
                )
            for m in _TYPEDEF_RE.finditer(line):
                out.append(
                    {
                        "alias": m.group("alias"),
                        "target": m.group("target").strip(),
                        "file": nfile,
                        "line": i,
                    }
                )
    return out


def _scan_class_members(files: list[Path], *, root: str, deadline: float) -> list[dict[str, Any]]:
    """All class/struct field members in source scope (complete composition graph)."""
    out: list[dict[str, Any]] = []
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        lines = text.splitlines()
        current: str | None = None
        depth = 0
        pending_type: str | None = None
        pending_line = 0
        for i, line in enumerate(lines, start=1):
            cm = _CLASS_RE.search(line)
            if cm and ";" not in line:
                current = cm.group("name")
                depth = line.count("{") - line.count("}")
                if depth < 0:
                    depth = 0
                pending_type = None
                continue
            if current is None:
                continue
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                current = None
                depth = 0
                pending_type = None
                continue
            if pending_type is not None:
                nm = _CONTINUATION_NAME_RE.match(line)
                combined = f"{pending_type} {line.strip()}"
                emit_name = ""
                emit_type = ""
                if nm:
                    emit_name = nm.group("name")
                    emit_type = pending_type
                elif ";" in line:
                    m = _MEMBER_RE.search(combined.replace("\n", " "))
                    if m:
                        emit_type = m.group("type").strip()
                        emit_name = m.group("name")
                    else:
                        m2 = _MEMBER_RE.search(line)
                        if m2:
                            emit_type = f"{pending_type} {m2.group('type')}".strip()
                            emit_name = m2.group("name")
                if emit_name:
                    pending_type = None
                    if is_valid_storage_name(emit_name):
                        base = _base_type_name(emit_type)
                        if base and base not in _CXX_SKIP_BASE:
                            out.append(
                                {
                                    "owner": current,
                                    "member": emit_name,
                                    "type_text": emit_type,
                                    "base_type": base,
                                    "file": _norm_file(str(path), root),
                                    "line": pending_line,
                                }
                            )
                    continue
                pending_type = combined
                continue
            if "(" in line and "std::conditional" not in line and "conditional_t" not in line:
                continue
            stripped = line.rstrip()
            if ";" not in line and (
                stripped.endswith("::type")
                or stripped.endswith(",")
                or (
                    ("MutexBuffer" in line or "conditional" in line or "Tensor" in line)
                    and not re.search(r"\b[A-Za-z_]\w*\s*;\s*$", line)
                )
            ):
                pending_type = stripped
                pending_line = i
                continue
            for m in _MEMBER_RE.finditer(line):
                type_text = m.group("type").strip()
                name = m.group("name")
                if not is_valid_storage_name(name):
                    continue
                base = _base_type_name(type_text)
                if not base or base in _CXX_SKIP_BASE:
                    continue
                out.append(
                    {
                        "owner": current,
                        "member": name,
                        "type_text": type_text,
                        "base_type": base,
                        "file": _norm_file(str(path), root),
                        "line": i,
                    }
                )
    return out


def _purge_root_trace_entities(codemap: CodeMap) -> None:
    drop_kinds = {
        EntityKind.OPERATION.value,
        EntityKind.BUFFER.value,
        EntityKind.REGISTER.value,
    }
    drop_ids = {e.id for e in codemap.entities.values() if e.kind_name() in drop_kinds}
    for e in list(codemap.entities.values()):
        if e.kind_name() != EntityKind.TYPE.value:
            continue
        if e.attrs.get("catalog") == "ascendc":
            drop_ids.add(e.id)
        if e.attrs.get("role") in {
            "storage_wrapper_type",
            "project_wrapper_type",
            "type_alias",
            "source_type",
        }:
            drop_ids.add(e.id)
    for eid in drop_ids:
        codemap.entities.pop(eid, None)
    keep_rel = {
        RelationKind.WRAPS.value,
        RelationKind.ROOTED_AT.value,
        RelationKind.ALIASES.value,
        RelationKind.REFERENCES.value,
        RelationKind.CALLS.value,
        RelationKind.CONTAINS.value,
    }
    for rid, rel in list(codemap.relations.items()):
        if rel.src in drop_ids or rel.dst in drop_ids:
            if (
                rel.kind_name() == RelationKind.CALLS.value
                and rel.src not in drop_ids
                and rel.dst not in drop_ids
            ):
                continue
            if (
                rel.kind_name() == RelationKind.REFERENCES.value
                and rel.src not in drop_ids
                and rel.dst not in drop_ids
                and str(rel.attrs.get("provenance") or "") != "kernel_root_trace"
            ):
                continue
            if rel.kind_name() in keep_rel or rel.src in drop_ids or rel.dst in drop_ids:
                if str(rel.attrs.get("provenance") or "") == "kernel_root_trace" or (
                    rel.src in drop_ids or rel.dst in drop_ids
                ):
                    codemap.relations.pop(rid, None)


def _link(
    codemap: CodeMap,
    kind: RelationKind,
    src: str,
    dst: str,
    *,
    attrs: dict[str, Any] | None = None,
    status: str = "confirmed",
) -> None:
    codemap.link(
        kind,
        src,
        dst,
        attrs={**(attrs or {}), "provenance": "kernel_root_trace"},
        status=status,
    )


def _propagate_reachability(codemap: CodeMap) -> None:
    """Single reverse fixed-point over WRAPS / ALIASES / CALLS from REACHED nodes."""
    reverse: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for rel in codemap.relations.values():
        if str(rel.attrs.get("provenance") or "") != "kernel_root_trace":
            # Also follow CALLS from kernel call binder if present.
            if rel.kind_name() != RelationKind.CALLS.value:
                continue
        kn = rel.kind_name()
        if kn not in {
            RelationKind.WRAPS.value,
            RelationKind.ALIASES.value,
            RelationKind.CALLS.value,
            RelationKind.ROOTED_AT.value,
        }:
            continue
        # Reverse: dst → src means "src reaches via dst"
        if kn == RelationKind.ROOTED_AT.value:
            continue
        reverse[rel.dst].append((rel.src, kn))

    queue: deque[str] = deque()
    seen: set[str] = set()
    for eid, e in codemap.entities.items():
        if e.attrs.get("root_status") == "REACHED":
            queue.append(eid)
            seen.add(eid)

    while queue:
        cur = queue.popleft()
        cur_e = codemap.entities.get(cur)
        if cur_e is None:
            continue
        cur_root = str(cur_e.attrs.get("root") or cur_e.name)
        cur_kind = str(cur_e.attrs.get("root_kind") or "")
        for parent, via in reverse.get(cur, []):
            pe = codemap.entities.get(parent)
            if pe is None:
                continue
            if pe.attrs.get("root_status") == "REACHED" and pe.attrs.get("root"):
                # Already rooted; still allow ROOTED_AT edge refresh below.
                pass
            else:
                pe.attrs["root_status"] = "REACHED"
                pe.attrs["root"] = cur_root if cur_root.startswith("AscendC::") else (
                    cur_root if "::" in cur_root else f"AscendC::{cur_root.replace('AscendC::', '')}"
                )
                if not str(pe.attrs.get("root") or "").startswith("AscendC::") and cur_e.attrs.get("catalog") == "ascendc":
                    pe.attrs["root"] = cur_e.name
                pe.attrs["root_kind"] = cur_kind or pe.attrs.get("root_kind") or "STORAGE"
                trace = list(pe.attrs.get("trace") or [pe.name])
                if cur_e.name not in trace:
                    trace.append(cur_e.name)
                pe.attrs["trace"] = trace
                pe.status = "extracted"
                pe.confidence = max(float(pe.confidence or 0), 0.9)

            # Point ROOTED_AT at AscendC catalog when available.
            target = cur
            root_spell = str(pe.attrs.get("root") or "").replace("AscendC::", "")
            if root_spell and _is_ascendc_root_spelling(root_spell):
                target = _ensure_ascendc_root(
                    codemap, root_spell, root_kind=str(pe.attrs.get("root_kind") or "STORAGE")
                )
            elif cur_e.attrs.get("catalog") == "ascendc":
                target = cur
            _link(
                codemap,
                RelationKind.ROOTED_AT,
                parent,
                target,
                attrs={"via": f"{via}_closure"},
            )
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)


def finalize_kernel_root_trace(
    codemap: CodeMap,
    source_root: Path | str,
    *,
    architecture: str = "arch35",
) -> CodeMap:
    if not _enabled():
        codemap.meta["kernel_root_trace"] = {"skipped": True, "reason": "UO_KERNEL_ROOT_TRACE=0"}
        return codemap

    t0 = time.perf_counter()
    deadline = t0 + _budget_s()
    root = str(Path(source_root).expanduser().resolve())
    arch = (architecture or codemap.architecture or "arch35").strip()
    reachable, filter_strict = kscan.reachable_function_names(codemap)
    files = kscan.selected_kernel_files(codemap, Path(root))

    _purge_root_trace_entities(codemap)

    # --- 1. Source facts -------------------------------------------------
    calls, decls, _controls, provenance = kscan.collect_call_sites_from_walks(
        Path(root),
        architecture=arch,
        reachable=reachable,
        filter_strict=filter_strict,
        deadline=deadline,
    )
    # Lexical fallback: all identifier calls in selected files (not primitive-only).
    if files and time.perf_counter() < deadline:
        lexical = kscan.lexical_source_call_sites(
            files,
            reachable=reachable,
            filter_strict=filter_strict,
            root=root,
            deadline=deadline,
        )
        calls, added = kscan.merge_lexical_sites(calls, lexical, root=root)
        if added:
            provenance = f"{provenance}+lexical_source_calls"
        lex_decls = kscan.lexical_buffer_decls(
            files,
            reachable=reachable,
            filter_strict=False,
            deadline=deadline,
        )
        decls = list(decls or []) + list(lex_decls or [])

    aliases = _scan_type_aliases(files, root=root, deadline=deadline) if files else []
    members = _scan_class_members(files, root=root, deadline=deadline) if files else []

    alias_to_target: dict[str, str] = {
        str(row["alias"]): str(row["target"]) for row in aliases
    }

    def _resolve_alias_chain(type_text: str) -> str:
        base = _base_type_name(type_text)
        seen: set[str] = set()
        while base and base in alias_to_target and base not in seen:
            seen.add(base)
            type_text = alias_to_target[base]
            base = _base_type_name(type_text)
        return type_text

    type_ents: dict[str, str] = {}

    # --- 2. Complete type / alias / member graph -------------------------
    for row in aliases:
        alias = str(row["alias"])
        target = str(row["target"])
        tid = make_id("Type", "alias", alias, row["file"], int(row["line"]))
        resolved = _resolve_alias_chain(target)
        root_spell = _base_type_name(resolved)
        reached = _is_ascendc_root_spelling(root_spell)
        ent = codemap.upsert(
            EntityKind.TYPE,
            alias,
            eid=tid,
            attrs={
                "role": "type_alias",
                "alias_of": target,
                "resolved_type": resolved,
                "root_status": "REACHED" if reached else "UNRESOLVED",
                "root_kind": (
                    "REGISTER"
                    if reached and root_spell in ASCENDC_REGISTER_TYPES
                    else ("STORAGE" if reached and root_spell in ASCENDC_BUFFER_TYPES else (
                        "SYNC" if reached and root_spell in SYNC_MECHANISM else (
                            "COMPUTE_API" if reached else ""
                        )
                    ))
                ),
                "root": f"AscendC::{root_spell}" if reached else "",
                "trace": [alias, _base_type_name(target)] + ([root_spell] if reached else []),
            },
            file=str(row["file"]),
            line=int(row["line"]),
            status="extracted" if reached else "partial",
            confidence=1.0 if reached else 0.5,
        )
        type_ents[alias] = ent.id
        # Always ALIASES to target type node (complete graph).
        tbase = _base_type_name(target)
        if tbase and tbase not in type_ents:
            if _is_ascendc_root_spelling(tbase):
                type_ents[tbase] = _ensure_ascendc_root(
                    codemap,
                    tbase,
                    root_kind="STORAGE" if tbase in ASCENDC_BUFFER_TYPES else (
                        "REGISTER" if tbase in ASCENDC_REGISTER_TYPES else "COMPUTE_API"
                    ),
                )
            else:
                mid = make_id("Type", "alias_target", tbase, row["file"], int(row["line"]))
                ment = codemap.upsert(
                    EntityKind.TYPE,
                    tbase,
                    eid=mid,
                    attrs={"role": "source_type", "root_status": "UNRESOLVED"},
                    file=str(row["file"]),
                    line=int(row["line"]),
                    status="partial",
                    confidence=0.5,
                )
                type_ents[tbase] = ment.id
        if tbase and tbase in type_ents:
            _link(codemap, RelationKind.ALIASES, ent.id, type_ents[tbase], attrs={"via": "using"})
        if reached:
            rid = _ensure_ascendc_root(
                codemap,
                root_spell,
                root_kind=str(ent.attrs.get("root_kind") or "STORAGE"),
            )
            _link(codemap, RelationKind.ROOTED_AT, ent.id, rid)

    # Every class that appears as an owner or member type gets a TYPE node.
    for row in members:
        owner = str(row["owner"])
        if owner not in type_ents:
            oid = make_id("Type", "class", owner, row["file"], int(row["line"]))
            ent = codemap.upsert(
                EntityKind.TYPE,
                owner,
                eid=oid,
                attrs={
                    "role": "source_type",
                    "root_status": "UNRESOLVED",
                    "root_kind": "",
                    "root": "",
                    "trace": [owner],
                },
                file=str(row["file"]),
                line=int(row["line"]),
                status="partial",
                confidence=0.5,
            )
            type_ents[owner] = ent.id

    wraps_edges: list[tuple[str, str, dict[str, Any]]] = []
    for row in members:
        owner = str(row["owner"])
        if owner not in type_ents:
            continue
        type_text = str(row["type_text"])
        resolved = _resolve_alias_chain(type_text)
        resolved_base = _base_type_name(resolved) or str(row["base_type"])
        if not resolved_base or resolved_base in _CXX_SKIP_BASE:
            continue
        if resolved_base not in type_ents:
            if is_storage_wrapper_type(resolved) or resolved_base in ASCENDC_STORAGE_WRAPPER_TYPES:
                mid = make_id("Type", "wrapper", resolved_base, row["file"], int(row["line"]))
                ment = codemap.upsert(
                    EntityKind.TYPE,
                    resolved_base,
                    eid=mid,
                    attrs={
                        "role": "storage_wrapper_type",
                        "root_status": "UNRESOLVED",
                        "type_text": resolved,
                    },
                    file=str(row["file"]),
                    line=int(row["line"]),
                    status="partial",
                    confidence=0.5,
                )
                type_ents[resolved_base] = ment.id
            elif _is_ascendc_root_spelling(resolved_base):
                type_ents[resolved_base] = _ensure_ascendc_root(
                    codemap,
                    resolved_base,
                    root_kind=(
                        "STORAGE"
                        if resolved_base in ASCENDC_BUFFER_TYPES
                        else (
                            "REGISTER"
                            if resolved_base in ASCENDC_REGISTER_TYPES
                            else "COMPUTE_API"
                        )
                    ),
                )
            else:
                mid = make_id("Type", "member_type", resolved_base, row["file"], int(row["line"]))
                ment = codemap.upsert(
                    EntityKind.TYPE,
                    resolved_base,
                    eid=mid,
                    attrs={
                        "role": "source_type",
                        "root_status": "UNRESOLVED",
                        "type_text": resolved,
                    },
                    file=str(row["file"]),
                    line=int(row["line"]),
                    status="partial",
                    confidence=0.5,
                )
                type_ents[resolved_base] = ment.id
        wraps_edges.append(
            (
                type_ents[owner],
                type_ents[resolved_base],
                {
                    "member": row["member"],
                    "type_text": type_text,
                    "file": row["file"],
                    "line": row["line"],
                },
            )
        )

    for src, dst, attrs in wraps_edges:
        _link(codemap, RelationKind.WRAPS, src, dst, attrs=attrs)

    # --- 3. Seed AscendC / CANN roots (+ framework wrapper contracts) ----
    for spell in sorted(ASCENDC_BUFFER_TYPES):
        type_ents.setdefault(spell, _ensure_ascendc_root(codemap, spell, root_kind="STORAGE"))
    for spell in sorted(ASCENDC_REGISTER_TYPES):
        type_ents.setdefault(spell, _ensure_ascendc_root(codemap, spell, root_kind="REGISTER"))
    for spell in sorted(SYNC_MECHANISM):
        type_ents.setdefault(spell, _ensure_ascendc_root(codemap, spell, root_kind="SYNC"))
    for spell in sorted(_ASCENDC_API_ROOTS - ASCENDC_BUFFER_TYPES - set(ASCENDC_REGISTER_TYPES) - set(SYNC_MECHANISM)):
        type_ents.setdefault(
            spell,
            _ensure_ascendc_root(codemap, spell, root_kind=_category_root_kind("", spell)),
        )

    # Framework wrapper contract: MutexBuffer (etc.) wraps LocalTensor when
    # the CANN-backed storage lives outside project source scope.
    for spell in sorted(ASCENDC_STORAGE_WRAPPER_TYPES):
        if spell == "Buffer":
            continue  # ambiguous bare Buffer
        if spell not in type_ents:
            mid = make_id("Type", "wrapper", spell, "catalog", 0)
            ment = codemap.upsert(
                EntityKind.TYPE,
                spell,
                eid=mid,
                attrs={
                    "role": "storage_wrapper_type",
                    "root_status": "UNRESOLVED",
                    "trace": [spell],
                },
                status="partial",
                confidence=0.5,
            )
            type_ents[spell] = ment.id
        rid = _ensure_ascendc_root(codemap, "LocalTensor", root_kind="STORAGE")
        _link(
            codemap,
            RelationKind.WRAPS,
            type_ents[spell],
            rid,
            attrs={"via": "framework_storage_contract"},
        )
        me = codemap.entities[type_ents[spell]]
        me.attrs["root_status"] = "REACHED"
        me.attrs["root"] = "AscendC::LocalTensor"
        me.attrs["root_kind"] = "STORAGE"
        me.attrs["role"] = "storage_wrapper_type"
        me.attrs["trace"] = list(me.attrs.get("trace") or [spell]) + ["AscendC::LocalTensor"]
        me.status = "extracted"
        _link(codemap, RelationKind.ROOTED_AT, type_ents[spell], rid)

    # --- 4. BUFFER / REGISTER decl sites ---------------------------------
    buffer_by_key: dict[tuple[str, str], str] = {}
    buffer_by_name: dict[str, str] = {}
    gaps: list[dict[str, Any]] = []
    buf_count = 0
    reg_count = 0

    # Member fields as BUFFER anchors when typed as storage/wrapper/alias-to-them.
    for row in members:
        type_text = str(row.get("type_text") or "")
        expanded = _resolve_alias_chain(type_text)
        name = str(row["member"])
        if not is_valid_storage_name(name):
            continue
        base = _base_type_name(expanded) or str(row.get("base_type") or "")
        known = (
            is_storage_type_text(expanded)
            or is_storage_wrapper_type(expanded)
            or base in alias_to_target
            or (
                base in type_ents
                and str(codemap.entities[type_ents[base]].attrs.get("root_status") or "") == "REACHED"
            )
            or is_storage_wrapper_type(type_text)
        )
        if not known:
            continue
        nfile = str(row["file"])
        line = int(row["line"])
        owner = str(row["owner"])
        bid = buffer_site_id(file=nfile, line=line, scope=owner, name=name, root=root)
        is_wrapper = is_storage_wrapper_type(expanded) or is_storage_wrapper_type(type_text)
        resolved = resolve_buffer_decl(expanded) or resolve_buffer_decl(type_text)
        space = memory_space_from_type_text(expanded) or memory_space_from_type_text(type_text) or "UNKNOWN"
        root_spell = ""
        if is_wrapper:
            root_spell = str((resolved or {}).get("storage_root_kind") or "LocalTensor")
        elif base in ASCENDC_BUFFER_TYPES:
            root_spell = base
        elif base in type_ents and codemap.entities[type_ents[base]].attrs.get("root_status") == "REACHED":
            root_spell = str(codemap.entities[type_ents[base]].attrs.get("root") or "").replace("AscendC::", "")
        attrs = {
            "memory_space": space,
            "scope": owner,
            "type_text": type_text,
            "role": "storage_wrapper" if is_wrapper else "project_wrapper",
            "wrapper": "MutexBuffer" if is_wrapper and "MutexBuffer" in (expanded + type_text) else (
                _base_type_name(expanded) if is_wrapper else ""
            ),
            "root_status": "REACHED" if root_spell else "UNRESOLVED",
            "root_kind": "STORAGE" if root_spell else "",
            "root": f"AscendC::{root_spell}" if root_spell else "",
            "trace": [name] + ([base] if base else []) + ([root_spell] if root_spell else []),
        }
        ent = codemap.upsert(
            EntityKind.BUFFER,
            name,
            eid=bid,
            attrs=attrs,
            file=nfile,
            line=line,
            status="extracted" if root_spell else "partial",
            confidence=0.9 if root_spell else 0.4,
        )
        buffer_by_key[(owner, name)] = ent.id
        buffer_by_name[name] = ent.id
        buf_count += 1
        if base in type_ents:
            _link(codemap, RelationKind.WRAPS, ent.id, type_ents[base], attrs={"via": "member_type"})
        if root_spell:
            rid = _ensure_ascendc_root(codemap, root_spell, root_kind="STORAGE")
            _link(codemap, RelationKind.WRAPS, ent.id, rid, attrs={"via": "storage_root"})
            _link(codemap, RelationKind.ROOTED_AT, ent.id, rid)

    for decl in decls or []:
        type_text, name, function, file, line = _decl_fields(decl)
        if not name or not is_valid_storage_name(name):
            continue
        expanded = _resolve_alias_chain(type_text)
        base = _base_type_name(expanded)
        known = (
            is_storage_type_text(expanded)
            or is_storage_type_text(type_text)
            or base in alias_to_target
            or (
                base in type_ents
                and str(codemap.entities[type_ents[base]].attrs.get("root_status") or "") == "REACHED"
            )
        )
        if not known:
            continue
        if is_non_storage_type(expanded):
            continue
        nfile = _norm_file(file, root)
        reg_class = register_class_from_type(expanded) or register_class_from_type(type_text)
        if reg_class:
            rid = register_site_id(file=file, line=line, scope=function, name=name, root=root)
            root_id = _ensure_ascendc_root(
                codemap, _base_type_name(expanded) or "RegTensor", root_kind="REGISTER"
            )
            ent = codemap.upsert(
                EntityKind.REGISTER,
                name,
                eid=rid,
                attrs={
                    "register_class": reg_class,
                    "type_text": type_text,
                    "scope": function,
                    "root_status": "REACHED",
                    "root_kind": "REGISTER",
                    "root": codemap.entities[root_id].name,
                    "trace": [name, _base_type_name(expanded) or type_text],
                },
                file=nfile,
                line=line,
                status="extracted",
                confidence=1.0,
            )
            _link(codemap, RelationKind.ROOTED_AT, ent.id, root_id)
            reg_count += 1
            continue

        resolved = resolve_buffer_decl(expanded) or resolve_buffer_decl(type_text)
        space = memory_space_from_type_text(expanded) or memory_space_from_type_text(type_text) or "UNKNOWN"
        is_wrapper = bool((resolved or {}).get("is_wrapper")) or is_storage_wrapper_type(expanded)
        wrapper_spell = ""
        if is_wrapper:
            wrapper_spell = (
                "MutexBuffer" if "MutexBuffer" in (expanded or type_text) else _base_type_name(expanded)
            )
        project_reached = (
            base in type_ents
            and str(codemap.entities[type_ents[base]].attrs.get("root_status") or "") == "REACHED"
        )
        root_status = "REACHED"
        root_spell = ""
        if is_wrapper:
            root_spell = str((resolved or {}).get("storage_root_kind") or "LocalTensor")
        elif base in ASCENDC_BUFFER_TYPES:
            root_spell = base
        elif project_reached:
            root_spell = str(codemap.entities[type_ents[base]].attrs.get("root") or "").replace(
                "AscendC::", ""
            ) or "LocalTensor"
        elif space != "UNKNOWN" and (resolved or is_storage_type_text(expanded)):
            # Memory space only from type template args (TPosition/BufferType), not names.
            root_spell = storage_root_kind_from_space(space)
        else:
            root_status = "UNRESOLVED"

        bid = buffer_site_id(file=file, line=line, scope=function, name=name, root=root)
        attrs = {
            "memory_space": space,
            "scope": function,
            "type_text": type_text,
            "role": (
                "storage_wrapper"
                if is_wrapper
                else ("project_wrapper" if project_reached else "cann_storage")
            ),
            "wrapper": wrapper_spell,
            "root_status": root_status,
            "root_kind": "STORAGE" if root_status == "REACHED" else "",
            "root": f"AscendC::{root_spell}" if root_spell else "",
            "trace": [name]
            + ([wrapper_spell] if wrapper_spell else [])
            + ([root_spell] if root_spell else []),
        }
        if root_status == "UNRESOLVED":
            attrs["gap_code"] = REASON_NO_ASCENDC_ROOT
            gaps.append(
                {
                    "code": REASON_NO_ASCENDC_ROOT,
                    "entity_id": bid,
                    "name": name,
                    "file": nfile,
                    "line": line,
                }
            )
        ent = codemap.upsert(
            EntityKind.BUFFER,
            name,
            eid=bid,
            attrs=attrs,
            file=nfile,
            line=line,
            status="extracted" if root_status == "REACHED" else "partial",
            confidence=1.0 if root_status == "REACHED" else 0.4,
        )
        buffer_by_key[(function, name)] = ent.id
        buffer_by_name[name] = ent.id
        buf_count += 1
        if root_spell:
            rid = _ensure_ascendc_root(codemap, root_spell, root_kind="STORAGE")
            if is_wrapper and wrapper_spell in type_ents:
                _link(codemap, RelationKind.WRAPS, ent.id, type_ents[wrapper_spell])
            if base in type_ents:
                _link(codemap, RelationKind.WRAPS, ent.id, type_ents[base], attrs={"via": "decl_type"})
            _link(codemap, RelationKind.WRAPS, ent.id, rid, attrs={"via": "storage_root"})
            _link(codemap, RelationKind.ROOTED_AT, ent.id, rid)

    # --- 5. METHOD + OPERATION call sites (all source calls) -------------
    method_ents: dict[str, str] = {}  # short method name → METHOD entity id

    def _ensure_method(name: str, *, file: str = "", line: int = 0) -> str:
        short = str(name or "").split("::")[-1]
        if not short or not short.isidentifier():
            return ""
        if short in method_ents:
            return method_ents[short]
        mid = make_id("Method", "kernel", short, file or "kernel", line)
        ent = codemap.upsert(
            EntityKind.METHOD,
            short,
            eid=mid,
            attrs={
                "role": "source_method",
                "root_status": "UNRESOLVED",
                "root_kind": "",
                "root": "",
                "trace": [short],
            },
            file=file,
            line=line,
            status="partial",
            confidence=0.5,
        )
        method_ents[short] = ent.id
        return ent.id

    op_count = 0
    ordinals: dict[tuple[str, int, int, str], int] = {}
    for site in calls or []:
        d = site if isinstance(site, dict) else kscan.site_as_dict(site)
        callee = str(d.get("callee") or "").split("::")[-1]
        if not callee or not callee.isidentifier():
            continue
        file = str(d.get("file") or "")
        line = int(d.get("line") or 0)
        column = int(d.get("column") or 0)
        okey = (_norm_file(file, root), line, column, callee)
        ordinal = ordinals.get(okey, 0)
        ordinals[okey] = ordinal + 1
        category, _engine, conf = semreg.classify(callee)
        receiver = str(d.get("receiver") or "")
        function = str(d.get("caller") or "")
        nfile = _norm_file(file, root)
        caller_short = function.split("::")[-1] if function else ""

        # Receiver buffer / type for framework bridges (MutexBuffer methods).
        bid_recv = ""
        if receiver:
            bid_recv = buffer_by_key.get((function, receiver)) or buffer_by_name.get(receiver) or ""
        recv_is_wrapper = False
        if bid_recv and bid_recv in codemap.entities:
            be = codemap.entities[bid_recv]
            recv_is_wrapper = be.attrs.get("role") in {
                "storage_wrapper",
                "project_wrapper",
            } or is_storage_wrapper_type(str(be.attrs.get("type_text") or ""))

        bridge = MUTEX_BUFFER_METHOD_BRIDGES.get(callee) if recv_is_wrapper else None
        is_terminal = _is_ascendc_root_spelling(callee) or callee in SYNC_MECHANISM
        is_root = bool(is_terminal or bridge)
        root_kind = ""
        root_spell = ""
        if bridge:
            root_spell, root_kind = bridge
        elif is_terminal:
            root_spell = callee
            root_kind = _category_root_kind(category, callee)

        oid = operation_site_id(
            file=file, line=line, column=column, callee=callee, ordinal=ordinal, root=root
        )
        args = [str(a) for a in (d.get("args") or [])]
        targs = [str(a) for a in (d.get("template_args") or [])]
        trace = [callee]
        if bridge:
            trace.append(f"AscendC::{root_spell}")
        attrs = {
            "callee": callee,
            "category": category if is_terminal else ("framework_bridge" if bridge else "UNKNOWN"),
            "function": function,
            "args": args,
            "template_args": targs,
            "receiver": receiver,
            "root_status": "REACHED" if is_root else "UNRESOLVED",
            "root_kind": root_kind if is_root else "",
            "root": f"AscendC::{root_spell}" if is_root and root_spell else "",
            "wrapper": callee if bridge else "",
            "trace": trace,
            "provenance": str(d.get("provenance") or provenance),
            "column": column,
        }
        if not is_root and (category != "UNKNOWN" or conf not in {"", "unresolved"}):
            attrs["gap_code"] = REASON_CALL_UNRESOLVED
            gaps.append(
                {
                    "code": REASON_CALL_UNRESOLVED,
                    "entity_id": oid,
                    "callee": callee,
                    "file": nfile,
                    "line": line,
                }
            )
        ent = codemap.upsert(
            EntityKind.OPERATION,
            callee,
            eid=oid,
            attrs=attrs,
            file=nfile,
            line=line,
            status="extracted" if is_root else "partial",
            confidence=1.0 if is_root and conf == "confirmed" else (0.85 if bridge else 0.5),
        )
        op_count += 1

        # Source METHOD CALLS graph (caller → callee method or this op).
        caller_mid = _ensure_method(caller_short, file=nfile, line=line) if caller_short else ""
        callee_mid = ""
        if not is_terminal and not bridge:
            callee_mid = _ensure_method(callee, file=nfile, line=line)
        if caller_mid and callee_mid and caller_mid != callee_mid:
            _link(
                codemap,
                RelationKind.CALLS,
                caller_mid,
                callee_mid,
                attrs={
                    "via": "source_call",
                    "file": nfile,
                    "line": line,
                    "column": column,
                    "receiver": receiver,
                },
            )
        if caller_mid:
            _link(
                codemap,
                RelationKind.CALLS,
                caller_mid,
                ent.id,
                attrs={
                    "via": "call_site",
                    "file": nfile,
                    "line": line,
                    "column": column,
                    "receiver": receiver,
                },
            )
            # METHOD → OPERATION also participates in reachability reverse.
        if is_root and root_spell:
            rid = _ensure_ascendc_root(codemap, root_spell, root_kind=root_kind or "COMPUTE_API")
            if bridge and "MutexBuffer" in type_ents:
                _link(
                    codemap,
                    RelationKind.WRAPS,
                    ent.id,
                    type_ents["MutexBuffer"],
                    attrs={"via": "framework_method_bridge"},
                )
            _link(
                codemap,
                RelationKind.ROOTED_AT,
                ent.id,
                rid,
                attrs={"via": "framework_method_bridge" if bridge else "ascendc_catalog"},
            )
            if caller_mid:
                # Direct edge so fixed-point can climb methods that call rooted ops.
                _link(
                    codemap,
                    RelationKind.CALLS,
                    caller_mid,
                    rid,
                    attrs={"via": "rooted_call", "file": nfile, "line": line},
                    status="partial",
                )
        if bid_recv:
            _link(
                codemap,
                RelationKind.REFERENCES,
                ent.id,
                bid_recv,
                attrs={"symbol": receiver},
            )
            _link(
                codemap,
                RelationKind.CALLS,
                bid_recv,
                ent.id,
                attrs={
                    "via": "method_receiver",
                    "file": nfile,
                    "line": line,
                    "column": column,
                },
                status="partial",
            )

    # --- 6. Single fixed-point -------------------------------------------
    _propagate_reachability(codemap)

    # Propagate REACHED onto METHOD entities that CALL a REACHED node.
    # (Fixed-point already walks CALLS; refresh METHOD attrs from ROOTED_AT.)
    for e in codemap.by_kind(EntityKind.METHOD):
        if e.attrs.get("root_status") == "REACHED":
            continue
        for rel, other in codemap.neighbors(e.id, kind=RelationKind.CALLS, direction="out"):
            if other.attrs.get("root_status") == "REACHED" or other.attrs.get("catalog") == "ascendc":
                e.attrs["root_status"] = "REACHED"
                e.attrs["root"] = other.attrs.get("root") or other.name
                e.attrs["root_kind"] = other.attrs.get("root_kind") or e.attrs.get("root_kind") or ""
                trace = list(e.attrs.get("trace") or [e.name])
                if other.name not in trace:
                    trace.append(other.name)
                e.attrs["trace"] = trace
                e.status = "extracted"
                break

    # --- 7. Gaps for still-unresolved source types that participate in WRAPS
    unresolved_types = 0
    for e in codemap.entities.values():
        if e.kind_name() != EntityKind.TYPE.value:
            continue
        if e.attrs.get("catalog") == "ascendc":
            continue
        if e.attrs.get("root_status") != "UNRESOLVED":
            continue
        # Only gap types that appear in a WRAPS edge (participated in composition).
        participates = any(
            (r.src == e.id or r.dst == e.id)
            and r.kind_name() == RelationKind.WRAPS.value
            for r in codemap.relations.values()
        )
        if not participates:
            continue
        unresolved_types += 1
        gaps.append(
            {
                "code": REASON_NO_ASCENDC_ROOT,
                "entity_id": e.id,
                "name": e.name,
                "file": e.file,
                "line": e.line_start,
            }
        )

    elapsed = time.perf_counter() - t0
    gap_counts = Counter(str(g.get("code") or "") for g in gaps)
    reached_bufs = sum(
        1
        for e in codemap.by_kind(EntityKind.BUFFER)
        if e.attrs.get("root_status") == "REACHED"
    )
    reached_ops = sum(
        1
        for e in codemap.by_kind(EntityKind.OPERATION)
        if e.attrs.get("root_status") == "REACHED"
    )
    quality = {
        "operations": op_count,
        "buffers": buf_count,
        "registers": reg_count,
        "reached_operations": reached_ops,
        "reached_buffers": reached_bufs,
        "wraps": sum(1 for r in codemap.relations.values() if r.kind_name() == RelationKind.WRAPS.value),
        "rooted_at": sum(
            1 for r in codemap.relations.values() if r.kind_name() == RelationKind.ROOTED_AT.value
        ),
        "aliases": sum(
            1 for r in codemap.relations.values() if r.kind_name() == RelationKind.ALIASES.value
        ),
    }
    meta = {
        "architecture": arch,
        "elapsed_s": round(elapsed, 3),
        "budget_s": _budget_s(),
        "provenance": provenance,
        "selected_files": len(files),
        "class_members": len(members),
        "type_aliases": len(aliases),
        "operations": op_count,
        "buffers": buf_count,
        "registers": reg_count,
        "reached_operations": reached_ops,
        "reached_buffers": reached_bufs,
        "unresolved_types": unresolved_types,
        "gap_count": len(gaps),
        "gap_counts": dict(gap_counts),
        "gaps": gaps[:200],
        "quality": quality,
    }
    codemap.meta["kernel_root_trace"] = meta
    # Thin compat for older query helpers (not an execution model).
    codemap.meta["kernel_execution"] = {
        "operations": op_count,
        "buffers": buf_count,
        "registers": reg_count,
        "elapsed_s": meta["elapsed_s"],
        "root_trace": True,
    }
    return codemap
