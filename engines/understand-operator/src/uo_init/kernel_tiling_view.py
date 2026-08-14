# -*- coding: utf-8 -*-
"""Kernel-visible TilingData view matching the compiler/UT stub.

CANN does not ship ``GET_TILING_DATA_WITH_STRUCT``. The real kernel compile
generates a packed POD + those macros (see ops-transformer
``gen_tiling_data_stub.py``). FAG vendors the POD under ``op_kernel/``;
other ops expect the generated header. UO force-includes the same view.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo_init.source_layout import (
    entry_include_architecture,
    selected_host_files,
    selected_kernel_files,
    selected_tiling_headers,
)

_BEGIN_RE = re.compile(r"\bBEGIN_TILING_DATA_DEF\s*\(\s*([A-Za-z_]\w*)\s*\)")
_END_RE = re.compile(r"\bEND_TILING_DATA_DEF\b")
_FIELD_HEAD_RE = re.compile(
    r"\bTILING_DATA_FIELD_DEF(?P<kind>_ARR|_STRUCT_ARR|_STRUCT)?\s*\("
)
_CLASS_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)\b")
_DEFAULT_REG_RE = re.compile(r"\bREGISTER_TILING_DEFAULT\s*\(\s*([A-Za-z_:][A-Za-z0-9_:]*)\s*\)")
_CPP_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}


def stub_path(op_dir: str | Path, arch_dir: str, op_name: str = "") -> Path:
    snake = (op_name or Path(op_dir).name).strip() or "op"
    return (
        Path(op_dir).expanduser().resolve()
        / ".ascendc-pilot"
        / arch_dir
        / "uo"
        / "cache"
        / "kernel_tiling_view"
        / f"{snake}_tiling_stub.h"
    )


def install_kernel_tiling_view(spec: Any, ctx: Any) -> Path | None:
    """Write the stub and attach it as a kernel force-include on ``ctx``."""
    op_dir = Path(getattr(spec, "op_dir", "") or getattr(ctx, "op_dir", "") or "")
    arch = str(getattr(spec, "arch_dir", "") or getattr(ctx, "arch_dir", "") or "")
    if not op_dir.is_dir() or not arch:
        return None
    op_name = str(getattr(spec, "op_snake", "") or getattr(spec, "op_name", "") or op_dir.name)
    path = write_stub(op_dir, arch, op_name=op_name)
    if path is None:
        return None
    add = getattr(ctx, "add_force_include", None)
    if callable(add):
        add(str(path), side="kernel")
    else:
        extras = list(getattr(ctx, "extra_kernel_force_includes", None) or [])
        posix = str(path).replace("\\", "/")
        if posix not in extras:
            extras.append(posix)
        ctx.extra_kernel_force_includes = extras
    return path


def write_stub(op_dir: Path, architecture: str, *, op_name: str = "") -> Path | None:
    body = render_stub(op_dir, architecture)
    if not body.strip():
        return None
    path = stub_path(op_dir, architecture, op_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def render_stub(op_dir: Path, architecture: str) -> str:
    existing = _kernel_defined_types(op_dir, architecture)
    structs = _collect_structs(op_dir, architecture)
    default_type = _default_tiling_type(op_dir, architecture) or (
        next((s["name"] for s in structs if s["name"] not in existing), "")
        or (structs[0]["name"] if structs else "")
    )
    chunks: list[str] = [
        "#pragma once",
        "#include <cstdint>",
        "#include <cstring>",
        "",
        "// UO kernel tiling view: packed POD + GET_TILING_DATA* macros",
        "// matching the compiler/UT generated header. Do not redefine types",
        "// already present under op_kernel/ (FAG-style vendored PODs).",
        "",
    ]
    emitted = 0
    for st in structs:
        if st["name"] in existing:
            continue
        chunks.append("#pragma pack(1)")
        chunks.append(f"struct {st['name']} {{")
        if not st["fields"]:
            chunks.append("  uint8_t _uo_placeholder = 0;")
        for field in st["fields"]:
            chunks.append("  " + field)
        chunks.append("};")
        chunks.append("#pragma pack()")
        chunks.append("")
        emitted += 1
        existing.add(st["name"])
    chunks.append("#ifndef GET_TILING_DATA_WITH_STRUCT")
    chunks.append("#define GET_TILING_DATA_WITH_STRUCT(tiling_struct, tiling_data, tiling_arg) \\")
    chunks.append("  tiling_struct tiling_data; \\")
    chunks.append(
        "  (void)memcpy(&tiling_data, tiling_arg, sizeof(tiling_struct))"
    )
    chunks.append("#endif")
    chunks.append("")
    if default_type:
        chunks.append("#ifndef GET_TILING_DATA")
        chunks.append("#define GET_TILING_DATA(tiling_data, tiling_arg) \\")
        chunks.append(
            f"  GET_TILING_DATA_WITH_STRUCT({default_type}, tiling_data, tiling_arg)"
        )
        chunks.append("#endif")
        chunks.append("")
    chunks.append("#ifndef GET_TILING_DATA_MEMBER")
    chunks.append("#define GET_TILING_DATA_MEMBER(tiling_type, member, var, tiling) \\")
    chunks.append("  decltype(tiling_type::member) var{}")
    chunks.append("#endif")
    chunks.append("")
    if emitted == 0 and not default_type:
        # Macros alone still make GET_TILING_DATA_WITH_STRUCT parse when the
        # operator already included a packed class (FAG).
        pass
    return "\n".join(chunks) + "\n"


def _kernel_defined_types(op_dir: Path, architecture: str) -> set[str]:
    names: set[str] = set()
    for path in selected_kernel_files(op_dir, architecture):
        if path.suffix.lower() not in _CPP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names.update(_CLASS_RE.findall(text))
    return names


def _collect_structs(op_dir: Path, architecture: str) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    seen: set[Path] = set()
    for path in list(selected_tiling_headers(op_dir, architecture)) + [
        p for p in selected_host_files(op_dir, architecture)
        if p.suffix.lower() in {".h", ".hpp", ".hh"}
    ]:
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "BEGIN_TILING_DATA_DEF" not in text:
            continue
        for st in _parse_macro_structs(text):
            merged.setdefault(st["name"], st)
    return list(merged.values())


def _parse_macro_structs(text: str) -> list[dict[str, Any]]:
    structs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    i = 0
    while i < len(text):
        m_begin = _BEGIN_RE.search(text, i)
        m_field = _FIELD_HEAD_RE.search(text, i)
        m_end = _END_RE.search(text, i)
        nxt = None
        kind = ""
        for cand, tag in (
            (m_begin, "begin"),
            (m_field, "field"),
            (m_end, "end"),
        ):
            if cand is None:
                continue
            if nxt is None or cand.start() < nxt.start():
                nxt = cand
                kind = tag
        if nxt is None:
            break
        if kind == "begin":
            current = {"name": nxt.group(1), "fields": []}
            i = nxt.end()
            continue
        if kind == "end":
            if current is not None:
                structs.append(current)
                current = None
            i = nxt.end()
            continue
        # field
        if current is None:
            i = nxt.end()
            continue
        open_pos = text.find("(", nxt.start())
        close_pos = _matching_paren(text, open_pos)
        if close_pos < 0:
            i = nxt.end()
            continue
        args = _split_args(text[open_pos + 1 : close_pos])
        field_kind = nxt.group("kind") or ""
        decl = _field_decl(field_kind, args)
        if decl:
            current["fields"].append(decl)
        i = close_pos + 1
    return structs


def _field_decl(kind: str, args: list[str]) -> str:
    if not args:
        return ""
    if kind in {"_ARR", "_STRUCT_ARR"}:
        if len(args) < 3:
            return ""
        ctype, size, name = args[0].strip(), args[1].strip(), args[2].strip()
        size_tok = size if re.fullmatch(r"\d+", size) else "8"
        return f"{ctype} {name}[{size_tok}];"
    if len(args) < 2:
        return ""
    ctype, name = args[0].strip(), args[1].strip()
    return f"{ctype} {name};"


def _default_tiling_type(op_dir: Path, architecture: str) -> str:
    arch = str(architecture or "").strip().lower()
    for path in selected_kernel_files(op_dir, architecture):
        if path.suffix.lower() not in _CPP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        owns = entry_include_architecture(text)
        if owns and arch and owns != arch:
            continue
        m = _DEFAULT_REG_RE.search(text)
        if m:
            return m.group(1).split("::")[-1]
    return ""


def _matching_paren(text: str, open_pos: int) -> int:
    depth = 0
    quote = ""
    escape = False
    for i in range(max(0, open_pos), len(text)):
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
