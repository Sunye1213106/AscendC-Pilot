# -*- coding: utf-8 -*-
"""Which case quantity sets which derivation variable, read from a file.

The bridge used to assert this mapping by hand, in the forward direction: a
table of tensors, each turned into eight variables. That is the wrong way
round twice over. It supplied 197 variables where the derivation reads 50,
and it could not say what happened to a variable the derivation reads and
nothing sets -- those simply came out missing, and an evaluator's `env.get`
cannot tell a variable that was never modelled from one whose value is
genuinely unknown.

The spec goes the other way: it starts from what the derivation reads, and
every one of those variables has to be accounted for. Either something in the
case sets it, or it is listed as unbound with a reason. There is no third
outcome, and a variable that appears in neither list is a spec that no longer
matches the derivation it was exported from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

#: What a bound variable is read off. The name says which quantity, not which
#: operator: `tensor_axis` is one axis of some tensor, whichever tensor the
#: entry names.
TENSOR_PRESENCE = "optional_presence"
TENSOR_NUMEL = "tensor_numel"
TENSOR_RANK = "tensor_rank"
TENSOR_AXIS = "tensor_axis"
TENSOR_AXIS_LAST = "tensor_axis_last"
TENSOR_DTYPE = "tensor_dtype"
TENSOR_VALUES = "tensor_values"
TENSOR_VALUE_LAST = "tensor_value_last"
TENSOR_VALUE_SECOND = "tensor_value_second"
TENSOR_VALUE_MAX = "tensor_value_max"
ATTR = "attr"
CONTEXT = "context"

TENSOR_KINDS = frozenset({
    TENSOR_PRESENCE, TENSOR_NUMEL, TENSOR_RANK, TENSOR_AXIS, TENSOR_AXIS_LAST,
    TENSOR_DTYPE, TENSOR_VALUES, TENSOR_VALUE_LAST, TENSOR_VALUE_SECOND,
    TENSOR_VALUE_MAX,
})
KINDS = TENSOR_KINDS | {ATTR, CONTEXT}


class SpecError(Exception):
    """A spec that cannot be honoured, said in terms of what to fix."""


@dataclass(frozen=True)
class Binding:
    """One variable, and where its value comes from."""

    var: str
    root: str
    kind: str
    #: The tensor or attribute this reads, as the operator definition spells
    #: it. Empty for `context`, which reads neither.
    operand: str = ""
    axis: int | None = None
    #: For `context`: the value, which is a property of the run rather than
    #: of the case.
    value: Any = None


@dataclass(frozen=True)
class Unbound:
    """A variable the derivation reads that no input can set.

    Written down rather than left out. Most of these are tiling state -- the
    host decides them partway through, so no case sets them and a dimension
    reading one is honestly unpredictable. Recording the reason is what keeps
    that an answer instead of a gap.
    """

    var: str
    root: str
    reason: str


@dataclass(frozen=True)
class Observation:
    """Host state a run reported, and the variable it fills.

    An observation is not a prediction: the logged value is what the tiling
    computed. `withheld_from` names the dimension it was read off, so using
    it to predict that same dimension -- where the answer would be the
    question -- can be refused.
    """

    var: str
    column: str
    withheld_from: str
    reading: str = "integer"
    when_true: Any = None
    when_false: Any = None

    def value(self, raw: int) -> Any:
        if self.reading == "boolean":
            return bool(raw)
        if self.reading == "boolean_constant":
            return self.when_true if raw else self.when_false
        return raw


@dataclass(frozen=True)
class BridgeSpec:
    """Everything the derivation reads, each accounted for exactly once."""

    operator: str
    arch: str
    bindings: tuple[Binding, ...] = ()
    unbound: tuple[Unbound, ...] = ()
    observations: tuple[Observation, ...] = ()
    #: Recorded so a spec exported from one derivation is not silently used
    #: against another.
    source: Mapping[str, Any] = field(default_factory=dict)

    @property
    def variables(self) -> frozenset[str]:
        return frozenset(
            [b.var for b in self.bindings] + [u.var for u in self.unbound])

    def tensors(self) -> frozenset[str]:
        """Tensors any binding reads, which is fewer than the operator has."""
        return frozenset(b.operand for b in self.bindings
                         if b.kind in TENSOR_KINDS)

    def attrs(self) -> frozenset[str]:
        return frozenset(b.operand for b in self.bindings if b.kind == ATTR)

    def identities(self) -> dict[str, str]:
        """What each bound variable denotes, as a name two readings can share.

        The solver isolates a variable per dimension unless it can show the
        two dimensions mean the same thing by it, and it shows that from the
        variable model -- which has no entry for a shape variable, so it
        isolates every one of them. That is not conservatism working, it is
        the conflicts that matter going undetected: `query` cannot have one D
        in the dimension deciding `DTemplateNum` and another in the one
        deciding `IsDNoEqual`, and while they were separate integers the
        solver had no way to say so.

        A binding is exactly the missing evidence. It was exported from the
        derivation and says which tensor and which axis, so two readings that
        land on the same operand and axis are one number and may be shared.
        Anything the spec lists as unbound stays isolated: no claim, no share.
        """
        out: dict[str, str] = {}
        for b in self.bindings:
            axis = "" if b.axis is None else f".{b.axis}"
            out[b.var] = f"{b.kind}:{b.operand}{axis}" if b.operand else b.kind
        return out

    @staticmethod
    def load(path: str | Path) -> "BridgeSpec":
        path = Path(path)
        if not path.is_file():
            raise SpecError(f"no bridge spec at {path}")
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, Mapping):
            raise SpecError(f"{path}: expected a mapping at the top level")

        bindings, seen = [], set()
        for var, entry in (doc.get("bindings") or {}).items():
            kind = str(entry.get("kind") or "")
            if kind not in KINDS:
                raise SpecError(
                    f"{path}: {var} is read as {kind!r}; expected one of "
                    f"{sorted(KINDS)}")
            if kind in TENSOR_KINDS and not entry.get("tensor"):
                raise SpecError(f"{path}: {var} reads a tensor and names none")
            if kind == ATTR and not entry.get("attr"):
                raise SpecError(f"{path}: {var} reads an attr and names none")
            if kind == TENSOR_AXIS and entry.get("axis") is None:
                raise SpecError(f"{path}: {var} reads an axis and names none")
            bindings.append(Binding(
                var=var,
                root=str(entry.get("root") or ""),
                kind=kind,
                operand=str(entry.get("tensor") or entry.get("attr") or ""),
                axis=entry.get("axis"),
                value=entry.get("value"),
            ))
            seen.add(var)

        unbound = []
        for var, entry in (doc.get("unbound") or {}).items():
            if var in seen:
                raise SpecError(
                    f"{path}: {var} is both bound and unbound; the spec has to "
                    f"say one thing about each variable")
            if not entry.get("reason"):
                raise SpecError(
                    f"{path}: {var} is unbound with no reason. An unexplained "
                    f"gap is what this file exists to prevent")
            unbound.append(Unbound(var=var, root=str(entry.get("root") or ""),
                                   reason=str(entry["reason"])))

        return BridgeSpec(
            operator=str(doc.get("operator") or ""),
            arch=str(doc.get("arch") or ""),
            bindings=tuple(bindings),
            unbound=tuple(unbound),
            observations=_observations(doc, path),
            source=dict(doc.get("source") or {}),
        )


#: How an observation may read its logged number. `boolean_constant` is for
#: a flag the tiling logs whose variable holds a code rather than a boolean:
#: the two constants are named in the file and resolved at export.
READINGS = frozenset({"integer", "boolean", "boolean_constant"})


def _observations(doc: Mapping[str, Any], path: Path) -> tuple[Observation, ...]:
    out = []
    for raw in (doc.get("observations") or []):
        reading = str(raw.get("reading") or "integer")
        if reading not in READINGS:
            raise SpecError(
                f"{path}: {raw.get('variable')} is read as {reading!r}; "
                f"expected one of {sorted(READINGS)}")
        if not raw.get("withheld_from"):
            raise SpecError(
                f"{path}: {raw.get('variable')} names no dimension it was read "
                f"from. Without it the observation could be used to predict "
                f"the very field it came from, which proves nothing")
        for key in ("when_true", "when_false"):
            if reading == "boolean_constant" and raw.get(key) is None:
                raise SpecError(
                    f"{path}: {raw.get('variable')} reads two constants and "
                    f"{key} is unresolved; the export could not find that "
                    f"name among the operator's constexprs")
        out.append(Observation(
            var=str(raw["variable"]),
            column=str(raw["column"]),
            withheld_from=str(raw["withheld_from"]),
            reading=reading,
            when_true=raw.get("when_true"),
            when_false=raw.get("when_false"),
        ))
    return tuple(out)


def squash(text: str) -> str:
    """Compare operand names without caring how they are punctuated.

    The definition spells a tensor `query_rope`, the replay case calls it
    `queryRope`, and the derivation slugs the C++ index enum to
    `QUERY_ROPE_IDX`. One tensor; only the separators moved. The exporter
    matches the definition to the variable this way, and the runtime matches
    the case to the definition the same way, so the two ends cannot drift
    into disagreeing about what counts as the same name.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def bind(spec: BridgeSpec, case: Any) -> dict[str, Any]:
    """Value every bound variable off one expanded case.

    Only the variables the spec names. A variable the derivation never reads
    is not supplied at all, which used to be 157 of them -- harmless to the
    solver but not to a reader trying to work out which of them mattered.
    """
    tensors = {squash(t.name): t for t in (*case.inputs, *case.outputs)}
    attrs = {squash(a.name): a for a in case.attrs}
    env: dict[str, Any] = {}

    for b in spec.bindings:
        if b.kind == CONTEXT:
            env[b.var] = _context(case, b)
            continue
        if b.kind == ATTR:
            attr = attrs.get(squash(b.operand))
            if attr is None:
                raise SpecError(
                    f"{b.var} reads attr {b.operand!r}, which the case does "
                    f"not carry; the spec and the adapter disagree about the "
                    f"operator's signature")
            env[b.var] = attr.value
            continue
        tensor = tensors.get(squash(b.operand))
        if tensor is None:
            raise SpecError(
                f"{b.var} reads tensor {b.operand!r}, which the case does not "
                f"carry; the spec and the adapter disagree about the "
                f"operator's signature")
        env[b.var] = _tensor(tensor, b)
    return env


def _context(case: Any, b: Binding) -> Any:
    for item in case.context:
        if item.var_key == b.var:
            return item.value
    # A context value the spec knows and the case does not is the run's to
    # supply, not the case's -- the architecture is the same for every case.
    return b.value


def _tensor(tensor: Any, b: Binding) -> Any:
    """One reading of one tensor.

    Absent is None throughout rather than zero. The host tests the pointer
    before it tests the size, so folding the two together flips the guard
    that selects the absent-tensor branch.
    """
    if b.kind == TENSOR_PRESENCE:
        return tensor.present
    if not tensor.present:
        return None
    if b.kind == TENSOR_NUMEL:
        return tensor.elements
    if b.kind == TENSOR_RANK:
        return len(tensor.dims)
    if b.kind == TENSOR_DTYPE:
        return tensor.dtype
    if b.kind == TENSOR_AXIS:
        assert b.axis is not None
        return tensor.dims[b.axis] if b.axis < len(tensor.dims) else None
    if b.kind == TENSOR_AXIS_LAST:
        return tensor.dims[-1] if tensor.dims else None

    # The value readings. A tensor the host reads by value always answers
    # these, with None when nothing was passed.
    vec = list(tensor.values or ())
    if b.kind == TENSOR_VALUES:
        return vec or None
    if not vec:
        return None
    if b.kind == TENSOR_VALUE_LAST:
        return vec[-1]
    if b.kind == TENSOR_VALUE_SECOND:
        return vec[1] if len(vec) > 1 else None
    if b.kind == TENSOR_VALUE_MAX:
        return max(vec)
    raise SpecError(f"{b.var}: no reading is defined for kind {b.kind!r}")
