# -*- coding: utf-8 -*-
"""Kernel Root Trace — UO canonical Kernel graph (not execution analysis).

Answers only:
  1. Can this Buffer / Sync / call reach an AscendC / CANN root?
  2. Which source wrappers / typedefs / call sites sit on the path?

Does **not** compute exec_rank, RAW/WAR/WAW, sync pairing, CopyIn/Out, overlap,
or buffer lifecycle. Those belong to optional deep analysis, not default UO.
"""

from __future__ import annotations

import os
import re
import time
from collections import Counter, defaultdict
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
    is_non_storage_type,
    is_storage_type_text,
    is_storage_view_accessor,
    is_storage_wrapper_type,
    is_valid_storage_name,
    memory_space_from_type_text,
    register_class_from_type,
    resolve_buffer_decl,
    storage_root_kind_from_space,
    wrapper_family_from_type,
)
from uo_init.semantics.ascendc_sync import SYNC_MECHANISM, SYNC_WRAPPER_TO_ROOT

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
}

# AscendC/CANN catalog roots only — project wrappers (MutexBuffer, …) are NOT roots.
_ASCENDC_ROOT_SPELLINGS: frozenset[str] = frozenset(
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
    }
)

_CLASS_RE = re.compile(r"\b(?:class|struct)\s+(?P<name>[A-Za-z_]\w*)\b")
_USING_RE = re.compile(
    r"\busing\s+(?P<alias>[A-Za-z_]\w*)\s*=\s*(?P<target>[^;{]{1,400})\s*;"
)
_MEMBER_RE = re.compile(
    r"(?P<type>(?:[\w:<>,\s*&]+?))\s+(?P<name>[A-Za-z_]\w*)\s*;"
)
_DECL_RE = re.compile(
    r"(?P<type>(?:[\w:<>,\s*&]+?))\s+(?P<name>[A-Za-z_]\w*)\s*(?:=|;)",
)
_PARAM_WRAPPER_RE = re.compile(
    r"(?P<type>(?:MutexBuffersPolicy\w*|MutexBuffer(?:Manager)?|MutexMatrix\w*)\s*(?:<[^;{}>]{0,300}>)?)"
    r"\s*&?\s*(?P<name>[A-Za-z_]\w*)\s*(?:,|\))",
)
_CONTINUATION_NAME_RE = re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\s*;\s*$")


def _scan_wrapper_params(files: list[Path], *, root: str, deadline: float) -> list[dict[str, Any]]:
    """Function parameters typed as MutexBuffer / policy (call-site receivers)."""
    out: list[dict[str, Any]] = []
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if "MutexBuffer" not in line and "MutexMatrix" not in line:
                continue
            for m in _PARAM_WRAPPER_RE.finditer(line):
                type_text = m.group("type").strip()
                name = m.group("name")
                if not is_valid_storage_name(name):
                    continue
                fam = wrapper_family_from_type(type_text)
                if not fam:
                    continue
                out.append(
                    {
                        "owner": "",
                        "member": name,
                        "type_text": type_text,
                        "base_type": _policy_base_from_type(type_text, fam),
                        "file": _norm_file(str(path), root),
                        "line": i,
                        "kind": "param",
                    }
                )
    return out


def _scan_selector_type_aliases(files: list[Path], *, deadline: float) -> dict[str, str]:
    """Map selector structs / ``using Alias = Selector::TYPE`` → policy type text."""
    selector_family_text: dict[str, str] = {}
    alias_target: dict[str, str] = {}
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        # Struct/class bodies (non-greedy-ish via brace depth).
        current: str | None = None
        depth = 0
        body: list[str] = []
        for line in text.splitlines():
            cm = _CLASS_RE.search(line)
            if cm and ";" not in line and depth == 0:
                current = cm.group("name")
                depth = line.count("{") - line.count("}")
                body = [line]
                if depth < 0:
                    depth = 0
                continue
            if current is None:
                # Top-level using
                um = _USING_RE.search(line)
                if um:
                    alias_target[um.group("alias")] = um.group("target").strip()
                continue
            body.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                blob = "\n".join(body)
                has_type_alias = bool(re.search(r"\busing\s+TYPE\s*=", blob))
                looks_like_selector = current.endswith("Selector") or has_type_alias
                if looks_like_selector and wrapper_family_from_type(blob):
                    for pol in (
                        "MutexBuffersPolicy3buff",
                        "MutexBuffersPolicy4buff",
                        "MutexBuffersPolicyDB",
                        "MutexBuffersPolicySingleBuffer",
                        "MutexMatrix2x2BufferPolicy",
                        "MutexBuffer",
                    ):
                        if pol in blob:
                            selector_family_text[current] = pol
                            break
                current = None
                depth = 0
                body = []
        for um in _USING_RE.finditer(text):
            alias_target[um.group("alias")] = um.group("target").strip()

    out: dict[str, str] = dict(selector_family_text)
    for alias, target in alias_target.items():
        fam = wrapper_family_from_type(target)
        if fam:
            out[alias] = target
            continue
        m = re.search(r"\b([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*::\s*TYPE\b", target)
        if m and m.group(1) in selector_family_text:
            out[alias] = selector_family_text[m.group(1)]
    return out


def _lexical_alias_and_wrapper_decls(
    files: list[Path],
    *,
    known_types: set[str],
    root: str,
    deadline: float,
) -> list[dict[str, Any]]:
    """Decls whose type base is a known alias / project wrapper (not AscendC spelling)."""
    if not known_types:
        return []
    out: list[dict[str, Any]] = []
    func = ""
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            func = kscan.update_enclosing_func(line, func)
            for m in _DECL_RE.finditer(line):
                type_text = m.group("type").strip()
                name = m.group("name")
                if not is_valid_storage_name(name):
                    continue
                base = _base_type_name(type_text)
                if base not in known_types:
                    continue
                # Skip if AscendC storage already matched by the main lexical path.
                if is_storage_type_text(type_text):
                    continue
                out.append(
                    {
                        "name": name,
                        "function": func,
                        "type_text": type_text,
                        "init": None,
                        "file": str(path),
                        "line": i,
                        "column": m.start() + 1,
                    }
                )
    return out


def _budget_s() -> float:
    raw = str(os.environ.get("UO_KERNEL_ROOT_TRACE_BUDGET_S") or "25").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 25.0


def _enabled() -> bool:
    raw = str(os.environ.get("UO_KERNEL_ROOT_TRACE") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _decl_fields(decl: Any) -> tuple[str, str, str, str, int]:
    if isinstance(decl, dict):
        return (
            str(decl.get("type_text") or ""),
            str(decl.get("name") or ""),
            str(decl.get("function") or ""),
            str(decl.get("file") or ""),
            int(decl.get("line") or 0),
        )
    return (
        str(getattr(decl, "type_text", "") or ""),
        str(getattr(decl, "name", "") or ""),
        str(getattr(decl, "function", "") or ""),
        str(getattr(decl, "file", "") or ""),
        int(getattr(decl, "line", 0) or 0),
    )


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
    return name in _ASCENDC_ROOT_SPELLINGS or name in ASCENDC_BUFFER_TYPES or name in ASCENDC_REGISTER_TYPES


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
    true_callee = SYNC_WRAPPER_TO_ROOT.get(callee, callee)
    if true_callee in SYNC_MECHANISM or category.startswith("sync_"):
        return "SYNC"
    if true_callee in ASCENDC_REGISTER_TYPES or category.startswith("reg_"):
        return "REGISTER"
    if category in _ROOT_KIND_BY_CATEGORY:
        return _ROOT_KIND_BY_CATEGORY[category]
    if true_callee in ASCENDC_BUFFER_TYPES or is_storage_wrapper_type(true_callee):
        return "STORAGE"
    return "COMPUTE_API"


def _ascendc_root_spelling_for_callee(callee: str) -> str:
    """Map call-site spelling to AscendC catalog root (wrappers → true root)."""
    return SYNC_WRAPPER_TO_ROOT.get(callee, callee)


def _scan_type_aliases(files: list[Path], *, root: str, deadline: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for m in _USING_RE.finditer(line):
                alias = m.group("alias")
                target = m.group("target").strip()
                out.append(
                    {
                        "alias": alias,
                        "target": target,
                        "file": _norm_file(str(path), root),
                        "line": i,
                    }
                )
    return out


def _scan_class_members(files: list[Path], *, root: str, deadline: float) -> list[dict[str, Any]]:
    """Lexical class/struct members for WRAPS discovery (no name heuristics)."""
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
                emit_line = pending_line
                if nm:
                    emit_name = nm.group("name")
                    emit_type = pending_type
                elif ";" in line:
                    # Closing line may be ``...>::type name;`` (type tail + name).
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
                        fam = wrapper_family_from_type(emit_type)
                        if fam and (not base or base in {"type", "conditional", "conditional_t", "nullptr_t"}):
                            base = _policy_base_from_type(emit_type, fam)
                        if (base or fam) and base not in {"public", "private", "protected", "return"}:
                            out.append(
                                {
                                    "owner": current,
                                    "member": emit_name,
                                    "type_text": emit_type,
                                    "base_type": base or _policy_base_from_type(emit_type, fam or ""),
                                    "file": _norm_file(str(path), root),
                                    "line": emit_line,
                                }
                            )
                    continue
                # Keep accumulating type text until a terminating ``;`` line.
                pending_type = combined
                continue
            if "(" in line and "std::conditional" not in line and "conditional_t" not in line:
                continue
            # Multi-line decl: type continues until a bare ``name;`` line.
            stripped = line.rstrip()
            if ";" not in line and (
                stripped.endswith("::type")
                or stripped.endswith(",")
                or (
                    ("MutexBuffer" in line or "conditional" in line)
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
                fam = wrapper_family_from_type(type_text)
                if not base and not fam:
                    continue
                if base in {"public", "private", "protected", "return"}:
                    continue
                if fam and (not base or base in {"type", "conditional", "conditional_t", "nullptr_t"}):
                    base = _policy_base_from_type(type_text, fam)
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


def _policy_base_from_type(type_text: str, fam: str) -> str:
    if "MutexBuffersPolicyDB" in type_text:
        return "MutexBuffersPolicyDB"
    if "MutexBuffersPolicy3buff" in type_text:
        return "MutexBuffersPolicy3buff"
    if "MutexBuffersPolicy4buff" in type_text:
        return "MutexBuffersPolicy4buff"
    if "MutexBuffersPolicySingleBuffer" in type_text:
        return "MutexBuffersPolicySingleBuffer"
    if "MutexMatrix2x2BufferPolicy" in type_text:
        return "MutexMatrix2x2BufferPolicy"
    if "MutexBufferManager" in type_text:
        return "MutexBufferManager"
    if "MutexBuffer" in type_text:
        return "MutexBuffer"
    return fam if fam != "MutexBuffersPolicy" else "MutexBuffersPolicySingleBuffer"


def _purge_root_trace_entities(codemap: CodeMap) -> None:
    drop_kinds = {
        EntityKind.OPERATION.value,
        EntityKind.BUFFER.value,
        EntityKind.BUFFER_VIEW.value,
        EntityKind.REGISTER.value,
        EntityKind.SYNC_EVENT.value,
        EntityKind.EXEC_REGION.value,
    }
    drop_ids = {e.id for e in codemap.entities.values() if e.kind_name() in drop_kinds}
    # Also drop AscendC catalog ROOT TYPE nodes we minted.
    for e in list(codemap.entities.values()):
        if e.kind_name() == EntityKind.TYPE.value and e.attrs.get("catalog") == "ascendc":
            drop_ids.add(e.id)
        if e.kind_name() == EntityKind.TYPE.value and e.attrs.get("role") in {
            "storage_wrapper_type",
            "project_wrapper_type",
            "type_alias",
        }:
            drop_ids.add(e.id)
    for eid in drop_ids:
        codemap.entities.pop(eid, None)
    drop_rel = {
        RelationKind.WRAPS.value,
        RelationKind.ROOTED_AT.value,
        RelationKind.ALIASES.value,
        RelationKind.REFERENCES.value,
        RelationKind.CALLS.value,
        RelationKind.VIEW_OF.value,
        RelationKind.READS_BUFFER.value,
        RelationKind.WRITES_BUFFER.value,
        RelationKind.READS_REGISTER.value,
        RelationKind.WRITES_REGISTER.value,
        RelationKind.CONTAINS.value,
        RelationKind.PRECEDES.value,
        RelationKind.EMITS_SYNC.value,
        RelationKind.SIGNALS.value,
        RelationKind.WAITS_ON.value,
        RelationKind.SYNCHRONIZES_WITH.value,
        RelationKind.HAPPENS_BEFORE.value,
        RelationKind.DATA_DEPENDS_ON.value,
        RelationKind.ALLOCATES.value,
        RelationKind.RELEASES.value,
        RelationKind.EXECUTES_ON.value,
    }
    for rid, rel in list(codemap.relations.items()):
        if rel.kind_name() in drop_rel or rel.src in drop_ids or rel.dst in drop_ids:
            # Keep host/kernel CALLS that are not among purged entities when possible.
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
            codemap.relations.pop(rid, None)


def finalize_kernel_root_trace(
    codemap: CodeMap,
    source_root: Path | str,
    *,
    architecture: str = "arch35",
) -> CodeMap:
    """Build Kernel Root Trace graph into the CodeMap."""
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

    # --- collect call sites + decls (clang walk + lexical) ---
    calls, decls, _controls, provenance = kscan.collect_call_sites_from_walks(
        Path(root),
        architecture=arch,
        reachable=reachable,
        filter_strict=filter_strict,
        deadline=deadline,
    )
    lexical_added = 0
    if files and time.perf_counter() < deadline:
        lexical = kscan.lexical_primitive_sites(
            files,
            reachable=reachable,
            filter_strict=False,
            root=root,
            deadline=deadline,
        )
        if lexical:
            if not calls:
                calls = lexical
                provenance = "lexical_ascendc_primitives"
            else:
                calls, lexical_added = kscan.merge_lexical_sites(calls, lexical, root=root)
                if lexical_added:
                    provenance = f"{provenance}+lexical_supplement"
        lex_decls = kscan.lexical_buffer_decls(
            files, reachable=reachable, filter_strict=False, deadline=deadline
        )
        seen_decl = {
            (
                _norm_file(str(d.get("file") if isinstance(d, dict) else getattr(d, "file", "")), root),
                int((d.get("line") if isinstance(d, dict) else getattr(d, "line", 0)) or 0),
                str((d.get("name") if isinstance(d, dict) else getattr(d, "name", "")) or ""),
            )
            for d in (decls or [])
        }
        for d in lex_decls or []:
            key = (
                _norm_file(str(d.get("file") or ""), root),
                int(d.get("line") or 0),
                str(d.get("name") or ""),
            )
            if key not in seen_decl:
                seen_decl.add(key)
                decls.append(d)

    aliases = _scan_type_aliases(files, root=root, deadline=deadline) if files else []
    members = _scan_class_members(files, root=root, deadline=deadline) if files else []
    params = _scan_wrapper_params(files, root=root, deadline=deadline) if files else []
    selector_aliases = _scan_selector_type_aliases(files, deadline=deadline) if files else {}
    # Expand dependent typedefs (L0CType / Selector::TYPE) into concrete policy spellings.
    for row in members:
        type_text = str(row.get("type_text") or "")
        if wrapper_family_from_type(type_text):
            continue
        for alias, target in selector_aliases.items():
            if alias and re.search(rf"\b{re.escape(alias)}\b", type_text):
                if wrapper_family_from_type(target):
                    row["type_text"] = target
                    row["base_type"] = _policy_base_from_type(target, wrapper_family_from_type(target))
                    break
    members = list(members) + list(params)

    # alias map: MyTensor -> LocalTensor
    alias_to_target: dict[str, str] = {}
    for row in aliases:
        alias_to_target[str(row["alias"])] = str(row["target"])

    # Decls typed as aliases / project wrappers (missed by AscendC-type lexical filter).
    if files and alias_to_target:
        extra = _lexical_alias_and_wrapper_decls(
            files,
            known_types=set(alias_to_target),
            root=root,
            deadline=deadline,
        )
        seen_extra = set()
        for d in decls:
            _t, name, _f, file, line = _decl_fields(d)
            seen_extra.add((_norm_file(file, root), line, name))
        for d in extra:
            key = (
                _norm_file(str(d.get("file") or ""), root),
                int(d.get("line") or 0),
                str(d.get("name") or ""),
            )
            if key not in seen_extra:
                seen_extra.add(key)
                decls.append(d)

    def _resolve_alias_chain(type_text: str) -> str:
        base = _base_type_name(type_text)
        seen: set[str] = set()
        while base and base in alias_to_target and base not in seen:
            seen.add(base)
            type_text = alias_to_target[base]
            base = _base_type_name(type_text)
        return type_text

    # --- TYPE alias nodes ---
    type_ents: dict[str, str] = {}  # base type name -> entity id
    for row in aliases:
        alias = str(row["alias"])
        target = str(row["target"])
        tid = make_id("Type", "alias", alias, row["file"], int(row["line"]))
        resolved = _resolve_alias_chain(target)
        root_spell = _base_type_name(resolved)
        via_wrapper = is_storage_wrapper_type(resolved) or is_storage_wrapper_type(target)
        reached_root = _is_ascendc_root_spelling(root_spell)
        # Alias to MutexBuffer/… is REACHED only once rooted at AscendC storage
        # (LocalTensor), not by treating the wrapper spelling as a catalog root.
        storage_root = ""
        if reached_root and root_spell in ASCENDC_BUFFER_TYPES:
            storage_root = root_spell
        elif reached_root and root_spell in ASCENDC_REGISTER_TYPES:
            storage_root = root_spell
        elif via_wrapper:
            storage_root = "LocalTensor"
        reached = bool(storage_root)
        attrs = {
            "role": "type_alias",
            "alias_of": target,
            "resolved_type": resolved,
            "wrapper": _base_type_name(target) if via_wrapper else "",
            "root_status": "REACHED" if reached else "UNRESOLVED",
            "root_kind": (
                "REGISTER"
                if storage_root in ASCENDC_REGISTER_TYPES
                else ("STORAGE" if reached else "")
            ),
            "root": f"AscendC::{storage_root}" if storage_root else "",
            "trace": [alias, _base_type_name(target)]
            + ([storage_root] if storage_root else []),
        }
        ent = codemap.upsert(
            EntityKind.TYPE,
            alias,
            eid=tid,
            attrs=attrs,
            file=str(row["file"]),
            line=int(row["line"]),
            status="extracted" if reached else "partial",
            confidence=1.0 if reached else 0.5,
        )
        type_ents[alias] = ent.id
        if reached and storage_root:
            rid = _ensure_ascendc_root(
                codemap,
                storage_root,
                root_kind=str(attrs["root_kind"] or "STORAGE"),
            )
            wrap_spell = _base_type_name(target)
            if via_wrapper and wrap_spell:
                # Keep alias → wrapper TYPE (project), then wrapper → AscendC root.
                wid = type_ents.get(wrap_spell)
                if not wid:
                    wid = make_id("Type", "wrapper", wrap_spell, row["file"], int(row["line"]))
                    went = codemap.upsert(
                        EntityKind.TYPE,
                        wrap_spell,
                        eid=wid,
                        attrs={
                            "role": "storage_wrapper_type",
                            "root_status": "REACHED",
                            "root_kind": "STORAGE",
                            "root": f"AscendC::{storage_root}",
                            "trace": [wrap_spell, f"AscendC::{storage_root}"],
                        },
                        file=str(row["file"]),
                        line=int(row["line"]),
                        status="extracted",
                        confidence=1.0,
                    )
                    type_ents[wrap_spell] = went.id
                    wid = went.id
                codemap.link(
                    RelationKind.ALIASES,
                    ent.id,
                    wid,
                    attrs={"provenance": "kernel_root_trace", "via": "using"},
                    status="confirmed",
                )
                codemap.link(
                    RelationKind.WRAPS,
                    ent.id,
                    wid,
                    attrs={"provenance": "kernel_root_trace", "via": "type_alias"},
                    status="confirmed",
                )
            else:
                codemap.link(
                    RelationKind.ALIASES,
                    ent.id,
                    rid,
                    attrs={"provenance": "kernel_root_trace", "via": "using"},
                    status="confirmed",
                )
            codemap.link(
                RelationKind.ROOTED_AT,
                ent.id,
                rid,
                attrs={"provenance": "kernel_root_trace"},
                status="confirmed",
            )

    # Seed AscendC storage catalog roots only (never project wrappers).
    for spell in sorted(ASCENDC_BUFFER_TYPES):
        type_ents.setdefault(
            spell,
            _ensure_ascendc_root(codemap, spell, root_kind="STORAGE"),
        )

    # --- class WRAPS graph from members ---
    # owner TYPE --WRAPS--> member base TYPE (only owners that hold storage wrappers)
    storage_owners = {
        str(row["owner"])
        for row in members
        if wrapper_family_from_type(str(row.get("type_text") or ""))
        or is_storage_wrapper_type(str(row.get("type_text") or ""))
        or _base_type_name(str(row.get("type_text") or "")) in ASCENDC_BUFFER_TYPES
        or _base_type_name(str(row.get("type_text") or "")) in ASCENDC_REGISTER_TYPES
    }
    owner_types: dict[str, str] = {}
    for row in members:
        owner = str(row["owner"])
        if owner not in storage_owners:
            continue
        if owner not in owner_types:
            oid = make_id("Type", "class", owner, row["file"], int(row["line"]))
            ent = codemap.upsert(
                EntityKind.TYPE,
                owner,
                eid=oid,
                attrs={
                    "role": "project_wrapper_type",
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
            owner_types[owner] = ent.id
            type_ents[owner] = ent.id

    wraps_edges: list[tuple[str, str, dict[str, Any]]] = []
    for row in members:
        owner = str(row["owner"])
        if owner not in owner_types:
            continue
        base = str(row["base_type"])
        type_text = str(row["type_text"])
        resolved = _resolve_alias_chain(type_text)
        resolved_base = _base_type_name(resolved) or base
        fam = wrapper_family_from_type(type_text)
        if fam and resolved_base in {"type", "conditional", "conditional_t", "nullptr_t", ""}:
            resolved_base = base
        # Ensure member type node exists
        if resolved_base not in type_ents:
            if is_storage_wrapper_type(resolved) or is_storage_wrapper_type(resolved_base):
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
                        "role": "project_wrapper_type",
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
                owner_types[owner],
                type_ents[resolved_base],
                {
                    "provenance": "kernel_root_trace",
                    "member": row["member"],
                    "type_text": type_text,
                    "file": row["file"],
                    "line": row["line"],
                },
            )
        )

    for src, dst, attrs in wraps_edges:
        codemap.link(RelationKind.WRAPS, src, dst, attrs=attrs, status="confirmed")

    # Propagate root_status along WRAPS (BFS from AscendC roots upward via reverse WRAPS).
    reverse: dict[str, list[str]] = defaultdict(list)
    for src, dst, _ in wraps_edges:
        reverse[dst].append(src)
    queue = [
        eid
        for eid, e in codemap.entities.items()
        if e.kind_name() == EntityKind.TYPE.value and e.attrs.get("root_status") == "REACHED"
    ]
    seen_q = set(queue)
    while queue:
        cur = queue.pop(0)
        cur_e = codemap.entities[cur]
        for parent in reverse.get(cur, []):
            pe = codemap.entities.get(parent)
            if pe is None:
                continue
            if pe.attrs.get("root_status") == "REACHED":
                continue
            pe.attrs["root_status"] = "REACHED"
            pe.attrs["root"] = cur_e.attrs.get("root") or cur_e.name
            pe.attrs["root_kind"] = cur_e.attrs.get("root_kind") or "STORAGE"
            trace = list(pe.attrs.get("trace") or [pe.name])
            if cur_e.name not in trace:
                trace.append(cur_e.name)
            pe.attrs["trace"] = trace
            pe.status = "extracted"
            pe.confidence = 0.9
            # Point ROOTED_AT at AscendC catalog root when available.
            root_spell = str(pe.attrs.get("root") or "").replace("AscendC::", "")
            target = cur
            if root_spell and _is_ascendc_root_spelling(root_spell):
                target = _ensure_ascendc_root(
                    codemap, root_spell, root_kind=str(pe.attrs.get("root_kind") or "STORAGE")
                )
            elif cur_e.attrs.get("catalog") == "ascendc":
                target = cur
            codemap.link(
                RelationKind.ROOTED_AT,
                parent,
                target,
                attrs={"provenance": "kernel_root_trace", "via": "wraps_closure"},
                status="confirmed",
            )
            if parent not in seen_q:
                seen_q.add(parent)
                queue.append(parent)

    # MutexBuffer / Buffer wrappers: explicit WRAPS → LocalTensor/GlobalTensor root
    for spell in ("MutexBuffer",):
        if spell in type_ents:
            space_default = "UNKNOWN"
            root_kind = "LocalTensor"
            rid = _ensure_ascendc_root(codemap, root_kind, root_kind="STORAGE")
            codemap.link(
                RelationKind.WRAPS,
                type_ents[spell],
                rid,
                attrs={"provenance": "kernel_root_trace", "via": "ascendc_storage_catalog"},
                status="confirmed",
            )
            codemap.link(
                RelationKind.ROOTED_AT,
                type_ents[spell],
                rid,
                attrs={"provenance": "kernel_root_trace"},
                status="confirmed",
            )
            me = codemap.entities[type_ents[spell]]
            me.attrs["root_status"] = "REACHED"
            me.attrs["root"] = f"AscendC::{root_kind}"
            me.attrs["root_kind"] = "STORAGE"
            me.attrs["role"] = "storage_wrapper_type"
            _ = space_default

    # Symbol → wrapper family (for Get/GetTensor disambiguation on policy receivers).
    symbol_family: dict[str, str] = {}
    for row in members:
        type_text = str(row.get("type_text") or "")
        fam = wrapper_family_from_type(type_text)
        if not fam:
            # Resolve through Selector::TYPE / local using aliases.
            for alias, target in selector_aliases.items():
                if alias and alias in type_text:
                    fam = wrapper_family_from_type(target)
                    if fam:
                        type_text = target
                        row["type_text"] = target
                        break
        if fam:
            symbol_family[str(row["member"])] = fam
    for alias, target in alias_to_target.items():
        fam = wrapper_family_from_type(target)
        if not fam and alias in selector_aliases:
            fam = wrapper_family_from_type(selector_aliases[alias])
            target = selector_aliases[alias]
        if fam:
            symbol_family[alias] = fam
    for alias, target in selector_aliases.items():
        fam = wrapper_family_from_type(target)
        if fam:
            symbol_family[alias] = fam
            # Also expand members typed as this alias.
            for row in members:
                if alias in str(row.get("type_text") or "") and str(row["member"]) not in symbol_family:
                    symbol_family[str(row["member"])] = fam
                    row["type_text"] = target

    # --- BUFFER / REGISTER decls ---
    buffer_by_key: dict[tuple[str, str], str] = {}
    buffer_by_name: dict[str, str] = {}
    gaps: list[dict[str, Any]] = []
    buf_count = 0
    reg_count = 0

    # Policy / MutexBuffer class members as BUFFER sites (code location anchors).
    for row in members:
        type_text = str(row.get("type_text") or "")
        fam = wrapper_family_from_type(type_text)
        if not fam:
            continue
        name = str(row["member"])
        if not is_valid_storage_name(name):
            continue
        nfile = str(row["file"])
        line = int(row["line"])
        owner = str(row["owner"])
        bid = buffer_site_id(file=nfile, line=line, scope=owner, name=name, root=root)
        root_spell = "LocalTensor"
        rid = _ensure_ascendc_root(codemap, root_spell, root_kind="STORAGE")
        wrap_spell = "MutexBuffer"
        ent = codemap.upsert(
            EntityKind.BUFFER,
            name,
            eid=bid,
            attrs={
                "memory_space": memory_space_from_type_text(type_text) or "UNKNOWN",
                "scope": owner,
                "type_text": type_text,
                "role": "storage_wrapper" if fam == "MutexBuffer" else "project_wrapper",
                "wrapper": wrap_spell,
                "root_status": "REACHED",
                "root_kind": "STORAGE",
                "root": f"AscendC::{root_spell}",
                "trace": [name, fam, root_spell],
            },
            file=nfile,
            line=line,
            status="extracted",
            confidence=0.9,
        )
        buffer_by_key[(owner, name)] = ent.id
        buffer_by_name[name] = ent.id
        buf_count += 1
        if wrap_spell in type_ents:
            codemap.link(
                RelationKind.WRAPS,
                ent.id,
                type_ents[wrap_spell],
                attrs={"provenance": "kernel_root_trace", "via": "member_wrapper"},
                status="confirmed",
            )
        codemap.link(
            RelationKind.WRAPS,
            ent.id,
            rid,
            attrs={"provenance": "kernel_root_trace", "via": "storage_wrapper"},
            status="confirmed",
        )
        codemap.link(
            RelationKind.ROOTED_AT,
            ent.id,
            rid,
            attrs={"provenance": "kernel_root_trace"},
            status="confirmed",
        )

    for decl in decls or []:
        type_text, name, function, file, line = _decl_fields(decl)
        if not name or not is_valid_storage_name(name):
            continue
        # Expand aliases in type text
        expanded = _resolve_alias_chain(type_text)
        base = _base_type_name(expanded)
        # Accept AscendC storage, wrappers, aliases to them, OR project types that WRAPS-reach a root.
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
            root_id = _ensure_ascendc_root(codemap, _base_type_name(expanded) or "RegTensor", root_kind="REGISTER")
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
            codemap.link(
                RelationKind.ROOTED_AT,
                ent.id,
                root_id,
                attrs={"provenance": "kernel_root_trace"},
                status="confirmed",
            )
            reg_count += 1
            continue

        resolved = resolve_buffer_decl(expanded) or resolve_buffer_decl(type_text)
        space = memory_space_from_type_text(expanded) or memory_space_from_type_text(type_text) or "UNKNOWN"
        is_wrapper = bool((resolved or {}).get("is_wrapper")) or is_storage_wrapper_type(expanded)
        wrapper_spell = ""
        if is_wrapper:
            wrapper_spell = "MutexBuffer" if "MutexBuffer" in (expanded or type_text) else _base_type_name(expanded)
        # Project wrapper type with REACHED status
        project_reached = (
            base in type_ents
            and str(codemap.entities[type_ents[base]].attrs.get("root_status") or "") == "REACHED"
        )
        root_status = "REACHED"
        root_spell = ""
        if is_wrapper:
            # Wrapper is not an AscendC buffer type — land on LocalTensor/GlobalTensor.
            root_spell = str((resolved or {}).get("storage_root_kind") or "LocalTensor")
        elif base in ASCENDC_BUFFER_TYPES:
            root_spell = base
        elif project_reached:
            root_spell = str(codemap.entities[type_ents[base]].attrs.get("root") or "").replace("AscendC::", "") or "LocalTensor"
        elif space != "UNKNOWN":
            root_spell = storage_root_kind_from_space(space)
        else:
            root_status = "UNRESOLVED"

        bid = buffer_site_id(file=file, line=line, scope=function, name=name, root=root)
        attrs = {
            "memory_space": space,
            "scope": function,
            "type_text": type_text,
            "role": "storage_wrapper" if is_wrapper else ("project_wrapper" if project_reached else "cann_storage"),
            "wrapper": wrapper_spell,
            "root_status": root_status,
            "root_kind": "STORAGE" if root_status == "REACHED" else "",
            "root": f"AscendC::{root_spell}" if root_spell else "",
            "trace": [name]
            + ([wrapper_spell] if wrapper_spell else [])
            + ([root_spell] if root_spell else []),
        }
        if root_status == "UNRESOLVED":
            attrs["gap_code"] = "buffer_root_unresolved"
            attrs["resolution_blocker"] = "no_ascendc_storage_root"
            gaps.append(
                {
                    "code": "buffer_root_unresolved",
                    "entity_id": bid,
                    "name": name,
                    "wrapper": wrapper_spell,
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
            if is_wrapper or project_reached:
                wrap_target = type_ents.get(wrapper_spell) if is_wrapper else None
                if not wrap_target and is_wrapper and base in type_ents:
                    wrap_target = type_ents[base]
                if wrap_target:
                    codemap.link(
                        RelationKind.WRAPS,
                        ent.id,
                        wrap_target,
                        attrs={"provenance": "kernel_root_trace"},
                        status="confirmed",
                    )
                codemap.link(
                    RelationKind.WRAPS,
                    ent.id,
                    rid,
                    attrs={"provenance": "kernel_root_trace", "via": "storage_wrapper"},
                    status="confirmed",
                )
            codemap.link(
                RelationKind.ROOTED_AT,
                ent.id,
                rid,
                attrs={"provenance": "kernel_root_trace"},
                status="confirmed",
            )
            if project_reached and base in type_ents:
                codemap.link(
                    RelationKind.WRAPS,
                    ent.id,
                    type_ents[base],
                    attrs={"provenance": "kernel_root_trace", "via": "decl_type"},
                    status="confirmed",
                )

    # --- OPERATION call sites: ROOTED_AT AscendC API, REFERENCES buffers ---
    op_count = 0
    ordinals: dict[tuple[str, int, int, str], int] = {}
    for site in calls or []:
        d = site if isinstance(site, dict) else kscan.site_as_dict(site)
        callee = str(d.get("callee") or "").split("::")[-1]
        if not callee:
            continue
        file = str(d.get("file") or "")
        line = int(d.get("line") or 0)
        column = int(d.get("column") or 0)
        okey = (_norm_file(file, root), line, column, callee)
        ordinal = ordinals.get(okey, 0)
        ordinals[okey] = ordinal + 1
        category, _engine, conf = semreg.classify(callee)
        root_kind = _category_root_kind(category, callee)
        root_spell = _ascendc_root_spelling_for_callee(callee)
        is_sync_wrapper = callee in SYNC_WRAPPER_TO_ROOT
        receiver = str(d.get("receiver") or "")
        function = str(d.get("caller") or "")
        # Disambiguate TQue::Get / GetTensor vs MutexBuffer/policy view accessors.
        view_family = ""
        if receiver and is_storage_view_accessor(callee):
            bid_recv = buffer_by_key.get((function, receiver)) or buffer_by_name.get(receiver)
            if bid_recv and bid_recv in codemap.entities:
                be = codemap.entities[bid_recv]
                view_family = str(be.attrs.get("wrapper") or "") or wrapper_family_from_type(
                    str(be.attrs.get("type_text") or "")
                )
                if not view_family and be.attrs.get("role") in {
                    "storage_wrapper",
                    "project_wrapper",
                }:
                    view_family = "MutexBuffer"
            if not view_family:
                view_family = symbol_family.get(receiver, "")
        is_view_wrapper = bool(view_family)
        if is_view_wrapper:
            root_spell = "LocalTensor"
            root_kind = "STORAGE"
        reached = (
            semreg.is_execution_primitive(callee)
            or callee in SYNC_MECHANISM
            or is_sync_wrapper
            or is_view_wrapper
        )
        oid = operation_site_id(
            file=file, line=line, column=column, callee=callee, ordinal=ordinal, root=root
        )
        args = [str(a) for a in (d.get("args") or [])]
        targs = [str(a) for a in (d.get("template_args") or [])]
        nfile = _norm_file(file, root)
        trace = [callee]
        if is_sync_wrapper and root_spell != callee:
            trace.append(root_spell)
        if is_view_wrapper:
            if view_family not in trace:
                trace.append(view_family)
            if root_spell not in trace:
                trace.append(root_spell)
        attrs: dict[str, Any] = {
            "callee": callee,
            "category": category if reached else "UNKNOWN",
            "function": function,
            "args": args,
            "template_args": targs,
            "receiver": receiver,
            "root_status": "REACHED" if reached else "UNRESOLVED",
            "root_kind": root_kind if reached else "",
            "root": f"AscendC::{root_spell}" if reached else "",
            "wrapper": (
                callee if is_sync_wrapper else (callee if is_view_wrapper else "")
            ),
            "trace": trace,
            "provenance": provenance,
        }
        if is_view_wrapper:
            attrs["via_receiver_family"] = view_family
        if not reached:
            attrs["gap_code"] = "call_root_unresolved"
            attrs["resolution_blocker"] = "not_in_ascendc_catalog"
            gaps.append(
                {
                    "code": "call_root_unresolved",
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
            status="extracted" if reached else "partial",
            confidence=1.0 if reached and conf == "confirmed" else 0.6,
        )
        op_count += 1
        if reached:
            rid = _ensure_ascendc_root(codemap, root_spell, root_kind=root_kind)
            if is_sync_wrapper or is_view_wrapper:
                via = "sync_wrapper" if is_sync_wrapper else "storage_view_accessor"
                if is_view_wrapper and "MutexBuffer" in type_ents:
                    codemap.link(
                        RelationKind.WRAPS,
                        ent.id,
                        type_ents["MutexBuffer"],
                        attrs={"provenance": "kernel_root_trace", "via": via},
                        status="confirmed",
                    )
                codemap.link(
                    RelationKind.WRAPS,
                    ent.id,
                    rid,
                    attrs={"provenance": "kernel_root_trace", "via": via},
                    status="confirmed",
                )
            codemap.link(
                RelationKind.ROOTED_AT,
                ent.id,
                rid,
                attrs={"provenance": "kernel_root_trace"},
                status="confirmed",
            )
        # REFERENCES to known buffers by arg / receiver name
        reads, writes = semreg.arg_effects(callee, args, receiver=receiver) if reached else ([], [])
        for bname in list(reads) + list(writes) + ([receiver] if receiver else []):
            if not is_valid_storage_name(bname):
                continue
            bid = buffer_by_key.get((function, bname)) or buffer_by_name.get(bname)
            if not bid:
                continue
            codemap.link(
                RelationKind.REFERENCES,
                ent.id,
                bid,
                attrs={"provenance": "kernel_root_trace", "symbol": bname},
                status="confirmed",
            )
        # Method-style forwarding: receiver.LockProd / receiver.GetTensor
        if receiver and reached and (root_kind == "SYNC" or is_view_wrapper):
            bid = buffer_by_key.get((function, receiver)) or buffer_by_name.get(receiver)
            if bid:
                codemap.link(
                    RelationKind.CALLS,
                    bid,
                    ent.id,
                    attrs={
                        "provenance": "kernel_root_trace",
                        "via": "method_receiver",
                        "file": nfile,
                        "line": line,
                        "column": column,
                    },
                    status="partial",
                )

    # Unresolved project types (never reached a root)
    _NON_STORAGE_TYPE_GAPS = frozenset(
        {
            "int64_t",
            "int32_t",
            "uint32_t",
            "uint16_t",
            "uint8_t",
            "int16_t",
            "int8_t",
            "bool",
            "float",
            "half",
            "bfloat16_t",
            "void",
            "type",
            "conditional",
            "conditional_t",
            "nullptr_t",
            "V",
            "size_t",
        }
    )
    unresolved_types = 0
    for e in codemap.entities.values():
        if e.kind_name() != EntityKind.TYPE.value:
            continue
        if e.attrs.get("catalog") == "ascendc":
            continue
        if e.name in _NON_STORAGE_TYPE_GAPS:
            continue
        if e.attrs.get("root_status") == "UNRESOLVED":
            unresolved_types += 1
            gaps.append(
                {
                    "code": "type_root_unresolved",
                    "entity_id": e.id,
                    "name": e.name,
                    "file": e.file,
                    "line": e.line_start,
                }
            )

    gap_counts = dict(Counter(str(g.get("code") or "") for g in gaps))
    reached_buf = sum(
        1
        for e in codemap.by_kind(EntityKind.BUFFER)
        if e.attrs.get("root_status") == "REACHED"
    )
    reached_op = sum(
        1
        for e in codemap.by_kind(EntityKind.OPERATION)
        if e.attrs.get("root_status") == "REACHED"
    )
    stats = {
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "budget_s": _budget_s(),
        "selected_files": len(files),
        "provenance": provenance,
        "lexical_supplement_added": lexical_added,
        "operations": op_count,
        "buffers": buf_count,
        "registers": reg_count,
        "type_aliases": len(aliases),
        "class_members": len(members),
        "wraps_edges": len(wraps_edges),
        "reached_buffers": reached_buf,
        "reached_operations": reached_op,
        "unresolved_types": unresolved_types,
        "gap_count": len(gaps),
        "gap_counts": gap_counts,
        "gaps": gaps,
        "quality": {
            "operations": op_count,
            "buffers": buf_count,
            "registers": reg_count,
            "reached_buffers": reached_buf,
            "reached_operations": reached_op,
            "gap_count": len(gaps),
            "gap_counts": gap_counts,
        },
    }
    if time.perf_counter() > deadline:
        stats["status"] = "partial"
        stats["notes"] = ["budget_exhausted"]
    codemap.meta["kernel_root_trace"] = stats
    # Compatibility shim for older query helpers expecting kernel_execution key.
    codemap.meta["kernel_execution"] = {
        "model": "root_trace",
        "elapsed_s": stats["elapsed_s"],
        "operations": op_count,
        "buffers": buf_count,
        "registers": reg_count,
        "gap_count": len(gaps),
        "gap_counts": gap_counts,
        "quality": stats["quality"],
    }
    return codemap
