"""Generic domain heuristics: KEY-capped D, drop-rate 0/1, head-group, layout mutex, platform KEY."""

from __future__ import annotations

from testcase_agent.csv_domain_cover import cover_points_for_domain, gqa_global_constraint
from testcase_agent.domain_policy import (
    find_head_group_pair,
    head_group_cover_pairs,
    head_group_global_constraint,
    is_drop_rate_column,
    is_packed_or_varlen_layout,
    probability_domain_values,
    shape_range_domain,
)
from testcase_agent.realization_map import apply_architecture_platform_fixes
from testcase_agent.realization_validation import _is_constant_fixed_expr, _is_platform_fixed_key
from testcase_agent.realize import apply_layout_column_mutex, _realization_columns


def test_shape_range_key_hi_tightens_safe_caps() -> None:
    key_space = {
        "fields": [{"id": "KEY_DTEMPLATENUM", "name": "DTemplateNum", "values": [0, 64, 128, 192, 256, 768]}],
    }
    domain = shape_range_domain("D", key_space=key_space)
    assert domain["max"] == 768
    assert domain["min"] >= 1


def test_shape_range_clamps_hint_above_key() -> None:
    key_space = {"fields": [{"id": "KEY_DTEMPLATENUM", "values": [64, 128, 768]}]}
    domain = shape_range_domain("D", key_space=key_space, hint_domain={"min": 1, "max": 1024})
    assert domain["max"] == 768


def test_drop_rate_domain_includes_zero_and_one() -> None:
    assert is_drop_rate_column("drop_out_possibility")
    vals = probability_domain_values(column="drop_out_possibility")
    assert 0.0 in vals
    assert 1.0 in vals
    assert any(0.0 < v < 1.0 for v in vals)


def test_keep_prob_still_excludes_zero() -> None:
    vals = probability_domain_values(column="keep_prob")
    assert all(v > 0 for v in vals)


def test_cover_prefers_key_buckets() -> None:
    key_space = {"fields": [{"id": "KEY_DTEMPLATENUM", "values": [64, 128, 256, 768]}]}
    points = cover_points_for_domain(
        {"kind": "range", "min": 1, "max": 768},
        column="D",
        key_space=key_space,
    )
    assert 64 in points and 128 in points and 768 in points


def test_head_group_constraint_shape() -> None:
    con = head_group_global_constraint("N1", "N2")
    assert "HEAD_GROUP" in con["id"]
    assert con["expr"]["op"] == "and"
    # Back-compat alias still works.
    alias = gqa_global_constraint()
    assert alias["expr"]["op"] == "and"


def test_head_group_pairs_from_domains() -> None:
    pairs = head_group_cover_pairs({"kind": "range", "min": 1, "max": 32}, {"kind": "range", "min": 1, "max": 8})
    assert pairs
    assert all(hi >= lo and hi % lo == 0 for hi, lo in pairs)
    assert find_head_group_pair(["B", "N1", "N2", "S1"]) == ("N1", "N2")
    assert find_head_group_pair(["num_q_heads", "num_kv_heads"]) == ("num_q_heads", "num_kv_heads")


def test_layout_mutex_packed_and_fixed() -> None:
    assert is_packed_or_varlen_layout("TND")
    assert is_packed_or_varlen_layout("THD")
    packed = {
        "Input_Layout": "TND",
        "S1": "128",
        "S2": "128",
        "seqlens_list_q": "[64,64]",
        "seqlens_list_kv": "[64,64]",
    }
    apply_layout_column_mutex(packed)
    assert packed["S1"] == "" and packed["S2"] == ""
    assert packed["seqlens_list_q"]

    fixed = {"Input_Layout": "BNSD", "S1": "128", "seqlens_list_q": "[1,1]", "cu_seqlens_q": "[0,1]"}
    apply_layout_column_mutex(fixed)
    assert fixed["S1"] == "128"
    assert fixed["seqlens_list_q"] == ""
    assert fixed["cu_seqlens_q"] == ""


def test_slim_columns_skip_tensor_placeholder() -> None:
    schema = {
        "fields": [
            {"name": "B", "order": 0, "role": "solver_input"},
            {"name": "q", "order": 1, "role": "tensor_placeholder"},
            {"name": "Enable", "order": 2, "role": "constant"},
        ]
    }
    cols = _realization_columns({"consumer": {"columns": ["B", "q", "Enable"]}}, schema)
    assert "B" in cols
    assert "q" not in cols


def test_constant_fixed_expr_detection() -> None:
    assert _is_constant_fixed_expr(
        {"op": "if_then_else", "condition": {"op": "eq", "var": "x", "value": 0}, "then": 0, "else": 0}
    )
    assert _is_platform_fixed_key("VAR_KEY_ISREGBASE")
    assert not _is_platform_fixed_key("VAR_KEY_ISNZOUT")


def test_low_importance_skipped_in_cover() -> None:
    from testcase_agent.csv_domain_cover import add_csv_domain_cover_obligations

    out: list = []
    realization = {
        "consumer": {"columns": ["seed", "B"]},
        "csv_variables": [
            {"id": "VAR_CSV_seed", "column": "seed", "free": True, "domain": {"kind": "range", "min": 0, "max": 100}},
            {"id": "VAR_CSV_B", "column": "B", "free": True, "domain": {"kind": "range", "min": 1, "max": 8}},
        ],
    }
    schema = {
        "domain_hints": {
            "columns": {"seed": {"importance": "low"}},
        }
    }
    add_csv_domain_cover_obligations(out, realization, consumer_schema=schema)
    fields = {o.get("field") for o in out}
    assert "seed" not in fields
    assert "B" in fields


def test_validation_rejects_constant_fixed_non_platform_key() -> None:
    from testcase_agent.realization_contract import CONSUMER_SCHEMA_VERSION, REALIZATION_MAP_VERSION
    from testcase_agent.realization_validation import validate_contract_artifacts

    evidence = {
        "evidence_hash": "ev",
        "field_accesses": {"B": [{"path": "x"}]},
        "sample_values": {"B": [1]},
        "ordered_header_candidates": [{"columns": ["B"]}],
    }
    schema = {
        "version": CONSUMER_SCHEMA_VERSION,
        "evidence_hash": "ev",
        "snapshot_hash": "snap",
        "plan_hash": "plan",
        "fields": [
            {
                "name": "B",
                "order": 0,
                "role": "solver_input",
                "value_type": "int",
                "required": True,
                "source_refs": [{"path": "x"}],
            }
        ],
    }
    realization = {
        "version": REALIZATION_MAP_VERSION,
        "evidence_hash": "ev",
        "snapshot_hash": "snap",
        "plan_hash": "plan",
        "consumer": {"columns": ["B"]},
        "csv_variables": [
            {"id": "VAR_CSV_B", "column": "B", "type": "int", "free": True, "domain": {"kind": "range", "min": 1, "max": 2}}
        ],
        "derived_variables": [
            {
                "id": "VAR_KEY_ISNZOUT",
                "expr": {
                    "op": "derived",
                    "var": "VAR_KEY_ISNZOUT",
                    "expr": {
                        "op": "if_then_else",
                        "condition": {"op": "eq", "var": "VAR_CSV_B", "value": 1},
                        "then": 0,
                        "else": 0,
                    },
                },
                "domain": [0],
            }
        ],
        "emit": {"columns": {}},
        "branch_mappings": [],
        "abstract_branches": [],
    }
    result = validate_contract_artifacts(
        evidence, schema, realization, snapshot_hash="snap", plan_hash="plan", allow_bootstrap=False
    )
    codes = {e["code"] for e in result.get("errors") or []}
    assert "KEY_FIXED_WITHOUT_ARCHITECTURE" in codes


def test_architecture_fixes_existing_platform_key_only() -> None:
    snapshot = {"files": {"contracts/testcase.yaml": {"architecture": "arch35"}}}
    realization = {
        "derived_variables": [
            {
                "id": "VAR_KEY_ISNZOUT",
                "expr": {
                    "op": "derived",
                    "var": "VAR_KEY_ISNZOUT",
                    "expr": {"op": "if_then_else", "condition": {}, "then": 0, "else": 0},
                },
                "domain": [0],
            },
            {
                "id": "VAR_KEY_ISREGBASE",
                "expr": {
                    "op": "derived",
                    "var": "VAR_KEY_ISREGBASE",
                    "expr": {"op": "if_then_else", "condition": {}, "then": 0, "else": 1},
                },
                "domain": [0, 1],
            },
        ],
        "warnings": [],
    }
    out = apply_architecture_platform_fixes(realization, snapshot)
    reg = next(i for i in out["derived_variables"] if "ISREGBASE" in i["id"])
    assert reg["domain"] == [1]
    assert reg.get("architecture_fixed") is True
    nz = next(i for i in out["derived_variables"] if "ISNZOUT" in i["id"])
    assert nz.get("architecture_fixed") is not True


def test_architecture_does_not_invent_missing_platform_key() -> None:
    snapshot = {"files": {"contracts/testcase.yaml": {"architecture": "arch35"}}}
    realization = {"derived_variables": [], "warnings": []}
    out = apply_architecture_platform_fixes(realization, snapshot)
    assert out["derived_variables"] == []
