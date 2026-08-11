# -*- coding: utf-8 -*-
"""Per-key steerable branch outcome ledger: T = (R ∩ T) ∪ E over (site, outcome).

Elements are ``(site_id, outcome)`` where ``outcome`` is True/False and
``site_id`` is a stable branch id (``file:line`` or UO BRANCH id).

  * R grows from host replay + TD decode + ``branch_eval.evaluate``
  * E grows from key-determined evaluation or lemma field pins
  * gap = goal − covered − excluded  (must reach 0 for a closed key)

This reuses the TilingKey closure identity without a parallel td-* workflow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from testcase_agent.closure.branch_eval import Env, Outcome, evaluate
from testcase_agent.closure import field_pins


Site = tuple[str, int] | str  # (file, line) or stable id string
OutcomeKey = tuple[str, bool]  # (site_id, True|False)


def site_id(branch: dict[str, Any]) -> str:
    if branch.get("id"):
        return str(branch["id"])
    f, ln = branch.get("file"), branch.get("line")
    if f is not None and ln is not None:
        return f"{f}:{ln}"
    return str(branch.get("name") or branch.get("condition") or "?")


@dataclass
class KeyBranchLedger:
    """Coverage state for one tiling key's steerable branches."""

    key: int | str
    dims: dict[str, Any] = field(default_factory=dict)
    live: set[str] = field(default_factory=set)
    covered: set[OutcomeKey] = field(default_factory=set)
    excluded: set[OutcomeKey] = field(default_factory=set)

    @property
    def goal(self) -> set[OutcomeKey]:
        return {(s, o) for s in self.live for o in (True, False)}

    @property
    def open_set(self) -> set[OutcomeKey]:
        return self.goal - self.covered - self.excluded

    @property
    def gap(self) -> int:
        return len(self.open_set)

    def summary(self) -> dict[str, Any]:
        excl = self.excluded - self.covered
        return {
            "key": self.key,
            "live": len(self.live),
            "goal": len(self.goal),
            "covered": len(self.covered),
            "excluded": len(excl),
            "gap": len(self.goal - self.covered - excl),
            "open": sorted(
                (s, str(o)) for s, o in (self.goal - self.covered - excl)
            ),
        }


def state_of(
    branch: dict[str, Any],
    env: Env,
    *,
    absent_members: set[str] | None = None,
    present_leaves: set[str] | None = None,
    owner: dict[str, str] | None = None,
) -> tuple[str, tuple[bool, ...], tuple[bool, ...]]:
    """(state, observed outcomes, excluded opposite outcomes)."""
    fields = list(branch.get("fields") or branch.get("tilingdata_fields") or [])
    absent = absent_members or set()
    present = present_leaves
    owner = owner or {}
    if fields and present is not None:
        gone = {owner.get(f, "") for f in fields} & absent
        unknown = [f for f in fields if f not in present]
        if gone or (unknown and len(unknown) == len(fields)):
            return "unreachable", (), ()
    cond = str(branch.get("condition") or branch.get("predicate") or "")
    if not cond:
        return "undecided", (), ()
    oc: Outcome = evaluate(cond, env)
    if oc.both_ways:
        return "both", (True, False), ()
    if oc.value is None:
        return "undecided", (), ()
    excluded = (not oc.value,) if oc.key_determined else ()
    return ("true" if oc.value else "false"), (oc.value,), excluded


def absorb_observation(
    ledger: KeyBranchLedger,
    branches: Iterable[dict[str, Any]],
    env: Env,
    *,
    absent_members: set[str] | None = None,
    present_leaves: set[str] | None = None,
    owner: dict[str, str] | None = None,
) -> int:
    """Fold one TD observation into the ledger; return newly covered count."""
    gained = 0
    for branch in branches:
        sid = site_id(branch)
        state, outs, excl = state_of(
            branch, env,
            absent_members=absent_members,
            present_leaves=present_leaves,
            owner=owner,
        )
        if state == "unreachable":
            continue
        ledger.live.add(sid)
        if state == "undecided":
            continue
        for o in excl:
            ledger.excluded.add((sid, o))
        for o in outs:
            if (sid, o) not in ledger.covered:
                ledger.covered.add((sid, o))
                gained += 1
    ledger.excluded -= ledger.covered
    return gained


def index_field_aliases(fields: dict[str, Any]) -> dict[str, Any]:
    """Expand leaf field maps so flattened condition names resolve.

    Host decode / callers often supply only ``{"sinkOptional": 1}``. Conditions
    name ``tilingData->base.sinkOptional`` which flattens to
    ``__td__base__sinkOptional``. Binding the leaf under every spelling the
    evaluator may ask for keeps Env construction operator-agnostic.
    """
    from testcase_agent.closure.branch_eval import TD_PREFIX, flat_name

    out = dict(fields)
    for key, val in list(fields.items()):
        leaf = field_pins.flat_leaf(key)
        out.setdefault(leaf, val)
        out.setdefault(flat_name(leaf), val)
        if "." in key:
            struct, leaf2 = key.rsplit(".", 1)
            out.setdefault(flat_name(struct, leaf2), val)
        # Also accept already-flattened keys' leaves.
        if key.startswith(TD_PREFIX):
            out.setdefault(field_pins.flat_leaf(key), val)
    return out


def build_env(
    *,
    fields: dict[str, Any],
    dims: dict[str, Any],
    enums: dict[str, Any] | None = None,
    param_to_dim: dict[str, str] | None = None,
    block_num: int = 0,
    derived: dict[str, str] | None = None,
    pins: dict[str, Any] | None = None,
    rules_path: str | None = None,
    usable_path: str | None = None,
) -> Env:
    pinned = dict(pins or {})
    if rules_path and not pinned:
        pinned = field_pins.load_pinned(
            dims, rules_path=rules_path, usable_path=usable_path
        )
    # Pins also need leaf aliases so flattened names hit them.
    pinned = index_field_aliases(pinned)
    return Env(
        fields=index_field_aliases(fields),
        dims={k: int(v) for k, v in dims.items()
              if str(v).lstrip("-").isdigit() or isinstance(v, int)},
        param_to_dim=dict(param_to_dim or {}),
        enums=dict(enums or {}),
        block_num=int(block_num or 0),
        derived=dict(derived or {}),
        pinned=pinned,
    )


def close_key(
    key: int | str,
    dims: dict[str, Any],
    branches: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    enums: dict[str, Any] | None = None,
    param_to_dim: dict[str, str] | None = None,
    derived: dict[str, str] | None = None,
    rules_path: str | None = None,
    usable_path: str | None = None,
) -> KeyBranchLedger:
    """Run all observations for one key and return the ledger summary state.

    Each observation: ``{"fields": {...}, "block_num": N}``.
    """
    ledger = KeyBranchLedger(key=key, dims=dict(dims))
    for obs in observations:
        env = build_env(
            fields=obs.get("fields") or {},
            dims=dims,
            enums=enums,
            param_to_dim=param_to_dim,
            block_num=int(obs.get("block_num") or 0),
            derived=derived,
            rules_path=rules_path,
            usable_path=usable_path,
        )
        absorb_observation(ledger, branches, env)
    return ledger
