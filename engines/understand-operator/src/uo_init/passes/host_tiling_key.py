# -*- coding: utf-8 -*-
"""Bind source-declared TilingKey fields to Host ``GET_TPL_TILING_KEY`` args.

AscendC declares packed key dimensions in ``ASCENDC_TPL_ARGS_DECL`` and Host
code constructs the packed value by passing ordered arguments to
``GET_TPL_TILING_KEY``. The positional mapping is a source-level contract and
is stronger than historical natural-language derivations.

This pass is operator-agnostic. It records each argument expression, links
known runtime/compile/API symbols to it when possible, and marks matched Host
variables for the subsequent def-use pass instead of treating an archive node
as an already-rooted value.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind

_CALL_TOKEN = "GET_TPL_TILING_KEY"
_SOURCE_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_IDENT_RE = re.compile(r"[A-Za-z_]\w*(?:\s*(?:\.|->|::)\s*[A-Za-z_]\w*)*")
_CAST_WORDS = {
    "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast", "true", "false",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t", "int16_t", "int32_t",
    "int64_t", "size_t", "bool", "int", "unsigned", "long", "short", "float", "double",
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

    symbol_index = _symbol_index(codemap)
    calls = 0
    bound_names: set[str] = set()
    mismatches: list[dict[str, Any]] = []

    host_dir = root / "op_host" / architecture
    if host_dir.is_dir():
        for path in sorted(host_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for start, _end, args_text in _calls(text, _CALL_TOKEN):
                args = _split_args(args_text)
                calls += 1
                if len(args) != len(keys):
                    mismatches.append(
                        {
                            "file": _rel(root, path),
                            "line": _line(text, start),
                            "argument_count": len(args),
                            "declared_key_count": len(keys),
                        }
                    )
                    continue
                for index, (key, expr) in enumerate(zip(keys, args)):
                    expr = expr.strip()
                    line = _line(text, start)
                    node = codemap.upsert(
                        EntityKind.PREDICATE,
                        expr,
                        eid=f"HOSTKEYEXPR::{_rel(root, path)}::{line}::{index}",
                        attrs={
                            "predicate_role": "host_tiling_key_argument",
                            "tiling_key": key.name,
                            "argument_index": index,
                            "expression": expr,
                            "provenance": "source_get_tpl_tiling_key",
                        },
                        file=_rel(root, path),
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
                            "file": _rel(root, path),
                            "line": line,
                        },
                        status="confirmed",
                    )
                    key.attrs.setdefault("host_packing_expressions", [])
                    if expr not in key.attrs["host_packing_expressions"]:
                        key.attrs["host_packing_expressions"].append(expr)
                    bound_names.add(key.name)
                    _link_expression_sources(
                        codemap,
                        node,
                        expr,
                        symbol_index=symbol_index,
                        file=_rel(root, path),
                        line=line,
                        key_name=key.name,
                    )

    codemap.meta["host_tiling_key_packing"] = {
        "calls": calls,
        "fields_bound": len(bound_names),
        "declared": len(keys),
        "bound_keys": sorted(bound_names),
        "argument_count_mismatches": mismatches,
    }
    return codemap


def _symbol_index(codemap: CodeMap) -> dict[str, list[Entity]]:
    out: dict[str, list[Entity]] = {}
    for ent in codemap.entities.values():
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
        for value in candidates:
            text = _normalize_symbol(value)
            if text:
                out.setdefault(text, []).append(ent)
                out.setdefault(text.split(".")[-1].split("::")[-1], []).append(ent)
    return out


def _mark_host_key_source(source: Entity, key_name: str) -> None:
    """Ensure an existing Host variable is still traced to its real roots."""
    if source.kind_name() != EntityKind.VARIABLE.value:
        return
    source.attrs["host_key_argument"] = True
    keys = source.attrs.setdefault("host_key_argument_keys", [])
    if key_name not in keys:
        keys.append(key_name)


def _link_expression_sources(
    codemap: CodeMap,
    expression: Entity,
    expr: str,
    *,
    symbol_index: dict[str, list[Entity]],
    file: str,
    line: int,
    key_name: str,
) -> None:
    literal = _literal(expr)
    if literal is not None:
        root = codemap.upsert(
            EntityKind.COMPILE_VAR,
            f"{key_name}=literal:{literal}",
            eid=f"HOSTKEYCONST::{key_name}::{literal}",
            attrs={
                "value": literal,
                "compile_root": True,
                "provenance": "source_get_tpl_tiling_key_literal",
            },
            file=file,
            line=line,
            status="confirmed",
        )
        codemap.link(
            RelationKind.DERIVES,
            root.id,
            expression.id,
            attrs={"provenance": "source_get_tpl_tiling_key_literal"},
            status="confirmed",
        )
        return

    linked: set[str] = set()
    for token in _identifiers(expr):
        normalized = _normalize_symbol(token)
        short = normalized.split(".")[-1].split("::")[-1]
        matches = list(symbol_index.get(normalized) or []) + list(symbol_index.get(short) or [])
        for source in matches:
            if source.id == expression.id or source.id in linked:
                continue
            if source.kind_name() not in {
                EntityKind.INPUT.value,
                EntityKind.VARIABLE.value,
                EntityKind.FIELD.value,
                EntityKind.TILING_FIELD.value,
                EntityKind.COMPILE_VAR.value,
                EntityKind.MACRO.value,
                EntityKind.BUILD_VARIANT.value,
                EntityKind.ARCH.value,
            }:
                continue
            _mark_host_key_source(source, key_name)
            codemap.link(
                RelationKind.DERIVES,
                source.id,
                expression.id,
                attrs={
                    "provenance": "source_get_tpl_tiling_key_symbol",
                    "symbol": token,
                    "file": file,
                    "line": line,
                },
                status="confirmed",
            )
            linked.add(source.id)

    if linked:
        return

    tokens = _identifiers(expr)
    if tokens:
        token = tokens[-1]
        local = codemap.upsert(
            EntityKind.VARIABLE,
            _normalize_symbol(token),
            eid=f"HOSTKEYVAR::{file}::{line}::{key_name}",
            attrs={
                "source_name": _normalize_symbol(token).split(".")[-1].split("::")[-1],
                "host_key_argument": True,
                "host_key_argument_keys": [key_name],
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
            attrs={"provenance": "source_get_tpl_tiling_key_symbol"},
            status="confirmed",
        )


def _calls(text: str, token: str):
    pattern = re.compile(rf"\b{re.escape(token)}\s*\(")
    for match in pattern.finditer(text):
        open_pos = text.find("(", match.start(), match.end())
        close_pos = _matching_paren(text, open_pos)
        if close_pos < 0:
            continue
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
        value = re.sub(r"\s*(?:->|\.)\s*", ".", match.group(0).strip())
        first = value.split(".")[0].split("::")[0]
        if first in _CAST_WORDS or first.isdigit():
            continue
        if value in _CAST_WORDS:
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


def _normalize_symbol(value: str) -> str:
    return re.sub(r"\s*(?:->|\.)\s*", ".", str(value or "").strip())


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()
