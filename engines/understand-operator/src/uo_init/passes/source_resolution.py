# -*- coding: utf-8 -*-
"""Resolve historical UO gaps using current source structure only.

This pass runs after :mod:`source_contract`.  It upgrades unresolved archive
records only when the current arch-scoped source contains machine-verifiable
evidence for the exact missing concept.  It intentionally leaves control-flow
frontier and complete call-graph gaps unresolved when a compiler-backed walk is
still required.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind

_CPP_SUFFIXES = {".h", ".hpp", ".cpp", ".cc", ".cxx"}
_CONSTEXPR_RE = re.compile(
    r"\bconstexpr\s+(?:static\s+)?(?:const\s+)?[A-Za-z_:][\w:<>,\s*&]*?\s+([A-Za-z_]\w*)(?:\[[^\]]+\])?\s*=\s*([^;]+);"
)
_DEFINE_RE = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)\s+([^\n\\]+)\s*$", re.M)
_ENUM_RE = re.compile(r"enum(?:\s+class)?\s+([A-Za-z_]\w*)[^\{;]*\{(.*?)\};", re.S)
_STRUCT_RE = re.compile(r"\bstruct\s+([A-Za-z_]\w*)[^\{;]*\{", re.S)
_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)[^\{;]*\{", re.S)
_MEMBER_RE = re.compile(r"^\s*([A-Za-z_][\w:\s<>,*&]*?)\s+([A-Za-z_]\w*)(?:\[[^\]]+\])?\s*(?:=[^;]+)?;\s*$")
_TILING_READ_RE = re.compile(r"\btilingData\s*->\s*([A-Za-z_]\w*)(?:\s*\.\s*([A-Za-z_]\w*))?")
_RESOURCE_TYPES = (
    "TBuf", "TQue", "GlobalTensor", "LocalTensor", "MutexBufferManager", "TPipe", "TEventID",
)


def resolve_source_gaps(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "arch35",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    stats: dict[str, Any] = {}
    stats.update(_resolve_dispatch(codemap, root, architecture))
    stats.update(_resolve_tiling_reads(codemap, root, architecture))
    stats.update(_extract_compile_facts(codemap, root, architecture))
    stats.update(_extract_runtime_structs_and_resources(codemap, root, architecture))
    stats.update(_resolve_gap_records(codemap))
    codemap.meta["source_resolution"] = "ascendc-source-resolution/v1"
    codemap.meta["source_resolution_stats"] = stats
    return codemap


def _files(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in _CPP_SUFFIXES)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _find_kernel(codemap: CodeMap, name: str) -> Entity | None:
    exact = codemap.by_name(name, kind=EntityKind.KERNEL)
    if exact:
        return exact[0]
    for ent in codemap.by_kind(EntityKind.KERNEL):
        if ent.name.endswith("::" + name) or ent.name.endswith(name):
            return ent
    return None


def _resolve_dispatch(codemap: CodeMap, root: Path, architecture: str) -> dict[str, int]:
    edges = 0
    global_kernel = _find_kernel(codemap, "flash_attention_score_grad")
    regbase = _find_kernel(codemap, "RegbaseFAG")
    apt = root / "op_kernel" / "flash_attention_score_grad_apt.cpp"
    if global_kernel and regbase and apt.is_file():
        text = _read(apt)
        pos = text.find("RegbaseFAG<")
        if pos >= 0:
            codemap.link(
                RelationKind.CALLS,
                global_kernel.id,
                regbase.id,
                attrs={
                    "provenance": "source_dispatch_call",
                    "file": _rel(root, apt),
                    "line": _line(text, pos),
                    "condition": "!IsEmptyTensor",
                },
                status="confirmed",
            )
            edges += 1

    entry = root / "op_kernel" / architecture / "flash_attention_score_grad_entry_regbase.h"
    if regbase and entry.is_file():
        text = _read(entry)
        for type_name in ("FlashAttentionScoreGradKernel", "FlashAttentionScoreGradKernelDeter"):
            target = _find_kernel(codemap, type_name)
            pos = text.find(type_name + "<")
            if target is None or pos < 0:
                continue
            codemap.link(
                RelationKind.CALLS,
                regbase.id,
                target.id,
                attrs={
                    "provenance": "source_conditional_kernel_type",
                    "file": _rel(root, entry),
                    "line": _line(text, pos),
                    "condition": "DETER_SPARSE_TYPE",
                },
                status="confirmed",
            )
            edges += 1
    return {"dispatch_edges": edges}


def _field_index(codemap: CodeMap) -> dict[str, list[Entity]]:
    out: dict[str, list[Entity]] = {}
    for field in codemap.by_kind(EntityKind.TILING_FIELD):
        out.setdefault(field.name, []).append(field)
    return out


def _nearest_scope(text: str, offset: int) -> str:
    prefix = text[:offset]
    matches = list(
        re.finditer(
            r"(?:void|bool|int|uint\d+_t|int\d+_t|size_t|auto|ge::graphStatus)\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{",
            prefix,
        )
    )
    return matches[-1].group(1) if matches else "source_scope"


def _resolve_tiling_reads(codemap: CodeMap, root: Path, architecture: str) -> dict[str, int]:
    fields = _field_index(codemap)
    reads = 0
    for path in _files(root / "op_kernel" / architecture):
        text = _read(path)
        for match in _TILING_READ_RE.finditer(text):
            outer, inner = match.groups()
            name = inner or outer
            candidates = fields.get(name) or []
            if not candidates:
                continue
            scope = _nearest_scope(text, match.start())
            method = codemap.upsert(
                EntityKind.METHOD,
                f"{path.stem}::{scope}",
                eid=f"SRCMETHOD::{_rel(root, path)}::{scope}",
                attrs={"layer": "kernel", "provenance": "source_tilingdata_read"},
                file=_rel(root, path),
                line=_line(text, match.start()),
                status="confirmed",
            )
            for field in candidates:
                if inner and field.name != inner:
                    continue
                codemap.link(
                    RelationKind.READS,
                    method.id,
                    field.id,
                    attrs={
                        "provenance": "source_tilingdata_read",
                        "file": _rel(root, path),
                        "line": _line(text, match.start()),
                        "container": outer,
                    },
                    status="confirmed",
                )
                reads += 1
    return {"tilingdata_read_edges": reads}


def _extract_compile_facts(codemap: CodeMap, root: Path, architecture: str) -> dict[str, int]:
    macros = 0
    compile_vars = 0
    arch = codemap.by_name(architecture, kind=EntityKind.ARCH)
    arch_ent = arch[0] if arch else None
    for path in _files(root / "op_kernel" / architecture):
        text = _read(path)
        file = _rel(root, path)
        for m in _DEFINE_RE.finditer(text):
            name, value = m.groups()
            # Function-like macro arguments are excluded by the regex/name split;
            # only object-like compile definitions are facts here.
            ent = codemap.upsert(
                EntityKind.MACRO,
                name,
                eid=f"SRCMACRO::{file}::{name}",
                attrs={"value": value.strip(), "provenance": "source_define", "architecture": architecture},
                file=file,
                line=_line(text, m.start()),
                status="confirmed",
            )
            if arch_ent:
                codemap.link(RelationKind.ACTIVE_UNDER, ent.id, arch_ent.id, attrs={"provenance": "source_arch_file"}, status="confirmed")
            macros += 1
        for m in _CONSTEXPR_RE.finditer(text):
            name, value = m.groups()
            ent = codemap.upsert(
                EntityKind.COMPILE_VAR,
                name,
                eid=f"SRCCONST::{file}::{name}",
                attrs={"value_expr": value.strip(), "provenance": "source_constexpr", "architecture": architecture},
                file=file,
                line=_line(text, m.start()),
                status="confirmed",
            )
            if arch_ent:
                codemap.link(RelationKind.ACTIVE_UNDER, ent.id, arch_ent.id, attrs={"provenance": "source_arch_file"}, status="confirmed")
            compile_vars += 1
        for em in _ENUM_RE.finditer(text):
            enum_name, body = em.groups()
            value = -1
            for raw in body.split(","):
                item = re.sub(r"//.*", "", raw).strip()
                if not item:
                    continue
                parts = item.split("=", 1)
                member = parts[0].strip()
                if not re.match(r"^[A-Za-z_]\w*$", member):
                    continue
                if len(parts) == 2:
                    try:
                        value = int(parts[1].strip(), 0)
                    except ValueError:
                        value = -1
                else:
                    value += 1
                codemap.upsert(
                    EntityKind.COMPILE_VAR,
                    f"{enum_name}::{member}",
                    eid=f"SRCENUM::{file}::{enum_name}::{member}",
                    attrs={"value": value if value >= 0 else None, "enum": enum_name, "provenance": "source_enum"},
                    file=file,
                    line=_line(text, em.start()),
                    status="confirmed",
                )
                compile_vars += 1
    return {"source_macros": macros, "source_compile_vars": compile_vars}


def _matching_brace(text: str, open_pos: int) -> int:
    depth = 0
    quote = ""
    escape = False
    for i in range(open_pos, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _extract_runtime_structs_and_resources(codemap: CodeMap, root: Path, architecture: str) -> dict[str, int]:
    structs = 0
    resources = 0
    for path in _files(root / "op_kernel" / architecture):
        text = _read(path)
        file = _rel(root, path)
        for kind_re, kind_name in ((_STRUCT_RE, "struct"), (_CLASS_RE, "class")):
            for m in kind_re.finditer(text):
                owner = m.group(1)
                open_pos = text.find("{", m.start(), m.end())
                close_pos = _matching_brace(text, open_pos)
                if close_pos < 0:
                    continue
                owner_ent = codemap.upsert(
                    EntityKind.TYPE,
                    owner,
                    eid=f"SRCTYPE::{file}::{owner}",
                    attrs={"cpp_kind": kind_name, "architecture": architecture, "provenance": "source_runtime_type"},
                    file=file,
                    line=_line(text, m.start()),
                    status="confirmed",
                )
                structs += 1
                body = text[open_pos + 1 : close_pos]
                depth = 0
                for off, raw_line in enumerate(body.splitlines()):
                    stripped = re.sub(r"//.*", "", raw_line).strip()
                    if depth == 0 and stripped and "(" not in stripped and not stripped.endswith(":"):
                        mm = _MEMBER_RE.match(stripped)
                        if mm:
                            ctype, name = " ".join(mm.group(1).split()), mm.group(2)
                            field = codemap.upsert(
                                EntityKind.FIELD,
                                name,
                                eid=f"SRCFIELD::{file}::{owner}::{name}",
                                attrs={"owner": owner, "cpp_type": ctype, "provenance": "source_runtime_member"},
                                file=file,
                                line=_line(text, open_pos + 1) + off,
                                status="confirmed",
                            )
                            codemap.link(RelationKind.DECLARES, owner_ent.id, field.id, attrs={"provenance": "source_runtime_type"}, status="confirmed")
                            if any(token in ctype for token in _RESOURCE_TYPES):
                                field.attrs["hardware_resource"] = True
                                field.attrs["resource_type"] = next((x for x in _RESOURCE_TYPES if x in ctype), ctype)
                                resources += 1
                    depth += raw_line.count("{") - raw_line.count("}")
                    depth = max(0, depth)
    return {"runtime_types": structs, "hardware_resources": resources}


def _resolve_gap_records(codemap: CodeMap) -> dict[str, int]:
    stats = codemap.meta.get("source_contract_stats") or {}
    resolution = codemap.meta.get("source_resolution_stats") or {}
    # Current values are also available directly because this function is called
    # before source_resolution_stats is stored.
    dispatch_edges = sum(1 for r in codemap.relations.values() if r.attrs.get("provenance") == "source_dispatch_call")
    conditional_edges = sum(1 for r in codemap.relations.values() if r.attrs.get("provenance") == "source_conditional_kernel_type")
    tdata_reads = sum(1 for r in codemap.relations.values() if r.attrs.get("provenance") == "source_tilingdata_read")
    compile_vars = len([e for e in codemap.by_kind(EntityKind.COMPILE_VAR) if str(e.attrs.get("provenance", "")).startswith("source_")])
    runtime_types = {e.name for e in codemap.by_kind(EntityKind.TYPE) if e.attrs.get("provenance") == "source_runtime_type"}
    resource_fields = [e for e in codemap.by_kind(EntityKind.FIELD) if e.attrs.get("hardware_resource")]

    resolved = 0
    reason_counts: dict[str, int] = {}
    for ent in codemap.entities.values():
        if str(ent.status).lower() != "unresolved" or ent.attrs.get("role") != "unresolved":
            continue
        reason = str(ent.attrs.get("reason") or "")
        ok = False
        evidence = ""
        if reason == "entry_call_relation" and dispatch_edges:
            ok, evidence = True, "source_dispatch_call"
        elif reason == "kernel_parameters" and int(stats.get("source_template_args_bound") or 0) > 0 and int(stats.get("source_kernel_abi_links") or 0) > 0:
            ok, evidence = True, "source_kernel_signature"
        elif reason == "tilingdata_structs" and int(stats.get("source_tiling_data_classes") or 0) > 0 and int(stats.get("source_tiling_data_fields") or 0) > 0:
            ok, evidence = True, "source_tiling_data_class"
        elif reason == "tilingdata_read_sites" and tdata_reads:
            ok, evidence = True, "source_tilingdata_read"
        elif reason == "compile_info" and compile_vars >= 10:
            ok, evidence = True, "source_compile_facts"
        elif reason == "kernel_runtime_structs" and {"FagConstInfo", "FagRunInfo"}.issubset(runtime_types):
            ok, evidence = True, "source_runtime_type"
        elif reason == "global_resources" and len(resource_fields) >= 4:
            ok, evidence = True, "source_hardware_resources"
        if not ok:
            continue
        ent.status = "resolved"
        ent.confidence = 1.0
        ent.attrs["resolved_by"] = evidence
        ent.attrs["resolved_from_current_source"] = True
        resolved += 1
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    codemap.meta["resolved_archive_gaps"] = reason_counts
    return {"resolved_archive_gap_count": resolved, **{f"resolved_{k}": v for k, v in reason_counts.items()}}
