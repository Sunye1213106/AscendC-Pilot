# -*- coding: utf-8 -*-
"""Mechanical checks a model's answer has to survive before it is believed.

`gap_patch.validate_patch` already refuses answers that are malformed: an
invented symbol, a value outside a declared domain, a quote that is not in the
source. Those catch a patch that is not *about* this operator. They say
nothing about whether a well-formed answer is *true*.

What can be checked mechanically, without a second opinion:

- **It reads what the code reads.** A condition standing in for an unreadable
  guard may only mention variables that stretch of code touches. Naming one it
  never sees is invention with the right spelling.
- **It decides something.** The guard it replaces is a branch in the source, so
  both ways through it exist. A condition that is true at every legal input, or
  false at every legal input, has replaced a branch with a constant.
- **It leaves the field inside its declared values.** Substituting the
  condition and walking the dimension forwards gives the values the field can
  then take. Values the kernel template never declared cannot be right, and no
  values at all means the answer contradicts the rest of the derivation.

Each failure carries a witness — the concrete input that shows it — so a
rejection is a fact the next attempt can read, not a verdict.

A check that was considered and dropped: comparing the substituted value
against the set the original expression could take over its free variables.
That set is built by giving the free variable every representative value, and
a condition can only ever pick one of them, so the comparison holds by
construction and rejects nothing.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Iterable

from uo_init.concrete_eval import (
    Premises,
    Unknown,
    ValueTree,
    domain_for,
    enumerate_cells,
    samples,
)

__all__ = ["GateFinding", "check_patch_condition", "condition_variables"]

#: How many input points a gate will walk before it gives up and says nothing.
#: Saying nothing is the only safe way to run out of budget here: a check that
#: reports a failure it did not establish is worse than one that abstains.
DEFAULT_CAP = 20_000


@dataclass(frozen=True)
class GateFinding:
    code: str
    message: str
    witness: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.witness is not None:
            out["witness"] = self.witness
        return out


def condition_variables(condition: Any) -> set[str]:
    return ValueTree(condition).variables()


def _points(
    names: Iterable[str],
    cuts: dict[str, set],
    domains: dict[str, Any],
    constants: dict[str, int] | None,
    cap: int,
) -> list[dict[str, Any]] | None:
    axes = [
        (v, samples(cuts.get(v, set()), domain_for(v, domains), constants))
        for v in sorted(names)
    ]
    total = 1
    for _, vals in axes:
        total *= len(vals)
    if total > cap:
        return None
    return [
        {v: x for (v, _), x in zip(axes, combo)}
        for combo in itertools.product(*[vals for _, vals in axes])
    ]


def check_reads_what_the_code_reads(
    condition: Any, readable: Iterable[str] | None
) -> list[GateFinding]:
    """Every variable the condition names must be one that stretch of code sees.

    Where the guard is unreadable, what it can possibly depend on is not: the
    walk recorded which variables the enclosing function or loop touches. A
    condition about something else describes different code.

    An empty `readable` is "not recorded", not "touches nothing", so it
    abstains — the check has to be silent where it has no information.
    """
    known = {str(v) for v in (readable or ())}
    if not known:
        return []
    stray = sorted(condition_variables(condition) - known)
    if not stray:
        return []
    return [
        GateFinding(
            "reads_what_the_code_cannot",
            f"condition names {stray}, which this code never reads",
        )
    ]


def check_condition_decides_something(
    condition: Any,
    *,
    domains: dict[str, Any] | None = None,
    constants: dict[str, int] | None = None,
    premises: Premises | None = None,
    cap: int = DEFAULT_CAP,
) -> list[GateFinding]:
    """A guard that never changes its mind has replaced a branch with a constant."""
    domains = domains or {}
    tree = ValueTree(condition)
    cuts, names = tree.cuts()
    if premises is not None:
        names = names | premises.vars
        for v, thresholds in premises.cuts.items():
            cuts.setdefault(v, set()).update(thresholds)
    points = _points(names, cuts, domains, constants, cap)
    if points is None:
        return []
    saw_true: dict[str, Any] | None = None
    saw_false: dict[str, Any] | None = None
    for env in points:
        if premises is not None and premises.rejects(env):
            continue
        try:
            got = tree.value(env)
        except Unknown:
            continue
        if got:
            saw_true = saw_true or env
        else:
            saw_false = saw_false or env
        if saw_true and saw_false:
            return []
    if saw_true is None and saw_false is None:
        return []
    if saw_false is None:
        return [
            GateFinding(
                "condition_never_false",
                "condition holds at every legal input, so it decides nothing "
                "the branch it replaces decided",
                witness=saw_true,
            )
        ]
    return [
        GateFinding(
            "condition_never_true",
            "condition fails at every legal input, so the branch it replaces "
            "would never be taken",
            witness=saw_false,
        )
    ]


def check_values_stay_declared(
    value_expr: Any,
    var_id: str,
    condition: Any,
    *,
    declared: Iterable[Any] | None,
    domains: dict[str, Any] | None = None,
    constants: dict[str, int] | None = None,
    premises: Premises | None = None,
    cap: int = DEFAULT_CAP,
) -> list[GateFinding]:
    """Put the condition in and walk the dimension: what can the field be now?

    The kernel template declares what the field is allowed to be. A condition
    that lets it be something else is wrong about the source, whatever it says
    about it — and one that leaves it able to be nothing at all contradicts the
    rest of the derivation just as plainly.
    """
    from uo_init.derive_key_fields import substitute_vars

    if value_expr is None:
        return []
    patched = substitute_vars(value_expr, {var_id: condition})
    out = enumerate_cells(
        patched,
        cap=cap,
        domains=domains or {},
        constants=constants,
        premises=premises,
    )
    if out.get("skipped"):
        return []
    values: dict[Any, dict[str, Any]] = out.get("values") or {}
    if not values:
        return [
            GateFinding(
                "no_values_left",
                "with this condition the field can take no value at all",
            )
        ]
    if declared is None:
        return []
    allowed = {str(v) for v in declared}
    if not allowed:
        return []
    findings = []
    for value, witness in values.items():
        if str(value) not in allowed:
            findings.append(
                GateFinding(
                    "value_outside_template",
                    f"with this condition the field can be {value!r}, which the "
                    f"template does not declare",
                    witness=witness,
                )
            )
    return findings


def check_patch_condition(
    condition: Any,
    *,
    var_id: str = "",
    value_expr: Any = None,
    readable: Iterable[str] | None = None,
    declared: Iterable[Any] | None = None,
    domains: dict[str, Any] | None = None,
    constants: dict[str, int] | None = None,
    premises: Premises | None = None,
    cap: int = DEFAULT_CAP,
) -> list[GateFinding]:
    """All three checks. An empty list means nothing mechanical objects."""
    findings = list(check_reads_what_the_code_reads(condition, readable))
    findings += check_condition_decides_something(
        condition,
        domains=domains,
        constants=constants,
        premises=premises,
        cap=cap,
    )
    if var_id and value_expr is not None:
        findings += check_values_stay_declared(
            value_expr,
            var_id,
            condition,
            declared=declared,
            domains=domains,
            constants=constants,
            premises=premises,
            cap=cap,
        )
    return findings
