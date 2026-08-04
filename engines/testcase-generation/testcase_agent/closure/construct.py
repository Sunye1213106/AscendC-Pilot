# -*- coding: utf-8 -*-
"""Build the input a target key asks for, instead of searching for it.

Tables live in ``operators/<op>/<arch>/construction_hints.yaml``. Missing
hints fail closed — there is no engine-side FAG construction table.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from testcase_agent.closure import workspace as W


@lru_cache(maxsize=4)
def _hints() -> dict[str, Any]:
    from replay.package_data import load_yaml

    doc = load_yaml("construction_hints.yaml")
    if not doc:
        raise FileNotFoundError(
            "operators/<op>/<arch>/construction_hints.yaml is required"
        )
    return doc


def _dtype_map() -> dict[str, str]:
    raw = _hints().get("dtype") or {}
    return {str(k): str(v) for k, v in raw.items()}


def _d_for() -> dict[str, list[int]]:
    raw = _hints().get("d_for") or {}
    return {str(k): [int(x) for x in (v or [])] for k, v in raw.items()}


def _deter_for() -> dict[str, list[tuple[int, int]]]:
    raw = _hints().get("deter_for") or {}
    out: dict[str, list[tuple[int, int]]] = {}
    for k, rows in raw.items():
        out[str(k)] = [tuple(int(x) for x in row) for row in (rows or [])]  # type: ignore[misc]
    return out


def _s1_for() -> dict[str, list[int]]:
    raw = _hints().get("s1_for") or {}
    return {str(k): [int(x) for x in (v or [])] for k, v in raw.items()}


def _masks() -> list[str]:
    return [str(x) for x in (_hints().get("masks") or [])]


def build(t: Mapping[str, str], seed: int = 0) -> list:
    """Spellings of one target key, most likely first.

    Uses construction_hints tables. Optional operator hook
    ``construct_case(target)`` on the semantics module overrides entirely.
    """
    del seed
    I = W.replay_inputs()
    mod = I
    if hasattr(mod, "construct_case"):
        return list(mod.construct_case(t) or [])

    # Declared construction via yaml tables + from_knobs.
    sem = I.SEMANTICS
    if not hasattr(sem, "from_knobs"):
        raise TypeError("InputSemantics.from_knobs required for construct.build")

    dtype = _dtype_map().get(str(t.get("InputDType")))
    require = _hints().get("require") or {}
    for dim, want in require.items():
        if str(t.get(str(dim))) != str(want):
            return []
    if dtype is None:
        return []
    if str(t.get("OutDType", t.get("InputDType"))) != str(t.get("InputDType")):
        # Default symmetry unless hints say otherwise.
        if not _hints().get("allow_out_dtype_mismatch"):
            return []

    out = []
    for d in _d_for().get(str(t.get("DTemplateNum")), []):
        for s1 in _s1_for().get(str(t.get("S1TemplateNum")), [1024]):
            for det, sparse in _deter_for().get(str(t.get("DeterType")), [(0, 0)]):
                for mask in (_masks() if str(t.get("IsAttenMask")) == "1" else ["none"]):
                    knobs = dict(_hints().get("defaults") or {})
                    knobs.update({
                        "dtype": dtype,
                        "d": d,
                        "s1": s1,
                        "sparse_mode": sparse,
                        "deterministic": det,
                        "atten_mask": mask,
                        "rope": str(t.get("IsRope")) == "1",
                        "pse": str(t.get("IsPse")) == "1",
                        "keep_prob": 0.5 if str(t.get("IsDrop")) == "1" else 1.0,
                        "g": 1 if str(t.get("IsNEqual")) == "1" else knobs.get("g", 2),
                        "layout": "TND" if str(t.get("IsTnd")) == "1" else knobs.get("layout", "BSND"),
                    })
                    # Derived rules from hints.
                    for rule in _hints().get("derived") or []:
                        when = rule.get("when") or {}
                        if all(str(t.get(k)) == str(v) for k, v in when.items()):
                            knobs.update(rule.get("set") or {})
                    if knobs.get("rope") and str(t.get("DTemplateNum")) not in (
                        str(x) for x in (_hints().get("rope_d_templates") or ["192"])
                    ):
                        continue
                    d1 = d if str(t.get("IsDNoEqual")) == "0" else max(16, d // 2)
                    if knobs.get("rope"):
                        d1 = None
                    knobs["d1"] = d1
                    knobs["s2"] = 1024 if str(t.get("S2TemplateNum")) == "128" else s1
                    try:
                        case = sem.from_knobs(knobs)
                        if hasattr(sem, "repair"):
                            case = sem.repair(case)
                        out.append(case.normalised() if hasattr(case, "normalised") else case)
                    except Exception:
                        pass
    return out
