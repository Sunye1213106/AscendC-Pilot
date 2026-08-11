# -*- coding: utf-8 -*-
"""Materialize Kernel Execution IR into CodeMap (operations / buffers / sync).

Runs after Kernel call/TilingData closure so reachability is known. Prefers
cached Clang WalkResult call sites (already paid during kernel_ir walks). Falls
back to a bounded AscendC-primitive lexical scan — not a general call binder.

Hard budget: ``UO_KERNEL_EXEC_BUDGET_S`` (default 25s) so compile_codemap does
not regress beyond the requested ~30s envelope.
"""

from __future__ import annotations

import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from uo_init.ids import (
    buffer_site_id,
    buffer_view_id,
    exec_region_id,
    operation_site_id,
    register_site_id,
    rel_posix,
    sync_event_id,
)
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.kernel_execution import (
    Buffer,
    BufferView,
    ExecOperation,
    ExecRegion,
    KernelExecutionIR,
    Register,
    SyncEvent,
)
from uo_init.ir.relation import RelationKind
from uo_init.kernel_sync import pair_events
from uo_init.passes.kernel_exec_order import assign_exec_ranks
from uo_init.passes.source_text_cache import read_text
from uo_init.semantics import registry as semreg
from uo_init.semantics.ascendc_storage import (
    BUFFER_MEMORY_SPACES,
    is_non_storage_type,
    is_storage_type_text,
    is_valid_storage_name,
    memory_space_from_type_text,
    register_class_from_type,
    resolve_buffer_decl,
)
from uo_init.semantics.ascendc_sync import mutex_pipe_for, resolve_sync_site

_WALK_CACHE_LIMIT = 48

# AscendC buffer + MicroAPI/Reg types (CANN: namespace MicroAPI = Reg).
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
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:<(?P<targs>[^;{}()]{0,240})>)?\s*\(",
)
_ARG_SPLIT_RE = re.compile(r",(?![^()]*\))")
_METHOD_DEF_RE = re.compile(
    r"\b(?:[A-Za-z_]\w*(?:\s*<[^;{}()]{0,200}>)?\s*::\s*)+"
    r"(?P<name>[A-Za-z_~]\w*)\s*\("
)
_FUNC_DEF_RE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?\{?\s*$"
)


def _budget_s() -> float:
    raw = str(os.environ.get("UO_KERNEL_EXEC_BUDGET_S") or "25").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 25.0


def _enabled() -> bool:
    raw = str(os.environ.get("UO_KERNEL_EXEC") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _caller_allowed(caller: str, reachable: set[str], *, filter_strict: bool) -> bool:
    if not filter_strict or not reachable or not caller:
        return True
    short = caller.split("::")[-1]
    return caller in reachable or short in reachable


def _norm_file(path: str, root: str = "") -> str:
    text = str(path or "").replace("\\", "/")
    # WSL-style absolute paths from Clang → host drive for IDE jump.
    if text.startswith("/mnt/") and len(text) >= 7 and text[5].isalpha() and text[6] == "/":
        text = f"{text[5].upper()}:{text[6:]}"
    return rel_posix(text, root)


def _reachable_function_names(codemap: CodeMap) -> tuple[set[str], bool]:
    """Return (names, filter_strict).

    ``filter_strict`` is True only when the closure produced a rich reachable
    set beyond bare KERNEL entries — otherwise keep all primitives in selected
    kernel files and mark ``entry_reachable`` separately.
    """
    from collections import deque

    starts = {
        e.id
        for e in codemap.by_kind(EntityKind.KERNEL)
        if e.attrs.get("source_definition") or e.attrs.get("source_signature")
    }
    bound = {
        "source_kernel_call_bound",
        "source_kernel_macro_call_bound",
        "source_kernel_call_refined",
    }
    adj: dict[str, set[str]] = defaultdict(set)
    for rel in codemap.relations.values():
        if rel.kind_name() != RelationKind.CALLS.value:
            continue
        prov = str(rel.attrs.get("provenance") or "")
        if prov not in bound and not prov.startswith("source_kernel"):
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
    filter_strict = non_kernel >= 3
    return names, filter_strict


def _selected_kernel_files(codemap: CodeMap, source_root: Path) -> list[Path]:
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
    # Fallback: op_kernel/<arch>/**
    arch = codemap.architecture or "arch35"
    arch_dir = source_root / "op_kernel" / arch
    if arch_dir.is_dir():
        for p in sorted(arch_dir.rglob("*")):
            if p.suffix.lower() in {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"} and p.is_file():
                out.append(p)
    return out


def _guards_from_path_conditions(pcs: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for pc in pcs or ():
        text = getattr(pc, "text", None)
        if text is None and isinstance(pc, dict):
            text = pc.get("text")
            neg = bool(pc.get("negated"))
        else:
            neg = bool(getattr(pc, "negated", False))
        text = str(text or "").strip()
        if not text:
            continue
        out.append(f"!({text})" if neg else text)
    return out


def _infer_memory_space(type_text: str, name: str = "") -> str:
    """Prefer CANN/AscendC type & position template args; names are fallback only."""
    from_type = memory_space_from_type_text(type_text)
    if from_type:
        return from_type
    t = f"{type_text} {name}".lower()
    n = str(name or "").lower()
    # TPipe is not a data buffer — mark so callers can drop it.
    if "tpipe" in t or n in {"tpipe", "pipe"} or n.startswith("pipe"):
        return "PIPE"
    if "globaltensor" in t or "__gm__" in t:
        return "GM"
    if n.endswith("gm") or "gmtensor" in n or n.endswith("gm_"):
        return "GM"
    if "workspace" in t or "workspace" in n or n.endswith("ws"):
        return "WORKSPACE"
    if "localtensor" in t or "tbuf" in t:
        return "UB"
    if n.endswith("ub") or "ubuf" in n:
        return "UB"
    if "l0a" in t or "l0a" in n:
        return "L0A"
    if "l0b" in t or "l0b" in n:
        return "L0B"
    if "l0c" in t or "l0c" in n:
        return "L0C"
    if "l1" in t or "l1" in n:
        return "L1"
    if "tque" in t or "queue" in t or n.endswith("que") or "queue" in n:
        return "QUEUE"
    return "UNKNOWN"


def _buffer_kind(type_text: str) -> str:
    resolved = resolve_buffer_decl(type_text)
    if resolved:
        return str(resolved["kind"])
    t = type_text
    for name in ("LocalTensor", "GlobalTensor", "TBuf", "TQue", "TPipe", "MutexBuffer"):
        if name in t:
            return name
    return "Buffer"


def _attach_storage_wrapper_root(
    ir: KernelExecutionIR,
    wrapper: Buffer,
    *,
    type_text: str,
    root: str,
    provenance: str,
) -> None:
    """Wrapper BUFFER views a synthetic CANN LocalTensor/GlobalTensor storage root.

    Root identity is structural (``{name}#storage``), not a source member name.
    Materialize links ``wrapper —VIEW_OF→ root`` via ``backing``.
    """
    resolved = resolve_buffer_decl(type_text)
    if not resolved or not resolved.get("is_wrapper"):
        return
    root_kind = str(resolved.get("storage_root_kind") or "LocalTensor")
    space = str(resolved.get("memory_space") or wrapper.memory_space or "UNKNOWN")
    root_name = f"{wrapper.name}#storage"
    rid = buffer_site_id(
        file=wrapper.file,
        line=wrapper.line,
        scope=wrapper.scope,
        name=root_name,
        root=root,
    )
    storage = Buffer(
        id=rid,
        name=root_name,
        kind=root_kind,
        memory_space=space,
        scope=wrapper.scope,
        file=wrapper.file,
        line=wrapper.line,
        role="cann_storage_root",
        provenance=provenance,
        confidence=wrapper.confidence,
    )
    ir.buffers.append(storage)
    wrapper.backing = rid
    wrapper.role = "storage_wrapper"


def _is_data_buffer(type_text: str, name: str, memory_space: str) -> bool:
    """Exclude TPipe / control objects from BUFFER entities."""
    if memory_space == "PIPE":
        return False
    kind = _buffer_kind(type_text)
    if kind == "TPipe":
        return False
    n = str(name or "").lower()
    if n in {"tpipe", "pipe"} or (n.startswith("pipe") and "tensor" not in n and "que" not in n):
        return False
    return True


def _site_dedupe_key(site: Any, *, root: str = "") -> tuple[str, int, str]:
    d = site if isinstance(site, dict) else None
    if d is None:
        file = str(getattr(site, "file", "") or "")
        line = int(getattr(site, "line", 0) or 0)
        callee = str(getattr(site, "callee", "") or "").split("::")[-1]
    else:
        file = str(d.get("file") or "")
        line = int(d.get("line") or 0)
        callee = str(d.get("callee") or "").split("::")[-1]
    return (_norm_file(file, root), line, callee)


def _site_as_dict(site: Any) -> dict[str, Any]:
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
    """Higher when template args carry CANN HardEvent / PIPE tokens."""
    joined = " ".join(str(t) for t in (targs or []))
    score = 0
    if "HardEvent" in joined or any(
        ev in joined for ev in ("MTE2_", "MTE1_", "MTE3_", "PIPE_", "_MTE", "_FIX", "V_S", "S_V", "V_V")
    ):
        score += 2
    if "PIPE_" in joined:
        score += 2
    if joined.strip():
        score += 1
    return score


def _enrich_site_templates(dst: Any, src: dict[str, Any]) -> Any:
    """Fill / upgrade template_args/args from lexical when Clang omitted or stripped them.

    Returns the (possibly replaced) site object.
    """
    src_t = list(src.get("template_args") or [])
    src_a = list(src.get("args") or [])
    if isinstance(dst, dict):
        cur_t = list(dst.get("template_args") or [])
        if _targs_quality(src_t) > _targs_quality(cur_t):
            dst["template_args"] = src_t
        if (not dst.get("args")) and src_a:
            dst["args"] = src_a
        if not dst.get("receiver") and src.get("receiver"):
            dst["receiver"] = src["receiver"]
        return dst
    d = _site_as_dict(dst)
    cur_t = list(d.get("template_args") or [])
    if _targs_quality(src_t) > _targs_quality(cur_t):
        d["template_args"] = src_t
    if (not d.get("args")) and src_a:
        d["args"] = src_a
    if not d.get("receiver") and src.get("receiver"):
        d["receiver"] = src["receiver"]
    if d.get("template_args") or d.get("args"):
        return d
    return dst


def _merge_lexical_sites(
    walk_calls: list[Any],
    lexical: list[dict[str, Any]],
    *,
    root: str,
) -> tuple[list[Any], int]:
    """Prefer Clang sites; add lexical AscendC primitives missing from walks.

    When Clang already recorded a site but dropped template args (common for
    ``SetFlag<HardEvent::…>`` / ``CrossCore* <mode, PIPE_*>``), enrich in place
    from the lexical twin so CANN sync engines can resolve.
    """
    index: dict[tuple[str, int, str], int] = {}
    out: list[Any] = list(walk_calls)
    for i, s in enumerate(out):
        index[_site_dedupe_key(s, root=root)] = i
    added = 0
    for site in lexical:
        key = _site_dedupe_key(site, root=root)
        if key in index:
            i = index[key]
            out[i] = _enrich_site_templates(out[i], site)
            continue
        index[key] = len(out)
        out.append(site)
        added += 1
    return out, added


def _collect_call_sites_from_walks(
    source_root: Path,
    *,
    architecture: str,
    reachable: set[str],
    filter_strict: bool,
    deadline: float,
) -> tuple[list[Any], list[Any], list[Any], str]:
    """Return (call_sites, local_decls, controls, provenance)."""
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
            if not _caller_allowed(caller, reachable, filter_strict=filter_strict):
                continue
            if not semreg.is_execution_primitive(callee):
                continue
            calls.append(site)
        decls.extend(getattr(wr, "local_decls", None) or [])
        controls.extend(getattr(wr, "controls", None) or [])
    provenance = "clang_walk_cache"
    if len(walks) >= _WALK_CACHE_LIMIT:
        provenance = "clang_walk_cache_partial"
    return calls, decls, controls, provenance


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


def _lexical_primitive_sites(
    files: list[Path],
    *,
    reachable: set[str],
    filter_strict: bool,
    root: str,
    deadline: float,
) -> list[dict[str, Any]]:
    """Bounded AscendC-primitive scan when Clang walk cache is empty."""
    primitives = set(semreg.load_registry())
    sites: list[dict[str, Any]] = []
    for path in files:
        if time.perf_counter() > deadline:
            break
        try:
            text = read_text(path)
        except OSError:
            continue
        func = ""
        lines = text.splitlines()
        for i, line in enumerate(lines, start=1):
            if time.perf_counter() > deadline:
                break
            func = _update_enclosing_func(line, func)
            for m in _CALL_RE.finditer(line):
                name = m.group("name")
                if name not in primitives:
                    continue
                if not _caller_allowed(func, reachable, filter_strict=filter_strict):
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
                        "entry_reachable": _caller_allowed(
                            func, reachable, filter_strict=True
                        )
                        if reachable
                        else True,
                    }
                )
    _ = root
    return sites


def _sync_kind_and_pipe(callee: str, args: list[str], targs: list[str]) -> dict[str, Any]:
    """CANN-aligned sync site fields (HardEvent / pipe / mutex / IB / cross-core)."""
    return resolve_sync_site(callee, args=args, targs=targs)


def _build_ir_from_sites(
    *,
    call_sites: list[Any],
    local_decls: list[Any],
    controls: list[Any],
    root: str,
    provenance: str,
) -> KernelExecutionIR:
    ir = KernelExecutionIR(registry_version=semreg.REGISTRY_VERSION, notes=[f"source={provenance}"])
    ordinals: dict[tuple[str, int, int, str], int] = {}
    ops_by_func: dict[str, list[ExecOperation]] = defaultdict(list)
    buffer_by_key: dict[tuple[str, str], Buffer] = {}
    register_by_key: dict[tuple[str, str], Register] = {}

    # Storage decls: AscendC buffers vs MicroAPI/Reg registers (CANN catalog).
    for decl in local_decls or []:
        if isinstance(decl, dict):
            type_text = str(decl.get("type_text") or "")
            name = str(decl.get("name") or "")
            function = str(decl.get("function") or "")
            file = str(decl.get("file") or "")
            line = int(decl.get("line") or 0)
            init = decl.get("init")
        else:
            type_text = str(getattr(decl, "type_text", "") or "")
            name = str(getattr(decl, "name", "") or "")
            function = str(getattr(decl, "function", "") or "")
            file = str(getattr(decl, "file", "") or "")
            line = int(getattr(decl, "line", 0) or 0)
            init = getattr(decl, "init", None)
        if not name or not is_valid_storage_name(name):
            continue
        if not (_STORAGE_TYPE_RE.search(type_text) or is_storage_type_text(type_text)):
            continue
        if is_non_storage_type(type_text):
            continue
        reg_class = register_class_from_type(type_text)
        if reg_class:
            rid = register_site_id(file=file, line=line, scope=function, name=name, root=root)
            reg = Register(
                id=rid,
                name=name,
                register_class=reg_class,
                type_text=type_text.strip(),
                scope=function,
                file=_norm_file(file, root),
                line=line,
                provenance=provenance,
                confidence="confirmed" if provenance.startswith("clang") else "partial",
            )
            ir.registers.append(reg)
            register_by_key[(function, name)] = reg
            continue
        mem = _infer_memory_space(type_text, name)
        if not _is_data_buffer(type_text, name, mem):
            continue
        resolved = resolve_buffer_decl(type_text)
        if resolved and resolved.get("memory_space") and resolved["memory_space"] != "UNKNOWN":
            mem = str(resolved["memory_space"])
        bid = buffer_site_id(file=file, line=line, scope=function, name=name, root=root)
        buf = Buffer(
            id=bid,
            name=name,
            kind=_buffer_kind(type_text),
            memory_space=mem,
            size_expr=str(init or ""),
            scope=function,
            file=_norm_file(file, root),
            line=line,
            role=str(resolved.get("role") or "") if resolved else "",
            provenance=provenance,
            confidence="confirmed" if provenance.startswith("clang") else "partial",
        )
        ir.buffers.append(buf)
        buffer_by_key[(function, name)] = buf
        if resolved and resolved.get("is_wrapper"):
            _attach_storage_wrapper_root(
                ir, buf, type_text=type_text, root=root, provenance=provenance
            )

    # Function regions.
    region_by_func: dict[str, ExecRegion] = {}
    for site in call_sites:
        d = _site_as_dict(site)
        func = str(d.get("caller") or "")
        if not func or func in region_by_func:
            continue
        rid = exec_region_id(kind="Function", file=str(d.get("file") or ""), line=int(d.get("line") or 0), function=func, root=root)
        region = ExecRegion(
            id=rid,
            kind="Function",
            name=func,
            function=func,
            file=_norm_file(str(d.get("file") or ""), root),
            line=int(d.get("line") or 0),
            provenance=provenance,
            confidence="confirmed" if provenance.startswith("clang") else "partial",
        )
        region_by_func[func] = region
        ir.regions.append(region)

    # Loop regions from controls.
    for ctrl in controls or []:
        kind = str(getattr(ctrl, "kind", None) or (ctrl.get("kind") if isinstance(ctrl, dict) else "") or "")
        if kind not in {"for", "while", "do"}:
            continue
        function = str(getattr(ctrl, "function", None) or (ctrl.get("function") if isinstance(ctrl, dict) else "") or "")
        file = str(getattr(ctrl, "file", None) or (ctrl.get("file") if isinstance(ctrl, dict) else "") or "")
        line = int(getattr(ctrl, "line", None) or (ctrl.get("line") if isinstance(ctrl, dict) else 0) or 0)
        rid = exec_region_id(kind="Loop", file=file, line=line, function=function, root=root)
        ir.regions.append(
            ExecRegion(
                id=rid,
                kind="Loop",
                name=f"loop@{line}",
                function=function,
                file=_norm_file(file, root),
                line=line,
                provenance=provenance,
                confidence="confirmed" if provenance.startswith("clang") else "partial",
            )
        )

    # Operations.
    for site in call_sites:
        d = _site_as_dict(site)
        callee = str(d.get("callee") or "").split("::")[-1]
        file = str(d.get("file") or "")
        line = int(d.get("line") or 0)
        column = int(d.get("column") or 0)
        okey = (_norm_file(file, root), line, column, callee)
        ordinal = ordinals.get(okey, 0)
        ordinals[okey] = ordinal + 1
        category, engine, conf = semreg.classify(callee)
        args = [str(a) for a in (d.get("args") or [])]
        targs = [str(a) for a in (d.get("template_args") or [])]
        receiver = str(d.get("receiver") or "")
        reads, writes = semreg.arg_effects(callee, args, receiver=receiver)
        guards = _guards_from_path_conditions(d.get("path_conditions") or ())
        oid = operation_site_id(
            file=file, line=line, column=column, callee=callee, ordinal=ordinal, root=root
        )
        entry_reachable = bool(d.get("entry_reachable", True))
        op = ExecOperation(
            id=oid,
            callee=callee,
            category=category,
            engine=engine,
            function=str(d.get("caller") or ""),
            file=_norm_file(file, root),
            line=line,
            column=column,
            ordinal=ordinal,
            args=args,
            receiver=receiver,
            guards=guards,
            reads=reads,
            writes=writes,
            provenance=provenance,
            confidence=conf if provenance.startswith("clang") else "partial",
            registry_version=semreg.REGISTRY_VERSION,
        )
        # Stash reachability for CodeMap attrs.
        op_extra_reach = entry_reachable
        ir.operations.append(op)
        ops_by_func[op.function].append(op)
        # Keep a side map for materialize.
        if not hasattr(ir, "_reach"):
            ir._reach = {}  # type: ignore[attr-defined]
        ir._reach[oid] = op_extra_reach  # type: ignore[attr-defined]

        # InitBuffer(queue, depth, size) → queue_depth / double-buffer hint.
        # Prefer args[0] as the queue identity; receiver is usually TPipe*.
        if callee == "InitBuffer":
            queue_name = ""
            depth_val: int | None = None
            if args:
                queue_name = str(args[0]).split("[", 1)[0].strip()
                # Drop this-> / pipe. prefixes already handled by arg text; strip -> remnants.
                if "->" in queue_name:
                    queue_name = queue_name.split("->")[-1]
                if "." in queue_name:
                    queue_name = queue_name.split(".")[-1]
                if len(args) >= 2:
                    try:
                        depth_val = int(str(args[1]).strip())
                    except ValueError:
                        depth_val = None
            if not queue_name:
                queue_name = receiver
            if queue_name and _is_data_buffer("TQue", queue_name, "QUEUE"):
                qkey = (op.function, queue_name)
                if qkey not in buffer_by_key:
                    qid = buffer_site_id(
                        file=file, line=line, scope=op.function, name=queue_name, root=root
                    )
                    qbuf = Buffer(
                        id=qid,
                        name=queue_name,
                        kind="TQue",
                        memory_space="QUEUE",
                        scope=op.function,
                        file=op.file,
                        line=line,
                        queue_depth=depth_val,
                        provenance=provenance,
                        confidence="partial",
                    )
                    ir.buffers.append(qbuf)
                    buffer_by_key[qkey] = qbuf
                elif depth_val is not None:
                    buffer_by_key[qkey].queue_depth = depth_val
                    buffer_by_key[qkey].memory_space = "QUEUE"
                    if not buffer_by_key[qkey].kind:
                        buffer_by_key[qkey].kind = "TQue"

        # Sync events from sync_* categories.
        # Only resolve engines from Clang/lexical template args + CANN catalog.
        # If HardEvent/PIPE cannot be resolved, leave UNKNOWN and mark as gap later.
        if category.startswith("sync_"):
            sync_info = _sync_kind_and_pipe(callee, args, targs)
            # Mutex LockProd/Cons: pipe from receiver memory_space when already known.
            if (
                str(sync_info.get("mechanism") or "") == "mutex"
                and not sync_info.get("pipe")
                and receiver
            ):
                rbuf = buffer_by_key.get((op.function, receiver))
                space = rbuf.memory_space if rbuf else ""
                if (not space or space == "UNKNOWN") and rbuf and rbuf.backing:
                    root_buf = next((b for b in ir.buffers if b.id == rbuf.backing), None)
                    if root_buf:
                        space = root_buf.memory_space
                mpipe = mutex_pipe_for(callee, space)
                if mpipe:
                    sync_info = dict(sync_info)
                    sync_info["pipe"] = mpipe
                    eng = resolve_sync_site(callee, args=args, targs=[mpipe])
                    sync_info["src_engine"] = eng.get("src_engine") or sync_info.get("src_engine")
                    sync_info["dst_engine"] = eng.get("dst_engine") or sync_info.get("dst_engine")
                    sync_info["engine"] = eng.get("engine") or sync_info.get("engine")
            skind = str(sync_info.get("kind") or callee)
            resolved_eng = str(sync_info.get("engine") or "")
            if resolved_eng and resolved_eng != "UNKNOWN":
                op.engine = resolved_eng
            elif engine == "UNKNOWN" and str(sync_info.get("mechanism") or "") == "barrier" and callee == "SyncAll":
                op.engine = "ALL"
            sid = sync_event_id(
                file=file, line=line, column=column, kind=skind, ordinal=ordinal, root=root
            )
            src_e = str(sync_info.get("src_engine") or "")
            dst_e = str(sync_info.get("dst_engine") or "")
            engine_gap = (
                skind != "BARRIER"
                and src_e in {"", "UNKNOWN"}
                and dst_e in {"", "UNKNOWN"}
                and str(op.engine or "UNKNOWN") == "UNKNOWN"
            )
            ir.sync_events.append(
                SyncEvent(
                    id=sid,
                    kind=skind,
                    file=op.file,
                    line=line,
                    column=column,
                    function=op.function,
                    flag=str(sync_info.get("flag") or ""),
                    pipe=str(sync_info.get("pipe") or ""),
                    event=str(sync_info.get("event") or ""),
                    cross_core=bool(sync_info.get("cross_core")),
                    mechanism=str(sync_info.get("mechanism") or ""),
                    src_engine=src_e,
                    dst_engine=dst_e,
                    guards=list(guards),
                    operation_id=oid,
                    provenance=provenance,
                    confidence="partial" if engine_gap else op.confidence,
                )
            )

        # Queue-backed views: AllocTensor / DeQue / Get on receiver.
        if category in {"buffer_acquire", "queue_dequeue", "buffer_view"} and receiver:
            # Ensure backing queue buffer exists.
            qkey = (op.function, receiver)
            if qkey not in buffer_by_key:
                qid = buffer_site_id(
                    file=file, line=line, scope=op.function, name=receiver, root=root
                )
                qbuf = Buffer(
                    id=qid,
                    name=receiver,
                    kind="TQue",
                    memory_space="QUEUE",
                    scope=op.function,
                    file=op.file,
                    line=line,
                    provenance=provenance,
                    confidence="partial",
                )
                ir.buffers.append(qbuf)
                buffer_by_key[qkey] = qbuf
            # Named result rarely available from call site; use synthetic view name.
            view_name = writes[0] if writes else f"{receiver}.{callee}"
            vid = buffer_view_id(
                buffer_id=buffer_by_key[qkey].id,
                name=view_name,
                file=file,
                line=line,
                root=root,
            )
            ir.buffer_views.append(
                BufferView(
                    id=vid,
                    name=view_name,
                    of_buffer=buffer_by_key[qkey].id,
                    file=op.file,
                    line=line,
                    provenance=provenance,
                    confidence="partial",
                )
            )

        # Bind referenced storage names: prefer declared REGISTER / BUFFER.
        # Do not invent UNKNOWN buffers for expressions or undeclared identifiers
        # without AscendC memory evidence (GM/UB/L1/...).
        for bname in list(reads) + list(writes):
            if not is_valid_storage_name(bname):
                continue
            key = (op.function, bname)
            if key in register_by_key or key in buffer_by_key:
                continue
            mem = _infer_memory_space("", bname)
            if mem not in BUFFER_MEMORY_SPACES:
                continue
            if not _is_data_buffer("", bname, mem):
                continue
            bid = buffer_site_id(
                file=file, line=line, scope=op.function, name=bname, root=root
            )
            buf = Buffer(
                id=bid,
                name=bname,
                kind="Buffer",
                memory_space=mem,
                scope=op.function,
                file=op.file,
                line=line,
                provenance=provenance,
                confidence="partial",
            )
            ir.buffers.append(buf)
            buffer_by_key[key] = buf

    # Program order within each function.
    for func, ops in ops_by_func.items():
        ops.sort(key=lambda o: (o.file, o.line, o.column, o.ordinal))
        _ = func

    ir.operations.sort(key=lambda o: (o.file, o.line, o.column, o.ordinal))
    return ir


def _dedupe_by_id(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        iid = str(getattr(item, "id", "") or "")
        if not iid or iid in seen:
            continue
        seen.add(iid)
        out.append(item)
    return out


def _materialize(codemap: CodeMap, ir: KernelExecutionIR, *, root: str) -> dict[str, Any]:
    """Write KernelExecutionIR into CodeMap entities/relations."""
    # Collapse duplicate site ids from clang+lexical overlay.
    ir.buffers = _dedupe_by_id(ir.buffers)
    ir.registers = _dedupe_by_id(ir.registers)
    ir.sync_events = _dedupe_by_id(ir.sync_events)
    ir.operations = _dedupe_by_id(ir.operations)
    ir.buffer_views = _dedupe_by_id(ir.buffer_views)

    # Purge previous execution entities from this pass.
    drop_kinds = {
        EntityKind.OPERATION.value,
        EntityKind.BUFFER.value,
        EntityKind.BUFFER_VIEW.value,
        EntityKind.REGISTER.value,
        EntityKind.SYNC_EVENT.value,
        EntityKind.EXEC_REGION.value,
    }
    drop_ids = {e.id for e in codemap.entities.values() if e.kind_name() in drop_kinds}
    for eid in drop_ids:
        codemap.entities.pop(eid, None)
    drop_rel_kinds = {
        RelationKind.CONTAINS.value,
        RelationKind.PRECEDES.value,
        RelationKind.READS_BUFFER.value,
        RelationKind.WRITES_BUFFER.value,
        RelationKind.READS_REGISTER.value,
        RelationKind.WRITES_REGISTER.value,
        RelationKind.VIEW_OF.value,
        RelationKind.ALIASES.value,
        RelationKind.ALLOCATES.value,
        RelationKind.RELEASES.value,
        RelationKind.SIGNALS.value,
        RelationKind.WAITS_ON.value,
        RelationKind.SYNCHRONIZES_WITH.value,
        RelationKind.HAPPENS_BEFORE.value,
        RelationKind.EXECUTES_ON.value,
        RelationKind.EMITS_SYNC.value,
        RelationKind.DATA_DEPENDS_ON.value,
    }
    for rid, rel in list(codemap.relations.items()):
        if rel.kind_name() in drop_rel_kinds or rel.src in drop_ids or rel.dst in drop_ids:
            codemap.relations.pop(rid, None)

    # Global execution order from Kernel entry call expand (not file/line sort).
    summaries, order_meta = assign_exec_ranks(codemap, ir.operations, ir.sync_events)
    ir.function_summaries = summaries
    if int(order_meta.get("unreached_appended") or 0) > 0:
        ir.notes.append("exec_order_unreached_appended")

    region_ents: dict[str, str] = {}
    for region in ir.regions:
        ent = codemap.upsert(
            EntityKind.EXEC_REGION,
            region.name or region.kind,
            eid=region.id,
            attrs=region.to_dict(),
            file=region.file,
            line=region.line,
            status="extracted",
            confidence=1.0 if region.confidence == "confirmed" else 0.6,
        )
        region_ents[region.function or region.name] = ent.id

    gaps: list[dict[str, Any]] = []

    buffer_ents: dict[str, str] = {}
    buffer_by_name_scope: dict[tuple[str, str], str] = {}
    for buf in ir.buffers:
        attrs = buf.to_dict()
        mem_gap = str(buf.memory_space or "UNKNOWN") == "UNKNOWN"
        if mem_gap:
            attrs["gap_code"] = "buffer_memory_space_unresolved"
            attrs["resolution_blocker"] = "missing_buffertype_or_tposition_from_clang"
            attrs["reason"] = (
                f"buffer kind={buf.kind or 'Buffer'} role={buf.role or '-'}: "
                "BufferType/TPosition/QuePosition not available from decl type text"
            )
            gaps.append(
                {
                    "code": "buffer_memory_space_unresolved",
                    "entity_id": buf.id,
                    "kind": buf.kind,
                    "role": buf.role,
                    "name": buf.name,
                    "file": buf.file,
                    "line": buf.line,
                }
            )
        ent = codemap.upsert(
            EntityKind.BUFFER,
            buf.name,
            eid=buf.id,
            attrs=attrs,
            file=buf.file,
            line=buf.line,
            status="partial" if mem_gap else "extracted",
            confidence=0.4 if mem_gap else (1.0 if buf.confidence == "confirmed" else 0.6),
        )
        buffer_ents[buf.id] = ent.id
        buffer_by_name_scope[(buf.scope, buf.name)] = ent.id

    # Wrapper → CANN storage root (structural, independent of member names).
    for buf in ir.buffers:
        if not buf.backing:
            continue
        src = buffer_ents.get(buf.id)
        dst = buffer_ents.get(buf.backing)
        if src and dst:
            codemap.link(
                RelationKind.VIEW_OF,
                src,
                dst,
                attrs={
                    "provenance": "ascendc_storage_wrapper",
                    "role": "storage_wrapper",
                },
                status="confirmed",
            )

    register_ents: dict[str, str] = {}
    register_by_name_scope: dict[tuple[str, str], str] = {}
    for reg in ir.registers:
        ent = codemap.upsert(
            EntityKind.REGISTER,
            reg.name,
            eid=reg.id,
            attrs=reg.to_dict(),
            file=reg.file,
            line=reg.line,
            status="extracted",
            confidence=1.0 if reg.confidence == "confirmed" else 0.6,
        )
        register_ents[reg.id] = ent.id
        register_by_name_scope[(reg.scope, reg.name)] = ent.id

    for view in ir.buffer_views:
        ent = codemap.upsert(
            EntityKind.BUFFER_VIEW,
            view.name,
            eid=view.id,
            attrs=view.to_dict(),
            file=view.file,
            line=view.line,
            status="extracted",
            confidence=0.6,
        )
        if view.of_buffer in buffer_ents:
            codemap.link(
                RelationKind.VIEW_OF,
                ent.id,
                buffer_ents[view.of_buffer],
                attrs={"provenance": "kernel_execution"},
                status="confirmed",
            )

    op_ents: list[tuple[ExecOperation, str]] = []
    for op in ir.operations:
        attrs = op.to_dict()
        reach = getattr(ir, "_reach", {}).get(op.id, True)
        attrs["entry_reachable"] = bool(reach)
        ent = codemap.upsert(
            EntityKind.OPERATION,
            op.callee,
            eid=op.id,
            attrs=attrs,
            file=op.file,
            line=op.line,
            status="extracted",
            confidence=1.0 if op.confidence == "confirmed" else 0.6,
        )
        op_ents.append((op, ent.id))
        # CONTAINS: region → operation
        rid = region_ents.get(op.function)
        if rid:
            codemap.link(
                RelationKind.CONTAINS,
                rid,
                ent.id,
                attrs={"provenance": "kernel_execution"},
                status="confirmed",
            )
        # Buffer / register effects
        for name in op.reads:
            bid = buffer_by_name_scope.get((op.function, name))
            if bid:
                codemap.link(
                    RelationKind.READS_BUFFER,
                    ent.id,
                    bid,
                    attrs={"provenance": "kernel_execution", "name": name},
                    status="confirmed" if op.confidence == "confirmed" else "partial",
                )
            rid = register_by_name_scope.get((op.function, name))
            if rid:
                codemap.link(
                    RelationKind.READS_REGISTER,
                    ent.id,
                    rid,
                    attrs={"provenance": "kernel_execution", "name": name},
                    status="confirmed" if op.confidence == "confirmed" else "partial",
                )
        for name in op.writes:
            bid = buffer_by_name_scope.get((op.function, name))
            if bid:
                codemap.link(
                    RelationKind.WRITES_BUFFER,
                    ent.id,
                    bid,
                    attrs={"provenance": "kernel_execution", "name": name},
                    status="confirmed" if op.confidence == "confirmed" else "partial",
                )
            rid = register_by_name_scope.get((op.function, name))
            if rid:
                codemap.link(
                    RelationKind.WRITES_REGISTER,
                    ent.id,
                    rid,
                    attrs={"provenance": "kernel_execution", "name": name},
                    status="confirmed" if op.confidence == "confirmed" else "partial",
                )
        # Alloc / release
        if op.category == "buffer_acquire" and op.receiver:
            bid = buffer_by_name_scope.get((op.function, op.receiver))
            if bid:
                codemap.link(
                    RelationKind.ALLOCATES,
                    ent.id,
                    bid,
                    attrs={"provenance": "kernel_execution"},
                    status="partial",
                )
        if op.category == "buffer_release":
            for name in op.writes or op.args[:1]:
                bid = buffer_by_name_scope.get((op.function, str(name).split("[", 1)[0]))
                if bid:
                    codemap.link(
                        RelationKind.RELEASES,
                        ent.id,
                        bid,
                        attrs={"provenance": "kernel_execution"},
                        status="partial",
                    )

    # PRECEDES within function by exec_rank (falls back to local site order).
    by_func: dict[str, list[tuple[ExecOperation, str]]] = defaultdict(list)
    for op, eid in op_ents:
        by_func[op.function].append((op, eid))
    for _func, rows in by_func.items():
        rows.sort(
            key=lambda t: (
                int(t[0].exec_rank) if int(t[0].exec_rank) >= 0 else 10**9,
                int(t[0].line),
                int(t[0].column),
                int(t[0].ordinal),
            )
        )
        for (a_op, a), (b_op, b) in zip(rows, rows[1:]):
            codemap.link(
                RelationKind.PRECEDES,
                a,
                b,
                attrs={
                    "provenance": "kernel_execution",
                    "kind": "program_order",
                    "exec_rank_a": int(a_op.exec_rank),
                    "exec_rank_b": int(b_op.exec_rank),
                },
                status="confirmed",
            )

    # Sync entities + EMITS_SYNC + pairing → SIGNALS / WAITS_ON / SYNCHRONIZES_WITH / HAPPENS_BEFORE
    sync_ents: dict[str, SyncEvent] = {}
    emits_sync = 0

    def _sync_needs_engine_gap(sev: SyncEvent) -> bool:
        """True when CANN HardEvent/PIPE could not be resolved from available templates."""
        if str(sev.src_engine or "UNKNOWN") != "UNKNOWN" or str(sev.dst_engine or "UNKNOWN") != "UNKNOWN":
            return False
        # SyncAll()-style: barrier without pipe/flag/event — not an engine-resolution gap.
        if sev.kind == "BARRIER" and not sev.pipe and not sev.flag and not sev.event:
            return False
        return True

    for sev in ir.sync_events:
        attrs = sev.to_dict()
        mark_gap = _sync_needs_engine_gap(sev)
        if mark_gap:
            attrs["gap_code"] = "sync_engine_unresolved"
            attrs["resolution_blocker"] = "missing_hard_event_or_pipe_from_clang"
            attrs["reason"] = (
                f"CANN sync {sev.kind}/{sev.mechanism or 'unknown'}: "
                "HardEvent/PIPE not available from Clang/lexical templates"
            )
            gaps.append(
                {
                    "code": "sync_engine_unresolved",
                    "entity_id": sev.id,
                    "kind": sev.kind,
                    "mechanism": sev.mechanism,
                    "file": sev.file,
                    "line": sev.line,
                    "function": sev.function,
                }
            )
        ent = codemap.upsert(
            EntityKind.SYNC_EVENT,
            sev.kind,
            eid=sev.id,
            attrs=attrs,
            file=sev.file,
            line=sev.line,
            status="partial" if mark_gap else "extracted",
            confidence=0.4 if mark_gap else (1.0 if sev.confidence == "confirmed" else 0.6),
        )
        sync_ents[sev.id] = sev
        if sev.operation_id and sev.operation_id in codemap.entities:
            codemap.link(
                RelationKind.EMITS_SYNC,
                sev.operation_id,
                sev.id,
                attrs={"provenance": "kernel_execution"},
                status="confirmed",
            )
            emits_sync += 1
        _ = ent

    pair_input = [s.to_dict() for s in ir.sync_events]
    pairs = pair_events(pair_input)
    paired = 0
    unresolved = 0
    ambiguous = 0
    for row in pairs:
        status = row.get("status")
        wait = row.get("wait") or {}
        producer = row.get("producer")
        pair_conf = str(row.get("confidence") or "confirmed")
        edge_status = "confirmed" if pair_conf == "confirmed" else "partial"
        if status == "PAIRED" and producer:
            paired += 1
            wait_id = str(wait.get("id") or "")
            prod_id = str(producer.get("id") or "")
            if wait_id and prod_id:
                codemap.link(
                    RelationKind.SIGNALS,
                    prod_id,
                    wait_id,
                    attrs={"provenance": "kernel_sync_pairing", "confidence": pair_conf},
                    status=edge_status,
                    confidence=1.0 if pair_conf == "confirmed" else 0.6,
                )
                codemap.link(
                    RelationKind.WAITS_ON,
                    wait_id,
                    prod_id,
                    attrs={"provenance": "kernel_sync_pairing", "confidence": pair_conf},
                    status=edge_status,
                    confidence=1.0 if pair_conf == "confirmed" else 0.6,
                )
                codemap.link(
                    RelationKind.SYNCHRONIZES_WITH,
                    prod_id,
                    wait_id,
                    attrs={"provenance": "kernel_sync_pairing", "confidence": pair_conf},
                    status=edge_status,
                    confidence=1.0 if pair_conf == "confirmed" else 0.6,
                )
                p_op = str(producer.get("operation_id") or "")
                w_op = str(wait.get("operation_id") or "")
                if p_op and w_op and p_op in codemap.entities and w_op in codemap.entities:
                    codemap.link(
                        RelationKind.HAPPENS_BEFORE,
                        p_op,
                        w_op,
                        attrs={
                            "provenance": "kernel_sync_pairing",
                            "via": "SetFlag/WaitFlag",
                            "confidence": pair_conf,
                        },
                        status=edge_status,
                        confidence=1.0 if pair_conf == "confirmed" else 0.6,
                    )
        elif status == "UNRESOLVED_SYNC_PAIRING":
            unresolved += 1
        elif status == "MULTIPLE_PAIR_CANDIDATES":
            ambiguous += 1

    # Buffer lifecycle summary (exec_rank ordered).
    lifecycle = _compute_buffer_lifecycles(codemap, ir)

    ranked = sum(1 for o in ir.operations if int(o.exec_rank) >= 0)
    gap_counts = dict(Counter(str(g.get("code") or "") for g in gaps))
    stats = {
        "operations": len(ir.operations),
        "buffers": len(ir.buffers),
        "registers": len(ir.registers),
        "buffer_views": len(ir.buffer_views),
        "sync_events": len(ir.sync_events),
        "regions": len(ir.regions),
        "function_summaries": len(ir.function_summaries),
        "ops_ranked": ranked,
        "sync_paired": paired,
        "sync_unresolved": unresolved,
        "sync_ambiguous": ambiguous,
        "emits_sync": emits_sync,
        "buffer_lifecycles": len(lifecycle),
        "gaps": gaps,
        "gap_count": len(gaps),
        "gap_counts": gap_counts,
        "exec_order": order_meta,
        "provenance": ir.notes[0] if ir.notes else "",
        "registry_version": ir.registry_version,
        "quality": {
            "ops": len(ir.operations),
            "buffers": len(ir.buffers),
            "registers": len(ir.registers),
            "sync_events": len(ir.sync_events),
            "ops_ranked": ranked,
            "emits_sync": emits_sync,
            "sync_paired": paired,
            "buffer_lifecycles": len(lifecycle),
            "gap_count": len(gaps),
            "gap_counts": gap_counts,
            "walk_partial": "partial" in str(ir.notes) or "partial" in (ir.notes[0] if ir.notes else ""),
        },
    }
    if any("partial" in str(n) for n in ir.notes) or "partial" in str(
        getattr(ir, "registry_version", "")
    ):
        stats["status"] = "partial"
    # Walk-cache truncation is recorded in provenance string.
    if "partial" in str(stats.get("provenance") or ""):
        stats["status"] = "partial"
        stats["quality"]["walk_partial"] = True
    codemap.meta["kernel_execution"] = stats
    codemap.meta["kernel_buffer_lifecycle"] = lifecycle
    codemap.meta["kernel_function_exec"] = [s.to_dict() for s in ir.function_summaries]
    _ = root
    return stats


def _compute_buffer_lifecycles(codemap: CodeMap, ir: KernelExecutionIR) -> dict[str, Any]:
    """Derive acquire / first_write / last_use / release per (scope, buffer_id)."""
    out: dict[str, Any] = {}
    ops = sorted(
        ir.operations,
        key=lambda o: (
            int(o.exec_rank) if int(o.exec_rank) >= 0 else 10**9,
            int(o.line),
            int(o.column),
            int(o.ordinal),
        ),
    )
    by_buf: dict[tuple[str, str], dict[str, Any]] = {}
    for buf in ir.buffers:
        slots = int(buf.queue_depth) if buf.queue_depth is not None else None
        capable = None
        if slots is not None:
            capable = "confirmed" if slots >= 2 else "no"
        by_buf[(buf.scope, buf.id)] = {
            "buffer": buf.name,
            "buffer_id": buf.id,
            "memory": buf.memory_space,
            "scope": buf.scope,
            "owner": buf.backing or "",
            "queue_depth": buf.queue_depth,
            "buffer_slots": slots,
            "double_buffer_capable": capable,
            # Stronger "double_buffer=confirmed" is no longer claimed from queue_depth alone.
            "overlap_usage": "partial" if capable == "confirmed" else ("no" if capable == "no" else None),
            "acquire": None,
            "first_write": None,
            "last_read": None,
            "last_use": None,
            "release": None,
            "accesses": [],
            "confidence": buf.confidence,
        }
    name_index: dict[tuple[str, str], str] = {
        (buf.scope, buf.name): buf.id for buf in ir.buffers
    }

    def _row(function: str, name: str) -> dict[str, Any] | None:
        bid = name_index.get((function, name))
        if not bid:
            return None
        return by_buf.get((function, bid))

    for op in ops:
        for name in op.writes:
            row = _row(op.function, name)
            if not row:
                continue
            site = {
                "op": op.id,
                "callee": op.callee,
                "line": op.line,
                "exec_rank": int(op.exec_rank),
                "role": "write",
            }
            row["accesses"].append(site)
            if row["first_write"] is None:
                row["first_write"] = site
            row["last_use"] = site
            if op.category == "buffer_acquire":
                row["acquire"] = site
            if op.category == "buffer_release":
                row["release"] = site
        for name in op.reads:
            row = _row(op.function, name)
            if not row:
                continue
            site = {
                "op": op.id,
                "callee": op.callee,
                "line": op.line,
                "exec_rank": int(op.exec_rank),
                "role": "read",
            }
            row["accesses"].append(site)
            row["last_read"] = site
            row["last_use"] = site
        if op.category == "buffer_acquire" and op.receiver:
            row = _row(op.function, op.receiver)
            if row and row["acquire"] is None:
                row["acquire"] = {
                    "op": op.id,
                    "callee": op.callee,
                    "line": op.line,
                    "exec_rank": int(op.exec_rank),
                    "role": "acquire",
                }
        if op.category == "buffer_release":
            for name in list(op.writes) or [a.split("[", 1)[0] for a in op.args[:1]]:
                row = _row(op.function, str(name))
                if row:
                    row["release"] = {
                        "op": op.id,
                        "callee": op.callee,
                        "line": op.line,
                        "exec_rank": int(op.exec_rank),
                        "role": "release",
                    }
        if op.category == "buffer_init" and op.callee == "InitBuffer":
            qname = op.receiver or (op.args[0].split("[", 1)[0] if op.args else "")
            row = _row(op.function, qname)
            if row and row["double_buffer_capable"] is None and row.get("queue_depth"):
                slots = int(row["queue_depth"])
                row["buffer_slots"] = slots
                row["double_buffer_capable"] = "confirmed" if slots >= 2 else "no"
                row["overlap_usage"] = "partial" if slots >= 2 else "no"

    for key, row in by_buf.items():
        if not row["accesses"] and row["acquire"] is None and row["queue_depth"] is None:
            continue
        # queue_depth alone is only capability evidence; require acquire+release for confirmed overlap.
        if row.get("double_buffer_capable") == "confirmed":
            if row.get("acquire") and row.get("release") and len(row.get("accesses") or []) >= 2:
                row["overlap_usage"] = "confirmed"
            else:
                row["overlap_usage"] = "partial"
                row["confidence"] = "partial"
        out[f"{key[0]}::{row['buffer']}"] = row
    _ = codemap
    return out


def finalize_kernel_execution(
    codemap: CodeMap,
    source_root: Path | str,
    *,
    architecture: str = "arch35",
) -> CodeMap:
    """Build KernelExecutionIR and materialize it into the CodeMap."""
    if not _enabled():
        codemap.meta["kernel_execution"] = {"skipped": True, "reason": "UO_KERNEL_EXEC=0"}
        return codemap
    t0 = time.perf_counter()
    deadline = t0 + _budget_s()
    root = str(Path(source_root).expanduser().resolve())
    arch = (architecture or codemap.architecture or "arch35").strip()
    reachable, filter_strict = _reachable_function_names(codemap)
    files = _selected_kernel_files(codemap, Path(root))

    calls, decls, controls, provenance = _collect_call_sites_from_walks(
        Path(root),
        architecture=arch,
        reachable=reachable,
        filter_strict=filter_strict,
        deadline=deadline,
    )
    # Always lexical-supplement selected kernel files: Clang walks miss many
    # method-style AscendC sites (InitBuffer/AllocTensor/EnQue) and template
    # DataCopy in cube/vec headers. Prefer walk sites on conflict.
    lexical_added = 0
    if files and time.perf_counter() < deadline:
        lexical = _lexical_primitive_sites(
            files,
            reachable=reachable,
            # Extract all primitives in selected files; reachability is stamped
            # per-site via entry_reachable.
            filter_strict=False,
            root=root,
            deadline=deadline,
        )
        if lexical:
            if not calls:
                calls = lexical
                provenance = "lexical_ascendc_primitives"
            else:
                calls, lexical_added = _merge_lexical_sites(calls, lexical, root=root)
                if lexical_added:
                    provenance = f"{provenance}+lexical_supplement"
            lex_decls = _lexical_buffer_decls(
                files,
                reachable=reachable,
                filter_strict=False,
                deadline=deadline,
            )
            if lex_decls:
                # Prefer existing decls; append unseen (file,line,name).
                seen_decl = {
                    (
                        _norm_file(str(d.get("file") if isinstance(d, dict) else getattr(d, "file", "")), root),
                        int((d.get("line") if isinstance(d, dict) else getattr(d, "line", 0)) or 0),
                        str((d.get("name") if isinstance(d, dict) else getattr(d, "name", "")) or ""),
                    )
                    for d in (decls or [])
                    if isinstance(d, (dict,)) or hasattr(d, "name")
                }
                for d in lex_decls:
                    key = (
                        _norm_file(str(d.get("file") or ""), root),
                        int(d.get("line") or 0),
                        str(d.get("name") or ""),
                    )
                    if key in seen_decl:
                        continue
                    seen_decl.add(key)
                    decls.append(d)

    ir = _build_ir_from_sites(
        call_sites=calls,
        local_decls=decls,
        controls=controls,
        root=root,
        provenance=provenance,
    )
    if lexical_added:
        ir.notes.append(f"lexical_supplement_added={lexical_added}")
    if "partial" in provenance:
        ir.notes.append("walk_cache_limit_partial")
    if time.perf_counter() > deadline:
        ir.notes.append("budget_exhausted")
    stats = _materialize(codemap, ir, root=root)
    stats["elapsed_s"] = round(time.perf_counter() - t0, 3)
    stats["budget_s"] = _budget_s()
    stats["reachable_functions"] = len(reachable)
    stats["filter_strict"] = filter_strict
    stats["selected_files"] = len(files)
    stats["lexical_supplement_added"] = lexical_added
    codemap.meta["kernel_execution"] = stats
    return codemap


def _lexical_buffer_decls(
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
            func = _update_enclosing_func(line, func)
            if not _caller_allowed(func, reachable, filter_strict=filter_strict):
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
