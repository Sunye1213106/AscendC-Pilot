# -*- coding: utf-8 -*-
"""Shared Kernel source scan helpers for Root Trace (Clang walk + lexical)."""

from __future__ import annotations

from uo_init.paths import require_architecture
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from uo_init.ids import rel_posix
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.source_text_cache import read_text
from uo_init.semantics import registry as semreg

_WALK_CACHE_LIMIT = 48

_STORAGE_TYPE_RE = re.compile(
    r"\b(?:LocalTensor|GlobalTensor|TBuf|TQue|TPipe|MutexBuffer|"
    r"RegTensor|MaskReg|UnalignReg(?:ForLoad|ForStore)?|AddrReg)\b",
    re.I,
)
_DECL_RE = re.compile(
    r"(?P<type>(?:[\w:<>,\s*&]+?))\s+(?P<name>[A-Za-z_]\w*)\s*(?:=|;)",
)
_CALL_RE = re.compile(
    r"(?:(?P<receiver>[A-Za-z_]\w*)\s*(?:\.|->)\s*)?"
    r"(?:template\s+)?"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    # Template args must stay inside one <> pair (no '=' / nested '>' from decls).
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


def caller_allowed(caller: str, reachable: set[str], *, filter_strict: bool) -> bool:
    if not filter_strict or not reachable or not caller:
        return True
    short = caller.split("::")[-1]
    return caller in reachable or short in reachable


def norm_file(path: str, root: str = "") -> str:
    text = str(path or "").replace("\\", "/")
    if text.startswith("/mnt/") and len(text) >= 7 and text[5].isalpha() and text[6] == "/":
        text = f"{text[5].upper()}:{text[6:]}"
    return rel_posix(text, root)


def reachable_function_names(codemap: CodeMap) -> tuple[set[str], bool]:
    from collections import deque

    starts = {
        e.id
        for e in codemap.by_kind(EntityKind.KERNEL)
        if e.attrs.get("source_definition") or e.attrs.get("source_signature")
    }
    adj: dict[str, set[str]] = defaultdict(set)
    for rel in codemap.relations.values():
        if rel.kind_name() != RelationKind.CALLS.value:
            continue
        prov = str(rel.attrs.get("provenance") or "")
        if prov not in {
            "source_kernel_call_bound",
            "source_kernel_macro_call_bound",
            "source_kernel_call_refined",
        } and not prov.startswith("source_kernel"):
            continue
        adj[rel.src].add(rel.dst)
    seen = set(starts)
    q = deque(starts)
    while q:
        cur = q.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    names: set[str] = set()
    non_kernel = 0
    for eid in seen:
        ent = codemap.entities.get(eid)
        if ent is None:
            continue
        names.add(ent.name)
        short = str(ent.attrs.get("short_name") or "").strip()
        if short:
            names.add(short)
        if "::" in ent.name:
            names.add(ent.name.rsplit("::", 1)[-1])
        if ent.kind_name() != EntityKind.KERNEL.value:
            non_kernel += 1
    if not names:
        for e in codemap.by_kind(EntityKind.KERNEL):
            names.add(e.name)
    return names, non_kernel >= 3


def selected_kernel_files(codemap: CodeMap, source_root: Path) -> list[Path]:
    meta = codemap.meta.get("kernel_tiling_closure") or {}
    listed = meta.get("selected_kernel_files") or []
    out: list[Path] = []
    seen: set[str] = set()
    for item in listed:
        p = Path(str(item))
        if not p.is_file():
            cand = source_root / item
            if cand.is_file():
                p = cand
            else:
                continue
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    if out:
        return out
    arch = require_architecture(codemap.architecture)
    arch_dir = source_root / "op_kernel" / arch
    if arch_dir.is_dir():
        for p in sorted(arch_dir.rglob("*")):
            if p.suffix.lower() in {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"} and p.is_file():
                out.append(p)
    return out


def site_dedupe_key(site: Any, *, root: str = "") -> tuple[str, int, str]:
    d = site if isinstance(site, dict) else None
    if d is None:
        file = str(getattr(site, "file", "") or "")
        line = int(getattr(site, "line", 0) or 0)
        callee = str(getattr(site, "callee", "") or "").split("::")[-1]
    else:
        file = str(d.get("file") or "")
        line = int(d.get("line") or 0)
        callee = str(d.get("callee") or "").split("::")[-1]
    return (norm_file(file, root), line, callee)


def site_as_dict(site: Any) -> dict[str, Any]:
    if isinstance(site, dict):
        return site
    return {
        "caller": getattr(site, "caller", "") or "",
        "callee": getattr(site, "callee", "") or "",
        "file": getattr(site, "file", "") or "",
        "line": int(getattr(site, "line", 0) or 0),
        "column": int(getattr(site, "column", 0) or 0),
        "args": list(getattr(site, "args", None) or []),
        "template_args": list(getattr(site, "template_args", None) or []),
        "receiver": getattr(site, "receiver", "") or "",
        "path_conditions": getattr(site, "path_conditions", None) or (),
        "entry_reachable": bool(getattr(site, "entry_reachable", True)),
        "caller_usr": getattr(site, "caller_usr", "") or "",
        "caller_qualified": getattr(site, "caller_qualified", "") or "",
        "callee_usr": getattr(site, "callee_usr", "") or "",
        "callee_qualified": getattr(site, "callee_qualified", "") or "",
        "callee_decl_file": getattr(site, "callee_decl_file", "") or "",
        "receiver_type": getattr(site, "receiver_type", "") or "",
        "receiver_canonical_type": getattr(site, "receiver_canonical_type", "") or "",
        "provenance": getattr(site, "provenance", "") or "clang_walk_cache",
    }


def _targs_quality(targs: list[str] | None) -> int:
    joined = " ".join(str(t) for t in (targs or []))
    score = 0
    if "HardEvent" in joined or "PIPE_" in joined:
        score += 2
    if joined.strip():
        score += 1
    return score


def _enrich_site_templates(dst: Any, src: dict[str, Any]) -> Any:
    src_t = list(src.get("template_args") or [])
    src_a = list(src.get("args") or [])
    if isinstance(dst, dict):
        if _targs_quality(src_t) > _targs_quality(list(dst.get("template_args") or [])):
            dst["template_args"] = src_t
        if (not dst.get("args")) and src_a:
            dst["args"] = src_a
        if not dst.get("receiver") and src.get("receiver"):
            dst["receiver"] = src["receiver"]
        return dst
    d = site_as_dict(dst)
    if _targs_quality(src_t) > _targs_quality(list(d.get("template_args") or [])):
        d["template_args"] = src_t
    if (not d.get("args")) and src_a:
        d["args"] = src_a
    if not d.get("receiver") and src.get("receiver"):
        d["receiver"] = src["receiver"]
    return d if (d.get("template_args") or d.get("args")) else dst


def merge_lexical_sites(
    walk_calls: list[Any],
    lexical: list[dict[str, Any]],
    *,
    root: str,
) -> tuple[list[Any], int]:
    index: dict[tuple[str, int, str], int] = {}
    out: list[Any] = list(walk_calls)
    for i, s in enumerate(out):
        index[site_dedupe_key(s, root=root)] = i
    added = 0
    for site in lexical:
        key = site_dedupe_key(site, root=root)
        if key in index:
            i = index[key]
            out[i] = _enrich_site_templates(out[i], site)
            continue
        index[key] = len(out)
        out.append(site)
        added += 1
    return out, added


def collect_call_sites_from_walks(
    source_root: Path,
    *,
    architecture: str,
    reachable: set[str],
    filter_strict: bool,
    deadline: float,
) -> tuple[list[Any], list[Any], list[Any], str]:
    from uo_init import tu_cache

    walks = tu_cache.iter_cached_walks(
        source_root, architecture, path_substr="op_kernel", limit=_WALK_CACHE_LIMIT
    )
    if time.perf_counter() > deadline:
        return [], [], [], "budget_exhausted_before_walk_cache"
    if not walks:
        return [], [], [], "no_walk_cache"

    calls: list[Any] = []
    decls: list[Any] = []
    controls: list[Any] = []
    for wr in walks:
        if time.perf_counter() > deadline:
            break
        for site in getattr(wr, "call_sites", None) or []:
            caller = str(getattr(site, "caller", "") or "")
            callee = str(getattr(site, "callee", "") or "").split("::")[-1]
            if not caller_allowed(caller, reachable, filter_strict=filter_strict):
                continue
            # Root Trace needs the full source call graph. Terminal AscendC/CANN
            # classification happens later; do not filter by registry primitives.
            if not callee or not callee.isidentifier():
                continue
            calls.append(site)
        decls.extend(getattr(wr, "local_decls", None) or [])
        controls.extend(getattr(wr, "controls", None) or [])
    provenance = "clang_walk_cache"
    if len(walks) >= _WALK_CACHE_LIMIT:
        provenance = "clang_walk_cache_partial"
    return calls, decls, controls, provenance


def collect_type_graph_from_walks(
    source_root: Path,
    *,
    architecture: str,
    deadline: float,
) -> dict[str, list[dict[str, Any]]]:
    """Clang-first type / member / alias / base facts from walk cache."""
    from uo_init import tu_cache

    walks = tu_cache.iter_cached_walks(
        source_root, architecture, path_substr="op_kernel", limit=_WALK_CACHE_LIMIT
    )
    members: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    types: list[dict[str, Any]] = []
    bases: list[dict[str, Any]] = []
    if time.perf_counter() > deadline:
        return {"members": members, "aliases": aliases, "types": types, "bases": bases}
    for wr in walks:
        if time.perf_counter() > deadline:
            break
        for fd in (getattr(wr, "field_decls", None) or {}).values():
            host = str(getattr(fd, "host", "") or "")
            name = str(getattr(fd, "name", "") or "")
            if not host or not name:
                continue
            type_text = str(getattr(fd, "type_text", "") or "")
            members.append(
                {
                    "owner": host,
                    "owner_qualified": str(getattr(fd, "owner_qualified", "") or host),
                    "member": name,
                    "type_text": type_text,
                    "canonical_type": str(getattr(fd, "canonical_type", "") or ""),
                    "referenced_type_usr": str(getattr(fd, "referenced_type_usr", "") or ""),
                    "base_type": type_text.split("<", 1)[0].split("::")[-1].strip()
                    if type_text
                    else "",
                    "file": str(getattr(fd, "file", "") or ""),
                    "line": int(getattr(fd, "line", 0) or 0),
                    "column": int(getattr(fd, "column", 0) or 0),
                    "provenance": "clang_field_decl",
                }
            )
        for ad in getattr(wr, "alias_decls", None) or []:
            aliases.append(
                {
                    "alias": str(getattr(ad, "name", "") or ""),
                    "qualified_name": str(getattr(ad, "qualified_name", "") or ""),
                    "target": str(getattr(ad, "target_type", "") or ""),
                    "canonical_type": str(getattr(ad, "canonical_type", "") or ""),
                    "target_usr": str(getattr(ad, "target_usr", "") or ""),
                    "file": str(getattr(ad, "file", "") or ""),
                    "line": int(getattr(ad, "line", 0) or 0),
                    "column": int(getattr(ad, "column", 0) or 0),
                    "provenance": "clang_alias_decl",
                }
            )
        for td in getattr(wr, "type_decls", None) or []:
            types.append(
                {
                    "name": str(getattr(td, "name", "") or ""),
                    "qualified_name": str(getattr(td, "qualified_name", "") or ""),
                    "usr": str(getattr(td, "usr", "") or ""),
                    "kind": str(getattr(td, "kind", "") or "class"),
                    "file": str(getattr(td, "file", "") or ""),
                    "line": int(getattr(td, "line", 0) or 0),
                    "column": int(getattr(td, "column", 0) or 0),
                    "provenance": "clang_type_decl",
                }
            )
        for bd in getattr(wr, "base_decls", None) or []:
            bases.append(
                {
                    "derived": str(getattr(bd, "derived_name", "") or ""),
                    "derived_usr": str(getattr(bd, "derived_usr", "") or ""),
                    "base": str(getattr(bd, "base_name", "") or ""),
                    "base_usr": str(getattr(bd, "base_usr", "") or ""),
                    "canonical_type": str(getattr(bd, "canonical_type", "") or ""),
                    "file": str(getattr(bd, "file", "") or ""),
                    "line": int(getattr(bd, "line", 0) or 0),
                    "column": int(getattr(bd, "column", 0) or 0),
                    "provenance": "clang_base_decl",
                }
            )
    return {"members": members, "aliases": aliases, "types": types, "bases": bases}


def update_enclosing_func(line: str, current: str) -> str:
    m_method = _METHOD_DEF_RE.search(line)
    if m_method:
        return m_method.group("name")
    mdef = _FUNC_DEF_RE.search(line)
    if mdef and not line.strip().startswith(("if", "for", "while", "switch", "else")):
        cand = mdef.group("name")
        if cand not in {"if", "for", "while", "switch", "return", "sizeof"}:
            return cand
    return current


# Control / language keywords that are never AscendC callees.
# NOTE: ``constexpr`` / ``consteval`` are intentionally NOT here — AscendC
# kernels are compile-time heavy (``if constexpr`` + NTTP templates). Lexical
# denoise must not treat “compile-time” as skippable; only reject the *false
# call shape* ``if constexpr (`` via :func:`_is_false_lexical_callee`.
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
        # TPL DSL schema macros — owned by tpl_schema pass, not call graphs.
        "ASCENDC_TPL_BOOL_SEL",
        "ASCENDC_TPL_UINT_SEL",
        "ASCENDC_TPL_TILING_STRUCT_SEL",
        "ASCENDC_TPL_ARGS_SEL",
        "ASCENDC_TPL_BOOL_DECL",
        "ASCENDC_TPL_UINT_DECL",
    }
)


def _is_false_lexical_callee(name: str, line: str, match_start: int) -> bool:
    """Reject regex hits that look like calls but are C++ / AscendC non-calls.

    AscendC relies on ``if constexpr``; that construct must stay in compile-time
    analysis (harness fold). Here we only suppress the lexical false positive
    where ``if constexpr (cond)`` is mistaken for a call named ``constexpr``.
    """
    if name in _CXX_CALL_SKIP:
        return True
    if name in {"constexpr", "consteval", "constinit"}:
        prefix = line[:match_start].rstrip()
        # ``if constexpr (`` / ``if consteval (`` — not a call.
        if re.search(r"\bif\s*$", prefix):
            return True
        # Bare ``constexpr (x);`` is ill-formed C++ and was only ever noise.
        if re.search(r"(^|[\s;{}])$", prefix) or not prefix:
            return True
        return False
    return False

_TPL_DSL_NAME_MARKERS = (
    "template_tiling_key.h",
    "tiling_key.h",
)


def _strip_line_noise(line: str) -> str:
    """Remove // comments and rough string/char literals before call scanning."""
    # License headers are sometimes emitted as bare ``Copyright (c) 2024``;
    # without this guard the generic call regex reports a callee named ``c``.
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


def _is_tpl_dsl_file(path: Path) -> bool:
    name = path.name.lower().replace("\\", "/")
    return any(marker in name for marker in _TPL_DSL_NAME_MARKERS)


def lexical_source_call_sites(
    files: list[Path],
    *,
    reachable: set[str],
    filter_strict: bool,
    root: str,
    deadline: float,
    primitives_only: bool = False,
) -> list[dict[str, Any]]:
    """Collect source-scope identifier call sites (Clang fallback).

    When ``primitives_only`` is True, only callees present in the AscendC
    semantics registry are kept.
    """
    registry_names: set[str] | None = None
    if primitives_only:
        try:
            # Prefer registry lookup table keys when available.
            names = set()
            lookup = getattr(semreg, "_TABLE", None) or getattr(semreg, "TABLE", None)
            if isinstance(lookup, dict):
                names.update(str(k) for k in lookup)
            if not names:
                from uo_init.semantics.ascendc_sync import SYNC_MECHANISM

                names.update(SYNC_MECHANISM)
            registry_names = names or None
        except Exception:  # noqa: BLE001
            registry_names = None

    sites: list[dict[str, Any]] = []
    for path in files:
        if time.perf_counter() > deadline:
            break
        if _is_tpl_dsl_file(path):
            continue
        try:
            text = read_text(path)
        except OSError:
            continue
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        func = ""
        for i, line in enumerate(text.splitlines(), start=1):
            if time.perf_counter() > deadline:
                break
            cleaned = _strip_line_noise(line)
            func = update_enclosing_func(cleaned, func)
            for m in _CALL_RE.finditer(cleaned):
                name = m.group("name")
                if not name or not name.isidentifier():
                    continue
                if _is_false_lexical_callee(name, cleaned, m.start()):
                    continue
                if registry_names is not None and name not in registry_names:
                    # Also accept names the classifier already knows.
                    try:
                        cat, _, conf = semreg.classify(name)
                        if cat == "UNKNOWN" or conf == "unresolved":
                            continue
                    except Exception:  # noqa: BLE001
                        continue
                if not caller_allowed(func, reachable, filter_strict=filter_strict):
                    continue
                rest = cleaned[m.end() :]
                depth = 1
                end = 0
                for j, ch in enumerate(rest):
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            end = j
                            break
                arg_text = rest[:end] if end else ""
                args = [a.strip() for a in _ARG_SPLIT_RE.split(arg_text) if a.strip()]
                targs = m.group("targs") or ""
                targs_list = [a.strip() for a in targs.split(",") if a.strip()] if targs else []
                sites.append(
                    {
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
                        "entry_reachable": caller_allowed(func, reachable, filter_strict=True)
                        if reachable
                        else True,
                    }
                )
    _ = root
    return sites


def lexical_primitive_sites(
    files: list[Path],
    *,
    reachable: set[str],
    filter_strict: bool,
    root: str,
    deadline: float,
) -> list[dict[str, Any]]:
    """Deprecated alias — prefer :func:`lexical_source_call_sites`."""
    return lexical_source_call_sites(
        files,
        reachable=reachable,
        filter_strict=filter_strict,
        root=root,
        deadline=deadline,
    )


def lexical_buffer_decls(
    files: list[Path],
    *,
    reachable: set[str],
    filter_strict: bool,
    deadline: float,
) -> list[dict[str, Any]]:
    decls: list[dict[str, Any]] = []
    func = ""
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            func = update_enclosing_func(line, func)
            if not caller_allowed(func, reachable, filter_strict=filter_strict):
                continue
            if not _STORAGE_TYPE_RE.search(line):
                continue
            for m in _DECL_RE.finditer(line):
                type_text = m.group("type")
                name = m.group("name")
                if not _STORAGE_TYPE_RE.search(type_text):
                    continue
                decls.append(
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
    return decls
