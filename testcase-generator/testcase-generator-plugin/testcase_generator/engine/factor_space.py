from __future__ import annotations

from typing import Any


CRITICAL_SINGLE_FIELDS = (
    "DeterType",
    "IsTnd",
    "IsTndSwizzle",
    "IsDrop",
    "IsPse",
    "IsAttenMask",
    "IsRope",
    "has_varlen",
    "InputDType",
    "SplitAxis",
)


def _infer_domain_from_bits(bits: list[int]) -> list[int]:
    if not bits:
        return []
    width = max(bits) - min(bits) + 1
    return list(range(1 << width))


def _io_factors(operator_io: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in operator_io.get("required_inputs", []) or []:
        if isinstance(item, dict) and item.get("name"):
            out[item["name"]] = {
                "kind": "tensor",
                "required": True,
                "dtype_domain": item.get("dtype", []),
                "exist": [True],
            }
        elif isinstance(item, str):
            out[item] = {"kind": "tensor", "required": True, "exist": [True]}
    for item in operator_io.get("optional_inputs", []) or []:
        if isinstance(item, dict) and item.get("name"):
            out[item["name"]] = {
                "kind": "tensor",
                "required": False,
                "dtype_domain": item.get("dtype", []),
                "exist": [True, False],
            }
        elif isinstance(item, str):
            out[item] = {"kind": "tensor", "required": False, "exist": [True, False]}
    for item in operator_io.get("attrs", []) or []:
        if isinstance(item, dict) and item.get("name"):
            out[item["name"]] = {"kind": "attr", "required": bool(item.get("required", False))}
        elif isinstance(item, str):
            out[item] = {"kind": "attr", "required": False}
    return out


def _build_solver(factor_fields: dict[str, Any], derived_fields: dict[str, Any]) -> dict[str, Any]:
    anchors: list[str] = []
    derived_names = set((derived_fields or {}).keys())
    for name, spec in factor_fields.items():
        if name in derived_names:
            continue
        if spec.get("constant") is not None:
            continue
        if not spec.get("domain"):
            continue
        anchors.append(name)

    level_1 = [n for n in derived_names if n in factor_fields]
    return {
        "strategy": "topological",
        "anchors": anchors,
        "derivation_order": {
            "level_0": anchors,
            "level_1": level_1,
            "level_2": ["family_id", "tilingdata_present", "numeric_overlay"],
        },
        "pairwise_candidate_fields": anchors[:6],
    }


def build_factor_space(snapshot: dict[str, Any]) -> dict[str, Any]:
    tiling = snapshot.get("tiling", {})
    key_space = tiling.get("key_space", {})
    families_doc = tiling.get("families", {})
    data_model = tiling.get("data_model", {})
    operator_io = snapshot.get("operator_io", {})

    fields = key_space.get("fields", {}) or {}
    factor_fields: dict[str, Any] = {}
    for name, spec in fields.items():
        domain = spec.get("domain")
        bits = spec.get("bits", []) or []
        if not domain and bits:
            domain = _infer_domain_from_bits(bits)
        factor_fields[name] = {
            "kind": "tiling_key_field",
            "type": "enum" if domain is not None else "unknown",
            "domain": domain or [],
            "bits": bits,
            "constant": spec.get("constant"),
            "derived_from": spec.get("derived_from"),
            "io_impact": spec.get("io_impact", []),
        }

    family_guards: dict[str, Any] = {}
    family_factors: dict[str, Any] = {}
    for fam_id, fam in (families_doc.get("families", {}) or {}).items():
        entry = {
            "kind": "family",
            "guard": fam.get("guard", {}),
            "reachability": fam.get("reachability", "unknown"),
            "struct_signature": fam.get("struct_signature", ""),
            "route_action": fam.get("route_action", ""),
            "key_pattern": fam.get("key_pattern", {}),
        }
        family_guards[fam_id] = entry
        family_factors[fam_id] = entry

    tilingdata_factors: dict[str, Any] = {}
    for struct_name, spec in (data_model.get("structs", {}) or {}).items():
        tilingdata_factors[struct_name] = {
            "kind": "tilingdata_block",
            "present_when": spec.get("present_when"),
            "fields": spec.get("fields", []),
            "coverage_points": spec.get("coverage_points", []),
        }

    numeric_overlay = data_model.get("numeric_overlay", {}) or {}
    solver = _build_solver(factor_fields, key_space.get("derived_fields", {}) or {})

    return {
        "version": 1,
        "op_name": snapshot.get("op_name"),
        "factors": {
            "key": factor_fields,
            "family": family_factors,
            "tilingdata": tilingdata_factors,
            "io": _io_factors(operator_io),
            "numeric_overlay": numeric_overlay,
        },
        # backward-compatible flat views used by prune/candidates
        "tiling_key_fields": factor_fields,
        "constants": key_space.get("constants", {}),
        "derived_fields": key_space.get("derived_fields", {}),
        "legal_constraints": key_space.get("legal_constraints", []),
        "unreachable": key_space.get("unreachable", []),
        "input_realization": key_space.get("input_realization", {}),
        "family_guards": family_guards,
        "tilingdata_structs": data_model.get("structs", {}),
        "numeric_overlay": numeric_overlay,
        "operator_io": operator_io,
        "critical_single_fields": [
            f for f in CRITICAL_SINGLE_FIELDS if f in factor_fields or f in numeric_overlay
        ],
        "solver": solver,
    }
