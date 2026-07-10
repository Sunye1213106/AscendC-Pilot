from __future__ import annotations

from typing import Any


def _compile_legal_rules(key_space: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for idx, item in enumerate(key_space.get("legal_constraints", []) or [], start=1):
        rules.append(
            {
                "id": item.get("id") or f"C-LEGAL-{idx:03d}",
                "type": "legal",
                "if": item.get("if", item.get("when", {})),
                "then": item.get("then", {}),
                "forbid": item.get("forbid", {}),
                "description": item.get("note", item.get("reason", "")),
            }
        )
    return rules


def _compile_constant_rules(key_space: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    constants = key_space.get("constants", {}) or {}
    for idx, (name, value) in enumerate(constants.items(), start=1):
        rules.append(
            {
                "id": f"C-CONST-{idx:03d}",
                "type": "constant",
                "if": {},
                "then": {name: value},
                "description": f"{name} must be {value}",
            }
        )
    # Also pick field-level constants
    for name, spec in (key_space.get("fields", {}) or {}).items():
        if spec.get("constant") is not None:
            rules.append(
                {
                    "id": f"C-CONST-FIELD-{name}",
                    "type": "constant",
                    "if": {},
                    "then": {name: spec["constant"]},
                    "description": f"field {name} constant",
                }
            )
    return rules


def _compile_unreachable_rules(key_space: dict[str, Any], families: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for idx, item in enumerate(key_space.get("unreachable", []) or [], start=1):
        cond = item.get("when", item.get("constraint", {}))
        rules.append(
            {
                "id": f"C-UNR-{idx:03d}",
                "type": "reachability",
                "if": cond if isinstance(cond, dict) else {"expr": cond},
                "forbid": True,
                "description": item.get("reason", ""),
                "level": "L2",
            }
        )
    for fam_id, fam in (families.get("families", {}) or {}).items():
        if fam.get("reachability") in ("unreachable", "excluded"):
            rules.append(
                {
                    "id": f"C-UNR-FAM-{fam_id}",
                    "type": "reachability",
                    "if": {"family_id": fam_id},
                    "forbid": True,
                    "description": fam.get("unreachable_reason", ""),
                    "level": "L2",
                }
            )
    return rules


def _compile_family_guard_rules(families: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for fam_id, fam in (families.get("families", {}) or {}).items():
        guard = fam.get("guard", {})
        if guard:
            rules.append(
                {
                    "id": f"C-GUARD-{fam_id}",
                    "type": "family_guard",
                    "family_id": fam_id,
                    "if": guard,
                    "then": {"family_id": fam_id},
                    "description": f"family guard for {fam_id}",
                }
            )
    return rules


def _compile_data_model_rules(data_model: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for struct_name, spec in (data_model.get("structs", {}) or {}).items():
        present_when = spec.get("present_when")
        if present_when:
            rules.append(
                {
                    "id": f"C-TD-{struct_name}",
                    "type": "tilingdata_present",
                    "if": present_when if isinstance(present_when, dict) else {"expr": present_when},
                    "then": {f"{struct_name}.exist": True},
                    "description": f"tilingdata present_when for {struct_name}",
                }
            )
    for overlay_name, spec in (data_model.get("numeric_overlay", {}) or {}).items():
        rules.append(
            {
                "id": f"C-OVERLAY-{overlay_name}",
                "type": "numeric_overlay",
                "if": {overlay_name: True},
                "then": {"numeric_overlay": overlay_name},
                "description": (spec or {}).get("note", "") if isinstance(spec, dict) else "",
            }
        )
    return rules


def build_rule_model(snapshot: dict[str, Any]) -> dict[str, Any]:
    tiling = snapshot.get("tiling", {})
    key_space = tiling.get("key_space", {})
    families = tiling.get("families", {})
    data_model = tiling.get("data_model", {})

    constraints: list[dict[str, Any]] = []
    constraints.extend(_compile_constant_rules(key_space))
    constraints.extend(_compile_legal_rules(key_space))
    constraints.extend(_compile_family_guard_rules(families))
    constraints.extend(_compile_data_model_rules(data_model))
    constraints.extend(_compile_unreachable_rules(key_space, families))

    factors: dict[str, Any] = {}
    for name, spec in (key_space.get("fields", {}) or {}).items():
        factors[name] = {
            "type": "enum",
            "domain": spec.get("domain", []),
            "bits": spec.get("bits", []),
            "param": name,
            "io_type": "tiling_key",
        }

    return {
        "version": 1,
        "op_name": snapshot.get("op_name"),
        "metadata": {
            "source": "kb_snapshot",
            "constraint_priority": [
                "constant",
                "legal",
                "family_guard",
                "reachability",
                "tilingdata_present",
                "numeric_overlay",
            ],
        },
        "constants": key_space.get("constants", {}),
        "input_realization": key_space.get("input_realization", {}),
        "factors": factors,
        "constraints": constraints,
        # backward compatible alias
        "rules": constraints,
    }
