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

from uo_init.clang_walk import (
    CallSite,
    CtrlNode,
    FieldDecl,
    PathCond,
    WriteRecord,
    walk_file,
)



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
    #: See `WriteRecord.kind`. `append` and `shrink` mean the RHS is not the
    #: destination's new value, so a consumer chasing a value must skip them.
    kind: str = "assign"
    #: See `WriteRecord.column`. Needed to order this write against a read on
    #: the same line.
    column: int = 0

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
    #: container path → elements appended to it. Kept out of `assigns` because
    #: an element is not the container's value; see `FuncRecord.appends`.
    appends: dict[str, list[str]] = field(default_factory=dict)


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


def _deref_actual(actual: str) -> str:
    """`&this->fBaseParams` and `fBaseParams` name the same thing here."""
    t = (actual or "").strip().lstrip("&*").strip()
    for prefix in ("this->", "this."):
        if t.startswith(prefix):
            t = t[len(prefix) :]
    return t


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
    #: The control statements themselves. A `PathCond` on a write says which
    #: guards were on the way there; these say what the statement *was* — a
    #: loop's induction variables in particular, which a path condition cannot
    #: carry. Needed to summarise a loop rather than give up at its body.
    controls: list[CtrlNode] = field(default_factory=list)
    #: (declaring struct, member) -> declaration. Read through `field_decl()`.
    field_decls: dict[tuple[str, str], FieldDecl] = field(default_factory=dict)

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

    def field_decl(self, path: str) -> FieldDecl | None:
        """The declaration of the member `path` names, if it can be identified.

        The table is keyed on (struct, member), but a write path names a
        *variable* — `this.fBaseParams.isNzOut` — not the struct. So the member
        name has to identify the declaration on its own: when two structs
        declare it there is no way to tell which is meant, and the answer is
        None. That is the safe direction. The generated tiling-data structs
        declare many of these same names `= 0`, and guessing would turn "cannot
        prove" into "proved to be zero".
        """
        cached = getattr(self, "_decls_by_member", None)
        if cached is None:
            cached = {}
            for (_, name), decl in self.field_decls.items():
                cached.setdefault(name, []).append(decl)
            self._decls_by_member = cached
        found = cached.get((path or "").rsplit(".", 1)[-1], ())
        return found[0] if len(found) == 1 else None

    def loop_at(self, file: str, line: int) -> CtrlNode | None:
        """The loop statement a `PathCond` of loop kind came from.

        A loop guard on a write carries the file and line of its header, which
        is how a write inside a loop is matched back to the loop's induction
        variables and condition. Nested loops start on different lines, so the
        pair identifies one statement; a one-line `for (…) for (…)` would not be
        told apart, and this returns the first.
        """
        cached = getattr(self, "_loops_by_site", None)
        if cached is None:
            cached = {}
            for n in self.controls:
                if n.kind in ("for", "while", "do", "cxx_for_range"):
                    cached.setdefault((n.file, n.line), n)
            self._loops_by_site = cached
        return cached.get((file, line))

    def container_events(self, container: str, function: str) -> list[WriteEvent]:
        """Every recorded change to `container` inside `function`, in program order.

        Deliberately not built on `writes_by_tail()` or `defs_by_function()`:
        both drop events with an empty RHS, and `clear()` / `pop_back()` are
        exactly those. A rule asking "was a `push_back` the last change before
        this read" would then be blind to the one kind of event that makes the
        answer no.

        Matched on the container's own name, so a local `slicePrefix1` and a
        member `deterPrefixData.prefix1` are told apart, while `prefix1` still
        finds the member's events.
        """
        cached = getattr(self, "_container_events", None)
        if cached is None:
            cached = {}
            for w in list(self.writes) + list(self.local_writes):
                tail = re.sub(r"\[.*", "", w.path.rsplit(".", 1)[-1])
                cached.setdefault((tail, w.function), []).append(w)
            for evs in cached.values():
                evs.sort(key=lambda w: (w.file, w.line, w.column))
            self._container_events = cached
        tail = re.sub(r"\[.*", "", (container or "").rsplit(".", 1)[-1])
        return cached.get((tail, function), [])

    def sole_member_read(
        self, function: str, receiver: str, callee: str
    ) -> CallSite | None:
        """The one `receiver.callee()` call in `function`, if there is exactly one.

        The expression IR carries no source position, so a `back()` node cannot
        say which of several reads it is. When the function holds only one such
        read the position is unambiguous without it; when it holds more, there
        is no way to tell, and the answer is None rather than a guess. That is
        the safe direction: the caller falls back to an over-approximation
        instead of pinning a value to the wrong read.
        """
        cached = getattr(self, "_member_reads", None)
        if cached is None:
            cached = {}
            for s in self.call_sites:
                recv = re.sub(r"\[.*", "", (s.receiver or "").rsplit(".", 1)[-1])
                if recv:
                    cached.setdefault((s.caller, recv, s.callee), []).append(s)
            self._member_reads = cached
        tail = re.sub(r"\[.*", "", (receiver or "").rsplit(".", 1)[-1])
        found = cached.get((function, tail, callee), ())
        return found[0] if len(found) == 1 else None

    def container_writers(self, path: str) -> set[str]:
        """Functions that write `path`, counting `push_back` as a write.

        Asked in order to decide whether one variable may stand for `back(v)`
        at every read point. That holds only while the container holds still,
        and program order across functions cannot be recovered from this IR:
        writes carry a line, reads do not. So a container written in more than
        one function has to be treated as changing between reads.
        """
        cached = getattr(self, "_container_writers", None)
        if cached is None:
            cached = {}
            for w in list(self.writes) + list(self.local_writes):
                tail = re.sub(r"\[.*", "", w.path.rsplit(".", 1)[-1])
                cached.setdefault(tail, set()).add(w.function)
            self._container_writers = cached
        tail = re.sub(r"\[.*", "", (path or "").rsplit(".", 1)[-1])
        return set(cached.get(tail, ()))

    def aggregate_heads(self) -> set[str]:
        """Symbols whose *fields* the host writes — the tiling state aggregates.

        A structural stand-in for a name list. `fBaseParams` and
        `deterPrefixData` qualify because host code fills their members, and
        that is what makes a value read back out of them tiling-derived rather
        than an input. An input accessor never qualifies: nothing assigns to
        `context->GetInputShape(0)->GetStorageShape().dim`.

        Spelling the aggregates by name instead — `Params|TilingData|PrefixData`
        — silently misclassifies any operator that named its own differently.
        """
        cached = getattr(self, "_aggregate_heads", None)
        if cached is None:
            cached = set()
            for w in list(self.writes) + list(self.local_writes):
                parts = w.path.split(".")
                if len(parts) < 2:
                    continue
                cached.add(parts[0])
                # `this.fBaseParams.b` names the aggregate one level in.
                if parts[0] == "this" and len(parts) > 2:
                    cached.add(parts[1])
            cached.discard("this")
            self._aggregate_heads = cached
        return cached

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

    def param_bound_member(self, fn: str, param: str) -> str | None:
        """The `this` member every caller passes for `param`, if they all agree.

        A free function taking `FuzzyBaseInfoParamsRegbase& fBaseParams` records
        its writes as `fBaseParams.splitAxis` — named after the parameter, not
        after the object. Those writes define `this.fBaseParams.splitAxis` only
        when no caller can pass anything else, so a single disagreeing call site,
        or an argument that is not a member of the enclosing class, gives `None`.
        """
        cached = getattr(self, "_param_binding", None)
        if cached is None:
            cached = {}
            self._param_binding = cached
        key = (fn, param)
        if key in cached:
            return cached[key]
        cached[key] = None  # break recursion through a self-call
        summary = self.summaries.get(fn)
        if not summary or param not in summary.params:
            return None
        idx = summary.params.index(param)
        seen: set[str] = set()
        for caller in self.summaries.values():
            for callee, args in caller.calls:
                if callee == fn and idx < len(args):
                    seen.add(_deref_actual(args[idx]))
        result = None
        if len(seen) == 1:
            only = next(iter(seen))
            if only in self.class_fields:
                result = only
        cached[key] = result
        return result

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
    """Version each field path in program order (file, line, column).

    Two writes to one path on the same line used to get an arbitrary relative
    version. `prefix0.push_back(x)` beside a `prefix0` read is exactly that
    case, and any rule asking "what was the last change before this read"
    needs the tie broken the way the source breaks it.
    """
    ordered = sorted(events, key=lambda w: (w.file, w.line, w.column))
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
        kind=rec.kind,
        column=rec.column,
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
    all_controls: list[CtrlNode] = []
    all_field_decls: dict[tuple[str, str], FieldDecl] = {}
    seen_calls: set[tuple[str, str, str, int, int, str]] = set()
    seen_controls: set[tuple[str, int, int, str]] = set()
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
        # A header is walked once per TU including it, so the same declaration
        # arrives repeatedly; they agree, so the first one stands.
        for key, decl in (getattr(res, "field_decls", None) or {}).items():
            all_field_decls.setdefault(key, decl)
        for site in getattr(res, "call_sites", ()) or ():
            # A header included by several TUs is walked once per TU, so the
            # same physical call arrives repeatedly. Position has to include the
            # column, and identity the receiver: `syncRounds.size() +
            # syncRoundRanges.size()` agrees on caller, callee, file and line,
            # and dropping either half loses a container's only read.
            key = (
                site.caller,
                site.callee,
                site.file,
                site.line,
                getattr(site, "column", 0),
                getattr(site, "receiver", ""),
            )
            if key not in seen_calls:
                seen_calls.add(key)
                all_calls.append(site)
        for node in getattr(res, "controls", ()) or ():
            # Deduplicated on position rather than `id`: the ordinal in an id is
            # assigned in walk order, and the TUs are walked in parallel.
            ckey = (node.file, node.line, node.column, node.kind)
            if ckey not in seen_controls:
                seen_controls.add(ckey)
                all_controls.append(node)
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
            for k, hist in getattr(fr, "appends", {}).items():
                slot = s.appends.setdefault(k, [])
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
        controls=all_controls,
        field_decls=all_field_decls,
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
