# -*- coding: utf-8 -*-
"""Operator-agnostic current-source enrichment for an AscendC CodeMap.

This pass is the deterministic fallback when the complete CANN translation unit
is unavailable.  It records only source-verifiable contracts shared by AscendC
operators: REG_OP API declarations, InputIndex/AttrIndex aliases, template
TilingKey declarations, TilingData classes and members, Host setter writes,
__aicore__ kernel templates, ABI positions and GET_TILING_DATA_WITH_STRUCT.

No operator name, repository macro name or free-text derivation is special-cased.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.source_layout import (
    GLOBAL_KERNEL_RE,
    selected_host_files,
    selected_kernel_files,
    selected_tiling_headers,
)

_CPP_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_DECL_RE = re.compile(
    r"ASCENDC_TPL_(BOOL|UINT)_DECL\s*\(\s*([A-Za-z_]\w*)\s*,\s*([^,\)]+)(.*?)\)",
    re.S,
)
_ENUM_RE = re.compile(r"enum\s+class\s+(InputIndex|AttrIndex)\s*:[^{]+\{(.*?)\};", re.S)
_ALIAS_INPUT_RE = re.compile(
    r"\b(?:auto|const\s+auto|[A-Za-z_:<>\s\*&]+)\s+([A-Za-z_]\w*)\s*=.{0,320}?InputIndex::([A-Za-z_]\w*)",
    re.S,
)
_ALIAS_ATTR_RE = re.compile(
    r"\b(?:auto|const\s+auto|[A-Za-z_:<>\s\*&]+)\s+([A-Za-z_]\w*)\s*=.{0,420}?AttrIndex::([A-Za-z_]\w*)",
    re.S,
)
_SETTER_RE = re.compile(r"(?:\.|->)set_([A-Za-z_]\w*)\s*\((.*?)\)\s*;", re.S)
_GET_TILING_RE = re.compile(
    r"GET_TILING_DATA_WITH_STRUCT\s*\(\s*([A-Za-z_:]\w*(?:::\w+)*)\s*,",
    re.S,
)
_GET_TILING_BARE_RE = re.compile(
    r"\bGET_TILING_DATA(?:_MEMBER)?\s*\(\s*([A-Za-z_:]\w*(?:::\w+)*)\s*,",
    re.S,
)
_REGISTER_TILING_KEY_RE = re.compile(
    r"REGISTER_TILING_FOR_TILINGKEY\s*\(\s*\"[^\"]+\"\s*,\s*([A-Za-z_:][A-Za-z0-9_:]*)\s*\)",
    re.S,
)
_REGISTER_TILING_DEFAULT_RE = re.compile(
    r"REGISTER_TILING_DEFAULT\s*\(\s*([A-Za-z_:][A-Za-z0-9_:]*)\s*\)",
    re.S,
)
_PRIMITIVE_TYPES = {
    "bool", "char", "short", "int", "long", "float", "double", "void",
    "unsigned", "signed", "size_t", "ptrdiff_t",
    "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
}
_GLOBAL_KERNEL_RE = GLOBAL_KERNEL_RE
_PARAM_NAME_RE = re.compile(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$")
_TEMPLATE_PARAM_RE = re.compile(
    r"(?:bool|u?int(?:8|16|32|64)_t|int(?:8|16|32|64)_t|size_t|int|unsigned(?:\s+int)?)\s+([A-Za-z_]\w*)"
)
_CLASS_RE = re.compile(
    r"(?:template\s*<.*?>\s*)?(?:class|struct)\s+([A-Za-z_]\w*)[^\{;]*\{",
    re.S,
)
_MEMBER_RE = re.compile(
    r"^\s*(?P<type>[A-Za-z_][\w:\s<>,*&]*?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<arrays>(?:\[[^\]]+\]\s*)*)"
    r"(?:=\s*(?P<init>[^;]+))?;\s*$"
)
_NON_TILING_TYPE_SUFFIXES = ("Helper", "Utils", "Util", "Traits", "Policy")


def enrich_codemap_from_operator_source(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    stats: dict[str, Any] = {}
    api = _parse_api(codemap, root)
    stats.update({k: v for k, v in api.items() if not k.startswith("_")})
    enum_maps = _parse_host_enums(root, architecture, api)
    _link_api_to_historical_variables(codemap, root, enum_maps)

    stats.update(_parse_tiling_keys(codemap, root, architecture))
    stats.update(_parse_tiling_data(codemap, root, architecture))
    _link_host_setters(codemap, root, architecture)

    stats.update(_parse_kernel_contract(codemap, root, architecture, api))
    _link_tiling_data_reads(codemap, root, architecture)
    _link_nested_tiling_data_types(codemap)

    codemap.meta["source_contract"] = "ascendc-source-contract/v2"
    codemap.meta["source_contract_architecture"] = architecture
    codemap.meta["source_contract_stats"] = stats
    return codemap


def _cpp_files(path: Path, *, recursive: bool = True) -> list[Path]:
    if not path.is_dir():
        return []
    it = path.rglob("*") if recursive else path.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in _CPP_SUFFIXES)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _split_args(text: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    escape = False
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
        elif ch in "(<[{":
            depth += 1
            buf.append(ch)
        elif ch in ")>]}":
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


def _tensor_dtypes(payload: str) -> list[str]:
    """Parse ``TensorType({DT_FLOAT16, DT_BF16, ...})`` into declared dtype tokens."""
    text = str(payload or "")
    m = re.search(r"TensorType\s*\(\s*\{([^}]*)\}", text)
    if not m:
        return []
    out: list[str] = []
    for tok in m.group(1).split(","):
        name = tok.strip()
        if name.startswith("DT_"):
            out.append(name)
    return out


def _parse_api(codemap: CodeMap, root: Path) -> dict[str, Any]:
    tensor_inputs: list[Entity] = []
    attrs: list[Entity] = []
    outputs: list[Entity] = []
    source_files = 0
    for path in _cpp_files(root / "op_graph"):
        text = _read(path)
        if "REG_OP(" not in text:
            continue
        source_files += 1
        for idx, line in enumerate(text.splitlines(), 1):
            m = re.match(
                r"\s*\.(INPUT|OPTIONAL_INPUT|OUTPUT|ATTR|REQUIRED_ATTR)\s*\(\s*([A-Za-z_]\w*)\s*,\s*(.*)\)\s*$",
                line,
            )
            if not m:
                continue
            op, name, payload = m.groups()
            file = _rel(root, path)
            if op in {"INPUT", "OPTIONAL_INPUT"}:
                dtypes = _tensor_dtypes(payload)
                ent = codemap.upsert(
                    EntityKind.INPUT,
                    name,
                    attrs={
                        "api_kind": "tensor",
                        "required": op == "INPUT",
                        "declaration": payload.strip(),
                        "dtype": dtypes,
                        "api_index": len(tensor_inputs),
                        "provenance": "source_reg_op",
                    },
                    file=file,
                    line=idx,
                    status="confirmed",
                )
                tensor_inputs.append(ent)
            elif op == "OUTPUT":
                dtypes = _tensor_dtypes(payload)
                ent = codemap.upsert(
                    EntityKind.OUTPUT,
                    name,
                    attrs={
                        "api_kind": "tensor",
                        "declaration": payload.strip(),
                        "dtype": dtypes,
                        "api_index": len(outputs),
                        "provenance": "source_reg_op",
                    },
                    file=file,
                    line=idx,
                    status="confirmed",
                )
                outputs.append(ent)
            else:
                parts = _split_args(payload)
                ent = codemap.upsert(
                    EntityKind.INPUT,
                    name,
                    attrs={
                        "api_kind": "attribute",
                        "required": op == "REQUIRED_ATTR",
                        "attr_type": parts[0] if parts else payload.strip(),
                        "default": parts[1] if len(parts) > 1 else None,
                        "api_attr_index": len(attrs),
                        "provenance": "source_reg_op",
                    },
                    file=file,
                    line=idx,
                    status="confirmed",
                )
                attrs.append(ent)
    return {
        "api_source_files": source_files,
        "api_tensor_inputs": len(tensor_inputs),
        "api_attributes": len(attrs),
        "api_outputs": len(outputs),
        "_api_tensor_input_names": [e.name for e in tensor_inputs],
        "_api_attribute_names": [e.name for e in attrs],
        "_api_output_names": [e.name for e in outputs],
    }


def _parse_enum_values(body: str) -> list[str]:
    names: list[str] = []
    for raw in body.split(","):
        item = re.sub(r"//.*", "", raw).strip()
        if not item:
            continue
        name = item.split("=", 1)[0].strip()
        if re.match(r"^[A-Za-z_]\w*$", name):
            names.append(name)
    return names


def _parse_host_enums(root: Path, architecture: str, api: dict[str, Any]) -> dict[str, dict[str, str]]:
    tokens: dict[str, list[str]] = {"InputIndex": [], "AttrIndex": []}
    for path in selected_host_files(root, architecture):
        text = _read(path)
        for m in _ENUM_RE.finditer(text):
            tokens[m.group(1)] = _parse_enum_values(m.group(2))
    tensor_names = list(api.get("_api_tensor_input_names") or [])
    attr_names = list(api.get("_api_attribute_names") or [])
    return {
        "InputIndex": {token: tensor_names[i] for i, token in enumerate(tokens["InputIndex"]) if i < len(tensor_names)},
        "AttrIndex": {token: attr_names[i] for i, token in enumerate(tokens["AttrIndex"]) if i < len(attr_names)},
    }


def _runtime_source_name(ent: Entity) -> str:
    norm = ((ent.attrs.get("identity") or {}).get("normalized") or {})
    return str(norm.get("source_name") or ent.attrs.get("source_name") or "").strip()


def _source_spans(ent: Entity) -> list[dict[str, Any]]:
    spans = [src for src in (ent.attrs.get("sources") or []) if isinstance(src, dict) and src.get("file")]
    if ent.file:
        spans.append({"file": ent.file, "span": {"start_line": ent.line_start, "end_line": ent.line_end}})
    return spans


def _resolve_source_file(root: Path, raw: str) -> Path | None:
    rel = raw.replace("\\", "/").lstrip("./")
    candidates = [root.parent / rel, root / rel]
    if rel.startswith(root.name + "/"):
        candidates.append(root / rel[len(root.name) + 1 :])
    for path in candidates:
        if path.is_file():
            return path
    return None


def _link_api_to_historical_variables(
    codemap: CodeMap,
    root: Path,
    enum_maps: dict[str, dict[str, str]],
) -> None:
    cache: dict[Path, tuple[list[str], dict[str, str], dict[str, str]]] = {}
    variables = codemap.by_kind(EntityKind.VARIABLE)
    var_by_source = {name: e for e in variables if (name := _runtime_source_name(e))}

    for var in variables:
        for src in _source_spans(var):
            candidate = _resolve_source_file(root, str(src.get("file") or ""))
            if candidate is None:
                continue
            if candidate not in cache:
                text = _read(candidate)
                lines = text.splitlines()
                input_alias: dict[str, str] = {}
                attr_alias: dict[str, str] = {}
                for m in _ALIAS_INPUT_RE.finditer(text):
                    api_name = enum_maps.get("InputIndex", {}).get(m.group(2))
                    if api_name:
                        input_alias[m.group(1)] = api_name
                for m in _ALIAS_ATTR_RE.finditer(text):
                    api_name = enum_maps.get("AttrIndex", {}).get(m.group(2))
                    if api_name:
                        attr_alias[m.group(1)] = api_name
                cache[candidate] = (lines, input_alias, attr_alias)
            lines, input_alias, attr_alias = cache[candidate]
            span = src.get("span") or {}
            start = max(1, int(span.get("start_line") or var.line_start or 1))
            end = max(start, int(span.get("end_line") or start))
            snippet = "\n".join(lines[start - 1 : min(len(lines), end)])
            for alias, api_name in {**input_alias, **attr_alias}.items():
                if not re.search(rf"\b{re.escape(alias)}\b", snippet):
                    continue
                for inp in codemap.by_name(api_name, kind=EntityKind.INPUT):
                    codemap.link(
                        RelationKind.DERIVES,
                        inp.id,
                        var.id,
                        attrs={
                            "provenance": "source_host_alias",
                            "file": _rel(root, candidate),
                            "line_start": start,
                            "line_end": end,
                            "alias": alias,
                        },
                        status="confirmed",
                    )
            for source_name, source_ent in var_by_source.items():
                if source_ent.id == var.id:
                    continue
                if re.search(rf"\b{re.escape(source_name)}\b", snippet):
                    codemap.link(
                        RelationKind.DERIVES,
                        source_ent.id,
                        var.id,
                        attrs={
                            "provenance": "source_host_assignment",
                            "file": _rel(root, candidate),
                            "line_start": start,
                            "line_end": end,
                        },
                        status="confirmed",
                    )


def _macro_ints(text: str) -> dict[str, int]:
    return {
        name: int(value)
        for name, value in re.findall(r"^\s*#define\s+([A-Za-z_]\w*)\s+([0-9]+)\s*$", text, re.M)
    }


def _parse_allowed_values(tail: str) -> list[int | str]:
    if "ASCENDC_TPL_UI_LIST" not in tail:
        return []
    after = tail.split("ASCENDC_TPL_UI_LIST", 1)[1]
    out: list[int | str] = []
    for token in _split_args(after.lstrip(", \n\t")):
        token = token.strip().rstrip(")")
        if not token:
            continue
        try:
            out.append(int(token, 0))
        except ValueError:
            out.append(token)
    return out


def _parse_tiling_keys(codemap: CodeMap, root: Path, architecture: str) -> dict[str, Any]:
    declared: list[str] = []
    for path in selected_kernel_files(root, architecture):
        text = _read(path)
        if "ASCENDC_TPL_ARGS_DECL" not in text:
            continue
        ints = _macro_ints(text)
        for m in _DECL_RE.finditer(text):
            decl_kind, name, width_token, tail = m.groups()
            if name in declared:
                continue
            order = len(declared)
            declared.append(name)
            if decl_kind == "BOOL":
                width = 1
                allowed = sorted({int(v) for v in re.findall(r"\b[01]\b", ",".join([width_token, tail]))})
            else:
                token = width_token.strip()
                try:
                    width = int(token, 0)
                except ValueError:
                    width = ints.get(token)
                allowed = _parse_allowed_values(tail)
            line = _line_of(text, m.start())
            attrs = {
                "bit_width": width,
                "allowed_values": allowed,
                "decl_kind": decl_kind.lower(),
                "source_declared": True,
                "provenance": "source_tpl_args_decl",
                "decl_order": order,
            }
            existing = codemap.by_name(name, kind=EntityKind.TILING_KEY)
            if existing:
                ent = existing[0]
                ent.attrs.update(attrs)
                ent.file = _rel(root, path)
                ent.line_start = line
                ent.line_end = line
                ent.status = "confirmed"
                ent.confidence = 1.0
            else:
                codemap.upsert(
                    EntityKind.TILING_KEY,
                    name,
                    attrs=attrs,
                    file=_rel(root, path),
                    line=line,
                    status="confirmed",
                )
    if not declared:
        declared = _parse_fallback_tiling_keys(codemap, root, architecture)
    codemap.meta["source_declared_tiling_keys"] = declared
    codemap.meta["source_declared_tiling_key_count"] = len(declared)
    return {"source_declared_tiling_keys": len(declared)}


_TILING_KEY_IS_RE = re.compile(r"\bTILING_KEY_IS\s*\(\s*([A-Za-z_]\w*)\s*\)")
_DEFINE_TILING_KEY_RE = re.compile(
    r"^\s*#\s*define\s+(TILING_KEY_[A-Za-z0-9_]+)\b", re.MULTILINE
)
_CONSTEXPR_TILING_KEY_RE = re.compile(
    r"\bconstexpr\s+(?:static\s+)?(?:const\s+)?"
    r"(?:u?int(?:32|64)_t|uint64_t)\s+(TILING_KEY_[A-Za-z0-9_]+)\s*="
)
_SET_TILING_KEY_IDENT_RE = re.compile(
    r"\b(?:SetTilingKey|set_tiling_key)\s*\(\s*([A-Za-z_]\w*)"
)


def _parse_fallback_tiling_keys(
    codemap: CodeMap, root: Path, architecture: str
) -> list[str]:
    """Integer/macro TilingKeys used when there is no ASCENDC_TPL_*_DECL."""
    found: list[tuple[str, Path, int, str]] = []
    seen: set[str] = set()
    files = list(selected_kernel_files(root, architecture)) + list(
        selected_host_files(root, architecture)
    )
    for path in files:
        try:
            text = _read(path)
        except OSError:
            continue
        for regex, prov in (
            (_TILING_KEY_IS_RE, "source_tiling_key_is"),
            (_DEFINE_TILING_KEY_RE, "source_tiling_key_define"),
            (_CONSTEXPR_TILING_KEY_RE, "source_tiling_key_constexpr"),
            (_SET_TILING_KEY_IDENT_RE, "source_set_tiling_key"),
        ):
            for m in regex.finditer(text):
                name = m.group(1)
                if name in seen:
                    continue
                seen.add(name)
                found.append((name, path, _line_of(text, m.start()), prov))
    declared: list[str] = []
    for name, path, line, prov in found:
        declared.append(name)
        codemap.upsert(
            EntityKind.TILING_KEY,
            name,
            attrs={
                "source_declared": True,
                "provenance": prov,
                "decl_order": len(declared) - 1,
                "decl_kind": "uint",
            },
            file=_rel(root, path),
            line=line,
            status="confirmed",
        )
    return declared


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


def _class_members(body: str, body_start_line: int) -> Iterable[tuple[str, str, int]]:
    depth = 0
    for off, line in enumerate(body.splitlines()):
        stripped = re.sub(r"//.*", "", line).strip()
        if depth == 0 and stripped and "(" not in stripped and not stripped.endswith(":"):
            m = _MEMBER_RE.match(stripped)
            if m:
                cpp_type = " ".join(m.group("type").split())
                name = m.group("name")
                arrays = re.sub(r"\s+", "", m.group("arrays") or "")
                if arrays:
                    cpp_type = f"{cpp_type}{arrays}"
                if name not in {"public", "private", "protected"} and cpp_type:
                    yield cpp_type, name, body_start_line + off
        depth += line.count("{") - line.count("}")
        depth = max(0, depth)


def _is_tiling_layout_type_name(name: str) -> bool:
    """Reject helper/policy classes that sit beside packing structs."""
    return bool(name) and not name.endswith(_NON_TILING_TYPE_SUFFIXES)


def wanted_tiling_data_names(codemap: CodeMap, root: Path, architecture: str) -> set[str]:
    """TilingData types from registration / GET_TILING_DATA contracts."""
    names = {e.name.split("::")[-1] for e in codemap.by_kind(EntityKind.TILING_DATA) if e.name}
    for path in _kernel_candidates(root, architecture):
        text = _read(path)
        names.update(n.split("::")[-1] for n in _GET_TILING_RE.findall(text))
        names.update(n.split("::")[-1] for n in _GET_TILING_BARE_RE.findall(text))
        names.update(n.split("::")[-1] for n in _REGISTER_TILING_KEY_RE.findall(text))
        names.update(n.split("::")[-1] for n in _REGISTER_TILING_DEFAULT_RE.findall(text))
    names.discard("")
    return names


def _class_index(files: list[Path]) -> dict[str, tuple[Path, str, int, int, int]]:
    """Map class name → (path, text, match_start, body_open, body_close)."""
    index: dict[str, tuple[Path, str, int, int, int]] = {}
    for path in files:
        text = _read(path)
        for m in _CLASS_RE.finditer(text):
            if re.search(r"\benum\s+$", text[: m.start()]):
                continue
            name = m.group(1)
            open_pos = text.find("{", m.start(), m.end())
            close_pos = _matching_brace(text, open_pos)
            if close_pos < 0:
                continue
            index.setdefault(name, (path, text, m.start(), open_pos, close_pos))
    return index


def _cpp_type_name(cpp_type: str) -> str:
    cleaned = re.sub(r"\b(?:const|volatile|mutable|static|inline|typename|class|struct)\b", " ", cpp_type)
    cleaned = re.sub(r"<.*", "", cleaned)
    cleaned = cleaned.replace("*", " ").replace("&", " ").strip()
    if not cleaned:
        return ""
    return cleaned.split()[-1].split("::")[-1]


_WORD_TYPE_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_USING_ALIAS_RE = re.compile(
    r"\busing\s+([A-Za-z_]\w*)\s*=\s*([^;]+);",
    re.S,
)


def _referenced_type_names(cpp_type: str, known: set[str]) -> set[str]:
    """All known type tokens inside a member type (incl. std::conditional arms)."""
    return {t for t in _WORD_TYPE_RE.findall(cpp_type or "") if t in known}


def _resolve_tiling_aliases(text: str, known_classes: set[str]) -> dict[str, str]:
    """Map ``using Alias = ConcreteType<...>`` onto class-index names."""
    out: dict[str, str] = {}
    for match in _USING_ALIAS_RE.finditer(text):
        alias = match.group(1)
        targets = [
            t for t in _WORD_TYPE_RE.findall(match.group(2) or "") if t in known_classes
        ]
        if len(targets) == 1:
            out[alias] = targets[0]
    return out


def _parse_tiling_data(codemap: CodeMap, root: Path, architecture: str) -> dict[str, Any]:
    class_count = 0
    field_count = 0
    files = list(_kernel_candidates(root, architecture))
    seen_files: set[Path] = {p.resolve() for p in files}
    for path in list(selected_tiling_headers(root, architecture)) + list(
        selected_host_files(root, architecture)
    ):
        key = path.resolve()
        if key in seen_files:
            continue
        seen_files.add(key)
        files.append(path)
    index = _class_index(files)
    known_classes = set(index)
    aliases: dict[str, str] = {}
    for path in files:
        try:
            aliases.update(_resolve_tiling_aliases(_read(path), known_classes))
        except OSError:
            continue
    wanted = wanted_tiling_data_names(codemap, root, architecture)
    # Generic AscendC packing layout: current-arch *tiling_data* headers declare
    # the ABI structs. Entry TUs may only REGISTER an alias or a subset type;
    # nested members still need owners for kernel reads / host setters.
    for path in selected_tiling_headers(root, architecture):
        name = path.name.lower()
        if "tiling_data" not in name and "tilingdata" not in name:
            continue
        try:
            text = _read(path)
        except OSError:
            continue
        for match in _CLASS_RE.finditer(text):
            if re.search(r"\benum\s+$", text[: match.start()]):
                continue
            type_name = match.group(1)
            if _is_tiling_layout_type_name(type_name):
                wanted.add(type_name)
    # Collapse ``using Alias = ConcreteType<...>`` onto the class index name.
    for alias, concrete in aliases.items():
        if alias in wanted:
            wanted.add(concrete)
    seen: set[str] = set()
    queue = list(wanted)
    while queue:
        owner = queue.pop()
        if not owner or owner in seen:
            continue
        owner = aliases.get(owner, owner)
        if owner in seen:
            continue
        seen.add(owner)
        loc = index.get(owner)
        if loc is None:
            if owner in wanted:
                existing = codemap.by_name(owner, kind=EntityKind.TILING_DATA)
                if not existing:
                    codemap.upsert(
                        EntityKind.TILING_DATA,
                        owner,
                        attrs={"provenance": "source_tiling_data_type_identity", "architecture": architecture},
                        status="partial",
                    )
            continue
        path, text, start, open_pos, close_pos = loc
        line = _line_of(text, start)
        owner_ent = codemap.upsert(
            EntityKind.TILING_DATA,
            owner,
            attrs={"provenance": "source_tiling_data_class", "architecture": architecture},
            file=_rel(root, path),
            line=line,
            status="confirmed",
        )
        class_count += 1
        body = text[open_pos + 1 : close_pos]
        body_line = _line_of(text, open_pos + 1)
        for cpp_type, field_name, field_line in _class_members(body, body_line):
            field = codemap.upsert(
                EntityKind.TILING_FIELD,
                field_name,
                eid=f"TDF::{owner}::{field_name}",
                attrs={
                    "owner": owner,
                    "qualified_name": f"{owner}::{field_name}",
                    "cpp_type": cpp_type,
                    "provenance": "source_tiling_data_member",
                },
                file=_rel(root, path),
                line=field_line,
                status="confirmed",
            )
            codemap.link(
                RelationKind.DECLARES,
                owner_ent.id,
                field.id,
                attrs={"provenance": "source_tiling_data_class"},
                status="confirmed",
            )
            field_count += 1
            nested_hits = _referenced_type_names(cpp_type, known_classes)
            nested = _cpp_type_name(cpp_type)
            if nested and nested not in _PRIMITIVE_TYPES and nested in index:
                nested_hits.add(nested)
            for nested_name in nested_hits:
                if nested_name not in _PRIMITIVE_TYPES:
                    queue.append(nested_name)
                    wanted.add(nested_name)
    from uo_init.tiling_data_ir import parse_macro_structs

    for path in files:
        try:
            text = _read(path)
        except OSError:
            continue
        if "BEGIN_TILING_DATA_DEF" not in text:
            continue
        for st in parse_macro_structs(text, file=_rel(root, path)):
            if st.name in seen:
                continue
            seen.add(st.name)
            owner_ent = codemap.upsert(
                EntityKind.TILING_DATA,
                st.name,
                attrs={"provenance": "source_tiling_data_macro", "architecture": architecture},
                file=_rel(root, path),
                line=st.line,
                status="confirmed",
            )
            class_count += 1
            for field in st.fields:
                field_ent = codemap.upsert(
                    EntityKind.TILING_FIELD,
                    field.name,
                    eid=f"TDF::{st.name}::{field.name}",
                    attrs={
                        "owner": st.name,
                        "qualified_name": f"{st.name}::{field.name}",
                        "cpp_type": field.ctype,
                        "provenance": "source_tiling_data_macro_field",
                    },
                    file=_rel(root, path),
                    line=field.line,
                    status="confirmed",
                )
                codemap.link(
                    RelationKind.DECLARES,
                    owner_ent.id,
                    field_ent.id,
                    attrs={"provenance": "source_tiling_data_macro"},
                    status="confirmed",
                )
                field_count += 1
    codemap.meta["source_tiling_data_class_count"] = class_count
    codemap.meta["source_tiling_data_field_count"] = field_count
    return {"source_tiling_data_classes": class_count, "source_tiling_data_fields": field_count}


def _link_nested_tiling_data_types(codemap: CodeMap) -> None:
    owners = {e.name: e for e in codemap.by_kind(EntityKind.TILING_DATA)}
    known = set(owners)
    for field in codemap.by_kind(EntityKind.TILING_FIELD):
        cpp_type = str(field.attrs.get("cpp_type") or "")
        targets = _referenced_type_names(cpp_type, known)
        simple = _cpp_type_name(cpp_type)
        if simple in known:
            targets.add(simple)
        for name in targets:
            target = owners.get(name)
            if target is None:
                continue
            codemap.link(
                RelationKind.REFERENCES,
                field.id,
                target.id,
                attrs={"provenance": "source_tiling_data_member_type"},
                status="confirmed",
            )


def _link_host_setters(codemap: CodeMap, root: Path, architecture: str) -> None:
    variables = {name: ent for ent in codemap.by_kind(EntityKind.VARIABLE) if (name := _runtime_source_name(ent))}
    fields_by_name: dict[str, list[Entity]] = {}
    for field in codemap.by_kind(EntityKind.TILING_FIELD):
        fields_by_name.setdefault(field.name, []).append(field)

    for path in selected_host_files(root, architecture):
        text = _read(path)
        for m in _SETTER_RE.finditer(text):
            field_name, expr = m.groups()
            targets = fields_by_name.get(field_name) or []
            if not targets:
                continue
            line = _line_of(text, m.start())
            for source_name, source in variables.items():
                if not re.search(rf"\b{re.escape(source_name)}\b", expr):
                    continue
                for target in targets:
                    codemap.link(
                        RelationKind.DERIVES,
                        source.id,
                        target.id,
                        attrs={
                            "provenance": "source_tilingdata_setter",
                            "file": _rel(root, path),
                            "line": line,
                            "expression": expr.strip()[:300],
                        },
                        status="confirmed",
                    )


def _kernel_candidates(root: Path, architecture: str) -> list[Path]:
    return selected_kernel_files(root, architecture)


def _param_name(raw: str) -> str:
    raw = raw.split("=", 1)[0].strip()
    m = _PARAM_NAME_RE.search(raw)
    return m.group(1) if m else ""


def _parse_kernel_contract(codemap: CodeMap, root: Path, architecture: str, api: dict[str, Any]) -> dict[str, Any]:
    input_names = list(api.get("_api_tensor_input_names") or [])
    output_names = list(api.get("_api_output_names") or [])
    kernel_count = 0
    tpl_args_bound = 0
    abi_links = 0
    seen_kernel_ids: set[str] = set()
    for path in _kernel_candidates(root, architecture):
        text = _read(path)
        for m in _GLOBAL_KERNEL_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            kernels = codemap.by_name(name, kind=EntityKind.KERNEL)
            if kernels:
                kernel = kernels[0]
                kernel.attrs.update({"source_signature": True, "architecture": architecture, "provenance": "source_kernel_signature"})
                kernel.file = _rel(root, path)
                kernel.line_start = line
                kernel.line_end = line
                kernel.status = "confirmed"
                kernel.confidence = 1.0
            else:
                kernel = codemap.upsert(
                    EntityKind.KERNEL,
                    name,
                    attrs={"source_signature": True, "architecture": architecture, "provenance": "source_kernel_signature"},
                    file=_rel(root, path),
                    line=line,
                    status="confirmed",
                )
            if kernel.id not in seen_kernel_ids:
                kernel_count += 1
                seen_kernel_ids.add(kernel.id)

            template = codemap.upsert(
                EntityKind.TEMPLATE,
                f"{name}<template>",
                attrs={"target": name, "architecture": architecture, "provenance": "source_kernel_template"},
                file=_rel(root, path),
                line=line,
                status="confirmed",
            )
            codemap.link(RelationKind.DEFINES, template.id, kernel.id, attrs={"provenance": "source_kernel_template"}, status="confirmed")
            for order, arg_name in enumerate(_TEMPLATE_PARAM_RE.findall(m.group("tpl") or "")):
                arg = codemap.upsert(
                    EntityKind.TEMPLATE_ARG,
                    arg_name,
                    eid=f"TPLARG::{name}::{arg_name}",
                    attrs={"owner": name, "order": order, "provenance": "source_kernel_template"},
                    file=_rel(root, path),
                    line=line,
                    status="confirmed",
                )
                codemap.link(RelationKind.DECLARES, template.id, arg.id, attrs={"provenance": "source_kernel_template"}, status="confirmed")
                for key in codemap.by_name(arg_name, kind=EntityKind.TILING_KEY):
                    codemap.link(RelationKind.BINDS, key.id, arg.id, attrs={"provenance": "source_tpl_name_match"}, status="confirmed")
                    codemap.link(RelationKind.CONTROLS, arg.id, kernel.id, attrs={"provenance": "source_kernel_template_param"}, status="confirmed")
                    tpl_args_bound += 1

            params = [_param_name(x) for x in _split_args(m.group("params"))]
            params = [p for p in params if p]
            if len(params) >= len(input_names) + len(output_names):
                for idx, api_name in enumerate(input_names):
                    hits = codemap.by_name(api_name, kind=EntityKind.INPUT)
                    if hits:
                        codemap.link(
                            RelationKind.FLOWS_TO,
                            hits[0].id,
                            kernel.id,
                            attrs={
                                "provenance": "source_kernel_abi_position",
                                "kernel_param": params[idx],
                                "api_index": idx,
                                "file": _rel(root, path),
                                "line": line,
                            },
                            status="confirmed",
                        )
                        abi_links += 1
                base = len(input_names)
                for idx, api_name in enumerate(output_names):
                    hits = codemap.by_name(api_name, kind=EntityKind.OUTPUT)
                    if hits:
                        codemap.link(
                            RelationKind.FLOWS_TO,
                            kernel.id,
                            hits[0].id,
                            attrs={
                                "provenance": "source_kernel_abi_position",
                                "kernel_param": params[base + idx],
                                "api_index": idx,
                                "file": _rel(root, path),
                                "line": line,
                            },
                            status="confirmed",
                        )
                        abi_links += 1
    return {
        "source_kernel_entries": kernel_count,
        "source_template_args_bound": tpl_args_bound,
        "source_kernel_abi_links": abi_links,
    }


def _link_tiling_data_reads(codemap: CodeMap, root: Path, architecture: str) -> None:
    owners = {e.name: e for e in codemap.by_kind(EntityKind.TILING_DATA)}
    for path in _kernel_candidates(root, architecture):
        text = _read(path)
        used = {name.split("::")[-1] for name in _GET_TILING_RE.findall(text)}
        if not used:
            continue
        entry_names = {m.group("name") for m in _GLOBAL_KERNEL_RE.finditer(text)}
        target_kernels = [
            k for k in codemap.by_kind(EntityKind.KERNEL)
            if k.name in entry_names
            or str(k.file).replace("\\", "/") == _rel(root, path)
        ]
        for type_name in used:
            tdata = owners.get(type_name)
            if tdata is None:
                continue
            for kernel in target_kernels:
                codemap.link(
                    RelationKind.FLOWS_TO,
                    tdata.id,
                    kernel.id,
                    attrs={"provenance": "source_get_tiling_data", "file": _rel(root, path)},
                    status="confirmed",
                )


def source_contract_stats(codemap: CodeMap) -> dict[str, int]:
    inputs = codemap.by_kind(EntityKind.INPUT)
    return {
        "api_tensor_inputs": sum(1 for e in inputs if e.attrs.get("api_kind") == "tensor"),
        "api_attributes": sum(1 for e in inputs if e.attrs.get("api_kind") == "attribute"),
        "outputs": len(codemap.by_kind(EntityKind.OUTPUT)),
        "tiling_keys": len(codemap.by_kind(EntityKind.TILING_KEY)),
        "tiling_data": len(codemap.by_kind(EntityKind.TILING_DATA)),
        "tiling_fields": len(codemap.by_kind(EntityKind.TILING_FIELD)),
        "kernels": len(codemap.by_kind(EntityKind.KERNEL)),
    }
