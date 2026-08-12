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


_CXX_CALL_SKIP = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "return",
        "sizeof",
        "alignof",
        "decltype",
        "static_assert",
        "sizeof...",
        "new",
        "delete",
        "catch",
    }
)


def lexical_source_call_sites(
    files: list[Path],
    *,
    reachable: set[str],
    filter_strict: bool,
    root: str,
    deadline: float,
) -> list[dict[str, Any]]:
    """Collect all source-scope identifier call sites (Clang fallback).

    Provenance is lexical; not filtered by AscendC registry primitives.
    """
    sites: list[dict[str, Any]] = []
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        func = ""
        for i, line in enumerate(text.splitlines(), start=1):
            if time.perf_counter() > deadline:
                break
            func = update_enclosing_func(line, func)
            for m in _CALL_RE.finditer(line):
                name = m.group("name")
                if not name or name in _CXX_CALL_SKIP or not name.isidentifier():
                    continue
                if not caller_allowed(func, reachable, filter_strict=filter_strict):
                    continue
                rest = line[m.end() :]
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
