# -*- coding: utf-8 -*-
"""Complete current-source TilingData declarations, including array/conditional members.

The original lightweight member regex accepted scalar declarations only and
rejected types containing template predicates such as ``!isNewDeter``.  Those
members are real ABI fields and must exist before read/write closure is built.
"""
from __future__ import annotations

import re
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind

_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_CLASS_RE = re.compile(r"(?:template\s*<.*?>\s*)?class\s+([A-Za-z_]\w*)[^\{;]*\{", re.S)
# Type text is intentionally permissive.  The field declarator at the end of a
# top-level class line is the stable anchor; restricting the type grammar loses
# valid std::conditional/decltype/template spellings.
_MEMBER_RE = re.compile(
    r"^\s*(?P<type>.+?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<arrays>(?:\[[^\]]+\]\s*)*)"
    r"(?:=\s*(?P<init>[^;]+))?;\s*$"
)


def complete_tiling_fields(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    kernel_dir = root / "op_kernel" / architecture
    if not kernel_dir.is_dir():
        return codemap

    owners = {e.name: e for e in codemap.by_kind(EntityKind.TILING_DATA)}
    added = 0
    arrays = 0
    initializers = 0
    for path in sorted(kernel_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SUFFIXES or "tiling_data" not in path.name.lower():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _CLASS_RE.finditer(text):
            owner_name = match.group(1)
            owner = owners.get(owner_name)
            if owner is None:
                continue
            open_pos = text.find("{", match.start(), match.end())
            close_pos = _matching_brace(text, open_pos)
            if close_pos < 0:
                continue
            body = text[open_pos + 1:close_pos]
            body_line = _line(text, open_pos + 1)
            depth = 0
            for offset, raw_line in enumerate(body.splitlines()):
                stripped = re.sub(r"//.*", "", raw_line).strip()
                if depth == 0 and stripped and "(" not in stripped and not stripped.endswith(":"):
                    mm = _MEMBER_RE.match(stripped)
                    if mm:
                        cpp_type = " ".join(mm.group("type").split())
                        # Access labels and other non-declarations are already
                        # excluded above; still fail closed on obviously empty
                        # or preprocessor-like type text.
                        if not cpp_type or cpp_type.startswith("#"):
                            mm = None
                    if mm:
                        field_name = mm.group("name")
                        array_suffix = re.sub(r"\s+", "", mm.group("arrays") or "")
                        initializer = (mm.group("init") or "").strip()
                        eid = f"TDF::{owner_name}::{field_name}"
                        existing = codemap.entities.get(eid)
                        if existing is None:
                            field = codemap.upsert(
                                EntityKind.TILING_FIELD,
                                field_name,
                                eid=eid,
                                attrs={
                                    "owner": owner_name,
                                    "qualified_name": f"{owner_name}::{field_name}",
                                    "cpp_type": cpp_type,
                                    "provenance": "source_tiling_data_member_complete",
                                },
                                file=_rel(root, path),
                                line=body_line + offset,
                                status="confirmed",
                            )
                            codemap.link(
                                RelationKind.DECLARES,
                                owner.id,
                                field.id,
                                attrs={"provenance": "source_tiling_data_class"},
                                status="confirmed",
                            )
                            added += 1
                        else:
                            field = existing
                            field.attrs.setdefault("owner", owner_name)
                            field.attrs.setdefault("qualified_name", f"{owner_name}::{field_name}")
                            field.attrs["cpp_type"] = cpp_type
                        if array_suffix:
                            field.attrs["array_extent"] = array_suffix
                            field.attrs["is_array"] = True
                            arrays += 1
                        if initializer:
                            field.attrs["default_initializer"] = initializer
                            field.attrs["default_initializer_site"] = {
                                "file": _rel(root, path),
                                "line": body_line + offset,
                            }
                            initializers += 1
                depth += raw_line.count("{") - raw_line.count("}")
                depth = max(0, depth)

    codemap.meta["source_tiling_data_complete"] = {
        "added_fields": added,
        "array_fields": arrays,
        "default_initializers": initializers,
        "total_fields": len(codemap.by_kind(EntityKind.TILING_FIELD)),
        "policy": "source-member-array-conditional/v2",
    }
    return codemap


def _matching_brace(text: str, open_pos: int) -> int:
    if open_pos < 0:
        return -1
    depth = 0
    quote = ""
    escape = False
    for idx in range(open_pos, len(text)):
        ch = text[idx]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'\"', "'"}:
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    return -1


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1
