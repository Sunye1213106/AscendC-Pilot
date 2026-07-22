"""Tests for high-only / chain→CSV / empty allowlist merge gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.io import write_yaml
from testcase_agent.resolve_policy import (
    collect_kernel_unbound_symbols,
    collect_open_mid_symbols,
    is_chaseable_mid_symbol,
    is_empty_allowlisted,
    is_fake_not_csv_excuse,
    is_legitimate_skip,
    require_chains_terminate_at_csv,
    require_full_csv_closure,
    require_high_only,
    require_no_nonempty_unresolved,
    require_no_placeholders,
    validate_chain_terminates_at_csv,
    validate_resolved_doc,
)
from testcase_agent.uo_resolve_merge import UoMergeError, merge_uo_resolve


def _base_out(tmp_path: Path) -> tuple[Path, Path]:
    out = tmp_path / "op"
    realization = out / "realization"
    resolve = realization / "uo_query_resolve"
    resolve.mkdir(parents=True)
    write_yaml(
        realization / "realization_map.yaml",
        {
            "csv_variables": [
                {"id": "VAR_CSV_B", "column": "B", "domain": {"kind": "range", "min": 1, "max": 8}},
                {"id": "VAR_CSV_N1", "column": "N1", "domain": {"kind": "range", "min": 1, "max": 64}},
                {"id": "VAR_CSV_Input_Layout", "column": "Input_Layout", "domain": ["BNSD", "TND"]},
            ]
        },
    )
    write_yaml(realization / "binding_lexicon.yaml", {"version": 1, "key_derivations": []})
    return out, resolve


def test_validate_rejects_medium_confidence() -> None:
    doc = {
        "status": "resolved",
        "confidence": "medium",
        "shape_expr": "B > 0",
        "derivation_chain": [{"id": "VAR_KEY_X", "deps": ["VAR_CSV_B"], "via": "set_by"}],
        "key_derivation": {"id": "VAR_KEY_X", "expr": {"op": "eq", "var": "VAR_CSV_B", "value": 1}},
    }
    ok, ask, reason = validate_resolved_doc(doc, key_id="KEY_X", key_var="VAR_KEY_X")
    assert ok is False
    assert ask == "confidence_not_high"
    assert "medium" in reason


def test_validate_rejects_half_chain() -> None:
    doc = {
        "status": "resolved",
        "confidence": "high",
        "shape_expr": "bnSparseLimit",
        "derivation_chain": [
            {"id": "VAR_KEY_BN", "deps": ["VAR_KVAR_bnSparseLimit"], "via": "set_by"},
        ],
        "key_derivation": {
            "id": "VAR_KEY_BN",
            "expr": {"op": "eq", "var": "VAR_KVAR_bnSparseLimit", "value": 1},
        },
    }
    ok, ask, reason = validate_resolved_doc(doc, key_id="KEY_BN", key_var="VAR_KEY_BN")
    assert ok is False
    assert ask == "shape_closure_incomplete"
    assert "VAR_KVAR_bnSparseLimit" in reason


def test_validate_accepts_nested_chain_to_csv() -> None:
    doc = {
        "status": "resolved",
        "confidence": "high",
        "shape_expr": "bnSparseLimit from B N1 and layout",
        "shape_determined": ["VAR_CSV_B", "VAR_CSV_N1", "VAR_CSV_Input_Layout"],
        "derivation_chain": [
            {
                "id": "VAR_KVAR_bnSparseLimit",
                "deps": ["VAR_CSV_B", "VAR_CSV_N1", "VAR_CSV_Input_Layout"],
                "via": "set_by",
            },
            {"id": "VAR_KEY_ISBN2MULTIBLK", "deps": ["VAR_KVAR_bnSparseLimit"], "via": "set_by"},
        ],
        "key_derivation": {
            "id": "VAR_KEY_ISBN2MULTIBLK",
            "expr": {
                "op": "if_then_else",
                "condition": {"op": "eq", "var": "VAR_CSV_B", "value": 1},
                "then": 1,
                "else": 0,
            },
        },
    }
    ok, ask, reason = validate_resolved_doc(doc, key_id="KEY_ISBN2MULTIBLK", key_var="VAR_KEY_ISBN2MULTIBLK")
    assert ok is True, reason
    assert ask == ""


def test_validate_rejects_opaque_get_in_shape_expr() -> None:
    doc = {
        "status": "resolved",
        "confidence": "high",
        "shape_expr": "attenMask = context_->GetOptionalInputDesc(IDX)",
        "derivation_chain": [{"id": "VAR_KEY_M", "deps": ["VAR_CSV_B"], "via": "set_by"}],
        "key_derivation": {"id": "VAR_KEY_M", "expr": {"op": "eq", "var": "VAR_CSV_B", "value": 1}},
    }
    ok, ask, _ = validate_resolved_doc(doc, key_id="KEY_M", key_var="VAR_KEY_M")
    assert ok is False
    assert ask == "opaque_fn_leaf"


def test_merge_rejects_medium(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_FOO.yaml",
        {
            "key_id": "KEY_FOO",
            "status": "resolved",
            "confidence": "medium",
            "shape_expr": "B==1",
            "derivation_chain": [{"id": "VAR_KEY_FOO", "deps": ["VAR_CSV_B"], "via": "set_by"}],
            "key_derivation": {
                "id": "VAR_KEY_FOO",
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_B", "value": 1},
                    "then": 1,
                    "else": 0,
                },
            },
        },
    )
    with pytest.raises(UoMergeError) as exc:
        merge_uo_resolve(out)
    assert exc.value.ask == "confidence_not_high"


def test_merge_rejects_incomplete_chain(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_FOO.yaml",
        {
            "key_id": "KEY_FOO",
            "status": "resolved",
            "confidence": "high",
            "shape_expr": "depends on mid",
            "derivation_chain": [{"id": "VAR_KEY_FOO", "deps": ["VAR_KVAR_MID"], "via": "set_by"}],
            "key_derivation": {
                "id": "VAR_KEY_FOO",
                "expr": {"op": "eq", "var": "VAR_KVAR_MID", "value": 1},
            },
        },
    )
    with pytest.raises(UoMergeError) as exc:
        merge_uo_resolve(out)
    assert exc.value.ask == "shape_closure_incomplete"


def test_merge_allows_empty_unresolved_only(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_ISEMPTYTENSOR.yaml",
        {
            "key_id": "KEY_ISEMPTYTENSOR",
            "status": "unresolved",
            "confidence": "low",
            "skip_reason": "empty_tensor",
            "unresolved_reason": "empty skipped",
            "key_derivation": {"id": "VAR_KEY_ISEMPTYTENSOR", "expr": None},
        },
    )
    write_yaml(
        resolve / "KEY_FOO.yaml",
        {
            "key_id": "KEY_FOO",
            "status": "resolved",
            "confidence": "high",
            "shape_expr": "B==1",
            "shape_determined": ["VAR_CSV_B"],
            "derivation_chain": [{"id": "VAR_KEY_FOO", "deps": ["VAR_CSV_B"], "via": "set_by"}],
            "key_derivation": {
                "id": "VAR_KEY_FOO",
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_B", "value": 1},
                    "then": 1,
                    "else": 0,
                },
            },
        },
    )
    report = merge_uo_resolve(out)
    assert report["status"] == "pass"
    assert require_high_only(out)["status"] == "pass"
    assert require_chains_terminate_at_csv(out)["status"] == "pass"
    assert require_no_nonempty_unresolved(out)["status"] == "pass"


def test_merge_rejects_nonempty_unresolved(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_ISNEQUAL.yaml",
        {
            "key_id": "KEY_ISNEQUAL",
            "status": "unresolved",
            "confidence": "low",
            "unresolved_reason": "depends on deterSparseType",
            "key_derivation": {"expr": None},
        },
    )
    with pytest.raises(UoMergeError) as exc:
        merge_uo_resolve(out)
    assert exc.value.ask == "key_unresolved"


def test_collect_kernel_unbound_symbols(tmp_path: Path) -> None:
    out = tmp_path / "op"
    (out / "realization").mkdir(parents=True)
    write_yaml(
        out / "realization" / "realization_map.yaml",
        {
            "abstract_branches": [
                {
                    "branch_ref": "KBR_1",
                    "determinant_source": "TilingKey",
                    "reason": "KEY_DERIVATION_MISSING",
                    "unbound_atoms": [{"name": "ISDROP", "reason": "KEY_DERIVATION_MISSING"}],
                },
                {
                    "branch_ref": "KBR_2",
                    "determinant_source": "KernelVariable",
                    "reason": "LOOP_LOCAL",
                    "unbound_atoms": [{"name": "taskId", "reason": "LOOP_LOCAL"}],
                },
            ]
        },
    )
    result = collect_kernel_unbound_symbols(out)
    names = {s["name"] for s in result["symbols"]}
    assert "ISDROP" in names
    assert "taskId" not in names


def test_chain_leaves_helper() -> None:
    ok, reason = validate_chain_terminates_at_csv(
        {
            "derivation_chain": [
                {"id": "VAR_KEY_X", "deps": ["VAR_CSV_B"], "via": "set_by"},
            ],
            "key_derivation": {"expr": {"op": "eq", "var": "VAR_CSV_B", "value": 1}},
        },
        key_var="VAR_KEY_X",
    )
    assert ok, reason


def test_validate_rejects_already_bound_placeholder() -> None:
    doc = {
        "status": "resolved",
        "confidence": "high",
        "shape_expr": "already_bound_in_kb",
        "derivation_chain": [{"id": "VAR_KEY_X", "deps": ["VAR_CSV_B"], "via": "set_by"}],
        "key_derivation": {"id": "VAR_KEY_X", "expr": "already_bound_in_kb"},
    }
    ok, ask, reason = validate_resolved_doc(doc, key_id="KEY_X", key_var="VAR_KEY_X")
    assert ok is False
    assert ask == "placeholder_expr"
    assert "already_bound" in reason


def test_merge_rejects_placeholder_expr(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_SPLITAXIS.yaml",
        {
            "key_id": "KEY_SPLITAXIS",
            "status": "resolved",
            "confidence": "high",
            "shape_expr": "already_bound_in_kb",
            "derivation_chain": [{"id": "VAR_KEY_SPLITAXIS", "deps": ["VAR_CSV_B"], "via": "set_by"}],
            "key_derivation": {"id": "VAR_KEY_SPLITAXIS", "expr": "already_bound_in_kb"},
        },
    )
    with pytest.raises(UoMergeError) as exc:
        merge_uo_resolve(out)
    assert exc.value.ask == "placeholder_expr"


def test_collect_open_mids_from_incomplete_chain(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_BN.yaml",
        {
            "key_id": "KEY_BN",
            "status": "resolved",
            "confidence": "high",
            "derivation_chain": [{"id": "VAR_KEY_BN", "deps": ["VAR_KVAR_bnSparseLimit"], "via": "set_by"}],
            "key_derivation": {
                "id": "VAR_KEY_BN",
                "expr": {"op": "eq", "var": "VAR_KVAR_bnSparseLimit", "value": 1},
            },
        },
    )
    queue = collect_open_mid_symbols(out)
    names = {s["name"] for s in queue["symbols"]}
    assert "VAR_KVAR_bnSparseLimit" in names


def test_full_csv_closure_pass_after_clean_merge(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_FOO.yaml",
        {
            "key_id": "KEY_FOO",
            "status": "resolved",
            "confidence": "high",
            "shape_expr": "B==1",
            "shape_determined": ["VAR_CSV_B"],
            "derivation_chain": [{"id": "VAR_KEY_FOO", "deps": ["VAR_CSV_B"], "via": "set_by"}],
            "key_derivation": {
                "id": "VAR_KEY_FOO",
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_B", "value": 1},
                    "then": 1,
                    "else": 0,
                },
            },
        },
    )
    report = merge_uo_resolve(out)
    assert report["status"] == "pass"
    assert require_no_placeholders(out)["status"] == "pass"
    verify = require_full_csv_closure(out)
    assert verify["status"] == "pass", verify


def test_enum_knob_without_csv_determinants_needs_binding() -> None:
    from testcase_agent.binding_inventory import build_binding_inventory

    inv = build_binding_inventory(
        schema={"columns": ["B"], "fields": []},
        lexicon={"key_derivations": []},
        snapshot_files={
            "contracts/testcase.yaml": {
                "key_determinants": {
                    "KEY_SPLITAXIS": {
                        "role": "enum_knob",
                        "needs_binding": False,
                        "csv_determinants": [],
                    }
                }
            }
        },
        consumer_root=None,
        binding_gaps=[],
    )
    assert "KEY_SPLITAXIS" in inv["needs_binding_keys"]


def test_not_input_derivable_skipped_from_needs_binding() -> None:
    from testcase_agent.binding_inventory import build_binding_inventory, build_llm_bind_prompt_bundle

    inv = build_binding_inventory(
        schema={"columns": ["B"], "fields": []},
        lexicon={"key_derivations": []},
        snapshot_files={
            "contracts/testcase.yaml": {
                "key_determinants": {
                    "KEY_BLOCKID": {
                        "role": "switch",
                        "input_derivable": False,
                        "not_input_derivable": True,
                        "needs_binding": False,
                        "csv_determinants": [],
                    },
                    "KEY_ISNZOUT": {
                        "role": "switch",
                        "input_derivable": True,
                        "needs_binding": True,
                        "csv_determinants": [],
                        "host_parent": "HELPER_ENABLE",
                        "derivation_roots": ["HOST_ATTR_SPARSEMODE"],
                    },
                }
            }
        },
        consumer_root=None,
        binding_gaps=[],
    )
    assert "KEY_BLOCKID" not in inv["needs_binding_keys"]
    assert "KEY_BLOCKID" in inv["not_input_derivable_keys"]
    assert "KEY_ISNZOUT" in inv["needs_binding_keys"]
    assert inv["host_parent_hints"]["KEY_ISNZOUT"]["host_parent"] == "HELPER_ENABLE"
    bundle = build_llm_bind_prompt_bundle(inv, {})
    assert "host_parent_hints" in bundle
    assert "KEY_ISNZOUT" in bundle["host_parent_hints"]
    assert is_legitimate_skip("KEY_BLOCKID", {"not_input_derivable": True}) is True


def test_forged_empty_allowlisted_ignored() -> None:
    assert is_empty_allowlisted("KEY_ISNEQUAL", {"empty_allowlisted": True, "skip_reason": "empty_tensor"}) is False
    assert is_empty_allowlisted("KEY_ISEMPTYTENSOR", {"skip_reason": "anything"}) is True


def test_fake_not_csv_excuse_detected() -> None:
    doc = {
        "key_id": "KEY_ISNEQUAL",
        "status": "unresolved",
        "not_csv_realizable": True,
        "skip_reason": "cross_variable_comparison_not_csv_realizable",
    }
    assert is_fake_not_csv_excuse(doc) is True
    assert is_legitimate_skip("KEY_ISNEQUAL", doc) is False


def test_phantom_key_is_legitimate_skip() -> None:
    doc = {"skip_reason": "phantom_key_not_in_tiling_key_space"}
    assert is_legitimate_skip("KEY_INDEX", doc) is True
    assert is_fake_not_csv_excuse({**doc, "key_id": "KEY_INDEX", "not_csv_realizable": True}) is False


def test_chaseable_mid_filters_arithmetic_noise() -> None:
    assert is_chaseable_mid_symbol("IS_ATTEN_MASK") is True
    assert is_chaseable_mid_symbol("IS_DETER_OLD(DETER_SPARSE_TYPE)") is True
    assert is_chaseable_mid_symbol("BaseClass::IS_N_EQUAL") is True
    assert is_chaseable_mid_symbol("bnSparseLimit") is True
    assert is_chaseable_mid_symbol("((x-p)+1) le y") is False
    assert is_chaseable_mid_symbol("HEAD_DIM_ALIGN gt 512") is False
    assert is_chaseable_mid_symbol("ENABLE_UNITFLAG") is False


def test_kernel_unbound_skips_arith_keeps_is_flags(tmp_path: Path) -> None:
    out = tmp_path / "op"
    (out / "realization").mkdir(parents=True)
    write_yaml(
        out / "realization" / "realization_map.yaml",
        {
            "abstract_branches": [
                {
                    "branch_ref": "KBR_1",
                    "determinant_source": "KernelVariable",
                    "reason": "UNBOUND_ATOM",
                    "unbound_atoms": [
                        {"name": "((x-p)+1) le y", "reason": "UNBOUND_ATOM"},
                        {"name": "IS_ATTEN_MASK", "reason": "UNBOUND_ATOM"},
                        {"name": "ENABLE_UNITFLAG", "reason": "UNBOUND_ATOM"},
                    ],
                }
            ]
        },
    )
    result = collect_kernel_unbound_symbols(out)
    names = {s["name"] for s in result["symbols"]}
    assert "IS_ATTEN_MASK" in names
    assert "((x-p)+1) le y" not in names
    assert "ENABLE_UNITFLAG" not in names
    assert result["skipped_noise"] >= 2


def test_merge_rejects_fake_not_csv_excuse(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_ISNEQUAL.yaml",
        {
            "key_id": "KEY_ISNEQUAL",
            "status": "unresolved",
            "not_csv_realizable": True,
            "empty_allowlisted": True,
            "skip_reason": "cross_variable_comparison_not_csv_realizable",
            "key_derivation": {"expr": None},
        },
    )
    with pytest.raises(UoMergeError) as exc:
        merge_uo_resolve(out)
    assert exc.value.ask == "fake_not_csv_excuse"


def test_merge_allows_phantom_key_skip(tmp_path: Path) -> None:
    out, resolve = _base_out(tmp_path)
    write_yaml(
        resolve / "KEY_INDEX.yaml",
        {
            "key_id": "KEY_INDEX",
            "status": "unresolved",
            "skip_reason": "phantom_key_not_in_tiling_key_space",
            "key_derivation": {"expr": None},
        },
    )
    write_yaml(
        resolve / "KEY_FOO.yaml",
        {
            "key_id": "KEY_FOO",
            "status": "resolved",
            "confidence": "high",
            "shape_expr": "B==1",
            "shape_determined": ["VAR_CSV_B"],
            "derivation_chain": [{"id": "VAR_KEY_FOO", "deps": ["VAR_CSV_B"], "via": "set_by"}],
            "key_derivation": {
                "id": "VAR_KEY_FOO",
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_B", "value": 1},
                    "then": 1,
                    "else": 0,
                },
            },
        },
    )
    report = merge_uo_resolve(out)
    assert report["status"] == "pass"
    assert require_no_nonempty_unresolved(out)["status"] == "pass"
