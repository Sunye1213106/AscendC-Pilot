"""Tests for uo_resolve_merge, domain symmetry, Allow solve gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.io import write_yaml
from testcase_agent.planner import compute_allow_solve
from testcase_agent.uo_resolve_merge import (
    UoMergeError,
    align_domains_from_review,
    build_effective_domains,
    merge_uo_resolve,
    require_domain_symmetry,
    try_fix_heuristic_expr,
    validate_derivation_expr,
)


def test_validate_rejects_out_of_domain_literal() -> None:
    domains = {"VAR_CSV_keep_prob": {"kind": "values", "values": [1.0, 0.9, 0.8]}}
    ok, reason = validate_derivation_expr(
        {"op": "eq", "var": "VAR_CSV_keep_prob", "value": 0},
        domains,
    )
    assert not ok
    assert "domain_asymmetry" in reason


def test_try_fix_heuristic_eq_zero_to_sentinel() -> None:
    domains = {"VAR_CSV_B": {"kind": "range", "min": 1, "max": 64}}
    expr = {
        "op": "if_then_else",
        "condition": {"op": "eq", "var": "VAR_CSV_B", "value": 0},
        "then": 0,
        "else": 1,
    }
    fixed = try_fix_heuristic_expr(expr, domains)
    assert fixed is not None
    assert fixed["condition"]["value"] == 1
    ok, _ = validate_derivation_expr(fixed, domains)
    assert ok


def test_align_keep_prob_from_domain_review() -> None:
    rmap = {
        "csv_variables": [
            {"id": "VAR_CSV_keep_prob", "column": "keep_prob", "domain": ["NONE"], "type": "enum"},
        ]
    }
    review = {
        "columns": [
            {"name": "keep_prob", "proposed_domain": [1.0, 0.9, 0.8]},
        ]
    }
    result = align_domains_from_review(rmap, review, {})
    assert "VAR_CSV_keep_prob" in result["updated"]
    assert rmap["csv_variables"][0]["domain"] == [1.0, 0.9, 0.8]


def test_merge_uo_resolve_and_confirm_gate(tmp_path: Path) -> None:
    out = tmp_path / "op"
    realization = out / "realization"
    resolve = realization / "uo_query_resolve"
    resolve.mkdir(parents=True)
    write_yaml(
        realization / "realization_map.yaml",
        {
            "csv_variables": [
                {"id": "VAR_CSV_keep_prob", "column": "keep_prob", "domain": ["NONE"]},
                {"id": "VAR_CSV_N1", "column": "N1", "domain": {"kind": "range", "min": 1, "max": 128}},
            ]
        },
    )
    write_yaml(
        realization / "domain_review.yaml",
        {"columns": [{"name": "keep_prob", "proposed_domain": [1.0, 0.9, 0.8]}]},
    )
    write_yaml(
        realization / "binding_lexicon.yaml",
        {
            "version": 1,
            "key_derivations": [
                {
                    "id": "VAR_KVAR_KEEPPROB",
                    "expr": {
                        "op": "if_then_else",
                        "condition": {"op": "eq", "var": "VAR_CSV_keep_prob", "value": 0},
                        "then": 0,
                        "else": 1,
                    },
                    "status": "proposed",
                }
            ],
        },
    )
    write_yaml(
        resolve / "KEY_ISDROP.yaml",
        {
            "key_id": "KEY_ISDROP",
            "status": "resolved",
            "confidence": "high",
            "shape_expr": "keepProb < 1.0",
            "shape_determined": ["VAR_CSV_keep_prob"],
            "derivation_chain": [
                {"id": "VAR_KEY_ISDROP", "deps": ["VAR_CSV_keep_prob"], "via": "set_by"},
            ],
            "key_derivation": {
                "id": "VAR_KEY_ISDROP",
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_keep_prob", "value": 1.0},
                    "then": 0,
                    "else": 1,
                },
            },
        },
    )
    report = merge_uo_resolve(out)
    assert report["status"] == "pass"
    sym = require_domain_symmetry(out)
    assert sym["status"] == "pass"
    # keep_prob domain aligned
    from testcase_agent.io import read_yaml

    rmap = read_yaml(realization / "realization_map.yaml")
    keep = next(v for v in rmap["csv_variables"] if v["id"] == "VAR_CSV_keep_prob")
    assert keep["domain"] == [1.0, 0.9, 0.8]


def test_merge_rejects_placeholder_expr(tmp_path: Path) -> None:
    out = tmp_path / "op"
    realization = out / "realization"
    resolve = realization / "uo_query_resolve"
    resolve.mkdir(parents=True)
    write_yaml(realization / "realization_map.yaml", {"csv_variables": []})
    write_yaml(realization / "binding_lexicon.yaml", {"version": 1, "key_derivations": []})
    write_yaml(
        resolve / "KEY_DETERTYPE.yaml",
        {
            "key_id": "KEY_DETERTYPE",
            "status": "resolved",
            "key_derivation": {
                "id": "VAR_KEY_DETERTYPE",
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_is_deter", "value": 1},
                    "then": "deter_branch",
                    "else": "non_deter_branch",
                },
            },
        },
    )
    with pytest.raises(UoMergeError) as exc:
        merge_uo_resolve(out, auto_fix_heuristics=False)
    assert exc.value.ask in {"uo_merge_required", "domain_asymmetry", "confidence_not_high"}


def test_allow_solve_empty_l1_reject() -> None:
    ok, reason = compute_allow_solve(
        level="L1-REJECT",
        obligations=[],
        unresolved={"blocking_hard_obligations": [], "contract_gaps": []},
        semantic_focus={},
    )
    assert ok is False
    assert reason == "empty_l1_reject"


def test_confirm_requires_audit_report(tmp_path: Path) -> None:
    from testcase_agent.init_status import InitGateError, mark_init_confirmed, write_init_status
    from testcase_agent.io import write_yaml

    out = tmp_path / "gen"
    (out / "init").mkdir(parents=True)
    (out / "realization").mkdir(parents=True)
    (out / "bind").mkdir(parents=True)
    write_init_status(out, {"version": 1, "status": "pending_confirm"})
    write_yaml(out / "realization" / "uo_merge_report.yaml", {"status": "pass"})
    write_yaml(out / "realization" / "binding_lexicon.yaml", {"key_derivations": []})
    write_yaml(out / "realization" / "realization_map.yaml", {"csv_variables": [], "abstract_branches": []})
    write_yaml(
        out / "bind" / "shape_derivation_graph.yaml",
        {"status": "built", "roots": [], "closure": [], "edges": [], "nodes": []},
    )
    # domain symmetry + full csv closure pass on empty lexicon / empty mids
    with pytest.raises(InitGateError) as exc:
        mark_init_confirmed(out, notes="x")
    assert exc.value.ask == "audit_required"

    write_yaml(
        out / "init" / "audit_report.yaml",
        {"version": 1, "status": "fail", "blockers": ["lexicon_resolve_sync"]},
    )
    with pytest.raises(InitGateError) as exc2:
        mark_init_confirmed(out, notes="x")
    assert exc2.value.ask == "audit_failed"

    write_yaml(out / "init" / "audit_report.yaml", {"version": 1, "status": "pass", "blockers": []})
    doc = mark_init_confirmed(out, notes="ok")
    assert doc["status"] == "confirmed"
