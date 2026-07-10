from __future__ import annotations

from typing import Any


DEFAULT_REALIZATION_MAP = {
    "InputDType": "query_dtype",
    "OutDType": "output_dtype",
    "IsTnd": "layout",
    "IsDrop": "keep_prob",
    "IsPse": "pse_exists",
    "IsAttenMask": "atten_mask_exists",
    "IsRope": "rope_exists",
    "DeterType": "deterministic_mode",
    "SplitAxis": "split_axis",
    "S1TemplateNum": "s1_shape_bucket",
    "S2TemplateNum": "s2_shape_bucket",
    "DTemplateNum": "d_shape_bucket",
    "has_varlen": "varlen_inputs",
}


def realize_inputs(
    selected: list[dict[str, Any]],
    rule_model: dict[str, Any],
    operator_io: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    realization = rule_model.get("input_realization", {}) or {}
    suggestions: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []

    for idx, target in enumerate(selected, start=1):
        level = target.get("level", "L1")
        prefix = "NEG" if target.get("expect_reject") or level == "L2" else "TK"
        case_id = f"{prefix}_{idx:03d}"
        expected = target.get("expected_key", {})
        inputs: dict[str, Any] = {
            "case_id": case_id,
            "candidate_id": target.get("candidate_id"),
            "family_id": target.get("family_id"),
            "expected_key": expected,
            "level": level,
            "expect_reject": bool(target.get("expect_reject")),
            "source": target.get("source"),
            "inputs": {},
            "attrs": {},
        }

        missing_fields: list[str] = []
        for field, value in expected.items():
            if field in ("family_id", "tilingdata_block", "relation", "unreachable"):
                continue
            spec = realization.get(field)
            if isinstance(spec, dict):
                inputs["inputs"].update(spec.get(str(value), spec.get("default", {})))
            elif field in DEFAULT_REALIZATION_MAP:
                inputs["inputs"][DEFAULT_REALIZATION_MAP[field]] = value
            else:
                inputs["inputs"][field] = value
                if field not in realization:
                    missing_fields.append(field)

        if "has_varlen" in expected or expected.get("varlen_inputs"):
            inputs["inputs"]["actualSeqQLen"] = {"present": True}
            inputs["inputs"]["actualSeqKvLen"] = {"present": True}

        if missing_fields:
            suggestions.append(
                {
                    "case_id": case_id,
                    "missing_realization_fields": missing_fields,
                    "suggestion": "Add input_realization entries in key_space.yaml or rule_model patch.",
                }
            )

        inputs["covers"] = target.get("covers", [])
        cases.append(inputs)

    return cases, suggestions
