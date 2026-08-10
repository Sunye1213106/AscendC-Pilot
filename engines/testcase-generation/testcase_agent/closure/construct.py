# -*- coding: utf-8 -*-
"""Build the input a target key asks for, instead of searching for it.

CodeMap-directed path:
  target dims → TILING_KEY packing → host producers/guards → reads → knobs → Case

``construction_hints.yaml`` is an adapter table used only when CodeMap cannot
spell a case yet (empty producers / no product).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from testcase_agent.closure import workspace as W

# Last CodeMap construct traces (entity ids / packing) for audit.
_LAST_TRACES: list[dict[str, Any]] = []


def last_traces() -> list[dict[str, Any]]:
    return list(_LAST_TRACES)


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


def _find_uo_product() -> Path | None:
    root = os.environ.get("ASCENDC_PROJECT_ROOT") or os.environ.get("UO_OP_DIR") or ""
    if not root:
        try:
            ws = W.default_workspace()
            # .../.ascendc-pilot/<arch>/tg/closure → op root
            root = str(Path(ws.state).parents[3])
        except Exception:
            return None
    try:
        from uo_init.store.reader import find_uo_product

        op = os.environ.get("UO_OPERATOR") or ""
        arch = os.environ.get("UO_ARCH") or ""
        return find_uo_product(Path(root), op_name=op, architecture=arch)
    except Exception:
        return None


def _codemap_build(t: Mapping[str, str], *, seed: int = 0) -> list:
    """Spell cases by walking CodeMap packing → producer → knobs."""
    del seed
    global _LAST_TRACES
    _LAST_TRACES = []
    product = _find_uo_product()
    if product is None:
        return []
    try:
        from uo_init.query.engine import CodeMapQuery
        from uo_init.store.reader import load_view_blob, read_codemap
    except Exception:
        return []

    cm = read_codemap(product)
    q = CodeMapQuery(cm, path=str(product))
    view = load_view_blob(product, "ir/tg_host_view.yaml") or {}
    if not isinstance(view, dict):
        view = {}

    I = W.replay_inputs()
    sem = getattr(I, "SEMANTICS", None)
    if sem is None or not hasattr(sem, "from_knobs"):
        return []

    # Base knobs from hints defaults when present.
    hints = _hints()
    defaults = dict(hints.get("defaults") or {})
    dtype_dim = str(hints.get("dtype_dim") or "InputDType")
    dtype_map = _dtype_map()
    dtype = dtype_map.get(str(t.get(dtype_dim)))
    if dtype is None:
        # Best-effort dtype from common names
        dtype = {
            "0": "float16",
            "1": "bfloat16",
            "2": "float",
            "3": "float8_e5m2",
            "4": "float8_e4m3fn",
            "5": "hifloat8",
            "6": "float",
        }.get(str(t.get(dtype_dim)), "float16")

    knobs = dict(defaults)
    knobs["dtype"] = dtype
    traces: list[dict[str, Any]] = []

    # Map each target dim via declared_keys packing + host fields.
    declared = view.get("declared_keys") or {}
    fields = list(view.get("fields") or [])
    uo_yaml_root = product.parent  # not used by CodemapQuery(.uo); knobs_for_field needs uo dir
    # Prefer arch uo dir beside product for feature_bindings compatibility
    arch_uo = None
    try:
        arch_uo = str(Path(W.default_workspace().state).parent.parent / "uo")
    except Exception:
        arch_uo = str(product.parent)

    from testcase_agent.closure.generate import knobs_for_field

    for dim, want in t.items():
        meta = declared.get(dim) or {}
        packing = list(meta.get("packing") or [])
        host_fields = [
            f for f in fields
            if str(f.get("tiling_key") or "") == dim or str(f.get("name") or "") == dim
        ]
        cone: list[str] = []
        entity_ids: list[str] = []
        for f in host_fields:
            if f.get("entity_id"):
                entity_ids.append(str(f["entity_id"]))
            try:
                cone.extend(knobs_for_field(str(f.get("name") or dim), uo_root=arch_uo))
            except Exception:
                pass
        if not cone:
            try:
                cone.extend(knobs_for_field(dim, uo_root=arch_uo))
            except Exception:
                pass

        # Bool-like dims: set matching bool knobs when we know the mapping.
        if str(want) in {"0", "1"} and cone:
            for k in cone:
                if "dtype" in k.lower():
                    continue
                knobs[k] = True if str(want) == "1" else knobs.get(k, False)

        # Query tiling key entity for packing symbols.
        key_rows = q.tiling_keys()
        key_row = next((r for r in key_rows if r.get("name") == dim), None)
        if key_row and not packing:
            packing = list(key_row.get("host_packing_expressions") or [])

        traces.append(
            {
                "dim": dim,
                "want": str(want),
                "packing": packing,
                "host_fields": [str(f.get("name") or "") for f in host_fields],
                "entity_ids": entity_ids,
                "knob_cone": sorted(set(cone)),
            }
        )

    # Apply bool_knobs table from hints when CodeMap cone is incomplete.
    bool_knobs = hints.get("bool_knobs") or {}
    for dim, spec in bool_knobs.items():
        if not isinstance(spec, dict):
            continue
        knob = str(spec.get("knob") or "")
        if not knob:
            continue
        on_val = spec.get("on", True)
        off_val = spec.get("off", False)
        knobs[knob] = on_val if str(t.get(str(dim))) == "1" else off_val

    try:
        case = sem.from_knobs(knobs)
        if hasattr(sem, "repair"):
            case = sem.repair(case)
        out = [case.normalised() if hasattr(case, "normalised") else case]
    except Exception:
        out = []

    _LAST_TRACES = traces
    if out:
        for tr in traces:
            tr["spelled"] = True
    return out


def _hints_build(t: Mapping[str, str], seed: int = 0) -> list:
    """Cartesian construction from adapter ``construction_hints.yaml`` tables."""
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
        return []

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


def build(t: Mapping[str, str], seed: int = 0) -> list:
    """Spellings of one target key, most likely first.

    Order: operator hook → CodeMap-directed → adapter hints tables.
    """
    # Operator hook still wins when present.
    I = W.replay_inputs()
    if hasattr(I, "construct_case"):
        try:
            hooked = list(I.construct_case(t) or [])
            if hooked:
                return hooked
        except Exception:
            pass

    coded = _codemap_build(t, seed=seed)
    if coded:
        return coded
    return _hints_build(t, seed=seed)


def explain(t: Mapping[str, str], seed: int = 0) -> list[str]:
    """Diagnostic notes for a target — never a reachability verdict."""
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
        reasons.append("constructor:empty")
        if _LAST_TRACES:
            reasons.append(f"codemap_trace_dims:{len(_LAST_TRACES)}")
        if not (hints.get("loops") or []):
            reasons.append("hints:no_loops")
    else:
        reasons.append(f"constructor:spelled:{len(built)}")
        if _LAST_TRACES:
            reasons.append("constructor:codemap_directed")
    return reasons
