# -*- coding: utf-8 -*-
"""Source-backed Host def-use for TilingKey argument variables.

This fallback starts from variables introduced by ``host_tiling_key`` and walks
current Host assignments plus guarding ``if`` conditions. It can therefore
recover dependencies such as ``query dtype -> inputDtype -> TilingKey`` without
promoting historical prose. API roots are recognized through source-declared
``InputIndex``/``AttrIndex`` tokens; enum/literal-only expressions become
compile roots. Ambiguous definitions remain unresolved.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind

_SOURCE_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_ENUM_RE = re.compile(r"enum\s+class\s+(InputIndex|AttrIndex)\s*:[^{]+\{(.*?)\};", re.S)
_ASSIGN_RE = re.compile(
    r"(?P<lhs>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*)\s*(?<![=!<>])=(?!=)\s*(?P<rhs>[^;]+);",
    re.S,
)
_IF_RE = re.compile(r"\b(?:if|else\s+if)\s*\((?P<cond>[^{};]*)\)\s*\{", re.S)
_IDENT_RE = re.compile(r"[A-Za-z_]\w*(?:\s*(?:\.|->|::)\s*[A-Za-z_]\w*)*")
_API_TOKEN_RE = re.compile(r"\b(InputIndex|AttrIndex)::([A-Za-z_]\w*)")
_IGNORED = {
    "auto", "const", "static_cast", "reinterpret_cast", "const_cast", "true", "false",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t", "int16_t", "int32_t",
    "int64_t", "size_t", "bool", "int", "unsigned", "long", "short", "float", "double",
    "return", "nullptr", "std", "ge",
}


@dataclass(frozen=True)
class _Record:
    lhs: str
    rhs: str
    guards: tuple[str, ...]
    file: str
    line: int


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
        by_short[_short(record.lhs)].append(record)

    api_maps = _api_maps(codemap, texts)
    symbol_nodes: dict[str, Entity] = {}
    for ent in codemap.by_kind(EntityKind.VARIABLE):
        if ent.attrs.get("host_key_argument"):
            symbol_nodes[_norm(ent.name)] = ent
            source_name = str(ent.attrs.get("source_name") or "")
            if source_name:
                symbol_nodes.setdefault(_norm(source_name), ent)

    targets = [e for e in codemap.by_kind(EntityKind.VARIABLE) if e.attrs.get("host_key_argument")]
    visiting: set[str] = set()
    visited: set[str] = set()
    for target in targets:
        _resolve_symbol(
            codemap,
            target,
            target.name,
            root=root,
            by_exact=by_exact,
            by_short=by_short,
            api_maps=api_maps,
            symbol_nodes=symbol_nodes,
            visiting=visiting,
            visited=visited,
        )

    rooted = _rooted_entities(codemap)
    resolved = 0
    for target in targets:
        if target.id in rooted:
            target.attrs["upstream_unresolved"] = False
            target.attrs["rooted_by_current_source"] = True
            target.status = "confirmed"
            target.confidence = 1.0
            resolved += 1

    codemap.meta["host_key_root_trace"] = {
        "target_variables": len(targets),
        "rooted_variables": resolved,
        "assignment_records": len(records),
    }
    return codemap


def _assignments(root: Path, path: Path, text: str) -> list[_Record]:
    guard_scopes: list[tuple[int, int, str]] = []
    for match in _IF_RE.finditer(text):
        open_pos = text.find("{", match.start(), match.end())
        close_pos = _matching_brace(text, open_pos)
        if close_pos >= 0:
            guard_scopes.append((open_pos + 1, close_pos, match.group("cond").strip()))
    out: list[_Record] = []
    for match in _ASSIGN_RE.finditer(text):
        lhs = _norm(match.group("lhs"))
        rhs = match.group("rhs").strip()
        # Avoid treating the type/declarator prefix as part of lhs: the regex
        # naturally starts at the last identifier before '=' for declarations.
        guards = tuple(
            cond for start, end, cond in guard_scopes if start <= match.start() <= end
        )
        out.append(
            _Record(
                lhs=lhs,
                rhs=rhs,
                guards=guards,
                file=_rel(root, path),
                line=_line(text, match.start()),
            )
        )
    return out


def _api_maps(codemap: CodeMap, texts: list[tuple[Path, str]]) -> dict[str, dict[str, Entity]]:
    tensor_inputs = sorted(
        (e for e in codemap.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "tensor"),
        key=lambda e: int(e.attrs.get("api_index") or 0),
    )
    attrs = sorted(
        (e for e in codemap.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "attribute"),
        key=lambda e: int(e.attrs.get("api_attr_index") or 0),
    )
    tokens: dict[str, list[str]] = {"InputIndex": [], "AttrIndex": []}
    for _path, text in texts:
        for match in _ENUM_RE.finditer(text):
            tokens[match.group(1)] = _enum_names(match.group(2))
    return {
        "InputIndex": {name: tensor_inputs[i] for i, name in enumerate(tokens["InputIndex"]) if i < len(tensor_inputs)},
        "AttrIndex": {name: attrs[i] for i, name in enumerate(tokens["AttrIndex"]) if i < len(attrs)},
    }


def _resolve_symbol(
    codemap: CodeMap,
    target: Entity,
    symbol: str,
    *,
    root: Path,
    by_exact: dict[str, list[_Record]],
    by_short: dict[str, list[_Record]],
    api_maps: dict[str, dict[str, Entity]],
    symbol_nodes: dict[str, Entity],
    visiting: set[str],
    visited: set[str],
) -> None:
    normalized = _norm(symbol)
    state = f"{target.id}:{normalized}"
    if state in visited or state in visiting:
        return
    visiting.add(state)
    records = list(by_exact.get(normalized) or [])
    if not records:
        short_records = list(by_short.get(_short(normalized)) or [])
        # A short-name fallback is safe only when all candidates represent the
        # same normalized lhs spelling.
        spellings = {r.lhs for r in short_records}
        if len(spellings) == 1:
            records = short_records

    for index, record in enumerate(records):
        expr = codemap.upsert(
            EntityKind.PREDICATE,
            record.rhs,
            eid=f"HOSTDEF::{record.file}::{record.line}::{_short(record.lhs)}::{index}",
            attrs={
                "predicate_role": "host_definition",
                "lhs": record.lhs,
                "expression": record.rhs,
                "guards": list(record.guards),
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
            attrs={"provenance": "source_host_defuse", "lhs": record.lhs},
            status="confirmed",
        )
        texts = [record.rhs, *record.guards]
        linked = False
        for text in texts:
            for kind, token in _API_TOKEN_RE.findall(text):
                api = api_maps.get(kind, {}).get(token)
                if api is not None:
                    codemap.link(
                        RelationKind.DERIVES,
                        api.id,
                        expr.id,
                        attrs={"provenance": "source_host_api_index", "token": f"{kind}::{token}"},
                        status="confirmed",
                    )
                    linked = True
            for ref in _identifiers(text):
                ref_norm = _norm(ref)
                ref_short = _short(ref_norm)
                if ref_norm == normalized or ref_short == _short(normalized):
                    continue
                if "::" in ref_norm and ref_norm.split("::", 1)[0] not in {"InputIndex", "AttrIndex"}:
                    compile_root = codemap.upsert(
                        EntityKind.COMPILE_VAR,
                        ref_norm,
                        eid=f"HOSTCONST::{ref_norm}",
                        attrs={"compile_root": True, "provenance": "source_host_constant"},
                        file=record.file,
                        line=record.line,
                        status="confirmed",
                    )
                    codemap.link(RelationKind.DERIVES, compile_root.id, expr.id, attrs={"provenance": "source_host_constant"}, status="confirmed")
                    linked = True
                    continue
                upstream_records = list(by_exact.get(ref_norm) or [])
                if not upstream_records:
                    candidates = list(by_short.get(ref_short) or [])
                    if len({r.lhs for r in candidates}) == 1:
                        upstream_records = candidates
                if upstream_records:
                    upstream = symbol_nodes.get(ref_norm) or symbol_nodes.get(ref_short)
                    if upstream is None:
                        upstream = codemap.upsert(
                            EntityKind.VARIABLE,
                            ref_norm,
                            eid=f"HOSTDEFVAR::{ref_norm}",
                            attrs={"source_name": ref_short, "provenance": "source_host_defuse"},
                            file=upstream_records[0].file,
                            line=upstream_records[0].line,
                            status="confirmed",
                        )
                        symbol_nodes[ref_norm] = upstream
                        symbol_nodes.setdefault(ref_short, upstream)
                    codemap.link(RelationKind.DERIVES, upstream.id, expr.id, attrs={"provenance": "source_host_defuse"}, status="confirmed")
                    _resolve_symbol(
                        codemap,
                        upstream,
                        ref_norm,
                        root=root,
                        by_exact=by_exact,
                        by_short=by_short,
                        api_maps=api_maps,
                        symbol_nodes=symbol_nodes,
                        visiting=visiting,
                        visited=visited,
                    )
                    linked = True
        if not linked and _compile_only(record.rhs):
            compile_root = codemap.upsert(
                EntityKind.COMPILE_VAR,
                f"host-expr:{record.file}:{record.line}",
                attrs={"value_expr": record.rhs, "compile_root": True, "provenance": "source_host_constant_expr"},
                file=record.file,
                line=record.line,
                status="confirmed",
            )
            codemap.link(RelationKind.DERIVES, compile_root.id, expr.id, attrs={"provenance": "source_host_constant_expr"}, status="confirmed")

    visiting.discard(state)
    visited.add(state)


def _rooted_entities(codemap: CodeMap) -> set[str]:
    roots = {
        e.id
        for e in codemap.entities.values()
        if e.kind_name() in {
            EntityKind.INPUT.value,
            EntityKind.COMPILE_VAR.value,
            EntityKind.MACRO.value,
            EntityKind.BUILD_VARIANT.value,
            EntityKind.ARCH.value,
        }
    }
    adjacency: dict[str, list[str]] = defaultdict(list)
    for rel in codemap.relations.values():
        if rel.kind_name() in {RelationKind.DERIVES.value, RelationKind.CONTROLS.value, RelationKind.FLOWS_TO.value}:
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


def _identifiers(text: str) -> list[str]:
    out: list[str] = []
    for match in _IDENT_RE.finditer(text):
        token = _norm(match.group(0))
        head = token.split(".")[0].split("::")[0]
        if head in _IGNORED or token in _IGNORED or token.isdigit():
            continue
        out.append(token)
    return out


def _compile_only(text: str) -> bool:
    tokens = _identifiers(text)
    return not tokens or all("::" in token for token in tokens)


def _enum_names(body: str) -> list[str]:
    out = []
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


def _norm(value: str) -> str:
    return re.sub(r"\s*(?:->|\.)\s*", ".", str(value or "").strip())


def _short(value: str) -> str:
    return _norm(value).split(".")[-1].split("::")[-1]


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()
