# -*- coding: utf-8 -*-
"""Host field-sensitive SSA + function summaries (DoOpTiling derivation chain).

The clang backend is authoritative. `extract_writes_text` remains only as a
fallback for files that cannot be parsed: it is a single-line regex, so it
misses assignments spanning lines, cannot attribute a write to its enclosing
function, and has no path conditions to attach. Coverage must be computed on
the clang backend.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from uo_init.clang_walk import CallSite, PathCond, WriteRecord, walk_file



@dataclass
class WriteEvent:
    path: str
    line: int
    rhs: str
    template_precondition: str | None = None
    file: str = ""
    function: str = ""
    version: int = 0
    path_conditions: tuple[PathCond, ...] = ()

    @property
    def ssa_name(self) -> str:
        return f"{self.path}@{self.version}"

    def guards(self) -> list[str]:
        return [pc.pretty() for pc in self.path_conditions if not pc.is_opaque]


@dataclass
class FuncSummary:
    name: str
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    guards: list[str] = field(default_factory=list)
    locals: dict[str, str] = field(default_factory=dict)
    params: list[str] = field(default_factory=list)
    out_params: list[str] = field(default_factory=list)
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    returns: list[str] = field(default_factory=list)
    assigns: dict[str, str] = field(default_factory=dict)
    assign_lists: dict[str, list[str]] = field(default_factory=dict)


_IS_LITERAL = re.compile(r"^\s*(?:-?\d[\w.]*|true|false|nullptr|NULL)\s*$")
_BARE_SELF = re.compile(r"^[A-Za-z_]\w*$")


def _rhs_mentions(var: str, rhs: str) -> bool:
    return bool(re.search(rf"\b{re.escape(var)}\b", rhs or ""))


def _pick_primary_def(var: str, candidates: list[str]) -> str | None:
    """Prefer a definition that does not re-mention the variable (breaks p=p+q cycles)."""
    cleaned: list[str] = []
    for c in candidates:
        n = (c or "").strip()
        if n:
            cleaned.append(n)
    if not cleaned:
        return None
    independent = [c for c in cleaned if not _rhs_mentions(var, c)]
    pool = independent or cleaned
    nonlit = [c for c in pool if not _IS_LITERAL.match(c)]
    return (nonlit or pool)[0]


_TUPLE_CALL_RE = re.compile(
    r"^(?:std::)?(?:make_tuple|tie|forward_as_tuple)\((.*)\)$", re.DOTALL
)


def _split_top_level_args(inner: str) -> list[str]:
    args: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(inner):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            piece = inner[start:i].strip()
            if piece:
                args.append(piece)
            start = i + 1
    tail = inner[start:].strip()
    if tail:
        args.append(tail)
    return args


def _expand_tuple_actual(actual: str, caller_locals: dict[str, str]) -> str | None:
    """Rewrite `make_tuple(m, n)` using the caller's defining expressions for m/n."""
    t = (actual or "").strip()
    m = _TUPLE_CALL_RE.match(t)
    if not m or not caller_locals:
        return None
    prefix = t[: t.index("(")]
    parts: list[str] = []
    changed = False
    for arg in _split_top_level_args(m.group(1)):
        if arg in caller_locals and caller_locals[arg] != arg:
            parts.append(caller_locals[arg])
            changed = True
        else:
            parts.append(arg)
    if not changed:
        return None
    return f"{prefix}({', '.join(parts)})"


@dataclass
class HostIR:
    writes: list[WriteEvent] = field(default_factory=list)
    summaries: dict[str, FuncSummary] = field(default_factory=dict)
    backend: str = "text"
    class_fields: set[str] = field(default_factory=set)
    # Guarded assignments to plain locals, keyed nowhere: use local_writes_in().
    local_writes: list[WriteEvent] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)

    def paths(self) -> list[str]:
        return [w.path for w in self.writes]

    def calls_to(self, callee: str) -> list[CallSite]:
        """Every recorded call of `callee`, with the guards reaching each one.

        A function reached from exactly one unguarded call always runs; one
        reached only under `layoutType == TND` runs exactly then. Either is a
        condition on the input, where the alternative is a free boolean.
        """
        cached = getattr(self, "_calls_by_callee", None)
        if cached is None:
            cached = {}
            for site in self.call_sites:
                cached.setdefault(site.callee, []).append(site)
            self._calls_by_callee = cached
        return cached.get(callee, [])

    def local_writes_in(self, function: str) -> dict[str, list[WriteEvent]]:
        """local name -> its guarded assignments inside `function`."""
        cached = getattr(self, "_local_writes_by_fn", None)
        if cached is None:
            cached = {}
            for w in self.local_writes:
                cached.setdefault(w.function, {}).setdefault(w.path, []).append(w)
            self._local_writes_by_fn = cached
        return cached.get(function, {})

    def writes_to(self, needle: str) -> list[WriteEvent]:
        return [w for w in self.writes if needle in w.path]

    def latest_version(self, path: str) -> int:
        vs = [w.version for w in self.writes if w.path == path]
        return max(vs) if vs else -1

    def writes_by_tail(self) -> dict[str, list[WriteEvent]]:
        """Index writes by final field name for O(1) field-chase lookup."""
        cached = getattr(self, "_writes_by_tail", None)
        if cached is not None:
            return cached
        out: dict[str, list[WriteEvent]] = {}
        for w in self.writes:
            if not w.rhs.strip():
                continue
            tail = w.path.rsplit(".", 1)[-1]
            # strip residual subscripts just in case
            tail = re.sub(r"\[.*", "", tail)
            out.setdefault(tail, []).append(w)
        self._writes_by_tail = out
        return out

    def defs_by_function(self) -> dict[str, dict[str, list[str]]]:
        """Every known RHS for each local (declaration + all assignments)."""
        cached = getattr(self, "_defs_by_function", None)
        if cached is not None:
            return cached
        out: dict[str, dict[str, list[str]]] = {}
        for name, s in self.summaries.items():
            slot: dict[str, list[str]] = {}
            for var, init in s.locals.items():
                slot.setdefault(var, [])
                if init and init not in slot[var]:
                    slot[var].append(init)
            for var, hist in s.assign_lists.items():
                slot.setdefault(var, [])
                for rhs in hist:
                    if rhs and rhs not in slot[var]:
                        slot[var].append(rhs)
            for var, rhs in s.assigns.items():
                slot.setdefault(var, [])
                if rhs and rhs not in slot[var]:
                    slot[var].append(rhs)
            out[name] = slot
        self._defs_by_function = out
        return out

    def locals_by_function(self) -> dict[str, dict[str, str]]:
        """Name → primary defining expression inside each function.

        Prefers an assignment that does not re-mention the variable so
        `p = CeilDiv(...); p = p + q` still chases the CeilDiv root.
        """
        cached = getattr(self, "_locals_by_function", None)
        if cached is not None:
            return cached
        out: dict[str, dict[str, str]] = {}
        for name, defs in self.defs_by_function().items():
            picked: dict[str, str] = {}
            for var, candidates in defs.items():
                primary = _pick_primary_def(var, candidates)
                if primary:
                    picked[var] = primary
            out[name] = picked
        self._locals_by_function = out
        return out

    def params_by_function(self) -> dict[str, set[str]]:
        return {name: set(s.params) for name, s in self.summaries.items()}

    def param_bindings(self) -> dict[str, dict[str, list[str]]]:
        """callee -> parameter name -> actual argument sources seen at call sites.

        Same-name formals (`foo(inputLayout)` where the caller also has
        `inputLayout`) are expanded transitively through the caller's locals
        and, if needed, the caller's own parameter bindings.
        """
        cached = getattr(self, "_param_bindings", None)
        if cached is not None:
            return cached
        locals_map = self.locals_by_function()
        # raw edges first
        raw: dict[str, dict[str, list[str]]] = {}
        caller_of: dict[str, list[str]] = {}
        for caller in self.summaries.values():
            for callee, args in caller.calls:
                target = self.summaries.get(callee)
                if target is None or not target.params:
                    continue
                slot = raw.setdefault(callee, {})
                caller_of.setdefault(callee, [])
                if caller.name not in caller_of[callee]:
                    caller_of[callee].append(caller.name)
                for name, actual in zip(target.params, args):
                    if not actual:
                        continue
                    resolved = actual.lstrip("&").strip()
                    # Expand make_tuple/tie args through the caller's locals so
                    # `make_tuple(m, n)` becomes `make_tuple(<m's def>, ...)`
                    # and callee std::get / __tuple_elem can close without a
                    # same-name cycle back into the callee.
                    tup = _expand_tuple_actual(resolved, locals_map.get(caller.name, {}))
                    if tup:
                        resolved = tup
                    seen = slot.setdefault(name, [])
                    if resolved not in seen:
                        seen.append(resolved)

        def expand(callee: str, pname: str, actual: str, stack: frozenset[str]) -> list[str]:
            key = f"{callee}::{pname}::{actual}"
            if key in stack:
                return []
            actual = actual.lstrip("&").strip()
            if not actual:
                return []
            if actual != pname:
                # expression or other name — still try one hop through a
                # caller's local of that name when it is a bare identifier
                if re.fullmatch(r"[A-Za-z_]\w*", actual):
                    out: list[str] = []
                    for cname in caller_of.get(callee, ()):
                        loc = locals_map.get(cname, {}).get(actual)
                        if loc and loc != actual:
                            out.extend(expand(cname, actual, loc, stack | {key}))
                        cparams = self.summaries.get(cname)
                        if cparams and actual in cparams.params:
                            for a2 in raw.get(cname, {}).get(actual, []):
                                out.extend(expand(cname, actual, a2, stack | {key}))
                    if out:
                        return list(dict.fromkeys(out))
                return [actual]
            # actual == formal name: must climb to callers
            out = []
            for cname in caller_of.get(callee, ()):
                loc = locals_map.get(cname, {}).get(pname)
                if loc and loc != pname:
                    out.extend(expand(cname, pname, loc, stack | {key}))
                for a2 in raw.get(cname, {}).get(pname, []):
                    out.extend(expand(cname, pname, a2, stack | {key}))
            return list(dict.fromkeys(out))

        out: dict[str, dict[str, list[str]]] = {}
        for callee, slots in raw.items():
            for pname, actuals in slots.items():
                expanded: list[str] = []
                for a in actuals:
                    expanded.extend(expand(callee, pname, a, frozenset()))
                # drop pure self-refs that could not be expanded
                expanded = [e for e in expanded if e and e != pname]
                if expanded:
                    out.setdefault(callee, {})[pname] = list(dict.fromkeys(expanded))
                else:
                    out.setdefault(callee, {})[pname] = list(actuals)
        self._param_bindings = out
        return out

    def output_bindings_by_function(self) -> dict[str, dict[str, str]]:
        """caller -> local receiving an out-param write -> RHS inside the callee."""
        cached = getattr(self, "_output_bindings", None)
        if cached is not None:
            return cached
        out: dict[str, dict[str, str]] = {}
        for caller in self.summaries.values():
            slot: dict[str, str] = {}
            for callee, args in caller.calls:
                target = self.summaries.get(callee)
                if target is None or not target.out_params:
                    continue
                outs = set(target.out_params)
                for name, actual in zip(target.params, args):
                    if name not in outs or not actual:
                        continue
                    local = actual.lstrip("&").strip()
                    rhs = target.assigns.get(name)
                    if rhs and local:
                        slot[local] = rhs
            if slot:
                out[caller.name] = slot
        self._output_bindings = out
        return out


_ASSIGN = re.compile(
    r"(?P<lhs>(?:this\.)?fBaseParams\.\w+(?:\.\w+)*|(?:this\.)?\w+\.\w+(?:\.\w+)*)\s*=\s*(?P<rhs>[^;]+);"
)


def extract_writes_text(path: str | Path, template_precondition: str | None = None) -> list[WriteEvent]:
    """Fallback single-line regex scanner. Under-counts; never use for coverage."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    events: list[WriteEvent] = []
    for m in _ASSIGN.finditer(text):
        lhs = m.group("lhs")
        if lhs.count(".") < 1:
            continue
        line = text[: m.start()].count("\n") + 1
        events.append(
            WriteEvent(
                path=lhs,
                line=line,
                rhs=m.group("rhs").strip(),
                template_precondition=template_precondition,
                file=str(path).replace("\\", "/"),
            )
        )
    return _assign_ssa(events)


def _assign_ssa(events: list[WriteEvent]) -> list[WriteEvent]:
    """Version each field path in program order (file, line)."""
    ordered = sorted(events, key=lambda w: (w.file, w.line))
    counter: dict[str, int] = {}
    for w in ordered:
        v = counter.get(w.path, 0)
        w.version = v
        counter[w.path] = v + 1
    return ordered


def _to_event(rec: WriteRecord, template_precondition: str | None) -> WriteEvent:
    return WriteEvent(
        path=rec.path,
        line=rec.line,
        rhs=rec.rhs,
        template_precondition=template_precondition,
        file=rec.file,
        function=rec.function,
        path_conditions=rec.path_conditions,
    )


def extract_writes_clang(
    path: str | Path,
    ctx,
    *,
    template_precondition: str | None = None,
    side: str = "host",
    op_needle: str = "",
) -> list[WriteEvent]:
    res = walk_file(path, ctx, side=side, op_needle=op_needle)
    return _assign_ssa([_to_event(r, template_precondition) for r in res.writes])


def build_host_ir(
    paths: list[str | Path],
    *,
    ctx=None,
    template_precondition: str | None = None,
    side: str = "host",
    op_needle: str = "",
) -> HostIR:
    """Build the host IR. Uses clang when a BuildContext is supplied."""
    if ctx is None:
        writes: list[WriteEvent] = []
        for p in paths:
            writes.extend(extract_writes_text(p, template_precondition=template_precondition))
        return HostIR(
            writes=_assign_ssa(writes),
            summaries=_text_summaries(paths),
            backend="text",
        )

    all_writes: list[WriteEvent] = []
    all_local_writes: list[WriteEvent] = []
    all_calls: list[CallSite] = []
    seen_calls: set[tuple[str, str, str, int]] = set()
    summaries: dict[str, FuncSummary] = {}
    class_fields: set[str] = set()
    path_list = [Path(p) for p in paths]

    def _walk_one(p: Path):
        return walk_file(p, ctx, side=side, op_needle=op_needle)

    if len(path_list) <= 1:
        results = [_walk_one(p) for p in path_list]
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = [None] * len(path_list)
        with ThreadPoolExecutor(max_workers=min(4, len(path_list))) as pool:
            futs = {pool.submit(_walk_one, p): i for i, p in enumerate(path_list)}
            for fut in as_completed(futs):
                results[futs[fut]] = fut.result()

    for res in results:
        all_writes.extend(_to_event(r, template_precondition) for r in res.writes)
        all_local_writes.extend(
            _to_event(r, template_precondition) for r in res.local_writes
        )
        class_fields |= res.class_fields
        for site in getattr(res, "call_sites", ()) or ():
            # A header included by several TUs is walked once per TU, so the
            # same physical call arrives repeatedly.
            key = (site.caller, site.callee, site.file, site.line)
            if key not in seen_calls:
                seen_calls.add(key)
                all_calls.append(site)
        for name, fr in res.functions.items():
            s = summaries.setdefault(name, FuncSummary(name=name))
            for w in fr.writes:
                if w not in s.writes:
                    s.writes.append(w)
            for r in fr.reads:
                if r not in s.reads:
                    s.reads.append(r)
            for g in fr.guards:
                if g not in s.guards:
                    s.guards.append(g)
            for k, v in fr.locals.items():
                s.locals.setdefault(k, v)
            for prm in fr.params:
                if prm not in s.params:
                    s.params.append(prm)
            for prm in getattr(fr, "out_params", []) or []:
                if prm not in s.out_params:
                    s.out_params.append(prm)
            for c in fr.calls:
                if c not in s.calls:
                    s.calls.append(c)
            for r in fr.returns:
                if r not in s.returns:
                    s.returns.append(r)
            for k, v in fr.assigns.items():
                # last write across TUs wins (path order preserved by results[])
                s.assigns[k] = v
            for k, hist in getattr(fr, "assign_lists", {}).items():
                slot = s.assign_lists.setdefault(k, [])
                for rhs in hist:
                    if rhs and rhs not in slot:
                        slot.append(rhs)
    return HostIR(
        writes=_assign_ssa(all_writes),
        summaries=summaries,
        backend="clang",
        class_fields=class_fields,
        local_writes=_assign_ssa(all_local_writes),
        call_sites=all_calls,
    )


_FN_HEADER = re.compile(
    r"^[\w:<>,\*&\s]*?\b(?P<name>\w+)\s*\([^;{]*\)\s*(?:const\s*)?\{",
    re.MULTILINE,
)
_NOT_A_FUNCTION = {"if", "for", "while", "switch", "catch", "else", "return", "do"}


def _text_summaries(paths: list[str | Path]) -> dict[str, FuncSummary]:
    """Coarse fallback: attribute writes to the nearest preceding function header."""
    out: dict[str, FuncSummary] = {}
    for p in paths:
        text = Path(p).read_text(encoding="utf-8", errors="replace")
        for m in _FN_HEADER.finditer(text):
            name = m.group("name")
            if name in _NOT_A_FUNCTION:
                continue
            body = text[m.end() : m.end() + 4000]
            s = out.setdefault(name, FuncSummary(name=name))
            for wm in _ASSIGN.finditer(body):
                lhs = wm.group("lhs")
                if lhs.count(".") >= 1 and lhs not in s.writes:
                    s.writes.append(lhs)
    return out


def assert_no_flatten(writes: Iterable[WriteEvent]) -> None:
    for w in writes:
        if "." not in w.path:
            raise AssertionError(f"flattened field path: {w.path}")


def derivation_chain(ir: HostIR, field_needle: str) -> list[dict[str, Any]]:
    """Every write to a field, with its SSA version and guarding path conditions."""
    out = []
    for w in ir.writes_to(field_needle):
        out.append(
            {
                "ssa": w.ssa_name,
                "file": w.file,
                "line": w.line,
                "rhs": w.rhs,
                "guards": w.guards(),
                "function": w.function,
                "template": w.template_precondition,
            }
        )
    return out
