# -*- coding: utf-8 -*-
"""Build a SourceIndex with one read + one lexical pass per file."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Iterable

from uo_init.ids import rel_posix
from uo_init.passes.source_text_cache import read_text
from uo_init.source_index.cache import cache_clear, cache_get, cache_put
from uo_init.source_index.model import SourceFacts, SourceIndex
from uo_init.semantics.ascendc_storage import is_valid_storage_name

_CALL_RE = re.compile(
    r"(?:(?P<receiver>[A-Za-z_]\w*)(?:\s*\[[^\n]{0,300}\])?\s*(?:\.|->)\s*)?"
    r"(?:template\s+)?"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:<(?P<targs>[^;{}()=<]{0,240})>)?\s*\(",
)
_ARG_SPLIT_RE = re.compile(r",(?![^()]*\))")
_METHOD_DEF_RE = re.compile(
    r"\b(?:[A-Za-z_]\w*(?:\s*<[^;{}()]{0,200}>)?\s*::\s*)+"
    r"(?P<name>[A-Za-z_~]\w*)\s*\("
)
_FUNC_DEF_RE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{"
)
_STORAGE_TYPE_RE = re.compile(
    r"\b(?:LocalTensor|GlobalTensor|TBuf|TQue|TPipe|MutexBuffer|"
    r"RegTensor|MaskReg|UnalignReg(?:ForLoad|ForStore)?|AddrReg)\b",
    re.I,
)
_DECL_RE = re.compile(
    r"(?P<type>(?:[\w:<>,\s*&]+?))\s+(?P<name>[A-Za-z_]\w*)\s*(?:=|;)",
)
_CLASS_RE = re.compile(r"\b(?:class|struct)\s+(?P<name>[A-Za-z_]\w*)\b")
_USING_RE = re.compile(
    r"\busing\s+(?P<alias>[A-Za-z_]\w*)\s*=\s*(?P<target>[^;{]{1,400})\s*;"
)
_USING_START_RE = re.compile(
    r"\busing\s+(?P<alias>[A-Za-z_]\w*)\s*=\s*(?P<target>[^;{]*)$"
)
_TYPEDEF_RE = re.compile(
    r"\btypedef\s+(?P<target>[\w:<>,\s*&]+?)\s+(?P<alias>[A-Za-z_]\w*)\s*;"
)
_MEMBER_RE = re.compile(
    r"(?P<type>(?:[\w:<>,\s*&]+?))\s+(?P<name>[A-Za-z_]\w*)\s*;"
)
# ``TPipe *pipe;`` — star sits between type and name, so _MEMBER_RE misses it.
_PTR_MEMBER_RE = re.compile(
    r"(?P<type>(?:const\s+|volatile\s+)*[\w:]+(?:\s*<[^;{>]*>)?)\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*;"
)
_CONTINUATION_NAME_RE = re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\s*;\s*$")
_QUOTED_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"')
_TPL_DSL_NAME_MARKERS = ("template_tiling_key.h", "tiling_key.h")
_CXX_CALL_SKIP = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "catch",
        "return",
        "sizeof",
        "alignof",
        "decltype",
        "static_assert",
        "sizeof...",
        "new",
        "delete",
        "static_cast",
        "reinterpret_cast",
        "const_cast",
        "dynamic_cast",
        "likely",
        "unlikely",
        "ASCENDC_TPL_BOOL_SEL",
        "ASCENDC_TPL_UINT_SEL",
        "ASCENDC_TPL_TILING_STRUCT_SEL",
        "ASCENDC_TPL_ARGS_SEL",
        "ASCENDC_TPL_BOOL_DECL",
        "ASCENDC_TPL_UINT_DECL",
    }
)
_CXX_SKIP_BASE = frozenset(
    {
        "public",
        "private",
        "protected",
        "return",
        "if",
        "for",
        "while",
        "switch",
        "int",
        "float",
        "double",
        "bool",
        "char",
        "void",
        "auto",
        "size_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "half",
        "bfloat16_t",
    }
)


def _norm_file(path: str, root: str = "") -> str:
    text = str(path or "").replace("\\", "/")
    if text.startswith("/mnt/") and len(text) >= 7 and text[5].isalpha() and text[6] == "/":
        text = f"{text[5].upper()}:{text[6:]}"
    return rel_posix(text, root)


def _base_type_name(type_text: str) -> str:
    text = str(type_text or "").strip()
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|template)\b", " ", text)
    text = text.replace("&", " ").replace("*", " ")
    no_tpl = text.split("<", 1)[0].strip()
    token = no_tpl.split("::")[-1].strip()
    return token if token.isidentifier() else ""


def _is_tpl_dsl_file(path: Path) -> bool:
    name = path.name.lower().replace("\\", "/")
    return any(marker in name for marker in _TPL_DSL_NAME_MARKERS)


_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _blank_block_comments(text: str) -> str:
    """Replace ``/* ... */`` with spaces, keeping newlines so line numbers stay physical.

    A single-space substitution collapses a file banner onto one line and shifts
    every later call. Clang walk sites use the raw file; merge keys ``(file,
    line, callee)`` then drop the lexical ``InitBuffer`` that landed on an
    earlier real call.
    """

    def _repl(m: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    return _BLOCK_COMMENT_RE.sub(_repl, str(text or ""))


def _strip_line_noise(line: str) -> str:
    if re.search(r"\bCopyright\s*\(\s*c\s*\)", line, flags=re.I):
        return ""
    out: list[str] = []
    i = 0
    n = len(line)
    in_str = False
    in_char = False
    while i < n:
        ch = line[i]
        nxt = line[i + 1] if i + 1 < n else ""
        if not in_str and not in_char and ch == "/" and nxt == "/":
            break
        if not in_char and ch == '"' and (i == 0 or line[i - 1] != "\\"):
            in_str = not in_str
            out.append(" ")
            i += 1
            continue
        if not in_str and ch == "'" and (i == 0 or line[i - 1] != "\\"):
            in_char = not in_char
            out.append(" ")
            i += 1
            continue
        if in_str or in_char:
            out.append(" ")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _update_enclosing_func(line: str, current: str) -> str:
    m_method = _METHOD_DEF_RE.search(line)
    if m_method:
        return m_method.group("name")
    mdef = _FUNC_DEF_RE.search(line)
    if mdef and not line.strip().startswith(("if", "for", "while", "switch", "else")):
        cand = mdef.group("name")
        if cand not in {"if", "for", "while", "switch", "return", "sizeof"}:
            return cand
    return current


def _is_false_lexical_callee(name: str, line: str, match_start: int) -> bool:
    if name in _CXX_CALL_SKIP:
        return True
    if name in {"constexpr", "consteval", "constinit"}:
        prefix = line[:match_start].rstrip()
        if re.search(r"\bif\s*$", prefix):
            return True
        if re.search(r"(^|[\s;{}])$", prefix) or not prefix:
            return True
        return False
    prefix = line[:match_start]
    if re.search(r"(?:\.|->|::)\s*$", prefix.rstrip()):
        return False
    if re.search(r"\b(return|else)\s+$", prefix):
        return False
    if re.search(r"\b(__aicore__|inline|constexpr|virtual|explicit|static)\b", prefix):
        return True
    if re.search(r"[=,]\s*$", prefix.rstrip()):
        return False
    if re.search(r"\b(if|while|for|switch|catch)\s*$", prefix.rstrip()):
        return False
    if re.search(r"(?:[\w:>]|[*&])\s+$", prefix):
        return True
    return False


def _registry_names() -> set[str] | None:
    try:
        from uo_init.semantics import registry as semreg

        names = set(semreg.load_registry())
        names.update({"Get", "GetTensor", "GetPre", "GetReused"})
        return names or None
    except Exception:  # noqa: BLE001
        return None


def _scan_file(path: Path, *, root: str, registry: set[str] | None) -> SourceFacts:
    nfile = _norm_file(str(path), root)
    facts = SourceFacts(file=nfile)
    try:
        text = read_text(path)
    except OSError:
        return facts
    try:
        from uo_init.perf import bump

        bump("regex_scan")
    except Exception:  # noqa: BLE001
        pass
    # Members/aliases must see raw lines (same as the historical scanner).
    # Stripping block comments joins lines and mints extra BUFFER fields.
    raw_lines = text.splitlines()
    call_lines = _blank_block_comments(text).splitlines()
    if len(call_lines) < len(raw_lines):
        call_lines = call_lines + [""] * (len(raw_lines) - len(call_lines))
    elif len(call_lines) > len(raw_lines):
        call_lines = call_lines[: len(raw_lines)]
    current: str | None = None
    depth = 0
    pending_type: str | None = None
    pending_line = 0
    pending_alias: str | None = None
    pending_alias_line = 0
    pending_alias_parts: list[str] = []
    skip_calls = _is_tpl_dsl_file(path)

    def _record_alias(alias: str, target: str, line_no: int) -> None:
        text_target = str(target or "").strip()
        if not alias or not text_target:
            return
        facts.type_aliases.append(
            {
                "alias": alias,
                "target": text_target,
                "file": nfile,
                "line": line_no,
            }
        )

    for i, line in enumerate(raw_lines, start=1):
        for inc in _QUOTED_INCLUDE_RE.findall(line):
            facts.includes.append(inc.replace("\\", "/"))
        if pending_alias is not None:
            pending_alias_parts.append(line.strip())
            joined = " ".join(pending_alias_parts)
            if ";" in joined:
                target = joined.split(";", 1)[0].strip()
                _record_alias(pending_alias, target, pending_alias_line)
                pending_alias = None
                pending_alias_parts = []
            continue
        using_hit = False
        for m in _USING_RE.finditer(line):
            _record_alias(m.group("alias"), m.group("target"), i)
            using_hit = True
        if not using_hit:
            start = _USING_START_RE.search(line)
            if start is not None:
                pending_alias = start.group("alias")
                pending_alias_line = i
                pending_alias_parts = [str(start.group("target") or "").strip()]
        for m in _TYPEDEF_RE.finditer(line):
            _record_alias(m.group("alias"), m.group("target"), i)
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
        pending_type, pending_line = _advance_members(
            facts,
            path=path,
            root=root,
            current=current,
            line=line,
            i=i,
            pending_type=pending_type,
            pending_line=pending_line,
        )

    # Decls and calls both use physical line numbers so they align with Clang
    # sites. Block comments are blanked in place; they must not collapse.
    func = ""
    for i, line in enumerate(raw_lines, start=1):
        func = _update_enclosing_func(line, func)
        if _STORAGE_TYPE_RE.search(line):
            for m in _DECL_RE.finditer(line):
                type_text = m.group("type")
                name = m.group("name")
                if not _STORAGE_TYPE_RE.search(type_text):
                    continue
                facts.buffer_decls.append(
                    {
                        "name": name,
                        "function": func,
                        "type_text": type_text.strip(),
                        "init": None,
                        "file": str(path),
                        "line": i,
                        "column": m.start() + 1,
                    }
                )
    func = ""
    for i, line in enumerate(call_lines, start=1):
        cleaned = _strip_line_noise(line)
        func = _update_enclosing_func(cleaned, func)
        if not skip_calls:
            _collect_calls(
                facts,
                path=path,
                lines=call_lines,
                i=i,
                cleaned=cleaned,
                func=func,
                registry=registry,
            )
    return facts


def _advance_members(
    facts: SourceFacts,
    *,
    path: Path,
    root: str,
    current: str,
    line: str,
    i: int,
    pending_type: str | None,
    pending_line: int,
) -> tuple[str | None, int]:
    if pending_type is not None:
        nm = _CONTINUATION_NAME_RE.match(line)
        combined = f"{pending_type} {line.strip()}"
        emit_name = ""
        emit_type = ""
        if nm:
            emit_name = nm.group("name")
            emit_type = pending_type
        elif ";" in line:
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
            _emit_member(facts, current, emit_name, emit_type, path, root, pending_line)
            return None, 0
        return combined, pending_line
    if "(" in line and "std::conditional" not in line and "conditional_t" not in line:
        return pending_type, pending_line
    stripped = line.rstrip()
    if ";" not in line and (
        stripped.endswith("::type")
        or stripped.endswith(",")
        or (
            ("MutexBuffer" in line or "conditional" in line or "Tensor" in line)
            and not re.search(r"\b[A-Za-z_]\w*\s*;\s*$", line)
        )
    ):
        return stripped, i
    for m in _MEMBER_RE.finditer(line):
        _emit_member(facts, current, m.group("name"), m.group("type").strip(), path, root, i)
    for m in _PTR_MEMBER_RE.finditer(line):
        _emit_member(
            facts,
            current,
            m.group("name"),
            f"{m.group('type').strip()} *",
            path,
            root,
            i,
        )
    return pending_type, pending_line


def _emit_member(
    facts: SourceFacts,
    owner: str,
    name: str,
    type_text: str,
    path: Path,
    root: str,
    line: int,
) -> None:
    if not is_valid_storage_name(name):
        return
    base = _base_type_name(type_text)
    if not base or base in _CXX_SKIP_BASE:
        return
    facts.class_members.append(
        {
            "owner": owner,
            "member": name,
            "type_text": type_text,
            "base_type": base,
            "file": _norm_file(str(path), root),
            "line": line,
        }
    )


def _collect_calls(
    facts: SourceFacts,
    *,
    path: Path,
    lines: list[str],
    i: int,
    cleaned: str,
    func: str,
    registry: set[str] | None,
) -> None:
    for m in _CALL_RE.finditer(cleaned):
        name = m.group("name")
        if not name or not name.isidentifier():
            continue
        if _is_false_lexical_callee(name, cleaned, m.start()):
            continue
        rest = cleaned[m.end() :]
        extra = 0
        end = 0
        while True:
            depth = 0
            end = 0
            for j, ch in enumerate(rest):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth < 0:
                        end = j
                        break
            if end or extra >= 6 or i + extra >= len(lines):
                break
            extra += 1
            rest = rest + " " + _strip_line_noise(lines[i + extra - 1])
        arg_text = rest[:end] if end else rest
        args = [a.strip() for a in _ARG_SPLIT_RE.split(arg_text) if a.strip()]
        targs = m.group("targs") or ""
        targs_list = [a.strip() for a in targs.split(",") if a.strip()] if targs else []
        site = {
            "caller": func,
            "callee": name,
            "file": str(path),
            "line": i,
            "column": m.start() + 1,
            "args": args,
            "template_args": targs_list,
            "receiver": m.group("receiver") or "",
            "path_conditions": (),
            "provenance": "lexical_source_calls",
        }
        facts.call_sites.append(site)
        primitive = False
        if registry is not None and name in registry:
            primitive = True
        elif registry is not None:
            try:
                from uo_init.semantics import registry as semreg

                cat, _, conf = semreg.classify(name)
                primitive = cat != "UNKNOWN" and conf != "unresolved"
            except Exception:  # noqa: BLE001
                primitive = False
        else:
            primitive = True
        if primitive:
            facts.primitive_calls.append(site)


class SourceIndexBuilder:
    @staticmethod
    def build(
        files: Iterable[Path | str],
        *,
        root: str = "",
        deadline: float | None = None,
    ) -> SourceIndex:
        index = SourceIndex(root=root)
        registry = _registry_names()
        for raw in files:
            if deadline is not None and time.perf_counter() >= deadline:
                break
            path = Path(raw)
            if not path.is_file():
                continue
            facts = _scan_file(path, root=root, registry=registry)
            index.by_file[_norm_file(str(path), root)] = facts
            index.by_file[str(path).replace("\\", "/")] = facts
        return index


def get_or_build(
    files: Iterable[Path | str],
    *,
    root: str = "",
    deadline: float | None = None,
) -> SourceIndex:
    index = SourceIndex(root=root)
    registry = _registry_names()
    missing: list[tuple[Path, str]] = []
    for raw in files:
        if deadline is not None and time.perf_counter() >= deadline:
            break
        path = Path(raw)
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path)
        cached = cache_get(resolved)
        if isinstance(cached, SourceFacts):
            index.by_file[_norm_file(str(path), root)] = cached
            index.by_file[str(path).replace("\\", "/")] = cached
            continue
        if not path.is_file():
            continue
        missing.append((path, resolved))

    def _scan_missing(item: tuple[Path, str]) -> tuple[Path, str, SourceFacts]:
        path, resolved = item
        return path, resolved, _scan_file(path, root=root, registry=registry)

    scanned: list[tuple[Path, str, SourceFacts]]
    if len(missing) <= 1:
        scanned = [_scan_missing(item) for item in missing]
    else:
        from uo_init.parallel import map_files

        scanned = map_files(missing, _scan_missing)

    for path, resolved, facts in scanned:
        cache_put(resolved, facts)
        index.by_file[_norm_file(str(path), root)] = facts
        index.by_file[str(path).replace("\\", "/")] = facts
    return index


def reset_index_cache() -> None:
    cache_clear()
