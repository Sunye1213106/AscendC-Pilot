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

from uo_init.ids import hash12

DERIVATION_VERSION = 1

# How a guard that survived normalization failure should be treated. The split
# is deterministic: it comes from the reason code and the guard text, never
# from a per-operator table.
PRESORT_SCHEDULING = "scheduling"
PRESORT_PLATFORM = "platform"
PRESORT_UNMAPPED = "unmapped"
PRESORT_UNKNOWN = "unknown"

PRESORTS = (PRESORT_SCHEDULING, PRESORT_PLATFORM, PRESORT_UNMAPPED, PRESORT_UNKNOWN)

# Scheduling guards are softened on purpose — a branch on traversal position is
# taken on some iteration whatever the input, so pinning it would wrongly rule
# keys out. They are recorded for audit but never become LLM work.
NON_ESCALATING = frozenset({PRESORT_SCHEDULING})

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
    if str(var_id).startswith("VAR_SCHED_"):
        return PRESORT_SCHEDULING
    reason, text = split_reason(detail)
    if reason == "SCHED_SOFT":
        return PRESORT_SCHEDULING
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
    original guard literally. Identifier overlap against every recorded path
    condition is enough to point a reader (or the LLM) at the right line, and a
    miss degrades to no evidence rather than to a fabricated one.
    """

    MIN_SCORE = 0.12

    def __init__(self, host_ir: Any) -> None:
        self._rows: list[tuple[frozenset[str], str, int, str]] = []
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
                    self._rows.append((toks, cfile, cline, text))

    def best(self, text: str) -> dict[str, Any] | None:
        toks = _tokens(text)
        if not toks or not self._rows:
            return None
        best: tuple[str, int, str] | None = None
        score = 0.0
        for row_toks, cfile, cline, raw in self._rows:
            hit = len(toks & row_toks)
            if not hit:
                continue
            s = hit / len(toks | row_toks)
            if s > score:
                score, best = s, (cfile, cline, raw)
        if best is None or score < self.MIN_SCORE:
            return None
        return {
            "file": best[0].replace("\\", "/"),
            "line": best[1],
            "snippet": best[2][:200],
            "match": round(score, 3),
        }


def encode_function(host_ir: Any, site: Any) -> str:
    """Function enclosing the encode call — the scope guards resolve against."""
    near = [
        w
        for w in getattr(host_ir, "local_writes", []) or []
        if w.file == site.file and w.line < site.line
    ]
    return max(near, key=lambda w: w.line).function if near else ""


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

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "var_id": self.var_id,
            "reason": self.reason,
            "text": self.text,
            "presort": self.presort,
            "escalate": self.escalate,
        }
        if self.evidence:
            out["evidence"] = dict(self.evidence)
        return out


@dataclass
class FieldDerivation:
    name: str
    index: int
    status: str
    host_expr: str = ""
    domain: list[str] = field(default_factory=list)
    value_expr: dict[str, Any] | None = None
    value_leaves: list[str] = field(default_factory=list)
    root_vars: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    undecided_guards: list[UndecidedGuard] = field(default_factory=list)
    unresolved: list[dict[str, str]] = field(default_factory=list)
    def_sites: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    seconds: float = 0.0
    expanded_chars: int = 0
    expanded: str = ""

    @property
    def escalating(self) -> list[UndecidedGuard]:
        return [g for g in self.undecided_guards if g.escalate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "status": self.status,
            "host_expr": self.host_expr,
            "domain": list(self.domain),
            "value_expr": self.value_expr,
            "value_leaves": list(self.value_leaves),
            "root_vars": list(self.root_vars),
            "variables": list(self.variables),
            "undecided_guards": [g.to_dict() for g in self.undecided_guards],
            "unresolved": list(self.unresolved),
            "def_sites": list(self.def_sites),
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

    def by_name(self) -> dict[str, FieldDerivation]:
        return {f.name: f for f in self.fields}

    def totals(self) -> dict[str, Any]:
        return {
            "total": len(self.fields),
            "derived": sum(1 for f in self.fields if f.status == "derived"),
            "partial": sum(1 for f in self.fields if f.status == "partial"),
            "unresolved": sum(1 for f in self.fields if f.status == "unresolved"),
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
    try:
        row = queue.get(timeout=timeout)
    except Exception:  # noqa: BLE001 — empty queue means timeout or crash
        row = None
    proc.join(timeout=5)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5)
    elapsed = round(time.time() - started, 1)
    if row is not None and "__error__" not in row:
        return row
    if row is not None:
        return _failed_row(name, index, str(row["__error__"]), elapsed)
    reason = "TIMEOUT" if elapsed >= timeout else f"CRASHED(exit={proc.exitcode})"
    return _failed_row(name, index, reason, elapsed)


# -- assembly --------------------------------------------------------------
def _readopt(row: dict[str, Any], key: str, default: Any) -> Any:
    got = row.get(key)
    return default if got is None else got


def _to_field(
    row: dict[str, Any], evidence: GuardEvidenceIndex | None
) -> FieldDerivation:
    guards: list[UndecidedGuard] = []
    for var_id, detail in sorted((row.get("undecided") or {}).items()):
        reason, text = split_reason(detail)
        presort = presort_guard(var_id, detail)
        guards.append(
            UndecidedGuard(
                id=guard_id(var_id),
                var_id=var_id,
                reason=reason,
                text=text[:TEXT_KEEP],
                presort=presort,
                escalate=presort not in NON_ESCALATING,
                evidence=evidence.best(text) if evidence is not None else None,
            )
        )
    return FieldDerivation(
        name=str(row.get("name") or ""),
        index=int(row.get("index") or 0),
        status=str(row.get("status") or "unresolved"),
        host_expr=str(_readopt(row, "host_expr", "")),
        domain=[str(v) for v in _readopt(row, "domain", [])],
        value_expr=row.get("value_expr"),
        value_leaves=sorted(str(v) for v in _readopt(row, "value_leaves", [])),
        root_vars=sorted(str(v) for v in _readopt(row, "input_roots", [])),
        variables=sorted(str(v) for v in _readopt(row, "variables", [])),
        undecided_guards=guards,
        unresolved=list(_readopt(row, "unresolved", [])),
        def_sites=list(_readopt(row, "def_sites", [])),
        note=str(_readopt(row, "note", "")),
        seconds=float(_readopt(row, "seconds", 0.0)),
        expanded_chars=int(_readopt(row, "expanded_chars", 0)),
        expanded=str(_readopt(row, "expanded", "")),
    )


def _reregister_soft_vars(var_model: Any, doc: HostDerivation) -> None:
    """Re-declare the free booleans the workers created.

    Softening happens inside the child process, so the parent's model never
    sees those `VarSpec`s. The solver needs them declared, and the patch
    validator needs `var_id` lookups to agree with what the derivation emitted.
    """
    from uo_init.kb_model import Domain
    from uo_init.variable_model import VarSpec

    for fld in doc.fields:
        for guard in fld.undecided_guards:
            if var_model.get(guard.var_id) is not None:
                continue
            source = (
                "scheduling_guard"
                if guard.presort == PRESORT_SCHEDULING
                else "undecidable_guard"
            )
            var_model.add(
                VarSpec(
                    var_id=guard.var_id,
                    name=guard.var_id,
                    value_type="bool",
                    domain=Domain(
                        var_id=guard.var_id,
                        value_type="bool",
                        completeness="open",
                        source=source,
                    ),
                    origin=(
                        "SCHED_SOFT"
                        if guard.presort == PRESORT_SCHEDULING
                        else "UNDECIDED_GUARD"
                    ),
                    description=f"{guard.reason}: {guard.text[:160]}",
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
                "expr": f.value_expr,
                "domain": list(f.domain),
                "value_leaves": list(f.value_leaves),
                "root_vars": list(f.root_vars),
                "variables": list(f.variables),
                "input_derivable": f.status == "derived" and bool(f.root_vars),
                "undecided_guard_ids": [g.id for g in f.undecided_guards],
            }
            for f in doc.fields
        },
    }
