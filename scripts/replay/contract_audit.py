# -*- coding: utf-8 -*-
"""Whether the generator's exits still describe the same case.

A case leaves the generator by four doors: the line the host replays, the
environment the derivation evaluates, the row the report table records, and
the case rebuilt from that row. Nothing forces them to agree. They are four
hand-written functions over one mental model, and they drift the moment one
of them learns something the others do not -- a dtype the host special-cases,
a field the table has no column for, a shape name that reaches a fallback
instead of an error. Each drift is silent and each produces a run whose
recorded inputs are not the inputs that ran.

This module knows none of the operator. It is handed the doors and the
vocabulary they share, and it asserts the only thing assertable without
knowing what a query tensor is: a case put through one door comes out the
same as through any other. Naming the tensors is the operator's job, and
after P1 that naming comes from the manifest rather than from a Python
module; the gate itself does not change when it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import prod
from typing import Any, Callable, Iterable, Mapping, Sequence

#: A tensor whose shape field carries `n@v0/v1/...`: the host reads its
#: contents, so the generator writes the contents rather than the extent.
VALUE_FIELD_SEP = "@"

PRESENCE_MISMATCH = "presence_mismatch"
SHAPE_MISMATCH = "shape_mismatch"
RANK_MISMATCH = "rank_mismatch"
DTYPE_MISMATCH = "dtype_mismatch"
VALUE_MISMATCH = "value_mismatch"
ENV_MISSING_KEY = "env_missing_key"
#: The spec reads a tensor the line has no slot for. Since the spec is
#: exported from the derivation and the line comes from the generator, this
#: is the two disagreeing about the operator's signature. The opposite --
#: a tensor the host is handed that nothing reads -- is not reported: that is
#: what the export found, and most tensors are like that.
ENV_UNMODELLED_TENSOR = "env_unmodelled_tensor"
ATTR_MISMATCH = "attr_mismatch"
REPORT_UNSTABLE = "report_unstable"
REPORT_LOSSY = "report_lossy"
ENUM_OUT_OF_RANGE = "enum_out_of_range"
MALFORMED_LINE = "malformed_line"
GENERATOR_REFUSED = "generator_refused"
#: The expansion the exits are made from contradicts itself -- a tensor
#: present with no shape, an extent that disagrees with the contents it
#: carries. Distinct from the mismatches above, which compare two exits: this
#: one is wrong before any exit reads it.
MATERIALISATION_INVALID = "materialisation_invalid"


@dataclass(frozen=True)
class Violation:
    """One place where two exits disagree about the same case."""

    kind: str
    case_id: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.case_id} {self.where}: {self.detail}"


@dataclass(frozen=True)
class HostCase:
    """A replay line read back into the quantities it names.

    Parsing the line the generator just wrote looks circular, and is not: the
    line is the only thing the host ever sees, so it is the only honest
    account of what was asked for. Everything else is an intention.
    """

    case_id: str
    in_shapes: dict[str, list[int]]
    in_values: dict[str, list[int]]
    in_dtypes: dict[str, int]
    out_shapes: dict[str, list[int]]
    out_dtypes: dict[str, int]
    attrs: dict[str, str]
    deterministic: int

    def present(self, name: str) -> bool:
        return bool(self.in_shapes.get(name) or self.in_values.get(name))


@dataclass(frozen=True)
class Surfaces:
    """The exits under audit and the vocabulary shared between them.

    `enum_guards` exists because some enumerations are conditional: a pse
    shape only has to name something real when there is a pse. A guard that
    returns False excuses the field for that case rather than declaring the
    empty string a legal member, which would let a genuinely wrong value in.
    """

    in_order: Sequence[str]
    out_order: Sequence[str]
    #: What the derivation reads and what each variable reads it off. The
    #: audit walks this rather than a list of tensors: a tensor the host is
    #: handed and the derivation never consults is not an omission to report,
    #: it is what the export found, and the only thing worth checking is that
    #: the readings the spec does claim are the ones the line carries.
    spec: Any
    serialize: Callable[[Any, str], str]
    static_env: Callable[[Any], Mapping[str, Any]]
    report: Callable[[Any], Mapping[str, Any]]
    rebuild: Callable[[Mapping[str, Any]], Any]
    value_tensors: frozenset[str] = frozenset()
    enums: Mapping[str, Sequence[Any]] = field(default_factory=dict)
    enum_guards: Mapping[str, Callable[[Any], bool]] = field(default_factory=dict)
    float_tol: float = 1e-9
    #: How the operator expands a case. Optional so an operator that has not
    #: adopted the shared expansion is still auditable the old way -- by
    #: comparing its exits against each other.
    materialize: Callable[[Any, str], Any] | None = None


def _dims(text: str) -> list[int]:
    return [int(x) for x in text.split("|") if x != ""]


def parse_line(line: str, s: Surfaces) -> HostCase:
    """Read a replay line back into shapes, dtypes and attrs.

    A line that does not have the shape the host expects is a violation in
    its own right, so this raises rather than guessing: a lenient parse here
    would hide exactly the corruption the gate exists to find.
    """
    parts = line.split(";")
    if len(parts) != 7:
        raise ValueError(f"expected 7 sections, got {len(parts)}")
    case_id, in_sh, in_dt, out_sh, out_dt, attr_text, det = parts

    def split(text: str, order: Sequence[str], what: str) -> list[str]:
        got = text.split(",")
        if len(got) != len(order):
            raise ValueError(f"{what}: expected {len(order)} fields, got {len(got)}")
        return got

    in_shapes: dict[str, list[int]] = {}
    in_values: dict[str, list[int]] = {}
    for name, text in zip(s.in_order, split(in_sh, s.in_order, "input shapes")):
        if VALUE_FIELD_SEP in text:
            count, _, body = text.partition(VALUE_FIELD_SEP)
            values = [int(x) for x in body.split("/") if x != ""]
            if int(count) != len(values):
                raise ValueError(f"{name}: count {count} but {len(values)} values")
            in_values[name] = values
            in_shapes[name] = [len(values)]
        else:
            in_shapes[name] = _dims(text)

    return HostCase(
        case_id=case_id,
        in_shapes=in_shapes,
        in_values=in_values,
        in_dtypes={n: int(t) for n, t in
                   zip(s.in_order, split(in_dt, s.in_order, "input dtypes"))},
        out_shapes={n: _dims(t) for n, t in
                    zip(s.out_order, split(out_sh, s.out_order, "output shapes"))},
        out_dtypes={n: int(t) for n, t in
                    zip(s.out_order, split(out_dt, s.out_order, "output dtypes"))},
        attrs=_parse_attrs(attr_text),
        deterministic=int(det),
    )


def _parse_attrs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in text.split("&"):
        if not item:
            continue
        name, _, rest = item.partition("=")
        _, _, value = rest.partition(":")
        out[name] = value
    return out


def _as_number(v: Any) -> float | None:
    """The value as a number, or None when it is not one.

    Everything on the host's side of a comparison arrived as text, so a
    tolerance that only applies to floats would never apply at all.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _same_number(a: Any, b: Any, tol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    x, y = _as_number(a), _as_number(b)
    if x is None or y is None:
        return str(a) == str(b)
    # The line is written with a fixed number of decimals, so a scale factor
    # is equal to what it was computed from only up to that rounding.
    return abs(x - y) <= tol * max(1.0, abs(x))


def audit_serialisation(case: Any, case_id: str, s: Surfaces) -> list[Violation]:
    """Whether the host's line and the derivation's environment agree.

    These two are the pair that matters most: the first decides what runs and
    the second decides what the solver believes ran. A disagreement does not
    fail anything at runtime, it just makes every static verdict about that
    case an answer to a different question.
    """
    out: list[Violation] = []
    try:
        line = s.serialize(case, case_id)
    except ValueError as exc:
        return [Violation(GENERATOR_REFUSED, case_id, "case", str(exc))]
    try:
        host = parse_line(line, s)
    except ValueError as exc:
        return [Violation(MALFORMED_LINE, case_id, "line", str(exc))]
    env = s.static_env(case)
    return out + _audit_bindings(host, env, case_id, s)


def _audit_bindings(host: HostCase, env: Mapping[str, Any], case_id: str,
                    s: Surfaces) -> list[Violation]:
    """Every reading the spec claims, against what the line actually says.

    Walking the spec rather than the tensor list changes what this can catch.
    It no longer reports a tensor nobody models -- the spec was exported from
    the derivation, so "nothing reads this" is a finding, not an oversight.
    What it catches instead is the spec being wrong about *how* a variable is
    read: an axis off by one, or a value tensor whose last element is not the
    element the host would see.
    """
    from . import bridge_spec as S

    out: list[Violation] = []
    for b in s.spec.bindings:
        if b.kind == S.CONTEXT:
            # Not on the line at all: the session and the platform are not
            # arguments, so the line is not evidence about them.
            continue
        if b.var not in env:
            out.append(Violation(
                ENV_MISSING_KEY, case_id, b.operand,
                f"the spec binds {b.var} and the env has no such key"))
            continue

        if b.kind == S.ATTR:
            got = host.attrs.get(b.operand)
            if got is None:
                out.append(Violation(
                    ATTR_MISMATCH, case_id, b.operand,
                    f"{b.var} reads this attr and the host is never told it"))
            elif not _same_number(env[b.var], got, s.float_tol):
                out.append(Violation(
                    ATTR_MISMATCH, case_id, b.operand,
                    f"host {got!r}, {b.var}={env[b.var]!r}"))
            continue

        found = _host_tensor(host, b.operand)
        if found is None:
            out.append(Violation(
                ENV_UNMODELLED_TENSOR, case_id, b.operand,
                f"{b.var} reads this tensor and the line carries no such slot"))
            continue
        want = _expected(found, b, S)
        if env[b.var] != want:
            out.append(Violation(
                _KIND_VIOLATION.get(b.kind, SHAPE_MISMATCH), case_id, b.operand,
                f"reading {b.kind}"
                + (f" axis {b.axis}" if b.axis is not None else "")
                + f": host says {want!r}, {b.var}={env[b.var]!r}"))
    return out


#: Which violation to raise when a reading disagrees, so a dtype problem is
#: still filed as one now that all the readings go through one comparison.
_KIND_VIOLATION = {
    "optional_presence": PRESENCE_MISMATCH,
    "tensor_rank": RANK_MISMATCH,
    "tensor_dtype": DTYPE_MISMATCH,
    "tensor_values": VALUE_MISMATCH,
    "tensor_value_last": VALUE_MISMATCH,
    "tensor_value_second": VALUE_MISMATCH,
    "tensor_value_max": VALUE_MISMATCH,
}


@dataclass(frozen=True)
class _HostTensor:
    """One tensor as the line carries it, whichever side it is on."""

    present: bool
    dims: list[int]
    values: list[int]
    dtype: int | None


def _host_tensor(host: HostCase, operand: str) -> _HostTensor | None:
    """Find the slot the spec's operand names.

    Matched the way the exporter matched the definition to the variable, so
    `query_rope` in the spec and `queryRope` on the line are one tensor.
    """
    from .bridge_spec import squash

    want = squash(operand)
    for name, dims in host.in_shapes.items():
        if squash(name) != want:
            continue
        values = host.in_values.get(name) or []
        return _HostTensor(
            present=bool(dims or values), dims=list(dims), values=values,
            dtype=host.in_dtypes.get(name))
    for name, dims in host.out_shapes.items():
        if squash(name) != want:
            continue
        return _HostTensor(present=bool(dims), dims=list(dims), values=[],
                           dtype=host.out_dtypes.get(name))
    return None


def _expected(t: _HostTensor, b: Any, S: Any) -> Any:
    """What the line says this reading should be.

    Absent is None rather than zero throughout, matching the runtime: the
    host tests the pointer before the extent, so collapsing the two flips the
    branch that handles a missing optional.
    """
    if b.kind == S.TENSOR_PRESENCE:
        return t.present
    if not t.present:
        return None
    if b.kind == S.TENSOR_NUMEL:
        return prod(t.dims) if t.dims else None
    if b.kind == S.TENSOR_RANK:
        return len(t.dims)
    if b.kind == S.TENSOR_DTYPE:
        return t.dtype
    if b.kind == S.TENSOR_AXIS:
        return t.dims[b.axis] if b.axis < len(t.dims) else None
    if b.kind == S.TENSOR_AXIS_LAST:
        return t.dims[-1] if t.dims else None
    if b.kind == S.TENSOR_VALUES:
        return t.values or None
    if not t.values:
        return None
    if b.kind == S.TENSOR_VALUE_LAST:
        return t.values[-1]
    if b.kind == S.TENSOR_VALUE_SECOND:
        return t.values[1] if len(t.values) > 1 else None
    if b.kind == S.TENSOR_VALUE_MAX:
        return max(t.values)
    raise ValueError(f"no reading is defined for {b.kind!r}")


def audit_roundtrip(case: Any, case_id: str, s: Surfaces) -> list[Violation]:
    """Whether the recorded row is enough to rebuild the case that ran.

    Comparing the two rows only catches a column that reads back wrong. A
    field the row never had is invisible that way -- it is equally absent on
    both sides -- so the case is rebuilt and re-serialised, and the line the
    host would get is compared instead. A field that changes the run and does
    not survive the round trip shows up there and nowhere else.
    """
    out: list[Violation] = []
    try:
        row = dict(s.report(case))
        back = s.rebuild(row)
        again = dict(s.report(back))
    except ValueError as exc:
        return [Violation(GENERATOR_REFUSED, case_id, "case", str(exc))]

    for key in sorted(set(row) | set(again)):
        if row.get(key) != again.get(key):
            out.append(Violation(
                REPORT_UNSTABLE, case_id, key,
                f"{row.get(key)!r} became {again.get(key)!r}"))

    try:
        before = s.serialize(case, case_id)
        after = s.serialize(back, case_id)
    except ValueError as exc:
        return out + [Violation(GENERATOR_REFUSED, case_id, "case", str(exc))]
    if before != after:
        out.extend(_diff_lines(before, after, case_id, s))
    return out


def _diff_lines(before: str, after: str, case_id: str,
                s: Surfaces) -> list[Violation]:
    """Name the fields that a rebuild changed, rather than dumping two lines."""
    try:
        a, b = parse_line(before, s), parse_line(after, s)
    except ValueError as exc:
        return [Violation(MALFORMED_LINE, case_id, "line", str(exc))]

    out: list[Violation] = []
    for name in s.in_order:
        if a.in_shapes.get(name) != b.in_shapes.get(name):
            out.append(Violation(
                REPORT_LOSSY, case_id, name,
                f"shape {a.in_shapes.get(name)} rebuilt as "
                f"{b.in_shapes.get(name)}"))
        if a.in_values.get(name) != b.in_values.get(name):
            out.append(Violation(
                REPORT_LOSSY, case_id, name,
                f"values {a.in_values.get(name)} rebuilt as "
                f"{b.in_values.get(name)}"))
        if a.in_dtypes.get(name) != b.in_dtypes.get(name):
            out.append(Violation(
                REPORT_LOSSY, case_id, name,
                f"dtype {a.in_dtypes.get(name)} rebuilt as "
                f"{b.in_dtypes.get(name)}"))
    for attr in sorted(set(a.attrs) | set(b.attrs)):
        if a.attrs.get(attr) != b.attrs.get(attr):
            out.append(Violation(
                REPORT_LOSSY, case_id, attr,
                f"{a.attrs.get(attr)!r} rebuilt as {b.attrs.get(attr)!r}"))
    if a.deterministic != b.deterministic:
        out.append(Violation(
            REPORT_LOSSY, case_id, "deterministic",
            f"{a.deterministic} rebuilt as {b.deterministic}"))
    if not out:
        out.append(Violation(
            REPORT_LOSSY, case_id, "line",
            "the rebuilt line differs in a field the parser does not name"))
    return out


def audit_enums(case: Any, case_id: str, s: Surfaces) -> list[Violation]:
    """Whether every closed field names something the generator can build.

    A value outside the set does not fail: the shape tables reach a fallback
    and the case is replayed as a different, legal one. The run then records
    a name that never ran, which is worse than a crash because it is counted.
    """
    out: list[Violation] = []
    for name, allowed in s.enums.items():
        guard = s.enum_guards.get(name)
        if guard is not None and not guard(case):
            continue
        got = getattr(case, name, None)
        if got not in allowed:
            out.append(Violation(
                ENUM_OUT_OF_RANGE, case_id, name,
                f"{got!r} is not one of {tuple(allowed)}"))
    return out


def audit_materialisation(case: Any, case_id: str, s: Surfaces) -> list[Violation]:
    """Whether the expansion the exits share is self-consistent.

    Since the exits are made from one expansion, most of what this file used
    to compare cannot differ any more. What replaces those comparisons is
    this: the expansion is asked whether it contradicts itself, which is the
    only place the fault can now be.
    """
    if s.materialize is None:
        return []
    try:
        expanded = s.materialize(case, case_id)
    except (ValueError, KeyError) as exc:
        return [Violation(GENERATOR_REFUSED, case_id, "case", str(exc))]
    return [Violation(MATERIALISATION_INVALID, case_id, "expansion", problem)
            for problem in expanded.validate_contract()]


def audit(case: Any, case_id: str, s: Surfaces) -> list[Violation]:
    """Every check, against one case.

    A case that names something outside a closed set stops here. The
    generator now refuses to build it, so the remaining checks would report
    that refusal three more times and say nothing the first one did not.
    """
    bad_enums = audit_enums(case, case_id, s)
    if bad_enums:
        return bad_enums
    expansion = audit_materialisation(case, case_id, s)
    if any(v.kind == GENERATOR_REFUSED for v in expansion):
        return expansion
    serialised = audit_serialisation(case, case_id, s)
    if any(v.kind == GENERATOR_REFUSED for v in serialised):
        return expansion + serialised
    return expansion + serialised + audit_roundtrip(case, case_id, s)


@dataclass
class AuditReport:
    """What an audit over a batch of cases found."""

    checked: int = 0
    violations: list[Violation] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.violations

    def by_kind(self) -> dict[str, list[Violation]]:
        out: dict[str, list[Violation]] = {}
        for v in self.violations:
            out.setdefault(v.kind, []).append(v)
        return out

    def summary(self) -> str:
        if self.clean:
            return f"{self.checked} cases, contract holds"
        counts = ", ".join(
            f"{kind} x{len(items)}"
            for kind, items in sorted(self.by_kind().items()))
        return (f"{self.checked} cases, {len(self.violations)} violations "
                f"({counts})")


def audit_many(cases: Iterable[Any], s: Surfaces,
               prefix: str = "audit") -> AuditReport:
    """Audit a batch, naming each case by its position when it has no name."""
    report = AuditReport()
    for i, case in enumerate(cases):
        case_id = getattr(case, "tag", "") or f"{prefix}{i:04d}"
        report.checked += 1
        report.violations.extend(audit(case, case_id, s))
    return report
