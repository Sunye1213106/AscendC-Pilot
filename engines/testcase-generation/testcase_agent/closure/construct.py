# -*- coding: utf-8 -*-
"""Build the input a target key asks for, instead of searching for it.

Tables live in ``operators/<op>/<arch>/construction_hints.yaml``. Missing
hints are empty (cold-start / before ``export_adapter_pack``).

The engine never names operator-specific Key dimensions. Loops, bool knobs
and post-rules are declared in yaml (``loops`` / ``bool_knobs`` / ``post``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from testcase_agent.closure import workspace as W


@lru_cache(maxsize=4)
def _hints() -> dict[str, Any]:
    """Construction tables from the adapter pack; empty when not exported yet."""
    from replay.package_data import load_yaml

    return load_yaml("construction_hints.yaml") or {}


def _table(name: str) -> dict[str, Any]:
    raw = _hints().get(name) or {}
    return {str(k): v for k, v in raw.items()}


def _dtype_map() -> dict[str, str]:
    raw = _hints().get("dtype") or {}
    return {str(k): str(v) for k, v in raw.items()}


def build(t: Mapping[str, str], seed: int = 0) -> list:
    """Spellings of one target key, most likely first.

    Optional operator hook ``construct_case(target)`` overrides entirely.
    Otherwise interprets ``loops`` / ``bool_knobs`` / ``post`` from hints.
    """
    del seed
    I = W.replay_inputs()
    hints = _hints()
    require = hints.get("require") or {}
    for dim, want in require.items():
        if str(t.get(str(dim))) != str(want):
            return []

    if hasattr(I, "construct_case"):
        return list(I.construct_case(t) or [])

    sem = I.SEMANTICS
    if not hasattr(sem, "from_knobs"):
        raise TypeError("InputSemantics.from_knobs required for construct.build")

    dtype_dim = str(hints.get("dtype_dim") or "InputDType")
    out_dtype_dim = str(hints.get("out_dtype_dim") or dtype_dim)
    dtype = _dtype_map().get(str(t.get(dtype_dim)))
    if dtype is None:
        return []
    if str(t.get(out_dtype_dim, t.get(dtype_dim))) != str(t.get(dtype_dim)):
        if not hints.get("allow_out_dtype_mismatch"):
            return []

    loops = list(hints.get("loops") or [])
    if not loops:
        # No declared construction loops → nothing to enumerate.
        return []

    # Expand cartesian product of loop axes declared in yaml.
    axes: list[list[dict[str, Any]]] = []
    for loop in loops:
        table_name = str(loop.get("table") or "")
        dim = str(loop.get("dim") or "")
        default = loop.get("default")
        when = loop.get("when")
        else_value = loop.get("else_value")
        table = _table(table_name) if table_name not in {"masks"} else {}
        key = str(t.get(dim)) if dim else ""

        choices: list[Any]
        if table_name == "masks":
            masks = [str(x) for x in (hints.get("masks") or [])]
            if when is not None and key == str(when):
                choices = masks
            else:
                choices = list(else_value or ["none"])
        elif table_name and key in table:
            choices = list(table[key] or [])
        elif default is not None:
            choices = list(default)
        else:
            choices = []

        axis: list[dict[str, Any]] = []
        knob = loop.get("knob")
        pair_knobs = loop.get("pair_knobs")
        for choice in choices:
            upd: dict[str, Any] = {}
            if pair_knobs and isinstance(choice, (list, tuple)) and len(choice) >= 2:
                for i, pk in enumerate(pair_knobs):
                    upd[str(pk)] = choice[i]
            elif knob:
                upd[str(knob)] = choice
            axis.append(upd)
        if not axis:
            return []
        axes.append(axis)

    # Cartesian product
    combos: list[dict[str, Any]] = [{}]
    for axis in axes:
        nxt: list[dict[str, Any]] = []
        for base in combos:
            for upd in axis:
                row = dict(base)
                row.update(upd)
                nxt.append(row)
        combos = nxt

    bool_knobs = hints.get("bool_knobs") or {}
    defaults = dict(hints.get("defaults") or {})
    out = []
    for combo in combos:
        knobs = dict(defaults)
        knobs["dtype"] = dtype
        knobs.update(combo)
        for dim, spec in bool_knobs.items():
            if not isinstance(spec, dict):
                continue
            knob = str(spec.get("knob") or "")
            on_val = spec.get("on", True)
            off_val = spec.get("off", False)
            if "off_default" in spec:
                off_val = knobs.get(knob, spec.get("off_default"))
            if "off_from_defaults" in spec:
                off_val = knobs.get(str(spec["off_from_defaults"]), knobs.get(knob))
            knobs[knob] = on_val if str(t.get(str(dim))) == "1" else off_val

        # Named derived rules (when/set) still supported.
        for rule in hints.get("derived") or []:
            when = rule.get("when") or {}
            if all(str(t.get(k)) == str(v) for k, v in when.items()):
                knobs.update(rule.get("set") or {})

        skip = False
        for step in hints.get("post") or []:
            kind = str(step.get("kind") or "")
            if kind == "skip_unless":
                when_knob = str(step.get("when_knob") or "")
                dim = str(step.get("dim") or "")
                allowed = [str(x) for x in (step.get("in") or [])]
                if knobs.get(when_knob) and str(t.get(dim)) not in allowed:
                    skip = True
                    break
            elif kind == "d1_split":
                dim = str(step.get("dim") or "")
                d_val = knobs.get("d")
                if d_val is None:
                    continue
                d_int = int(d_val)
                equal = str(step.get("equal") or "0")
                d1 = d_int if str(t.get(dim)) == equal else max(16, d_int // 2)
                if knobs.get("rope"):
                    d1 = None
                knobs["d1"] = d1
            elif kind == "s2_from_s1":
                dim = str(step.get("dim") or "")
                match = str(step.get("match") or "")
                then_val = step.get("then")
                else_as = step.get("else")
                if str(t.get(dim)) == match:
                    knobs["s2"] = then_val
                elif else_as == "s1":
                    knobs["s2"] = knobs.get("s1")
                elif else_as is not None:
                    knobs["s2"] = else_as
        if skip:
            continue

        try:
            case = sem.from_knobs(knobs)
            if hasattr(sem, "repair"):
                case = sem.repair(case)
            out.append(case.normalised() if hasattr(case, "normalised") else case)
        except Exception:
            pass
    return out


def explain(t: Mapping[str, str], seed: int = 0) -> list[str]:
    """Diagnostic notes for a target — never a reachability verdict.

    Prefers operator ``construct_reasons`` (rewrite-risk *hypotheses*) and
    whether ``build`` can spell a case.  Callers must still construct + replay;
    lemmas come from oracle HIT/REWRITE/REFUSE plus source proof, not from
    this list alone.
    """
    del seed
    I = W.replay_inputs()
    hints = _hints()
    reasons: list[str] = []
    require = hints.get("require") or {}
    for dim, want in require.items():
        if str(t.get(str(dim))) != str(want):
            reasons.append(f"require:{dim}={want}")
    if hasattr(I, "construct_reasons"):
        try:
            reasons.extend(str(x) for x in (I.construct_reasons(t) or []))
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"construct_reasons_error:{str(exc)[:120]}")
    try:
        built = build(t)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"construct.build error:{str(exc)[:120]}")
        return reasons or ["constructor:error"]
    if not built:
        reasons.append("constructor:no_case")
    elif reasons:
        reasons.append("constructor:best_effort_case_emitted")
    return reasons
