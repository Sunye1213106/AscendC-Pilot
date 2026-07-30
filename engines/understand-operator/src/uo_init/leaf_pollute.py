# -*- coding: utf-8 -*-
"""Value-leaf pollution: a leaf must be a value the declared domain allows.

The check is source-driven. Enum members and `constexpr` names already resolve
to integers in `VariableModel.named_constants`, so `DtypeEnum::FLOAT32` can be
compared against the TPL domain `['0'..'6']` without anyone writing down that
`FLOAT32` means 1. An operator-specific alias table would be the same knowledge
entered by hand, and it would silently stop matching the moment the enum moves.

Reporting only. Whether a dimension is *allowed* to fold to one value is a
statement about that operator's source, so it belongs in a fixture assertion,
not in the engine.
"""
from __future__ import annotations

from typing import Any, Mapping

from uo_init.derive_key_fields import value_leaves  # re-exported

__all__ = ["value_leaves", "short", "leaf_int", "pollute_leaves", "constant_fold"]

_TRUE_FORMS = frozenset({"True", "true", "ENABLE"})
_FALSE_FORMS = frozenset({"False", "false", "DISABLE"})


def short(value: str) -> str:
    """`DtypeEnum::FLOAT32` -> `FLOAT32`."""
    return str(value).split("::")[-1]


def leaf_int(leaf: str, named_constants: Mapping[str, int] | None = None) -> int | None:
    """Integer a leaf stands for, when the source proves one."""
    text = str(leaf).strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return int(text)
    if text in _TRUE_FORMS:
        return 1
    if text in _FALSE_FORMS:
        return 0
    consts = named_constants or {}
    got = consts.get(text)
    if got is None:
        got = consts.get(short(text))
    return int(got) if got is not None else None


def pollute_leaves(
    name: str,
    domain: list[str],
    leaves: Any,
    *,
    named_constants: Mapping[str, int] | None = None,
) -> list[str]:
    """Leaves that the declared domain does not admit.

    `name` is kept for call-site readability and error messages; nothing about
    the check depends on it.
    """
    del name
    allowed_text = {str(d) for d in domain} | {short(str(d)) for d in domain}
    allowed_int = {
        v for v in (leaf_int(d, named_constants) for d in domain) if v is not None
    }
    bad: list[str] = []
    for leaf in sorted(str(x) for x in (leaves or [])):
        if leaf in allowed_text or short(leaf) in allowed_text:
            continue
        as_int = leaf_int(leaf, named_constants)
        if as_int is not None and as_int in allowed_int:
            continue
        bad.append(leaf)
    return bad


def constant_fold(value_expr: Any) -> Any | None:
    """The literal this expression folded to, or None if it stayed symbolic.

    A dimension folding to one value is sometimes correct — a platform flag
    hard-wired by the arch path — and sometimes a derivation that lost its
    guards. The engine cannot tell those apart, so it reports the fact and
    leaves the judgement to the operator's fixture.
    """
    if isinstance(value_expr, dict) and set(value_expr) == {"lit"}:
        return value_expr["lit"]
    return None
