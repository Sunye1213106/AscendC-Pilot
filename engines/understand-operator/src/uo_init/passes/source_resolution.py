# -*- coding: utf-8 -*-
"""Resolve historical UO gaps from operator-agnostic current-source facts.

The pass inventories arch-scoped kernel functions, macro expansions, direct call
sites, compile-time constants, control-flow frontier sites, TilingData reads and
hardware-resource members.  Historical gaps are upgraded only when their own
candidate source span is covered by corresponding machine-verifiable facts.

A complete C++ call graph remains a compiler responsibility; this fallback does
not claim completeness for template/macro call resolution merely from regex.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind

_CPP_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_CONSTEXPR_RE = re.compile(
    r"\bconstexpr\s+(?:static\s+)?(?:const\s+)?[A-Za-z_:][\w:<>,\s*&]*?\s+([A-Za-z_]\w*)(?:\[[^\]]+\])?\s*=\s*([^;]+);"
)
_DEFINE_OBJECT_RE = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)\s+([^\n\\]+)\s*$", re.M)
_ENUM_RE = re.compile(r"enum(?:\s+class)?\s+([A-Za-z_]\w*)[^\{;]*\{(.*?)\};", re.S)
_STRUCT_RE = re.compile(r"\bstruct\s+([A-Za-z_]\w*)[^\{;]*\{", re.S)
_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)[^\{;]*\{", re.S)
_MEMBER_RE = re.compile(
    r"^\s*([A-Za-z_][\w:\s<>,*&]*?)\s+([A-Za-z_]\w*)(?:\[[^\]]+\])?\s*(?:=[^;]+)?;\s*$"
)
_TILING_READ_RE = re.compile(r"\btilingData\s*->\s*([A-Za-z_]\w*)(?:\s*\.\s*([A-Za-z_]\w*))?")
_FUNCTION_RE = re.compile(
    r"(?:(?:template\s*<[^;{}]{0,1500}>\s*){0,4})"
    r"(?:(?:inline|static|constexpr|__aicore__|__global__)\s+){0,8}"
    r"[A-Za-z_][\w:<>,\s*&]{0,200}?\s+"
    r"(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*){0,6})\s*"
    r"\((?P<params>[^;{}]{0,4000})\)\s*(?:const\s*)?\{",
)
_CALL_RE = re.compile(
    r"(?:(?P<receiver>[A-Za-z_]\w*)\s*(?:\.|->)\s*)?"
    r"(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*"
    r"(?:<[^;{}()]{0,600}>)?\s*\("
)
_BRANCH_RE = re.compile(r"\b(if\s+constexpr|if|while|for|switch)\s*\(")
_PP_BRANCH_RE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif)\b(.*)$", re.M)
_TYPE_ALIAS_RE = re.compile(
    r"\busing\s+([A-Za-z_]\w*)\s*=\s*(?:typename\s+)?([A-Za-z_:][A-Za-z0-9_:]*)\s*<",
    re.S,
)
_RESOURCE_TYPES = (
    "TBuf",
    "TQue",
    "GlobalTensor",
    "LocalTensor",
    "MutexBufferManager",
    "TPipe",
    "TEventID",
)
_CALL_SKIP = {
    "if", "while", "for", "switch", "sizeof", "alignof", "decltype", "static_cast",
    "reinterpret_cast", "const_cast", "dynamic_cast", "return", "likely", "unlikely",
}


@dataclass(frozen=True)
class _Scope:
    name: str
    file: str
    start: int
    end: int
    body_start: int
    body_end: int
    kind: str


def resolve_source_gaps(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    stats: dict[str, Any] = {}
    stats.update(_extract_calls_macros_and_frontiers(codemap, root, architecture))
    stats.update(_resolve_tiling_reads(codemap, root, architecture))
    stats.update(_extract_compile_facts(codemap, root, architecture))
    stats.update(_extract_runtime_structs_and_resources(codemap, root, architecture))
    stats.update(_resolve_gap_records(codemap, stats))
    codemap.meta["source_resolution"] = "ascendc-source-resolution/v2"
    codemap.meta["source_resolution_stats"] = stats
    return codemap


def _files(path: Path, *, recursive: bool = True) -> list[Path]:
    if not path.is_dir():
        return []
    it = path.rglob("*") if recursive else path.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in _CPP_SUFFIXES)


def _kernel_files(root: Path, architecture: str) -> list[Path]:
    kernel_root = root / "op_kernel"
    out = list(_files(kernel_root / architecture))
    for path in _files(kernel_root, recursive=False):
        text = _read(path)
        if "__aicore__" in text or f'"{architecture}/' in text or "GET_TILING_DATA_WITH_STRUCT" in text:
            out.append(path)
    seen: set[Path] = set()
    result: list[Path] = []
    for path in out:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _read(path: Path) -> str:
    from uo_init.passes.source_text_cache import read_text

    return read_text(path)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _line_index(text: str) -> list[int]:
    """Newline offsets for O(log n) line lookup via bisect."""
    return [i for i, ch in enumerate(text) if ch == "\n"]


def _line_at(newlines: list[int], offset: int) -> int:
    import bisect

    return bisect.bisect_right(newlines, max(0, offset)) + 1


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


def _find_kernel(
    codemap: CodeMap,
    source_name: str,
    cache: dict[str, Entity | None] | None = None,
) -> Entity | None:
    short = source_name.split("::")[-1]
    if cache is not None and short in cache:
        return cache[short]
    exact = codemap.by_name(source_name, kind=EntityKind.KERNEL)
    if exact:
        hit = exact[0]
        if cache is not None:
            cache[short] = hit
        return hit
    hit = None
    for ent in codemap.by_kind(EntityKind.KERNEL):
        if ent.name.split("::")[-1] == short:
            hit = ent
            break
    if cache is not None:
        cache[short] = hit
    return hit


def _function_scopes(
    text: str, file: str, *, newlines: list[int] | None = None
) -> list[_Scope]:
    out: list[_Scope] = []
    line_of = (lambda off: _line_at(newlines, off)) if newlines is not None else (
        lambda off: _line(text, off)
    )
    for match in _FUNCTION_RE.finditer(text):
        name = match.group("name")
        if name in _CALL_SKIP:
            continue
        open_pos = text.find("{", match.start(), match.end())
        close_pos = _matching_brace(text, open_pos)
        if close_pos < 0:
            continue
        out.append(
            _Scope(
                name=name,
                file=file,
                start=line_of(match.start()),
                end=line_of(close_pos),
                body_start=open_pos + 1,
                body_end=close_pos,
                kind="function",
            )
        )
    return out


def _macro_scopes(text: str, file: str) -> list[_Scope]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    pos = 0
    for raw in lines:
        offsets.append(pos)
        pos += len(raw)
    out: list[_Scope] = []
    i = 0
    while i < len(lines):
        match = re.match(r"\s*#define\s+([A-Za-z_]\w*)\s*(?:\([^\n]*?\))?(.*)$", lines[i])
        if not match:
            i += 1
            continue
        name = match.group(1)
        start_i = i
        while i < len(lines) - 1 and lines[i].rstrip().endswith("\\"):
            i += 1
        end_i = i
        start_off = offsets[start_i]
        end_off = offsets[end_i] + len(lines[end_i])
        out.append(
            _Scope(
                name=name,
                file=file,
                start=start_i + 1,
                end=end_i + 1,
                body_start=start_off,
                body_end=end_off,
                kind="macro",
            )
        )
        i += 1
    return out


def _scope_entity(codemap: CodeMap, scope: _Scope) -> Entity:
    if scope.kind == "function":
        kernel = _find_kernel(codemap, scope.name)
        if kernel is not None:
            kernel.attrs.setdefault("source_definition", True)
            return kernel
        kind = EntityKind.METHOD if "::" in scope.name else EntityKind.FUNCTION
    else:
        kind = EntityKind.MACRO
    return codemap.upsert(
        kind,
        scope.name,
        eid=f"SRCSCOPE::{scope.kind}::{scope.file}::{scope.start}::{scope.name}",
        attrs={"layer": "kernel", "source_scope": True, "provenance": "source_scope"},
        file=scope.file,
        line=scope.start,
        status="confirmed",
    )


def _containing_scope(scopes: Iterable[_Scope], offset: int) -> _Scope | None:
    matches = [s for s in scopes if s.body_start <= offset <= s.body_end]
    if not matches:
        return None
    return min(matches, key=lambda s: s.body_end - s.body_start)


def _extract_calls_macros_and_frontiers(codemap: CodeMap, root: Path, architecture: str) -> dict[str, int]:
    direct_kernel_calls = 0
    call_edges = 0
    type_dispatch_edges = 0
    branch_sites = 0
    macro_scopes_count = 0
    kernel_cache: dict[str, Entity | None] = {}
    kernel_by_short: dict[str, list] = {}
    for kernel in codemap.by_kind(EntityKind.KERNEL):
        short = kernel.name.split("::")[-1]
        if short:
            kernel_by_short.setdefault(short, []).append(kernel)
    kernel_type_re = None
    if kernel_by_short:
        shorts = sorted(kernel_by_short, key=len, reverse=True)
        kernel_type_re = re.compile(
            r"\b(" + "|".join(re.escape(s) for s in shorts) + r")\s*<"
        )

    for path in _kernel_files(root, architecture):
        text = _read(path)
        file = _rel(root, path)
        newlines = _line_index(text)
        functions = _function_scopes(text, file, newlines=newlines)
        macros = _macro_scopes(text, file)
        macro_scopes_count += len(macros)
        all_scopes = functions + macros
        scope_entities = {scope: _scope_entity(codemap, scope) for scope in all_scopes}

        # Macro references from functions are explicit source expansion edges.
        macro_by_name = {m.name: m for m in macros}
        macro_re = None
        if macro_by_name:
            # Longest-first so prefixes do not steal longer macro names.
            names = sorted(macro_by_name, key=len, reverse=True)
            macro_re = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\s*\(")
        for function in functions:
            body = text[function.body_start:function.body_end]
            caller = scope_entities[function]
            if macro_re is None:
                continue
            seen_macros: set[str] = set()
            for hit in macro_re.finditer(body):
                mname = hit.group(1)
                if mname in seen_macros:
                    continue
                seen_macros.add(mname)
                macro = macro_by_name[mname]
                codemap.link(
                    RelationKind.CALLS,
                    caller.id,
                    scope_entities[macro].id,
                    attrs={"provenance": "source_macro_invocation", "file": file},
                    status="confirmed",
                )
                call_edges += 1

        for scope in all_scopes:
            caller = scope_entities[scope]
            body = text[scope.body_start:scope.body_end]
            body_abs = scope.body_start

            # Direct function/method call sites. Existing KERNEL names receive a
            # real call edge; unknown callees are retained as method call targets.
            for match in _CALL_RE.finditer(body):
                target_name = match.group("name")
                if target_name in _CALL_SKIP or target_name == scope.name.split("::")[-1]:
                    continue
                absolute = body_abs + match.start()
                line = _line_at(newlines, absolute)
                target_kernel = _find_kernel(codemap, target_name, kernel_cache)
                if target_kernel is not None and target_kernel.id != caller.id:
                    target = target_kernel
                    direct_kernel_calls += 1
                else:
                    receiver = str(match.group("receiver") or "").strip()
                    display = f"{receiver}.{target_name}" if receiver else target_name
                    target = codemap.upsert(
                        EntityKind.METHOD,
                        display,
                        eid=f"CALLTARGET::{file}::{line}::{display}",
                        attrs={
                            "call_target": target_name,
                            "receiver": receiver,
                            "provenance": "source_call_site",
                        },
                        file=file,
                        line=line,
                        status="confirmed",
                    )
                codemap.link(
                    RelationKind.CALLS,
                    caller.id,
                    target.id,
                    attrs={
                        "provenance": "source_call_site",
                        "file": file,
                        "line": line,
                    },
                    status="confirmed",
                )
                call_edges += 1

            # Template/class types named in a scope can choose an existing
            # kernel implementation even when the invocation is indirect via an
            # object or std::conditional. Record only textual type references.
            if kernel_type_re is not None:
                seen_shorts: set[str] = set()
                for hit in kernel_type_re.finditer(body):
                    short = hit.group(1)
                    if short in seen_shorts:
                        continue
                    seen_shorts.add(short)
                    for kernel in kernel_by_short.get(short, []):
                        if kernel.id == caller.id:
                            continue
                        codemap.link(
                            RelationKind.CONTROLS,
                            caller.id,
                            kernel.id,
                            attrs={"provenance": "source_kernel_type_reference", "file": file},
                            status="confirmed",
                        )
                        type_dispatch_edges += 1

            # Control-flow frontier inventory.
            for branch in _BRANCH_RE.finditer(body):
                absolute = body_abs + branch.start()
                kind = branch.group(1).replace(" ", "_")
                line = _line_at(newlines, absolute)
                node = codemap.upsert(
                    EntityKind.BRANCH,
                    f"{scope.name}:{kind}@{line}",
                    eid=f"SRCBRANCH::{file}::{line}::{kind}",
                    attrs={"branch_kind": kind, "provenance": "source_frontier"},
                    file=file,
                    line=line,
                    status="confirmed",
                )
                codemap.link(
                    RelationKind.CONTROLS,
                    node.id,
                    caller.id,
                    attrs={"provenance": "source_frontier"},
                    status="confirmed",
                )
                branch_sites += 1

        for branch in _PP_BRANCH_RE.finditer(text):
            line = _line_at(newlines, branch.start())
            node = codemap.upsert(
                EntityKind.BRANCH,
                f"pp_{branch.group(1)}@{line}",
                eid=f"SRCPPBRANCH::{file}::{line}::{branch.group(1)}",
                attrs={
                    "branch_kind": f"pp_{branch.group(1)}",
                    "condition": branch.group(2).strip(),
                    "provenance": "source_frontier",
                },
                file=file,
                line=line,
                status="confirmed",
            )
            owner = _containing_scope(all_scopes, branch.start())
            if owner is not None:
                codemap.link(
                    RelationKind.CONTROLS,
                    node.id,
                    scope_entities[owner].id,
                    attrs={"provenance": "source_frontier"},
                    status="confirmed",
                )
            branch_sites += 1

    return {
        "source_call_edges": call_edges,
        "source_direct_kernel_calls": direct_kernel_calls,
        "source_kernel_type_dispatch_edges": type_dispatch_edges,
        "source_frontier_sites": branch_sites,
        "source_macro_scopes": macro_scopes_count,
    }


def _field_index(codemap: CodeMap) -> dict[str, list[Entity]]:
    out: dict[str, list[Entity]] = {}
    for field in codemap.by_kind(EntityKind.TILING_FIELD):
        out.setdefault(field.name, []).append(field)
    return out


def _resolve_tiling_reads(codemap: CodeMap, root: Path, architecture: str) -> dict[str, int]:
    fields = _field_index(codemap)
    reads = 0
    for path in _kernel_files(root, architecture):
        text = _read(path)
        file = _rel(root, path)
        scopes = _function_scopes(text, file)
        for match in _TILING_READ_RE.finditer(text):
            outer, inner = match.groups()
            name = inner or outer
            candidates = fields.get(name) or []
            if not candidates:
                continue
            scope = _containing_scope(scopes, match.start())
            if scope is not None:
                owner = _scope_entity(codemap, scope)
            else:
                owner = codemap.upsert(
                    EntityKind.METHOD,
                    f"{path.stem}:source_scope",
                    eid=f"SRCMETHOD::{file}::source_scope",
                    attrs={"layer": "kernel", "provenance": "source_tilingdata_read"},
                    file=file,
                    line=_line(text, match.start()),
                    status="confirmed",
                )
            for field in candidates:
                if inner and field.name != inner:
                    continue
                codemap.link(
                    RelationKind.READS,
                    owner.id,
                    field.id,
                    attrs={
                        "provenance": "source_tilingdata_read",
                        "file": file,
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
    archs = codemap.by_name(architecture, kind=EntityKind.ARCH)
    arch_ent = archs[0] if archs else None
    for path in _kernel_files(root, architecture):
        text = _read(path)
        file = _rel(root, path)
        for m in _DEFINE_OBJECT_RE.finditer(text):
            name, value = m.groups()
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


def _extract_runtime_structs_and_resources(codemap: CodeMap, root: Path, architecture: str) -> dict[str, int]:
    structs = 0
    resources = 0
    for path in _kernel_files(root, architecture):
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


def _candidate_spans(ent: Entity) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for src in ent.attrs.get("candidate_sources") or []:
        if not isinstance(src, dict) or not src.get("file"):
            continue
        span = src.get("span") or {}
        start = int(span.get("start_line") or 0)
        end = int(span.get("end_line") or start or 0)
        out.append((str(src.get("file") or "").replace("\\", "/"), start, end))
    return out


def _facts_cover_candidates(codemap: CodeMap, ent: Entity, *, kinds: set[str], provenances: set[str]) -> bool:
    candidates = _candidate_spans(ent)
    if not candidates:
        return False
    facts = [
        fact for fact in codemap.entities.values()
        if fact.kind_name() in kinds and str(fact.attrs.get("provenance") or "") in provenances
    ]
    for file, start, end in candidates:
        matched = False
        for fact in facts:
            fact_file = str(fact.file or "").replace("\\", "/")
            if not (fact_file.endswith(file) or file.endswith(fact_file)):
                continue
            line = int(fact.line_start or 0)
            if not start or not end or start <= line <= end:
                matched = True
                break
        if not matched:
            return False
    return True


def _resolve_gap_records(codemap: CodeMap, stats: dict[str, Any]) -> dict[str, int]:
    contract = codemap.meta.get("source_contract_stats") or {}
    resolved = 0
    reason_counts: dict[str, int] = {}
    for ent in codemap.entities.values():
        if str(ent.status).lower() != "unresolved" or ent.attrs.get("role") != "unresolved":
            continue
        reason = str(ent.attrs.get("reason") or "")
        ok = False
        evidence = ""
        if reason == "entry_call_relation" and (
            int(stats.get("source_direct_kernel_calls") or 0) > 0
            or int(stats.get("source_kernel_type_dispatch_edges") or 0) > 0
        ):
            ok, evidence = True, "source_dispatch_inventory"
        elif reason == "kernel_parameters" and int(contract.get("source_template_args_bound") or 0) > 0 and int(contract.get("source_kernel_abi_links") or 0) > 0:
            ok, evidence = True, "source_kernel_signature"
        elif reason == "tilingdata_structs" and int(contract.get("source_tiling_data_classes") or 0) > 0 and int(contract.get("source_tiling_data_fields") or 0) > 0:
            ok, evidence = True, "source_tiling_data_class"
        elif reason == "tilingdata_read_sites" and int(stats.get("tilingdata_read_edges") or 0) > 0:
            ok, evidence = True, "source_tilingdata_read"
        elif reason == "compile_info" and (int(stats.get("source_compile_vars") or 0) + int(stats.get("source_macros") or 0)) > 0:
            ok, evidence = True, "source_compile_facts"
        elif reason == "kernel_runtime_structs" and _facts_cover_candidates(
            codemap,
            ent,
            kinds={EntityKind.TYPE.value},
            provenances={"source_runtime_type"},
        ):
            ok, evidence = True, "source_runtime_type"
        elif reason == "global_resources" and int(stats.get("hardware_resources") or 0) > 0:
            ok, evidence = True, "source_hardware_resources"
        elif reason == "frontier_sites" and _facts_cover_candidates(
            codemap,
            ent,
            kinds={EntityKind.BRANCH.value},
            provenances={"source_frontier"},
        ):
            ok, evidence = True, "source_frontier_inventory"
        # kernel_call_edges intentionally remains unresolved: syntax-level call
        # sites are useful CodeMap facts but do not prove a complete C++ graph.
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
