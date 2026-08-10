# -*- coding: utf-8 -*-
"""Bind source-declared TilingKey fields to Host ``GET_TPL_TILING_KEY`` args.

The positional packed-key call is a source contract. This pass records that
contract and identifies the concrete Host symbol used for every argument. It
must not derive the full value function and must not guess across ambiguous
short names.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.symbol_identity import normalize_symbol, short_symbol

_CALL_TOKEN = "GET_TPL_TILING_KEY"
_SOURCE_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_IDENT_RE = re.compile(r"[A-Za-z_]\w*(?:\s*(?:\.|->|::)\s*[A-Za-z_]\w*)*")
_FUNCTION_RE = re.compile(
    r"(?:inline\s+|static\s+|virtual\s+|constexpr\s+)*"
    r"[A-Za-z_][\w:<>,\s*&~]*?\s+"
    r"(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*"
    r"\([^;{}]*\)\s*(?:const\s*)?(?:override\s*)?\{",
    re.S,
)
_CAST_WORDS = {
    "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast", "true", "false",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t", "int16_t", "int32_t",
    "int64_t", "size_t", "bool", "int", "unsigned", "long", "short", "float", "double",
}
_RUNTIME_KINDS = {EntityKind.VARIABLE.value, EntityKind.FIELD.value}
_DIRECT_ROOT_KINDS = {
    EntityKind.INPUT.value,
    EntityKind.COMPILE_VAR.value,
    EntityKind.MACRO.value,
    EntityKind.BUILD_VARIANT.value,
    EntityKind.ARCH.value,
}


def bind_host_tiling_key_expressions(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "arch35",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    keys = sorted(
        (e for e in codemap.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")),
        key=lambda e: int(e.attrs.get("decl_order") or 0),
    )
    if not keys:
        codemap.meta["host_tiling_key_packing"] = {"calls": 0, "fields_bound": 0, "declared": 0}
        return codemap

    exact_index, short_index = _symbol_indexes(codemap)
    calls = 0
    bound_names: set[str] = set()
    mismatches: list[dict[str, Any]] = []
    ambiguous_sources: list[dict[str, Any]] = []

    host_dir = root / "op_host" / architecture
    if host_dir.is_dir():
        for path in sorted(host_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            file = _rel(root, path)
            for start, _end, args_text in _calls(text, _CALL_TOKEN):
                args = _split_args(args_text)
                calls += 1
                line = _line(text, start)
                function = _containing_function(text, start)
                if len(args) != len(keys):
                    mismatches.append(
                        {
                            "file": file,
                            "line": line,
                            "argument_count": len(args),
                            "declared_key_count": len(keys),
                        }
                    )
                    continue
                for index, (key, expr) in enumerate(zip(keys, args)):
                    expr = expr.strip()
                    node = codemap.upsert(
                        EntityKind.PREDICATE,
                        expr,
                        eid=f"HOSTKEYEXPR::{file}::{line}::{index}",
                        attrs={
                            "predicate_role": "host_tiling_key_argument",
                            "tiling_key": key.name,
                            "argument_index": index,
                            "expression": expr,
                            "function": function,
                            "provenance": "source_get_tpl_tiling_key",
                        },
                        file=file,
                        line=line,
                        status="confirmed",
                    )
                    codemap.link(
                        RelationKind.DERIVES,
                        node.id,
                        key.id,
                        attrs={
                            "provenance": "source_get_tpl_tiling_key",
                            "argument_index": index,
                            "expression": expr,
                            "file": file,
                            "line": line,
                            "function": function,
                        },
                        status="confirmed",
                    )
                    key.attrs.setdefault("host_packing_expressions", [])
                    if expr not in key.attrs["host_packing_expressions"]:
                        key.attrs["host_packing_expressions"].append(expr)
                    bound_names.add(key.name)
                    ambiguity = _link_expression_sources(
                        codemap,
                        node,
                        expr,
                        exact_index=exact_index,
                        short_index=short_index,
                        file=file,
                        line=line,
                        function=function,
                        key_name=key.name,
                    )
                    if ambiguity:
                        ambiguous_sources.append(ambiguity)

    codemap.meta["host_tiling_key_packing"] = {
        "calls": calls,
        "fields_bound": len(bound_names),
        "declared": len(keys),
        "bound_keys": sorted(bound_names),
        "argument_count_mismatches": mismatches,
        "ambiguous_source_count": len(ambiguous_sources),
        "ambiguous_sources": ambiguous_sources[:50],
    }
    return codemap


def _entity_spellings(ent: Entity) -> set[str]:
    candidates = {ent.name}
    norm = ((ent.attrs.get("identity") or {}).get("normalized") or {})
    for key in ("source_name", "qualified_name"):
        value = norm.get(key) if isinstance(norm, dict) else None
        if value:
            candidates.add(str(value))
        value = ent.attrs.get(key)
        if value:
            candidates.add(str(value))
    owner = str(ent.attrs.get("owner") or "")
    if owner and ent.name:
        candidates.add(f"{owner}.{ent.name}")
        candidates.add(f"{owner}::{ent.name}")
    return {normalize_symbol(value) for value in candidates if normalize_symbol(value)}


def _symbol_indexes(codemap: CodeMap) -> tuple[dict[str, list[Entity]], dict[str, list[Entity]]]:
    """Build separate canonical and short-name indexes.

    A previous implementation inserted short aliases into the same map as exact
    identities, so looking up bare ``x`` incorrectly looked "exact" when the
    only entities were ``foo.x`` and ``bar.x``. Keeping the namespaces separate
    makes the fallback policy explicit and auditable.
    """
    exact: dict[str, list[Entity]] = {}
    short: dict[str, list[Entity]] = {}
    for ent in codemap.entities.values():
        for spelling in _entity_spellings(ent):
            exact.setdefault(spelling, []).append(ent)
            short.setdefault(short_symbol(spelling), []).append(ent)
    return exact, short


def _dedupe_entities(values: list[Entity]) -> list[Entity]:
    seen: set[str] = set()
    out: list[Entity] = []
    for ent in values:
        if ent.id not in seen:
            seen.add(ent.id)
            out.append(ent)
    return out


def _source_matches(
    exact_index: dict[str, list[Entity]],
    short_index: dict[str, list[Entity]],
    token: str,
) -> tuple[list[Entity], bool]:
    """Prefer canonical exact identity; short-name fallback must be unique."""
    normalized = normalize_symbol(token)
    exact = _dedupe_entities(list(exact_index.get(normalized) or []))
    if exact:
        runtime = [e for e in exact if e.kind_name() in _RUNTIME_KINDS]
        if runtime:
            preferred = sorted(
                runtime,
                key=lambda e: (
                    0 if ("." in normalized and e.kind_name() == EntityKind.FIELD.value) else 1,
                    0 if ("." not in normalized and e.kind_name() == EntityKind.VARIABLE.value) else 1,
                    e.id,
                ),
            )
            return [preferred[0]], False
        return exact, False

    short = _dedupe_entities(list(short_index.get(short_symbol(normalized)) or []))
    # A short fallback is safe only when all hits describe one canonical symbol.
    canonical = {
        spelling
        for ent in short
        for spelling in _entity_spellings(ent)
        if short_symbol(spelling) == short_symbol(normalized)
    }
    if len(short) == 1 and len(canonical) == 1:
        return short, False
    return [], bool(short)


def _mark_host_key_source(
    source: Entity,
    key_name: str,
    *,
    file: str,
    line: int,
    function: str,
) -> None:
    if source.kind_name() not in _RUNTIME_KINDS:
        return
    source.attrs["host_key_argument"] = True
    source.attrs["canonical_symbol"] = normalize_symbol(source.name)
    keys = source.attrs.setdefault("host_key_argument_keys", [])
    if key_name not in keys:
        keys.append(key_name)
    sites = source.attrs.setdefault("host_key_use_sites", [])
    site = {"file": file, "line": line, "function": function, "key": key_name}
    if site not in sites:
        sites.append(site)


def _link_expression_sources(
    codemap: CodeMap,
    expression: Entity,
    expr: str,
    *,
    exact_index: dict[str, list[Entity]],
    short_index: dict[str, list[Entity]],
    file: str,
    line: int,
    function: str,
    key_name: str,
) -> dict[str, Any] | None:
    literal = _literal(expr)
    if literal is not None:
        root = codemap.upsert(
            EntityKind.COMPILE_VAR,
            f"{key_name}=literal:{literal}",
            eid=f"HOSTKEYCONST::{key_name}::{literal}",
            attrs={"value": literal, "compile_root": True, "provenance": "source_get_tpl_tiling_key_literal"},
            file=file,
            line=line,
            status="confirmed",
        )
        codemap.link(RelationKind.DERIVES, root.id, expression.id, attrs={"provenance": "source_get_tpl_tiling_key_literal"}, status="confirmed")
        return None

    tokens = _identifiers(expr)
    linked: set[str] = set()
    ambiguous_tokens: list[str] = []
    for token in tokens:
        matches, ambiguous = _source_matches(exact_index, short_index, token)
        if ambiguous:
            ambiguous_tokens.append(normalize_symbol(token))
        for source in matches:
            if source.id == expression.id or source.id in linked:
                continue
            if source.kind_name() not in (_RUNTIME_KINDS | _DIRECT_ROOT_KINDS | {EntityKind.TILING_FIELD.value}):
                continue
            _mark_host_key_source(source, key_name, file=file, line=line, function=function)
            codemap.link(
                RelationKind.DERIVES,
                source.id,
                expression.id,
                attrs={
                    "provenance": "source_get_tpl_tiling_key_symbol",
                    "symbol": token,
                    "canonical_symbol": normalize_symbol(token),
                    "file": file,
                    "line": line,
                    "function": function,
                },
                status="confirmed",
            )
            linked.add(source.id)

    if linked and not ambiguous_tokens:
        return None

    runtime_tokens = [t for t in tokens if "::" not in normalize_symbol(t)]
    if runtime_tokens:
        token = runtime_tokens[-1]
        canonical = normalize_symbol(token)
        local = codemap.upsert(
            EntityKind.VARIABLE,
            canonical,
            eid=f"HOSTKEYVAR::{file}::{line}::{key_name}",
            attrs={
                "source_name": short_symbol(canonical),
                "canonical_symbol": canonical,
                "host_key_argument": True,
                "host_key_argument_keys": [key_name],
                "host_key_use_sites": [{"file": file, "line": line, "function": function, "key": key_name}],
                "upstream_unresolved": True,
                "provenance": "source_get_tpl_tiling_key_symbol",
            },
            file=file,
            line=line,
            status="partial",
            confidence=1.0,
        )
        codemap.link(
            RelationKind.DERIVES,
            local.id,
            expression.id,
            attrs={
                "provenance": "source_get_tpl_tiling_key_symbol",
                "canonical_symbol": canonical,
                "file": file,
                "line": line,
                "function": function,
            },
            status="confirmed",
        )
    if ambiguous_tokens:
        return {"key": key_name, "file": file, "line": line, "tokens": sorted(set(ambiguous_tokens))}
    return None


def _calls(text: str, token: str):
    pattern = re.compile(rf"\b{re.escape(token)}\s*\(")
    for match in pattern.finditer(text):
        open_pos = text.find("(", match.start(), match.end())
        close_pos = _matching_paren(text, open_pos)
        if close_pos >= 0:
            yield match.start(), close_pos + 1, text[open_pos + 1 : close_pos]


def _matching_paren(text: str, open_pos: int) -> int:
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
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


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


def _containing_function(text: str, offset: int) -> str:
    hits: list[tuple[int, str]] = []
    for match in _FUNCTION_RE.finditer(text):
        open_pos = text.find("{", match.start(), match.end())
        close_pos = _matching_brace(text, open_pos)
        if open_pos <= offset <= close_pos:
            hits.append((close_pos - open_pos, match.group("name")))
    return min(hits, default=(0, ""))[1]


def _split_args(text: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    escape = False
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
    closes = set(pairs.values())
    for ch in text:
        if quote:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
            buf.append(ch)
        elif ch in pairs:
            depth += 1
            buf.append(ch)
        elif ch in closes:
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return out


def _identifiers(expr: str) -> list[str]:
    out: list[str] = []
    for match in _IDENT_RE.finditer(expr):
        value = normalize_symbol(match.group(0))
        first = value.split(".")[0].split("::")[0]
        if first in _CAST_WORDS or first.isdigit() or value in _CAST_WORDS:
            continue
        out.append(value)
    return out


def _literal(expr: str) -> int | float | bool | None:
    text = expr.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text, 0)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()
