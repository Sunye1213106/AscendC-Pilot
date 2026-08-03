# -*- coding: utf-8 -*-
"""One case, expanded once into what the host is actually handed.

Four things are made from a case: the line the driver replays, the
environment the derivation evaluates, the row the report records, and the
audit that says those three agree. They used to be four functions reading the
case independently, which is why they disagreed -- the line special-cased a
dtype and the environment did not, and nothing made that impossible, only
detectable.

Here the expansion happens once. A tensor's presence, shape and dtype are
decided in a single place and every exit reads the same tuple, so the class
of bug E2 found cannot occur again: there is no second opinion to differ
from. What is left for the audit is the part that genuinely can drift -- the
round trip through the report, and values outside a closed set.

The operator's part is `materialize`. Everything below it is arithmetic on
the result and knows no operator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import prod
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

ROLE_INPUT = "input"
ROLE_OUTPUT = "output"


@dataclass(frozen=True)
class MaterializedTensor:
    """One tensor as the host will see it.

    `values` is for the tensors the host reads the contents of rather than
    only the extent. Its absence is not the empty tuple: a tensor nobody
    reads by value and one whose value is empty are different things.
    """

    name: str
    present: bool
    dims: tuple[int, ...] = ()
    #: The dtype the tensor is declared with, whether or not it is passed.
    #: The driver is told one for every slot -- a tensor's type is a property
    #: of the signature, not of this case -- while the derivation sees it
    #: only when the tensor is there, because a guard reading the dtype of an
    #: absent optional is reading nothing. One value, two readings.
    dtype: int = 0
    values: tuple[int, ...] | None = None
    #: Whether the host reads this tensor's contents at all. Distinct from
    #: having contents this time: a tensor the host reads by value always has
    #: the value variables, set to None when nothing was passed. Minting them
    #: only when a value turns up would make `env.get(var)` on an empty case
    #: indistinguishable from asking about a tensor nobody reads.
    read_by_value: bool = False
    role: str = ROLE_INPUT

    @property
    def elements(self) -> int | None:
        """Element count, or None when the tensor is absent.

        The distinction matters: expressions test `shape != nullptr` before
        they test `size != 0`, so folding an absent tensor to 0 flips those
        guards.
        """
        return prod(self.dims) if self.present and self.dims else None

    def csv_field(self) -> str:
        """The shape column, which carries contents when there are any."""
        if self.values is not None:
            return f"{len(self.values)}@" + "/".join(str(v) for v in self.values)
        return "|".join(str(x) for x in self.dims)


@dataclass(frozen=True)
class MaterializedAttr:
    """One attribute, and how the driver's line spells it.

    `text` exists because the line is a text protocol and the derivation is
    not. A scale factor is written to a fixed number of decimals for the
    driver and reasoned about exactly by the solver; those are two readings
    of one value, not two values, so the value is stored once and the
    rendering beside it.
    """

    name: str
    kind: str          # 'i', 'f' or 's', as the driver's parser expects
    value: Any
    text: str = ""     # empty: the line spells it with str()

    @property
    def rendered(self) -> str:
        return self.text or str(self.value)


@dataclass(frozen=True)
class ContextValue:
    """Something the host reads off the context rather than off an input.

    The session's deterministic flag and the platform's architecture are not
    arguments to the operator, but tiling branches on them, so the derivation
    needs them and they have to come from somewhere.
    """

    var_key: str
    value: Any


@dataclass(frozen=True)
class MaterializedCase:
    """A case, expanded. Every exit below reads only what is here."""

    case_id: str
    inputs: tuple[MaterializedTensor, ...] = ()
    outputs: tuple[MaterializedTensor, ...] = ()
    attrs: tuple[MaterializedAttr, ...] = ()
    context: tuple[ContextValue, ...] = ()
    #: The flat record the wide table stores, in column order.
    report: Mapping[str, Any] = field(default_factory=dict)
    #: Appended to the driver's line after the attrs. The driver reads a few
    #: things positionally rather than as attributes; which ones is the
    #: driver's business, so they arrive already rendered.
    driver_flags: tuple[str, ...] = ()

    # --- the four exits ---------------------------------------------------

    def serialize_for_host(self) -> str:
        """The line the driver replays."""
        return ";".join([
            self.case_id,
            ",".join(t.csv_field() for t in self.inputs),
            ",".join(str(t.dtype) for t in self.inputs),
            ",".join(t.csv_field() for t in self.outputs),
            ",".join(str(t.dtype) for t in self.outputs),
            "&".join(f"{a.name}={a.kind}:{a.rendered}" for a in self.attrs),
            *self.driver_flags,
        ])

    def build_static_env(self, spec: Any = None) -> dict[str, Any]:
        """The derivation's input variables, valued for this case.

        The spec decides which variables exist and what each reads; this
        supplies the readings. Passing none falls back to the operator's own
        spec, which is what every caller wants and none should have to say.
        """
        from . import bridge_spec as S
        if spec is None:
            spec = default_spec()
        return S.bind(spec, self)

    def report_inputs(self) -> dict[str, Any]:
        """The flat record for the wide table."""
        return dict(self.report)

    def validate_contract(self, *, enums: Mapping[str, Sequence[Any]] = (),
                          case: Any = None) -> list[str]:
        """What is still checkable now that the exits share one expansion.

        Presence, shape and dtype agreeing is no longer a claim worth
        testing: the two exits read the same tuple. What can still go wrong
        is inside the expansion -- a tensor present with no shape, a value
        tensor whose extent contradicts its contents, a dtype on something
        that is not there -- and those are what this reports.
        """
        problems: list[str] = []
        for tensor in (*self.inputs, *self.outputs):
            problems.extend(_tensor_problems(tensor))

        seen: set[str] = set()
        for tensor in (*self.inputs, *self.outputs):
            key = f"{tensor.role}:{tensor.name}"
            if key in seen:
                problems.append(f"{tensor.name}: listed twice as a {tensor.role}")
            seen.add(key)

        names = [a.name for a in self.attrs]
        if len(names) != len(set(names)):
            problems.append("an attribute is given more than once")
        for attr in self.attrs:
            if attr.kind not in ("i", "f", "s"):
                problems.append(
                    f"{attr.name}: kind {attr.kind!r} is not one the driver reads")

        keys = [c.var_key for c in self.context]
        if len(keys) != len(set(keys)):
            problems.append("a context value is given more than once")

        if case is not None:
            for name, allowed in dict(enums).items():
                got = getattr(case, name, None)
                if got not in allowed:
                    problems.append(
                        f"{name}: {got!r} is not one of {tuple(allowed)}")
        return problems


_SPEC: Any = None


def default_spec() -> Any:
    """The bridge spec of the operator this run is about.

    Loaded once and lazily, like the schema, so a module that only wants the
    dataclasses does not need an operator package on disk to import.
    """
    global _SPEC
    if _SPEC is None:
        from . import bridge_spec as S
        from .runner import default
        _SPEC = S.BridgeSpec.load(default().manifest.package / "bridge_spec.yaml")
    return _SPEC


def use_spec(spec: Any) -> None:
    """Point the default at another spec. For tests and for a second operator."""
    global _SPEC
    _SPEC = spec


def _tensor_problems(tensor: MaterializedTensor) -> list[str]:
    out: list[str] = []
    if tensor.present and not tensor.dims:
        out.append(f"{tensor.name}: present with no shape")
    if not tensor.present and tensor.dims:
        out.append(f"{tensor.name}: absent but carries a shape {tensor.dims}")
    if tensor.values is not None and tensor.present \
            and tensor.dims != (len(tensor.values),):
        out.append(
            f"{tensor.name}: read by value, so its extent should be "
            f"{(len(tensor.values),)} and is {tensor.dims}")
    if any(d < 0 for d in tensor.dims):
        out.append(f"{tensor.name}: negative extent in {tensor.dims}")
    if tensor.role not in (ROLE_INPUT, ROLE_OUTPUT):
        out.append(f"{tensor.name}: role {tensor.role!r} is neither")
    return out


@runtime_checkable
class OperatorInputAdapter(Protocol):
    """The one thing an operator has to supply.

    Everything the engine does with a case, it does with the result of this.
    An operator that can expand its own cases needs no other engine change,
    which is the whole claim P2 is here to make good on.
    """

    def materialize(self, case: Any, case_id: str) -> MaterializedCase:
        """Expand a case into what the host will be handed."""
        ...
