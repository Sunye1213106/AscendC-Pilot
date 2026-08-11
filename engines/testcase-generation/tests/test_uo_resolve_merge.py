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


def test_merge_locks_high_resolve_and_clears_binding_gaps(tmp_path: Path) -> None:
    out = tmp_path / "op"
    realization = out / "realization"
    resolve = realization / "uo_query_resolve"
    resolve.mkdir(parents=True)
    write_yaml(
        realization / "realization_map.yaml",
        {
            "csv_variables": [
                {"id": "VAR_CSV_keep_prob", "column": "keep_prob", "domain": [1.0, 0.9, 0.8]},
            ]
        },
    )
    write_yaml(realization / "binding_lexicon.yaml", {"version": 1, "key_derivations": []})
    write_yaml(
        realization / "unresolved.yaml",
        {
            "binding_gaps": [
                {"code": "UNBOUND_KEY", "variable_id": "VAR_KEY_ISDROP", "key_id": "KEY_ISDROP"},
            ]
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
    from testcase_agent.io import read_yaml

    lexicon = read_yaml(realization / "binding_lexicon.yaml")
    item = next(x for x in lexicon["key_derivations"] if x["id"] == "VAR_KEY_ISDROP")
    assert item["locked"] is True
    assert item["status"] == "reviewed"
    unresolved = read_yaml(realization / "unresolved.yaml")
    assert unresolved.get("binding_gaps") == []


def test_binding_resolve_coverage_requires_files(tmp_path: Path) -> None:
    from testcase_agent.resolve_policy import require_binding_resolve_coverage

    out = tmp_path / "op"
    realization = out / "realization"
    realization.mkdir(parents=True)
    write_yaml(
        realization / "binding_inventory.yaml",
        {"needs_binding_keys": ["KEY_FOO"], "not_input_derivable_keys": []},
    )
    cov = require_binding_resolve_coverage(out)
    assert cov["status"] == "fail"
    assert "KEY_FOO" in cov["missing"]
    (realization / "uo_query_resolve").mkdir()
    write_yaml(realization / "uo_query_resolve" / "KEY_FOO.yaml", {"key_id": "KEY_FOO", "status": "resolved"})
    assert require_binding_resolve_coverage(out)["status"] == "pass"


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


def test_allow_solve_l1_key_derivation_missing() -> None:
    ok, reason = compute_allow_solve(
        level="L1",
        obligations=[{"id": "x", "status": "pending"}],
        unresolved={"blocking_hard_obligations": [], "contract_gaps": []},
        semantic_focus={
            "csv_realization": {
                "pending_count": 1,
                "not_csv_realizable_count": 0,
                "by_unreachability_code": {"KEY_DERIVATION_MISSING": 1},
            }
        },
    )
    assert ok is False
    assert reason == "key_derivation_missing"


def test_confirm_requires_audit_report(tmp_path: Path) -> None:
    from testcase_agent.init_status import InitGateError, mark_init_confirmed, write_init_status
    from testcase_agent.io import write_yaml

    out = tmp_path / "gen"
    project = tmp_path / "operator"
    uo_root = project / ".ascendc-pilot" / "uo"
    uo_root.mkdir(parents=True)
    # This is a UO-side fixture, so write it directly. Going through TG's
    # write_yaml would correctly trip the UO/TG isolation guard.
    (uo_root / "manifest.yaml").write_text(
        "version: 1\nauthority: legacy_test_fixture\nsource:\n  revision: fixture\n",
        encoding="utf-8",
    )
    (out / "init").mkdir(parents=True)
    (out / "realization").mkdir(parents=True)
    (out / "bind").mkdir(parents=True)
    write_init_status(
        out,
        {
            "version": 1,
            "status": "pending_confirm",
            "project_root": project.as_posix(),
            "op_name": "fixture_op",
        },
    )
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

    from testcase_agent.resolve_policy import AUDIT_CHECKLIST_IDS

    write_yaml(
        out / "init" / "audit_report.yaml",
        {
            "version": 1,
            "status": "pass",
            "blockers": [],
            "checks": [{"id": cid, "status": "pass", "detail": "ok"} for cid in AUDIT_CHECKLIST_IDS],
        },
    )
    doc = mark_init_confirmed(out, notes="ok")
    assert doc["status"] == "confirmed"
    assert doc["kb_fingerprint_digest"]


def test_confirm_rejects_incomplete_audit_checklist(tmp_path: Path) -> None:
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
    write_yaml(out / "init" / "audit_report.yaml", {"version": 1, "status": "pass", "blockers": [], "checks": []})
    with pytest.raises(InitGateError) as exc:
        mark_init_confirmed(out, notes="x")
    assert exc.value.ask == "audit_incomplete"
