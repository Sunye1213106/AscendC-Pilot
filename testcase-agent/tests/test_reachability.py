"""Unit tests for reachability filtering and contract bootstrap."""

from __future__ import annotations

from testcase_agent.planner import apply_realization_filters, _key_var_from_obligation
from testcase_agent.reachability import annotate_reachable_values, evaluate_expr_image, is_value_reachable
from testcase_agent.realization_map import csv_var


def test_bucket_expr_reachable_image_excludes_unreachable_values() -> None:
    expr = {
        "op": "if_then_else",
        "condition": {"op": "ge", "var": csv_var("D"), "value": 256},
        "then": 256,
        "else": {
            "op": "if_then_else",
            "condition": {"op": "ge", "var": csv_var("D"), "value": 64},
            "then": 64,
            "else": 0,
        },
    }
    image = evaluate_expr_image(expr, {csv_var("D"): [64, 128, 256]})
    assert set(image) == {64, 256}
    assert 768 not in image
    assert 0 not in image


def test_annotate_narrows_derived_domain() -> None:
    realization_map = {
        "csv_variables": [{"id": csv_var("Dtype"), "column": "Dtype", "type": "enum", "domain": ["fp16", "bf16", "fp32"]}],
        "derived_variables": [
            {
                "id": "VAR_KEY_INPUTDTYPE",
                "type": "int",
                "domain": [0, 1, 2, 3, 4, 5, 6],
                "expr": {
                    "op": "derived",
                    "var": "VAR_KEY_INPUTDTYPE",
                    "expr": {
                        "op": "if_then_else",
                        "condition": {"op": "eq", "var": csv_var("Dtype"), "value": "bf16"},
                        "then": 1,
                        "else": {
                            "op": "if_then_else",
                            "condition": {"op": "eq", "var": csv_var("Dtype"), "value": "fp32"},
                            "then": 2,
                            "else": 0,
                        },
                    },
                },
            }
        ],
    }
    out = annotate_reachable_values(realization_map)
    derived = out["derived_variables"][0]
    assert set(derived["reachable_values"]) == {0, 1, 2}
    assert set(derived["domain"]) == {0, 1, 2}
    assert is_value_reachable(out, "VAR_KEY_INPUTDTYPE", 3) is False
    assert is_value_reachable(out, "VAR_KEY_INPUTDTYPE", 1) is True


def test_apply_realization_filters_marks_unrealizable_key_and_abstract_branch() -> None:
    realization_map = annotate_reachable_values(
        {
            "csv_variables": [{"id": csv_var("Dtype"), "type": "enum", "domain": ["fp16"]}],
            "derived_variables": [
                {
                    "id": "VAR_KEY_INPUTDTYPE",
                    "type": "int",
                    "domain": [0, 1],
                    "expr": {
                        "op": "derived",
                        "var": "VAR_KEY_INPUTDTYPE",
                        "expr": {"op": "if_then_else", "condition": {"op": "eq", "var": csv_var("Dtype"), "value": "fp16"}, "then": 0, "else": 1},
                    },
                }
            ],
            "branch_mappings": [{"branch_ref": "KBR_OK", "var": "VAR_KBR_OK"}],
            "abstract_branches": [
                {"branch_ref": "KBR_ABS", "abstract_only": True, "reason": "UNBOUND_ATOM"},
                {"branch_ref": "KBR_LOOP", "abstract_only": True, "reason": "LOOP_LOCAL", "condition": "taskId > 0"},
            ],
        }
    )
    obligations = [
        {
            "id": "OB_KEY_BAD",
            "kind": "tiling_key_field_value",
            "status": "pending",
            "reachability": "reachable",
            "target_refs": ["KEY_INPUTDTYPE"],
            "target_value": 5,
            "field": "InputDType",
        },
        {
            "id": "OB_KEY_OK",
            "kind": "tiling_key_field_value",
            "status": "pending",
            "reachability": "reachable",
            "target_refs": ["KEY_INPUTDTYPE"],
            "target_value": 0,
            "field": "InputDType",
        },
        {
            "id": "OB_BR_ABS",
            "kind": "kernel_branch",
            "status": "pending",
            "reachability": "reachable",
            "target_refs": ["KBR_ABS"],
            "target_value": True,
        },
        {
            "id": "OB_BR_LOOP",
            "kind": "kernel_branch",
            "status": "pending",
            "reachability": "reachable",
            "target_refs": ["KBR_LOOP"],
            "target_value": True,
        },
        {
            "id": "OB_BR_OK",
            "kind": "kernel_branch",
            "status": "pending",
            "reachability": "reachable",
            "target_refs": ["KBR_OK"],
            "target_value": True,
        },
    ]
    filtered = apply_realization_filters(obligations, realization_map)
    by_id = {item["id"]: item for item in filtered}
    assert by_id["OB_KEY_BAD"]["status"] == "proof_required"
    assert "NOT_CSV_REALIZABLE" in by_id["OB_KEY_BAD"]["unresolved_reason"]
    assert by_id["OB_KEY_OK"]["status"] == "pending"
    assert by_id["OB_BR_ABS"]["status"] == "proof_required"
    assert by_id["OB_BR_ABS"]["csv_unreachability_code"] == "UNBOUND_ATOM"
    assert "OB_BR_LOOP" not in by_id  # LOOP_LOCAL dropped entirely from L1 set
    assert by_id["OB_BR_OK"]["status"] == "pending"
    assert _key_var_from_obligation(by_id["OB_KEY_OK"]) == "VAR_KEY_INPUTDTYPE"
