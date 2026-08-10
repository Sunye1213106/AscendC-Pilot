# -*- coding: utf-8 -*-
"""Source-backed Host producer/def-use graph for packed TilingKey arguments.

This pass deliberately stops at a dependency skeleton.  It finds the current
source producer sites for every Host value passed to ``GET_TPL_TILING_KEY`` and
links API/compile/runtime dependencies without deriving a closed-form key
formula.  Member identity is canonical (``this.foo.x == foo.x``); ambiguous
short names are never silently merged.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.symbol_identity import is_member_symbol, normalize_symbol, short_symbol

_SOURCE_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_ENUM_INDEX_RE = re.compile(r"enum\s+class\s+(InputIndex|AttrIndex)\s*:[^{]+\{(.*?)\};", re.S)
_ENUM_RE = re.compile(r"enum\s+(?P<scoped>class\s+)?(?P<name>[A-Za-z_]\w*)[^\{;]*\{(?P<body>.*?)\};", re.S)
_CONST_INT_RE = re.compile(
    r"\bconstexpr\s+(?:static\s+)?(?:const\s+)?[A-Za-z_:][\w:<>,\s*&]*?\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>[-+]?0[xX][0-9A-Fa-f]+|[-+]?\d+)\s*;"
)
_CONST_ANY_RE = re.compile(
    r"\bconstexpr\s+(?:static\s+)?(?:const\s+)?[A-Za-z_:][\w:<>,\s*&]*?\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>[^;]+);"
)
_DEFINE_RE = re.compile(r"^\s*#define\s+(?P<name>[A-Za-z_]\w*)\s+(?P<value>[^\n\\]+)\s*$", re.M)
_ASSIGN_RE = re.compile(
    r"(?P<lhs>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*)\s*(?<![=!<>])=(?!=)\s*(?P<rhs>[^;]+);",
    re.S,
)
_IF_RE = re.compile(r"\b(?:if|else\s+if)\s*\((?P<cond>[^{};]*)\)\s*\{", re.S)
_FUNCTION_RE = re.compile(
    r"(?:inline\s+|static\s+|virtual\s+|constexpr\s+)*"
    r"[A-Za-z_][\w:<>,\s*&~]*?\s+"
    r"(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*"
    r"\([^;{}]*\)\s*(?:const\s*)?(?:override\s*)?\{",
    re.S,
)
_IDENT_RE = re.compile(r"[A-Za-z_]\w*(?:\s*(?:\.|->|::)\s*[A-Za-z_]\w*)*")
_API_TOKEN_RE = re.compile(r"\b(InputIndex|AttrIndex)::([A-Za-z_]\w*)")
_INPUT_ACCESS_RE = re.compile(
    r"\bGet(?:Optional)?Input(?:Shape|Desc)\s*\(\s*(?P<arg>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)?|[-+]?\d+)"
)
_ATTR_ACCESS_RE = re.compile(
    r"\bGetAttrPointer(?:\s*<[^>]+>)?\s*\(\s*(?P<arg>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)?|[-+]?\d+)"
)
_IGNORED = {
    "auto", "const", "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast", "true", "false",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t", "int16_t", "int32_t",
    "int64_t", "size_t", "bool", "int", "unsigned", "long", "short", "float", "double",
    "return", "nullptr", "std", "ge", "this",
}
_RUNTIME_KINDS = {EntityKind.VARIABLE.value, EntityKind.FIELD.value}
_ROOT_RELATIONS = {RelationKind.DERIVES.value, RelationKind.FLOWS_TO.value}


@dataclass(frozen=True)
class _Scope:
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class _Record:
    lhs: str
    rhs: str
    guards: tuple[str, ...]
    file: str
    line: int
    function: str


def trace_host_key_roots(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "arch35",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    host_dir = root / "op_host" / architecture
    if not host_dir.is_dir():
        return codemap

    texts: list[tuple[Path, str]] = []
    records: list[_Record] = []
    for path in sorted(host_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        texts.append((path, text))
        records.extend(_assignments(root, path, text))

    by_exact: dict[str, list[_Record]] = defaultdict(list)
    by_short: dict[str, list[_Record]] = defaultdict(list)
    for record in records:
        by_exact[record.lhs].append(record)
        by_short[short_symbol(record.lhs)].append(record)

    api_maps = _api_maps(codemap, texts)
    compile_symbols = _compile_symbols(codemap, texts)
    symbol_nodes: dict[str, Entity] = {}
    for kind in (EntityKind.VARIABLE, EntityKind.FIELD):
        for ent in codemap.by_kind(kind):
            if not ent.attrs.get("host_key_argument"):
                continue
            canonical = normalize_symbol(str(ent.attrs.get("canonical_symbol") or ent.name))
            symbol_nodes[canonical] = ent
            source_name = str(ent.attrs.get("source_name") or "")
            if source_name:
                symbol_nodes.setdefault(normalize_symbol(source_name), ent)

    targets = [
        e
        for kind in (EntityKind.VARIABLE, EntityKind.FIELD)
        for e in codemap.by_kind(kind)
        if e.attrs.get("host_key_argument")
    ]
    visiting: set[str] = set()
    visited: set[str] = set()
    for target in targets:
        use_file, use_function = _target_scope(target)
        _resolve_symbol(
            codemap,
            target,
            str(target.attrs.get("canonical_symbol") or target.name),
            by_exact=by_exact,
            by_short=by_short,
            api_maps=api_maps,
            compile_symbols=compile_symbols,
            symbol_nodes=symbol_nodes,
            visiting=visiting,
            visited=visited,
            use_file=use_file,
            use_function=use_function,
        )

    rooted = _source_rooted_entities(codemap)
    rooted_targets = 0
    producer_targets = 0
    for target in targets:
        producer_count = int(target.attrs.get("producer_site_count") or 0)
        if producer_count:
            producer_targets += 1
        if producer_count and target.id in rooted:
            target.attrs["upstream_unresolved"] = False
            target.attrs["rooted_by_current_source"] = True
            target.status = "confirmed"
            target.confidence = 1.0
            rooted_targets += 1
        elif producer_count:
            target.attrs["rooted_by_current_source"] = False
            target.attrs["upstream_unresolved"] = True

    codemap.meta["host_key_root_trace"] = {
        "target_variables": len(targets),
        "producer_variables": producer_targets,
        "rooted_variables": rooted_targets,
        "assignment_records": len(records),
        "policy": "canonical-source-producer/v2",
    }
    return codemap


def _function_scopes(text: str) -> list[_Scope]:
    out: list[_Scope] = []
    for match in _FUNCTION_RE.finditer(text):
        open_pos = text.find("{", match.start(), match.end())
        close_pos = _matching_brace(text, open_pos)
        if close_pos >= 0:
            out.append(_Scope(match.group("name"), open_pos + 1, close_pos))
    return out


def _containing_scope(scopes: list[_Scope], offset: int) -> str:
    matches = [s for s in scopes if s.start <= offset <= s.end]
    if not matches:
        return ""
    return min(matches, key=lambda s: s.end - s.start).name


def _assignments(root: Path, path: Path, text: str) -> list[_Record]:
    scopes = _function_scopes(text)
    guard_scopes: list[tuple[int, int, str]] = []
    for match in _IF_RE.finditer(text):
        open_pos = text.find("{", match.start(), match.end())
        close_pos = _matching_brace(text, open_pos)
        if close_pos >= 0:
            guard_scopes.append((open_pos + 1, close_pos, match.group("cond").strip()))
    out: list[_Record] = []
    for match in _ASSIGN_RE.finditer(text):
        lhs = normalize_symbol(match.group("lhs"))
        rhs = match.group("rhs").strip()
        guards = tuple(cond for start, end, cond in guard_scopes if start <= match.start() <= end)
        out.append(
            _Record(
                lhs=lhs,
                rhs=rhs,
                guards=guards,
                file=_rel(root, path),
                line=_line(text, match.start()),
                function=_containing_scope(scopes, match.start()),
            )
        )
    return out


def _api_maps(codemap: CodeMap, texts: list[tuple[Path, str]]) -> dict[str, Any]:
    tensor_inputs = sorted(
        (e for e in codemap.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "tensor"),
        key=lambda e: int(e.attrs.get("api_index") or 0),
    )
    attrs = sorted(
        (e for e in codemap.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "attribute"),
        key=lambda e: int(e.attrs.get("api_attr_index") or 0),
    )
    tokens: dict[str, list[str]] = {"InputIndex": [], "AttrIndex": []}
    constants: dict[str, int] = {}
    for _path, text in texts:
        for match in _ENUM_INDEX_RE.finditer(text):
            tokens[match.group(1)] = _enum_names(match.group(2))
        for match in _CONST_INT_RE.finditer(text):
            try:
                constants[match.group("name")] = int(match.group("value"), 0)
            except ValueError:
                pass
        for match in _DEFINE_RE.finditer(text):
            raw = match.group("value").strip()
            try:
                constants[match.group("name")] = int(raw, 0)
            except ValueError:
                pass
    return {
        "InputIndex": {name: tensor_inputs[i] for i, name in enumerate(tokens["InputIndex"]) if i < len(tensor_inputs)},
        "AttrIndex": {name: attrs[i] for i, name in enumerate(tokens["AttrIndex"]) if i < len(attrs)},
        "input_by_position": {i: ent for i, ent in enumerate(tensor_inputs)},
        "attr_by_position": {i: ent for i, ent in enumerate(attrs)},
        "constants": constants,
    }


def _compile_symbols(codemap: CodeMap, texts: list[tuple[Path, str]]) -> set[str]:
    symbols: set[str] = set()
    for _path, text in texts:
        for match in _CONST_ANY_RE.finditer(text):
            symbols.add(normalize_symbol(match.group("name")))
        for match in _DEFINE_RE.finditer(text):
            symbols.add(normalize_symbol(match.group("name")))
        for match in _ENUM_RE.finditer(text):
            enum_name = match.group("name")
            scoped = bool(match.group("scoped"))
            for member in _enum_names(match.group("body")):
                symbols.add(f"{enum_name}::{member}")
                if not scoped:
                    symbols.add(member)
    for kind in (EntityKind.COMPILE_VAR, EntityKind.MACRO):
        for ent in codemap.by_kind(kind):
            if _trusted_compile_root(ent):
                symbols.add(normalize_symbol(ent.name))
    return symbols


def _target_scope(target: Entity) -> tuple[str, str]:
    sites = [s for s in (target.attrs.get("host_key_use_sites") or []) if isinstance(s, dict)]
    if not sites:
        return "", ""
    files = {str(s.get("file") or "") for s in sites}
    functions = {str(s.get("function") or "") for s in sites}
    return (next(iter(files)) if len(files) == 1 else "", next(iter(functions)) if len(functions) == 1 else "")


def _select_records(
    symbol: str,
    *,
    by_exact: dict[str, list[_Record]],
    by_short: dict[str, list[_Record]],
    use_file: str = "",
    use_function: str = "",
) -> tuple[list[_Record], bool]:
    normalized = normalize_symbol(symbol)
    records = list(by_exact.get(normalized) or [])
    if records:
        if not is_member_symbol(normalized) and use_function:
            scoped = [r for r in records if r.function == use_function and (not use_file or r.file == use_file)]
            if scoped:
                records = scoped
        return records, False

    candidates = list(by_short.get(short_symbol(normalized)) or [])
    if not candidates:
        return [], False
    if not is_member_symbol(normalized) and use_function:
        scoped = [r for r in candidates if r.function == use_function and (not use_file or r.file == use_file)]
        if scoped:
            candidates = scoped
    spellings = {r.lhs for r in candidates}
    if len(spellings) == 1:
        return candidates, False
    # A member target must never degrade to a bare short-name guess.  The
    # canonical ``this.`` normalization should have produced an exact hit; if it
    # did not, retain the ambiguity instead of inventing a producer.
    return [], True


def _resolve_symbol(
    codemap: CodeMap,
    target: Entity,
    symbol: str,
    *,
    by_exact: dict[str, list[_Record]],
    by_short: dict[str, list[_Record]],
    api_maps: dict[str, Any],
    compile_symbols: set[str],
    symbol_nodes: dict[str, Entity],
    visiting: set[str],
    visited: set[str],
    use_file: str = "",
    use_function: str = "",
) -> None:
    normalized = normalize_symbol(symbol)
    state = f"{target.id}:{normalized}:{use_file}:{use_function}"
    if state in visited or state in visiting:
        return
    visiting.add(state)
    records, ambiguous = _select_records(
        normalized,
        by_exact=by_exact,
        by_short=by_short,
        use_file=use_file,
        use_function=use_function,
    )
    if ambiguous:
        target.attrs["producer_lookup_ambiguous"] = True
        target.attrs.setdefault("producer_lookup_symbols", []).append(normalized)

    producer_sites: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        site = {"file": record.file, "line": record.line, "function": record.function, "lhs": record.lhs}
        if site not in producer_sites:
            producer_sites.append(site)
        expr = codemap.upsert(
            EntityKind.PREDICATE,
            record.rhs,
            eid=f"HOSTDEF::{record.file}::{record.line}::{short_symbol(record.lhs)}::{index}",
            attrs={
                "predicate_role": "host_definition",
                "lhs": record.lhs,
                "expression": record.rhs,
                "guards": list(record.guards),
                "function": record.function,
                "provenance": "source_host_defuse",
            },
            file=record.file,
            line=record.line,
            status="confirmed",
        )
        codemap.link(
            RelationKind.DERIVES,
            expr.id,
            target.id,
            attrs={
                "provenance": "source_host_defuse",
                "lhs": record.lhs,
                "file": record.file,
                "line": record.line,
                "function": record.function,
            },
            status="confirmed",
        )
        for text in [record.rhs, *record.guards]:
            _link_api_accesses(codemap, expr, text, api_maps, file=record.file, line=record.line)
            for ref in _identifiers(text):
                ref_norm = normalize_symbol(ref)
                if ref_norm == normalized:
                    continue
                if _is_compile_reference(ref_norm, compile_symbols):
                    compile_root = codemap.upsert(
                        EntityKind.COMPILE_VAR,
                        ref_norm,
                        eid=f"HOSTCONST::{ref_norm}",
                        attrs={
                            "compile_root": True,
                            "provenance": (
                                "source_host_compile_symbol"
                                if ref_norm in compile_symbols
                                else "source_host_qualified_constant"
                            ),
                        },
                        file=record.file,
                        line=record.line,
                        status="confirmed",
                    )
                    codemap.link(
                        RelationKind.DERIVES,
                        compile_root.id,
                        expr.id,
                        attrs={"provenance": compile_root.attrs["provenance"]},
                        status="confirmed",
                    )
                    continue

                upstream_records, upstream_ambiguous = _select_records(
                    ref_norm,
                    by_exact=by_exact,
                    by_short=by_short,
                    use_file=record.file,
                    use_function=record.function,
                )
                if upstream_records:
                    upstream = symbol_nodes.get(ref_norm)
                    if upstream is None:
                        kind = EntityKind.FIELD if is_member_symbol(ref_norm) else EntityKind.VARIABLE
                        upstream = codemap.upsert(
                            kind,
                            ref_norm,
                            eid=f"HOSTDEFVAR::{kind.value}::{ref_norm}",
                            attrs={
                                "source_name": short_symbol(ref_norm),
                                "canonical_symbol": ref_norm,
                                "provenance": "source_host_defuse",
                            },
                            file=upstream_records[0].file,
                            line=upstream_records[0].line,
                            status="confirmed",
                        )
                        symbol_nodes[ref_norm] = upstream
                    codemap.link(
                        RelationKind.DERIVES,
                        upstream.id,
                        expr.id,
                        attrs={"provenance": "source_host_defuse_dependency", "symbol": ref_norm},
                        status="confirmed",
                    )
                    _resolve_symbol(
                        codemap,
                        upstream,
                        ref_norm,
                        by_exact=by_exact,
                        by_short=by_short,
                        api_maps=api_maps,
                        compile_symbols=compile_symbols,
                        symbol_nodes=symbol_nodes,
                        visiting=visiting,
                        visited=visited,
                        use_file=record.file,
                        use_function=record.function,
                    )
                    continue

                # Preserve an unresolved runtime dependency in the graph rather
                # than silently dropping it or promoting it to a compile root.
                if _looks_like_runtime_reference(ref_norm):
                    unresolved = codemap.upsert(
                        EntityKind.FIELD if is_member_symbol(ref_norm) else EntityKind.VARIABLE,
                        ref_norm,
                        eid=f"HOSTUNRESOLVED::{ref_norm}",
                        attrs={
                            "source_name": short_symbol(ref_norm),
                            "canonical_symbol": ref_norm,
                            "dependency_unresolved": True,
                            "producer_lookup_ambiguous": upstream_ambiguous,
                            "provenance": "source_host_unresolved_dependency",
                        },
                        file=record.file,
                        line=record.line,
                        status="partial",
                    )
                    codemap.link(
                        RelationKind.DERIVES,
                        unresolved.id,
                        expr.id,
                        attrs={"provenance": "source_host_unresolved_dependency", "symbol": ref_norm},
                        status="partial",
                    )

        if not _identifiers(record.rhs) and not _link_api_accesses(
            codemap, expr, record.rhs, api_maps, file=record.file, line=record.line
        ):
            root = codemap.upsert(
                EntityKind.COMPILE_VAR,
                f"host-expr:{record.file}:{record.line}",
                attrs={
                    "value_expr": record.rhs,
                    "compile_root": True,
                    "provenance": "source_host_constant_expr",
                },
                file=record.file,
                line=record.line,
                status="confirmed",
            )
            codemap.link(
                RelationKind.DERIVES,
                root.id,
                expr.id,
                attrs={"provenance": "source_host_constant_expr"},
                status="confirmed",
            )

    if producer_sites:
        existing = [s for s in (target.attrs.get("producer_sites") or []) if isinstance(s, dict)]
        for site in producer_sites:
            if site not in existing:
                existing.append(site)
        target.attrs["producer_sites"] = existing
        target.attrs["producer_site_count"] = len(existing)
        target.attrs["producer_provenance"] = "source_host_defuse"

    visiting.discard(state)
    visited.add(state)


def _link_api_accesses(
    codemap: CodeMap,
    expression: Entity,
    text: str,
    api_maps: dict[str, Any],
    *,
    file: str,
    line: int,
) -> bool:
    linked = False
    for kind, token in _API_TOKEN_RE.findall(text):
        api = api_maps.get(kind, {}).get(token)
        if api is not None:
            codemap.link(
                RelationKind.DERIVES,
                api.id,
                expression.id,
                attrs={"provenance": "source_host_api_index", "token": f"{kind}::{token}"},
                status="confirmed",
            )
            linked = True
    for match in _INPUT_ACCESS_RE.finditer(text):
        api = _api_from_index(match.group("arg"), "input", api_maps)
        if api is not None:
            codemap.link(
                RelationKind.DERIVES,
                api.id,
                expression.id,
                attrs={"provenance": "source_host_api_accessor", "accessor": match.group(0)},
                status="confirmed",
            )
            linked = True
    for match in _ATTR_ACCESS_RE.finditer(text):
        api = _api_from_index(match.group("arg"), "attr", api_maps)
        if api is not None:
            codemap.link(
                RelationKind.DERIVES,
                api.id,
                expression.id,
                attrs={"provenance": "source_host_api_accessor", "accessor": match.group(0)},
                status="confirmed",
            )
            linked = True
    if "GetDeterministic(" in text:
        runtime = codemap.upsert(
            EntityKind.INPUT,
            "__context__.deterministic",
            eid="HOST_CONTEXT::deterministic",
            attrs={
                "api_kind": "runtime_context",
                "source_accessor": "GetDeterministic",
                "provenance": "source_host_runtime_context",
            },
            file=file,
            line=line,
            status="confirmed",
        )
        codemap.link(
            RelationKind.DERIVES,
            runtime.id,
            expression.id,
            attrs={"provenance": "source_host_runtime_context"},
            status="confirmed",
        )
        linked = True
    return linked


def _api_from_index(raw: str, kind: str, api_maps: dict[str, Any]) -> Entity | None:
    token = normalize_symbol(raw).strip()
    enum_kind = "InputIndex" if kind == "input" else "AttrIndex"
    if token.startswith(enum_kind + "::"):
        return api_maps.get(enum_kind, {}).get(token.split("::", 1)[1])
    try:
        position = int(token, 0)
    except ValueError:
        position = api_maps.get("constants", {}).get(token)
    if position is None:
        return None
    table = api_maps.get("input_by_position" if kind == "input" else "attr_by_position", {})
    return table.get(int(position))


def _is_compile_reference(value: str, compile_symbols: set[str]) -> bool:
    if value in compile_symbols:
        return True
    if "::" not in value:
        return False
    tail = value.rsplit("::", 1)[-1]
    # Qualified value tokens such as ge::DT_FLOAT or OptionEnum::ENABLE may be
    # declared in external CANN headers.  Only constant-like value spellings are
    # accepted; method/type names are not promoted merely for containing '::'.
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]*|NUM\d+|DT_[A-Z0-9_]+", tail))


def _looks_like_runtime_reference(value: str) -> bool:
    if not value:
        return False
    head = value.split(".")[0].split("::")[0]
    return head not in _IGNORED and not value.isdigit()


def _identifiers(text: str) -> list[str]:
    out: list[str] = []
    for match in _IDENT_RE.finditer(text):
        token = normalize_symbol(match.group(0))
        head = token.split(".")[0].split("::")[0]
        if head in _IGNORED or token in _IGNORED or token.isdigit():
            continue
        # Function/method names are call-graph facts, not value dependencies.
        rest = text[match.end():]
        if re.match(r"\s*\(", rest):
            continue
        out.append(token)
    return out


def _source_rooted_entities(codemap: CodeMap) -> set[str]:
    roots = {e.id for e in codemap.entities.values() if _trusted_root(e)}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for rel in codemap.relations.values():
        if rel.kind_name() in _ROOT_RELATIONS:
            adjacency[rel.src].append(rel.dst)
    seen = set(roots)
    queue = deque(roots)
    while queue:
        cur = queue.popleft()
        for nxt in adjacency.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _trusted_root(entity: Entity) -> bool:
    kind = entity.kind_name()
    if kind in {EntityKind.INPUT.value, EntityKind.BUILD_VARIANT.value, EntityKind.ARCH.value}:
        return True
    if kind in {EntityKind.COMPILE_VAR.value, EntityKind.MACRO.value}:
        return _trusted_compile_root(entity)
    return False


def _trusted_compile_root(entity: Entity) -> bool:
    provenance = str(entity.attrs.get("provenance") or "")
    origin = str(entity.attrs.get("origin") or "")
    return bool(
        entity.attrs.get("compile_root")
        or provenance.startswith("source_")
        or provenance.startswith("source_host_")
        or origin == "constexpr_or_define"
    )


def _enum_names(body: str) -> list[str]:
    out: list[str] = []
    for raw in body.split(","):
        item = re.sub(r"//.*", "", raw).strip()
        if not item:
            continue
        name = item.split("=", 1)[0].strip()
        if re.match(r"^[A-Za-z_]\w*$", name):
            out.append(name)
    return out


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


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()
