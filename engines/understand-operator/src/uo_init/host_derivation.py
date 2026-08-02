# -*- coding: utf-8 -*-
"""Key-field derivation as a first-class KB artifact.

`KeyFieldDeriver` expands every TilingKey dimension down to input roots. That
result used to live only in a debug probe, so the contract layer had nothing to
reason with: per-key reachability fell back to a pair of hand-written
invariants, and TG had no key derivations to bind against.

This module runs the derivation for a whole operator and turns it into
`ir/host_derivation.yaml`. Two consumers depend on it:

- `materialize_tiling` compiles the 19 `value_expr` trees into one solver
  context, so cross-dimension conflicts fall out of the shared root variables
  instead of being enumerated by hand.
- `gaps` escalates the guards that could not be reduced, which is exactly the
  set of questions source analysis cannot answer on its own.

Every field derives in its own process. One runaway expansion must not be able
to stall or crash the rest of the run, and a field that times out is recorded
as `unresolved` rather than failing the export.
"""
from __future__ import annotations

import multiprocessing as mp
import pickle
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uo_init.derive_key_fields import (
    EX_CONSTANT,
    EX_EXACT,
    EX_UNRESOLVED,
    LOOPELEM_PREFIX,
    decode_expr_dag,
    encode_expr_dag,
)
from uo_init.ids import hash12
from uo_init.kb_model import classify_input_closure, input_closure_is_drivable

DERIVATION_VERSION = 1

# How a guard that survived normalization failure should be treated. The split
# is deterministic: it comes from the reason code and the guard text, never
# from a per-operator table.
PRESORT_SCHEDULING = "scheduling"
PRESORT_PLATFORM = "platform"
PRESORT_REACHABILITY = "reachability"
PRESORT_UNMAPPED = "unmapped"
PRESORT_LOOP_ELEMENT = "loop_element"
PRESORT_UNKNOWN = "unknown"

PRESORTS = (
    PRESORT_SCHEDULING,
    PRESORT_PLATFORM,
    PRESORT_REACHABILITY,
    PRESORT_UNMAPPED,
    PRESORT_LOOP_ELEMENT,
    PRESORT_UNKNOWN,
)

# Guards that must not become LLM work, for opposite reasons.
#
# Scheduling guards are softened on purpose: a branch on traversal position is
# taken on some iteration whatever the input, so pinning it would wrongly rule
# keys out. Nothing to ask.
#
# Reachability guards ("did control reach the function that wrote this") are a
# gap in our own call-graph analysis. A model guessing at them would be
# guessing at something the source states outright, so they are tracked as
# unclosed — they still count as over-approximations — and fixed by analysis.
#
# Loop-element guards used to be excluded from this set, on the theory that a
# quantified statement about a container is a judgement call. Reading the source
# disproved it: all six surviving loop elements in FAG are computed from the
# operator's own inputs — `invalidS1Array[j]` is interval coverage over sparse
# bands, `parseInfo[i][LENGTH_IDX]` is a prefix sum, `size(syncRounds)` is a
# filtered count. Nothing is unknown; what is missing is the ability to *reason*
# about aggregation, and a model asked "is this input-derived?" would answer yes
# without that making the expression any more solvable. So they are tracked as
# over-approximations until the summaries land (P2).
NON_ESCALATING = frozenset(
    {PRESORT_SCHEDULING, PRESORT_REACHABILITY, PRESORT_LOOP_ELEMENT}
)

# Platform quantities are locked by the CANN profile (K5). One still showing up
# undecided means the fold missed it, which is a real gap.
_PLATFORM_RE = re.compile(
    r"PlatformAscendC|GetPlatformInfo|GetCoreNumAic|GetCoreNumAiv|GetCoreNum|GetL2Size",
    re.I,
)

_UNMAPPED_REASONS = frozenset(
    {"UNMAPPED_SYMBOL", "UNMAPPED_CALL", "UNMAPPED_LEAF", "FUNCTION_PARAMETER"}
)

# Keep the pipe (and the YAML) bounded; the full tree stays in `value_expr`.
EXPANDED_KEEP = 20000
TEXT_KEEP = 400

DEFAULT_TIMEOUT = 180
DEFAULT_HELPER_GUARDS = 4


def short(value: str) -> str:
    """`DtypeEnum::FLOAT32` -> `FLOAT32`."""
    return str(value).split("::")[-1]


# -- guard identity and pre-sort -------------------------------------------
def guard_id(var_id: str) -> str:
    """`VAR_UNDECIDED_<h>` / `VAR_SCHED_<h>` -> `UG_<h>`.

    Reusing the normalizer's digest keeps the guard, its free boolean and the
    blocker that reports it on one identity instead of three.
    """
    tail = str(var_id).rsplit("_", 1)[-1]
    return f"UG_{tail}" if tail else f"UG_{hash12(var_id)}"


def split_reason(detail: str) -> tuple[str, str]:
    """`"UNMAPPED_SYMBOL: foo"` -> `("UNMAPPED_SYMBOL", "foo")`."""
    text = str(detail or "")
    head, sep, tail = text.partition(":")
    if sep and head and " " not in head.strip():
        return head.strip(), tail.strip()
    return "UNKNOWN", text.strip()


def presort_guard(var_id: str, detail: str) -> str:
    """Deterministic bucket for one softened guard."""
    if str(var_id).startswith("VAR_REACHED_"):
        return PRESORT_REACHABILITY
    if str(var_id).startswith("VAR_SCHED_"):
        return PRESORT_SCHEDULING
    if str(var_id).startswith(LOOPELEM_PREFIX):
        return PRESORT_LOOP_ELEMENT
    reason, text = split_reason(detail)
    if reason == "REACHED_SOFT":
        return PRESORT_REACHABILITY
    if reason == "SCHED_SOFT":
        return PRESORT_SCHEDULING
    if reason == "LOOP_ELEMENT":
        return PRESORT_LOOP_ELEMENT
    if _PLATFORM_RE.search(text):
        return PRESORT_PLATFORM
    if reason in _UNMAPPED_REASONS:
        return PRESORT_UNMAPPED
    return PRESORT_UNKNOWN


# -- evidence --------------------------------------------------------------
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_IDENT_STOP = frozenset(
    {
        "static_cast", "const_cast", "reinterpret_cast", "dynamic_cast",
        "int", "bool", "float", "double", "size_t", "uint8_t", "uint16_t",
        "uint32_t", "uint64_t", "int8_t", "int16_t", "int32_t", "int64_t",
        "true", "false", "Unknown", "and", "not", "ite",
    }
)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        t for t in _IDENT_RE.findall(str(text or "")) if t not in _IDENT_STOP
    )


class GuardEvidenceIndex:
    """Map a softened guard back to a source location.

    The undecided text is the *expanded* form, so it cannot be matched to the
    original guard literally. What can be asked instead is which recorded path
    conditions appear *inside* it, so the score is how much of the source
    guard the expansion covers — not how similar the two texts are overall.

    Symmetric similarity was the wrong question: an expanded guard is a
    conjunction of many source guards, so every individual one scores low
    against it, and short unrelated conditions score as well as the real
    source. That is how `platformInfoPtr == nullptr` came to be cited, at
    0.25, as the origin of a guard about `coreIdx` — a location that sent a
    reader to an unrelated function. A wrong line is worse than no line.

    An expanded guard has no single origin, so `also` reports how many other
    source guards are in there with it.
    """

    #: How much of a source guard must appear in the expansion. Below 1.0
    #: because normalisation rewrites some tokens (`nullptr` -> `None`).
    MIN_COVERAGE = 0.75

    def __init__(self, host_ir: Any) -> None:
        self._rows: list[tuple[frozenset[str], str, int, str, str]] = []
        seen: set[tuple[str, int, str]] = set()
        writes = list(getattr(host_ir, "writes", []) or [])
        writes += list(getattr(host_ir, "local_writes", []) or [])
        for w in writes:
            for cond in getattr(w, "path_conditions", ()) or ():
                text = getattr(cond, "text", "") or ""
                cfile = getattr(cond, "file", "") or getattr(w, "file", "") or ""
                cline = int(getattr(cond, "line", 0) or 0)
                if not text or not cfile:
                    continue
                key = (cfile, cline, text)
                if key in seen:
                    continue
                seen.add(key)
                toks = _tokens(text)
                if toks:
                    self._rows.append(
                        (toks, cfile, cline, text, getattr(w, "function", "") or "")
                    )

    def best(self, text: str, scope: str = "") -> dict[str, Any] | None:
        """Where this guard came from, optionally confined to one function.

        Without `scope` the answer is whichever source guard shares the most
        tokens, and identically-worded guards in two functions are
        indistinguishable — that is how both `invalidS1Array[j]` variables came
        to cite the normal-path line, sending a reader to the wrong coordinate
        domain. When a scope is known and it has no match, the answer is None
        rather than a line from some other function: a wrong line is worse than
        no line.
        """
        toks = _tokens(text)
        if not toks or not self._rows:
            return None
        found: list[tuple[int, float, str, int, str]] = []
        for row_toks, cfile, cline, raw, fn in self._rows:
            if scope and fn and fn != scope:
                continue
            covered = len(toks & row_toks) / len(row_toks)
            if covered < self.MIN_COVERAGE:
                continue
            # Longest first: where several source guards are present, the most
            # specific one is the most useful place to start reading.
            found.append((len(row_toks), covered, cfile, cline, raw))
        if not found:
            return None
        found.sort(key=lambda r: (r[0], r[1]), reverse=True)
        _n, covered, cfile, cline, raw = found[0]
        out: dict[str, Any] = {
            "file": cfile.replace("\\", "/"),
            "line": cline,
            "snippet": raw[:200],
            "match": round(covered, 3),
        }
        if len(found) > 1:
            out["also"] = len(found) - 1
        return out


def encode_function(host_ir: Any, site: Any) -> str:
    """Function enclosing the encode call — the scope guards resolve against."""
    near = [
        w
        for w in getattr(host_ir, "local_writes", []) or []
        if w.file == site.file and w.line < site.line
    ]
    return max(near, key=lambda w: w.line).function if near else ""


def _as_int(text: Any) -> int | None:
    """Numeric value of a rendered constant, or None if it stays symbolic."""
    s = str(text).strip()
    if s in ("True", "true"):
        return 1
    if s in ("False", "false"):
        return 0
    try:
        return int(s, 0)
    except ValueError:
        return None


# -- records ---------------------------------------------------------------
@dataclass
class UndecidedGuard:
    id: str
    var_id: str
    reason: str
    text: str
    presort: str
    escalate: bool
    evidence: dict[str, Any] | None = None
    #: The symbol resolution stopped on. `text` is the whole guard, which for a
    #: deeply expanded condition says nothing about where it went wrong.
    blocked_on: str = ""
    #: Function the variable was read in. Part of its identity: same-named
    #: locals in two functions are two variables, not one.
    scope: str = ""
    #: Type the worker declared the variable with, when it said. Empty means
    #: fall back to guessing from the bucket, which is right for a softened
    #: guard and wrong for anything else sharing its prefix.
    var_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "var_id": self.var_id,
            "reason": self.reason,
            "text": self.text,
            "presort": self.presort,
            "escalate": self.escalate,
        }
        if self.var_type:
            out["var_type"] = self.var_type
        if self.blocked_on:
            out["blocked_on"] = self.blocked_on
        if self.scope:
            out["scope"] = self.scope
        if self.evidence:
            out["evidence"] = dict(self.evidence)
        return out


@dataclass
class FieldDerivation:
    name: str
    index: int
    status: str
    exactness: str = EX_UNRESOLVED
    #: Over-approximation variables still standing in `value_expr`. Closing the
    #: derivation means emptying this list, not merely reaching `status=derived`.
    free_vars: list[str] = field(default_factory=list)
    host_expr: str = ""
    domain: list[str] = field(default_factory=list)
    value_expr: dict[str, Any] | None = None
    value_leaves: list[str] = field(default_factory=list)
    root_vars: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    undecided_guards: list[UndecidedGuard] = field(default_factory=list)
    unresolved: list[dict[str, str]] = field(default_factory=list)
    def_sites: list[dict[str, Any]] = field(default_factory=list)
    #: Sites where an if/else-if chain was closed with an assumed zero default
    #: because no unguarded write was found. Not an over-approximation — the
    #: expression is exact *if* the assumption holds — but it rests on a
    #: declaration we never read, so it is reported rather than taken silently.
    implicit_defaults: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    seconds: float = 0.0
    expanded_chars: int = 0
    expanded: str = ""

    @property
    def escalating(self) -> list[UndecidedGuard]:
        return [g for g in self.undecided_guards if g.escalate]

    @property
    def domain_violations(self) -> list[str]:
        """Values the field can take that the template never declared.

        A generic sentinel for "derivation disagrees with the TPL contract". It
        fires on `OutDType` here: the template declares 0-3, but the FP8 and
        HiFloat8 paths write 4/5/6 into the key. That is an operator-side
        inconsistency, not a derivation bug — the derivation is what exposes it.

        Only leaves that resolve to a number are judged. `value_leaves` also
        carries unfolded enum spellings (`DtypeEnum::FLOAT32`, `TILING_KEY_1`),
        and counting those as out-of-domain would flag all 19 dimensions and
        make the check useless. So this is a lower bound on the real conflicts.
        """
        allowed = {n for n in (_as_int(v) for v in self.domain) if n is not None}
        if not allowed:
            return []
        bad = {n for n in (_as_int(v) for v in self.value_leaves) if n is not None}
        return [str(n) for n in sorted(bad - allowed)]

    @property
    def input_closure(self) -> str:
        """Whether a test case can drive this field, which `exactness` cannot say.

        Derived from `root_vars` rather than stored so the two can never
        disagree. See `kb_model.classify_input_closure`.
        """
        return classify_input_closure(self.root_vars)

    @property
    def input_derivable(self) -> bool:
        """Closed *and* drivable — the single question a generator should ask.

        The old rule was `status == "derived" and bool(root_vars)`, which passed
        any non-empty root set. Four dimensions here close onto `TILING_DATA`
        alone, so a generator was told it controlled them while nothing it can
        set reaches them.
        """
        return self.exactness in (EX_EXACT, EX_CONSTANT) and input_closure_is_drivable(
            self.input_closure
        )

    def unrecorded_free_vars(self) -> list[str]:
        """Over-approximations in `value_expr` that nothing on the books explains.

        This must always be empty. A free variable with nothing behind it is
        invisible to the gap machinery, so it can never be escalated or closed,
        while the solver still treats the condition it replaced as "either
        way" — an over-approximation that has dropped off the books rather
        than been resolved.

        Two kinds of record answer for a variable. A softened guard is one. The
        other is an assumed default: the chain reached a point where the field's
        prior value was unreadable, which is not a guard at all but is recorded
        just as precisely, down to the site that raised it.
        """
        recorded = {g.var_id for g in self.undecided_guards}
        recorded |= {
            str(d["variable"]) for d in self.implicit_defaults if d.get("variable")
        }
        return sorted(v for v in self.free_vars if v not in recorded)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "status": self.status,
            "exactness": self.exactness,
            "input_closure": self.input_closure,
            "input_derivable": self.input_derivable,
            "free_vars": list(self.free_vars),
            "host_expr": self.host_expr,
            "domain": list(self.domain),
            # Shared sub-expressions are named rather than repeated; see
            # `encode_expr_dag`. Read it back with `decode_expr_dag`.
            "value_expr": encode_expr_dag(self.value_expr),
            "value_leaves": list(self.value_leaves),
            "domain_violations": self.domain_violations,
            "root_vars": list(self.root_vars),
            "variables": list(self.variables),
            "undecided_guards": [g.to_dict() for g in self.undecided_guards],
            "unresolved": list(self.unresolved),
            "def_sites": list(self.def_sites),
            "implicit_defaults": list(self.implicit_defaults),
            "note": self.note,
            "seconds": self.seconds,
            "expanded_chars": self.expanded_chars,
        }


@dataclass
class HostDerivation:
    op_name: str = ""
    architecture: str = ""
    encode_site: dict[str, Any] = field(default_factory=dict)
    encode_function: str = ""
    fields: list[FieldDerivation] = field(default_factory=list)
    note: str = ""
    #: What the operator requires of its inputs, one entry per rejection it
    #: writes. These hold on every run that produces a key, so they constrain
    #: every field at once and belong to the document rather than to any one of
    #: them. Without them an input the operator refuses — FAG's HIFLOAT8 query —
    #: still looks available, and the values only it can produce are reported as
    #: reachable. See `HostIR.legality_premises`.
    premises: list[dict[str, Any]] = field(default_factory=list)

    def by_name(self) -> dict[str, FieldDerivation]:
        return {f.name: f for f in self.fields}

    def totals(self) -> dict[str, Any]:
        return {
            "total": len(self.fields),
            "derived": sum(1 for f in self.fields if f.status == "derived"),
            "partial": sum(1 for f in self.fields if f.status == "partial"),
            "unresolved": sum(1 for f in self.fields if f.status == "unresolved"),
            # The closure target. `derived` counts fields we have *some*
            # expression for; `exact` counts the ones whose expression still
            # means what the source means.
            "exact": sum(1 for f in self.fields if f.exactness == EX_EXACT),
            "free_vars": len({v for f in self.fields for v in f.free_vars}),
            # Must stay 0: see FieldDerivation.unrecorded_free_vars.
            "unrecorded_free_vars": len(
                {v for f in self.fields for v in f.unrecorded_free_vars()}
            ),
            "input_derivable": sum(1 for f in self.fields if f.input_derivable),
            # Operator-side contract conflicts, reported not gated: the template
            # and the host disagree, and neither is ours to change.
            "domain_violations": sum(1 for f in self.fields if f.domain_violations),
            "implicit_defaults": sum(len(f.implicit_defaults) for f in self.fields),
            "undecided": sum(len(f.undecided_guards) for f in self.fields),
            "scheduling": sum(
                1
                for f in self.fields
                for g in f.undecided_guards
                if g.presort == PRESORT_SCHEDULING
            ),
            "escalating": len(
                {g.id for f in self.fields for g in f.escalating}
            ),
            "max_chars": max((f.expanded_chars for f in self.fields), default=0),
            "seconds": round(sum(f.seconds for f in self.fields), 1),
        }

    @property
    def status(self) -> str:
        if not self.fields:
            return "unresolved"
        t = self.totals()
        if t["derived"] == t["total"]:
            return "derived"
        return "unresolved" if t["derived"] == 0 else "partial"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": DERIVATION_VERSION,
            "status": self.status,
            "op_name": self.op_name,
            "architecture": self.architecture,
            "encode_site": dict(self.encode_site),
            "encode_function": self.encode_function,
            "totals": self.totals(),
            "note": self.note,
            "premises": [dict(p) for p in self.premises],
            "fields": [f.to_dict() for f in self.fields],
        }


# -- worker ----------------------------------------------------------------
def _derive_row(bundle: dict[str, Any], index: int, helper: int) -> dict[str, Any]:
    """Derive one dimension. Pure function of the bundle — no I/O."""
    from uo_init.derive_key_fields import KeyFieldDeriver

    host_ir = bundle["host_ir"]
    binding = bundle["binding"]
    b = binding.bindings[index]
    deriver = KeyFieldDeriver(
        host_ir=host_ir,
        resolver=bundle["resolver"],
        var_model=bundle["var_model"],
        max_helper_guards=helper,
    )
    started = time.time()
    result = deriver.derive(
        dim_name=b.decl.name,
        index=b.index,
        host_expr=b.host_expr,
        function=encode_function(host_ir, binding.site),
    )
    row = result.to_dict()
    row["domain"] = [str(v) for v in b.decl.value_domain]
    row["seconds"] = round(time.time() - started, 1)
    row["expanded_chars"] = len(row["expanded"])
    row["expanded"] = row["expanded"][:EXPANDED_KEEP]
    row["undecided"] = {k: v[:TEXT_KEEP] for k, v in row["undecided"].items()}
    return row


#: Names a premise may not depend on. A premise *narrows* the input space, so
#: an inexact one hides reachable keys — the one failure mode worth being
#: paranoid about here. A free variable means the expansion gave up somewhere,
#: and "some unknown thing is false" excludes inputs on no evidence at all.
_SOFT_PREFIXES = ("VAR_LOCAL_", "VAR_INIT_", "VAR_UNMODELLED_")


def _mentions_soft(node: Any) -> bool:
    if isinstance(node, dict):
        name = node.get("var")
        if isinstance(name, str) and name.startswith(_SOFT_PREFIXES):
            return True
        return any(_mentions_soft(v) for v in node.values())
    if isinstance(node, list):
        return any(_mentions_soft(v) for v in node)
    return False


def _mentions_any_var(node: Any) -> bool:
    if isinstance(node, dict):
        if isinstance(node.get("var"), str):
            return True
        return any(_mentions_any_var(v) for v in node.values())
    if isinstance(node, list):
        return any(_mentions_any_var(v) for v in node)
    return False


def _derive_premises(
    bundle: dict[str, Any], host_ir: Any, function: str, helper: int
) -> list[dict[str, Any]]:
    """Expand each input-legality condition the same way a dimension is expanded.

    A rejection is written in the operator's own vocabulary — `fBaseParams
    .queryType`, a member assigned three calls earlier — so it needs the same
    chasing a key field does, and gets it by going through the same deriver.
    """
    from uo_init.derive_key_fields import KeyFieldDeriver

    out: list[dict[str, Any]] = []
    for i, (text, fn, file, line) in enumerate(host_ir.legality_premises()):
        try:
            deriver = KeyFieldDeriver(
                host_ir=host_ir,
                resolver=bundle["resolver"],
                var_model=bundle["var_model"],
                max_helper_guards=helper,
            )
            row = deriver.derive(
                dim_name=f"__premise{i}",
                index=-1 - i,
                host_expr=text,
                function=fn or function,
            ).to_dict()
        except Exception as exc:  # noqa: BLE001 — a premise we cannot read is dropped
            out.append({"text": text, "file": file, "line": line, "function": fn,
                        "usable": False, "why": f"{type(exc).__name__}: {exc}"[:120]})
            continue
        expr = row.get("value_expr")
        why = ""
        if expr is None:
            why = "no expression"
        elif row.get("unresolved"):
            why = str((row["unresolved"][0] or {}).get("reason") or "unresolved")[:120]
        elif _mentions_soft(expr):
            why = "free variable"
        elif not _mentions_any_var(expr):
            # A requirement on the inputs that mentions no input is not one:
            # expansion lost it somewhere. `if (!IsSameShape(dy, attentionIn))`
            # folds to a bare constant once the call cannot be read, and a
            # constant-false premise would reject every input there is.
            why = "no input dependence"
        out.append(
            {
                "text": text,
                "file": file,
                "line": line,
                "function": fn,
                "usable": not why,
                "why": why,
                "expr": None if why else expr,
            }
        )
    return out


def _worker(bundle_path: str, sys_path: list[str], index: int, helper: int, queue) -> None:
    for entry in sys_path:
        if entry and entry not in sys.path:
            sys.path.insert(0, entry)
    sys.setrecursionlimit(20000)
    try:
        with open(bundle_path, "rb") as fh:
            bundle = pickle.load(fh)
        queue.put(_derive_row(bundle, index, helper))
    except Exception as exc:  # noqa: BLE001 — the parent turns this into a row
        queue.put({"__error__": f"{type(exc).__name__}: {exc}"[:400]})


def _failed_row(name: str, index: int, reason: str, seconds: float) -> dict[str, Any]:
    return {
        "name": name,
        "index": index,
        "host_expr": "",
        "expanded": "",
        "expanded_chars": 0,
        "value_expr": None,
        "value_leaves": [],
        "input_roots": [],
        "variables": [],
        "def_sites": [],
        "unresolved": [{"text": "", "reason": reason}],
        "scheduling": {},
        "undecided": {},
        "domain": [],
        "status": "unresolved",
        "note": reason,
        "seconds": seconds,
    }


def _reap(proc: Any, queue: Any) -> int | None:
    """Leave no worker behind, whatever state it is in. Returns its exit code.

    The caller cannot read `exitcode` afterwards -- closing the handle is part
    of the cleanup -- so it is read here, while it is still there to read.
    """
    exitcode: int | None = None
    try:
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=5)
        exitcode = proc.exitcode
    finally:
        try:
            # The queue's feeder thread keeps the pipe open, and on Windows an
            # open handle keeps the process object alive after it has exited.
            queue.close()
            queue.join_thread()
        except Exception:  # noqa: BLE001 — teardown must not mask the result
            pass
        try:
            proc.close()
        except Exception:  # noqa: BLE001 — already reaped, or never started
            pass
    return exitcode


def _derive_isolated(
    bundle_path: str, index: int, name: str, helper: int, timeout: int
) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(
        target=_worker,
        args=(bundle_path, list(sys.path), index, helper, queue),
        daemon=True,
    )
    started = time.time()
    proc.start()
    row: dict[str, Any] | None = None
    exitcode: int | None = None
    try:
        try:
            row = queue.get(timeout=timeout)
        except Exception:  # noqa: BLE001 — empty queue means timeout or crash
            row = None
    finally:
        # One worker per dimension, so a worker that outlives its collection
        # is not a one-off: it is one stray interpreter per dimension, holding
        # its parsed translation units until the machine is out of memory.
        # `daemon` only covers a clean parent exit, and the escalation matters
        # because `terminate` posts a signal that a process wedged in a native
        # call can ignore.
        exitcode = _reap(proc, queue)
    elapsed = round(time.time() - started, 1)
    if row is not None and "__error__" not in row:
        return row
    if row is not None:
        return _failed_row(name, index, str(row["__error__"]), elapsed)
    reason = "TIMEOUT" if elapsed >= timeout else f"CRASHED(exit={exitcode})"
    return _failed_row(name, index, reason, elapsed)


# -- assembly --------------------------------------------------------------
def _readopt(row: dict[str, Any], key: str, default: Any) -> Any:
    got = row.get(key)
    return default if got is None else got


def _guards_of(
    row: dict[str, Any], evidence: GuardEvidenceIndex | None
) -> list[UndecidedGuard]:
    """The softened guards, from either shape a row arrives in.

    A worker hands back `undecided` as `{var_id: "reason: text"}`; a document
    that has been through `to_dict` carries `undecided_guards` as whole records.
    Reading only the worker shape leaves the guards empty after a round-trip,
    and then `_reregister_soft_vars` declares nothing -- so the solver meets
    those variables as unknown symbols, which is exactly the state that drops a
    dimension.
    """
    records = row.get("undecided_guards")
    if records:
        return [
            UndecidedGuard(
                id=str(r.get("id") or guard_id(str(r.get("var_id") or ""))),
                var_id=str(r.get("var_id") or ""),
                reason=str(r.get("reason") or ""),
                text=str(r.get("text") or "")[:TEXT_KEEP],
                presort=str(r.get("presort") or ""),
                escalate=bool(r.get("escalate")),
                evidence=dict(r["evidence"]) if r.get("evidence") else None,
                blocked_on=str(r.get("blocked_on") or ""),
                scope=str(r.get("scope") or ""),
                var_type=str(r.get("var_type") or ""),
            )
            for r in records
        ]

    guards: list[UndecidedGuard] = []
    blocked_on = row.get("blocked_on") or {}
    var_scope = row.get("var_scope") or {}
    var_types = row.get("var_types") or {}
    for var_id, detail in sorted((row.get("undecided") or {}).items()):
        reason, text = split_reason(detail)
        presort = presort_guard(var_id, detail)
        scope = str(var_scope.get(var_id) or "")
        guards.append(
            UndecidedGuard(
                id=guard_id(var_id),
                var_id=var_id,
                reason=reason,
                text=text[:TEXT_KEEP],
                presort=presort,
                escalate=presort not in NON_ESCALATING,
                evidence=evidence.best(text, scope) if evidence is not None else None,
                blocked_on=str(blocked_on.get(var_id) or ""),
                scope=scope,
                var_type=str(var_types.get(var_id) or ""),
            )
        )
    return guards


def _roots_of(row: dict[str, Any]) -> list[Any]:
    """The input roots, under either name the two serialisations give them.

    Losing them is not a quiet loss of detail: an empty root set grades as
    `IC_NONE`, which reads as "constant, nothing needs setting" and counts as
    drivable -- the opposite of "closed onto host state no test can drive".
    """
    value = row.get("input_roots")
    if value is None:
        value = row.get("root_vars")
    return list(value or [])


def _to_field(
    row: dict[str, Any], evidence: GuardEvidenceIndex | None
) -> FieldDerivation:
    guards = _guards_of(row, evidence)
    return FieldDerivation(
        name=str(row.get("name") or ""),
        index=int(row.get("index") or 0),
        status=str(row.get("status") or "unresolved"),
        exactness=str(_readopt(row, "exactness", EX_UNRESOLVED)),
        free_vars=sorted(str(v) for v in _readopt(row, "free_vars", [])),
        host_expr=str(_readopt(row, "host_expr", "")),
        domain=[str(v) for v in _readopt(row, "domain", [])],
        value_expr=decode_expr_dag(row.get("value_expr")),
        value_leaves=sorted(str(v) for v in _readopt(row, "value_leaves", [])),
        root_vars=sorted(str(v) for v in _roots_of(row)),
        variables=sorted(str(v) for v in _readopt(row, "variables", [])),
        undecided_guards=guards,
        unresolved=list(_readopt(row, "unresolved", [])),
        def_sites=list(_readopt(row, "def_sites", [])),
        implicit_defaults=list(_readopt(row, "implicit_defaults", [])),
        note=str(_readopt(row, "note", "")),
        seconds=float(_readopt(row, "seconds", 0.0)),
        expanded_chars=int(_readopt(row, "expanded_chars", 0)),
        expanded=str(_readopt(row, "expanded", "")),
    )


#: How to re-declare a softened guard, by the bucket it was sorted into. This
#: has to reproduce what the worker declared: a loop element is an unbounded
#: int (`_truthy` renders it as `!= 0`, which only type-checks as an int) while
#: the other soft variables really are booleans. Declaring them all bool used
#: to rewrite the loop-element variables' type and origin behind the caller's
#: back, which then made them look interchangeable across dimensions.
_SOFT_VAR_KINDS: dict[str, dict[str, Any]] = {
    PRESORT_LOOP_ELEMENT: {
        "type": "int",
        "origin": "LOOP_ELEMENT",
        "source": "loop_local_element",
        "merged": True,
    },
    PRESORT_SCHEDULING: {
        "type": "bool",
        "origin": "SCHED_SOFT",
        "source": "scheduling_guard",
        "merged": False,
    },
    PRESORT_REACHABILITY: {
        "type": "bool",
        "origin": "REACHED_SOFT",
        "source": "reachability_guard",
        "merged": False,
    },
    "": {
        "type": "bool",
        "origin": "UNDECIDED_GUARD",
        "source": "undecidable_guard",
        "merged": False,
    },
}


def _reregister_soft_vars(var_model: Any, doc: HostDerivation) -> None:
    """Re-declare the free variables the workers created.

    Softening happens inside the child process, so the parent's model never
    sees those `VarSpec`s. The solver needs them declared, and the patch
    validator needs `var_id` lookups to agree with what the derivation emitted.

    Two kinds come back this way. A softened guard arrives as an
    `UndecidedGuard`; the variable standing in for a field's value before any
    write arrives on the `implicit_defaults` record instead, and it is an
    unbounded int rather than a bool. Leaving the second kind undeclared is not
    a silent no-op -- the solver reads an unknown symbol as `unmodelled_variable`
    and drops the whole dimension.
    """
    from uo_init.kb_model import Domain
    from uo_init.variable_model import VarSpec

    for fld in doc.fields:
        for guard in fld.undecided_guards:
            if var_model.get(guard.var_id) is not None:
                continue
            kind = _SOFT_VAR_KINDS.get(guard.presort) or _SOFT_VAR_KINDS[""]
            # What the worker declared beats what the bucket suggests. The
            # bucket only knows the prefix, and `VAR_SCHED_` carries both
            # softened guards and traversal positions -- one bool, one int.
            var_type = guard.var_type or kind["type"]
            var_model.add(
                VarSpec(
                    var_id=guard.var_id,
                    name=guard.var_id,
                    value_type=var_type,
                    domain=Domain(
                        var_id=guard.var_id,
                        value_type=var_type,
                        completeness="open",
                        source=kind["source"],
                    ),
                    origin=kind["origin"],
                    description=f"{guard.reason}: {guard.text[:160]}",
                    identity_merged=bool(kind["merged"]),
                )
            )
        for record in fld.implicit_defaults:
            var_id = str(record.get("variable") or "")
            if not var_id or var_model.get(var_id) is not None:
                continue
            where = f"{record.get('file')}:{record.get('line')}"
            var_model.add(
                VarSpec(
                    var_id=var_id,
                    name=var_id,
                    value_type="int",
                    domain=Domain(
                        var_id=var_id,
                        value_type="int",
                        completeness="open",
                        source="init_unknown",
                    ),
                    origin="INIT_UNKNOWN",
                    description=(
                        f"value of {record.get('field')} before any write ({where})"
                    ),
                )
            )


def derive_host_fields(
    bundle: dict[str, Any],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_helper_guards: int = DEFAULT_HELPER_GUARDS,
    isolate: bool = True,
    only: list[str] | None = None,
) -> HostDerivation:
    """Derive every bound TilingKey dimension of one operator.

    `isolate=False` runs in-process: no timeout protection, but usable from a
    test runner where spawning is more trouble than the protection is worth.
    """
    binding = bundle.get("binding")
    spec = bundle.get("spec")
    doc = HostDerivation(
        op_name=getattr(spec, "op_name", "") or "",
        architecture=getattr(spec, "arch_dir", "") or "",
    )
    if binding is None or not getattr(binding, "bindings", None):
        doc.note = str(bundle.get("bind_error") or "no tpl binding")
        return doc

    host_ir = bundle["host_ir"]
    doc.encode_site = binding.site.to_dict()
    doc.encode_function = encode_function(host_ir, binding.site)
    evidence = GuardEvidenceIndex(host_ir)
    wanted = set(only or [])
    targets = [
        b for b in binding.bindings if not wanted or b.decl.name in wanted
    ]

    tmp_path = ""
    if isolate:
        keep = {
            k: bundle[k]
            for k in ("binding", "host_ir", "resolver", "var_model")
            if k in bundle
        }
        fd, tmp_path = tempfile.mkstemp(prefix="uo_derive_", suffix=".pkl")
        try:
            with open(fd, "wb") as fh:
                pickle.dump(keep, fh)
        except Exception:  # noqa: BLE001 — fall back to in-process
            isolate = False
            tmp_path = ""

    try:
        for b in targets:
            if isolate and tmp_path:
                row = _derive_isolated(
                    tmp_path, b.index, b.decl.name, max_helper_guards, timeout
                )
            else:
                started = time.time()
                try:
                    row = _derive_row(bundle, b.index, max_helper_guards)
                except Exception as exc:  # noqa: BLE001
                    row = _failed_row(
                        b.decl.name,
                        b.index,
                        f"{type(exc).__name__}: {exc}"[:200],
                        round(time.time() - started, 1),
                    )
            doc.fields.append(_to_field(row, evidence))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    doc.fields.sort(key=lambda f: f.index)
    try:
        doc.premises = _derive_premises(
            bundle, host_ir, doc.encode_function, max_helper_guards
        )
    except Exception as exc:  # noqa: BLE001 — premises sharpen, they do not gate
        doc.note = (doc.note + f" premises failed: {type(exc).__name__}").strip()
    if bundle.get("var_model") is not None:
        _reregister_soft_vars(bundle["var_model"], doc)
    return doc


def to_key_derivations(doc: HostDerivation) -> dict[str, Any]:
    """TG-facing view: one entry per dimension, no derivation bookkeeping.

    TG binds `key_derivations` to decide which CSV variables move a key field.
    It needs the expression and the roots, not the guard audit trail.
    """
    return {
        "version": DERIVATION_VERSION,
        "status": doc.status,
        "source": "uo_init.host_derivation",
        "encode_site": dict(doc.encode_site),
        "key_derivations": {
            f.name: {
                "index": f.index,
                "status": f.status,
                "host_expr": f.host_expr,
                "expr": encode_expr_dag(f.value_expr),
                "domain": list(f.domain),
                "value_leaves": list(f.value_leaves),
                "root_vars": list(f.root_vars),
                "variables": list(f.variables),
                "input_closure": f.input_closure,
                "input_derivable": f.input_derivable,
                "undecided_guard_ids": [g.id for g in f.undecided_guards],
            }
            for f in doc.fields
        },
    }
