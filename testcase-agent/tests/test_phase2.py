from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testcase_agent.candidates import CandidateError, branch_stable_key, coverage_signature, dedupe_candidates, greedy_set_cover
from testcase_agent.constraint_ir import build_constraint_ir, compile_obligation_target, parse_bool_literal
from testcase_agent.hashing import semantic_plan_hash, semantic_snapshot_hash
from testcase_agent.io import read_yaml, write_json, write_yaml
from testcase_agent.planner import build_plan
from testcase_agent.solve import TgSolveError, solve_from_docs, tg_solve
from testcase_agent.z3_backend import Z3Backend


def _snapshot(contract: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = {
        "version": 1,
        "op_name": "DemoOp",
        "view": "testcase-contract",
        "files": {
            "contracts/testcase.yaml": contract or _contract(),
            "quality.yaml": {"status": "pass"},
        },
    }
    snapshot["snapshot_hash"] = semantic_snapshot_hash(snapshot)
    return snapshot


def _contract(**updates: Any) -> dict[str, Any]:
    base = {
        "version": 2,
        "op_name": "DemoOp",
        "variables": [
            {"id": "VAR_BOOL", "type": "bool"},
            {"id": "VAR_INT", "type": "int", "domain": {"min": 0, "max": 16}},
            {"id": "VAR_ENUM", "type": "enum", "domain": ["A", "B"]},
            {"id": "VAR_TAIL", "type": "int", "domain": {"min": 0, "max": 31}},
        ],
        "interface": {
            "required_inputs": [],
            "optional_inputs": [{"name": "mask"}],
            "outputs": [],
            "attrs": [],
            "dtype_layout_domains": [{"id": "ND"}],
        },
        "typed_constraints": [],
        "coverage_obligations": {},
        "golden_contract": {},
    }
    base.update(updates)
    return base


def _obligations(items: list[dict[str, Any]], snapshot_hash: str | None = None) -> dict[str, Any]:
    return {"version": 1, "snapshot_hash": snapshot_hash or "snap", "obligations": items}


def _pending(oid: str, *, priority: str = "normal", constraints: dict[str, Any] | None = None, kind: str = "tiling_key_field", target_refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": oid,
        "kind": kind,
        "target_refs": target_refs or [oid],
        "source_refs": [],
        "priority": priority,
        "status": "pending",
        "reachability": "reachable",
        "constraints": constraints or {},
        "realization_hints": {},
        "evidence_refs": [],
        "unresolved_reason": "",
    }


def _repo_with_phase1(tmp_path: Path, contract: dict[str, Any], obligations: dict[str, Any], supplement: dict[str, Any] | None = None) -> Path:
    repo = tmp_path / "repo"
    root = repo / ".testcase-generator" / "DemoOp"
    (root / "snapshot").mkdir(parents=True)
    (root / "plan").mkdir(parents=True)
    snapshot = _snapshot(contract)
    obligations["snapshot_hash"] = snapshot["snapshot_hash"]
    matrix = {"version": 1, "snapshot_hash": snapshot["snapshot_hash"], "by_kind": {}, "priority_counts": {}, "total": len(obligations.get("obligations", [])), "unreachable": []}
    unresolved = {"version": 1, "snapshot_hash": snapshot["snapshot_hash"], "status": "ready_for_manual_review", "blocking_hard_obligations": [], "unresolved_obligations": [], "contract_gaps": []}
    plan_hash = semantic_plan_hash(snapshot["snapshot_hash"], obligations.get("obligations", []), matrix, unresolved)
    obligations["plan_hash"] = plan_hash
    matrix["plan_hash"] = plan_hash
    unresolved["plan_hash"] = plan_hash
    write_json(root / "snapshot" / "understand_contract.json", snapshot)
    write_yaml(root / "plan" / "coverage_obligations.yaml", obligations)
    write_yaml(root / "plan" / "coverage_matrix.yaml", matrix)
    write_yaml(root / "plan" / "unresolved.yaml", unresolved)
    write_yaml(
        root / "plan" / "human_supplement.yaml",
        supplement
        or {
            "version": 1,
            "decision": "approve",
            "approved_snapshot_hash": snapshot["snapshot_hash"],
            "approved_plan_hash": plan_hash,
            "approved_at": "2026-01-01T00:00:00+00:00",
            "supplements": [],
            "notes": "",
        },
    )
    return repo


def test_bool_int_enum_variables_compile() -> None:
    result = build_constraint_ir(_snapshot(), _obligations([]), {"decision": "approve"})

    assert not result.errors
    variables = {item["id"]: item for item in result.ir["variables"]}
    assert variables["VAR_BOOL"]["type"] == "bool"
    assert variables["VAR_INT"]["type"] == "int"
    assert variables["VAR_ENUM"]["type"] == "enum"


def test_implies_mutex_requires() -> None:
    contract = _contract(
        typed_constraints=[
            {"id": "CON_IMPLIES", "expr": {"op": "implies", "antecedent": {"op": "eq", "var": "VAR_BOOL", "value": True}, "consequent": {"op": "eq", "var": "VAR_ENUM", "value": "A"}}},
            {"id": "CON_REQUIRES", "expr": {"op": "requires", "antecedent": {"op": "eq", "var": "VAR_ENUM", "value": "A"}, "consequent": {"op": "ge", "var": "VAR_INT", "value": 4}}},
            {"id": "CON_MUTEX", "expr": {"op": "mutex", "args": [{"op": "eq", "var": "VAR_ENUM", "value": "A"}, {"op": "eq", "var": "VAR_ENUM", "value": "B"}]}},
        ]
    )
    obligations = _obligations([_pending("OB_BOOL", constraints={"expr": {"op": "eq", "var": "VAR_BOOL", "value": True}})])
    result = solve_from_docs(_snapshot(contract), obligations, {"decision": "approve"})

    assert result["solve_results"][0]["status"] == "sat"
    model = result["solve_results"][0]["model"]
    assert model["VAR_ENUM"] == "A"
    assert model["VAR_INT"] >= 4


def test_mod_aligned_tail_conditions() -> None:
    contract = _contract(
        typed_constraints=[
            {"id": "CON_ALIGNED", "expr": {"op": "aligned", "var": "VAR_INT", "alignment": 4}},
            {"id": "CON_TAIL", "expr": {"op": "eq", "lhs": {"op": "mod", "args": [{"var": "VAR_TAIL"}, 8]}, "rhs": 0}},
        ]
    )
    obligations = _obligations([_pending("OB_TAIL", constraints={"expr": {"op": "gt", "var": "VAR_TAIL", "value": 0}})])
    result = solve_from_docs(_snapshot(contract), obligations, {"decision": "approve"})

    assert result["solve_results"][0]["status"] == "sat"
    model = result["solve_results"][0]["model"]
    assert model["VAR_INT"] % 4 == 0
    assert model["VAR_TAIL"] % 8 == 0


def test_derived_field_cannot_be_free_and_not_in_model() -> None:
    contract = _contract(
        variables=[{"id": "VAR_BASE", "type": "int", "domain": {"min": 0, "max": 4}}],
        typed_constraints=[
            {"id": "CON_DERIVED", "type": "int", "expr": {"op": "derived", "var": "VAR_DERIVED", "expr": {"op": "add", "args": [{"var": "VAR_BASE"}, 1]}}},
            {"id": "CON_USE_DERIVED", "expr": {"op": "eq", "var": "VAR_DERIVED", "value": 3}},
        ],
    )
    obligations = _obligations([_pending("OB_BASE", constraints={"expr": {"op": "ge", "var": "VAR_BASE", "value": 0}})])
    result = solve_from_docs(_snapshot(contract), obligations, {"decision": "approve"})
    variables = {item["id"]: item for item in result["constraint_ir"]["variables"]}

    assert variables["VAR_DERIVED"]["free"] is False
    assert result["solve_results"][0]["status"] == "sat"
    assert "VAR_DERIVED" not in result["solve_results"][0]["model"]
    assert result["solve_results"][0]["model"]["VAR_BASE"] == 2


def test_sat_returns_witness() -> None:
    obligations = _obligations([_pending("OB_ENUM", constraints={"expr": {"op": "eq", "var": "VAR_ENUM", "value": "B"}})])
    result = solve_from_docs(_snapshot(), obligations, {"decision": "approve"})

    assert result["solve_results"][0]["status"] == "sat"
    assert result["solve_results"][0]["model"]["VAR_ENUM"] == "B"
    assert result["candidates"]


def test_unsat_returns_related_constraints() -> None:
    contract = _contract(typed_constraints=[{"id": "CON_FORCE_A", "expr": {"op": "eq", "var": "VAR_ENUM", "value": "A"}}])
    obligations = _obligations([_pending("OB_FORCE_B", priority="hard", constraints={"expr": {"op": "eq", "var": "VAR_ENUM", "value": "B"}})])
    result = solve_from_docs(_snapshot(contract), obligations, {"decision": "approve"})

    assert result["solve_results"][0]["status"] == "unsat"
    assert result["unsat_obligations"][0]["unsat_core"]
    assert any("CON_FORCE_A" in label or "OB_FORCE_B" in label for label in result["unsat_obligations"][0]["unsat_core"])


def test_unknown_timeout_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def unknown(self: Z3Backend, obligation: dict[str, Any]) -> dict[str, Any]:
        return {"obligation_id": obligation["id"], "status": "unknown", "model": {}, "unsat_core": [], "reason": "timeout"}

    monkeypatch.setattr(Z3Backend, "solve_one", unknown)
    obligations = _obligations([_pending("OB_TIMEOUT")])
    result = solve_from_docs(_snapshot(), obligations, {"decision": "approve"}, timeout_ms=1)

    assert result["solve_results"][0]["status"] == "unknown"
    assert result["unknown_obligations"][0]["reason"] == "timeout"


def test_unsupported_expression_fails_explicitly() -> None:
    contract = _contract(typed_constraints=[{"id": "CON_BAD", "expr": {"op": "regex", "var": "VAR_ENUM", "value": "A"}}])
    result = build_constraint_ir(_snapshot(contract), _obligations([]), {"decision": "approve"})

    assert result.errors
    assert result.errors[0]["code"] == "UNSUPPORTED_EXPRESSION"
    assert "regex" in result.errors[0]["message"]


def test_duplicate_candidate_dedupes() -> None:
    candidate = {
        "id": "CAND_A",
        "coverage_signature": {"family_ref": "FAM_A"},
        "source_obligation_ids": ["OB1"],
        "covered_obligation_ids": ["OB1"],
    }
    duplicate = {
        "id": "CAND_B",
        "coverage_signature": {"family_ref": "FAM_A"},
        "source_obligation_ids": ["OB2"],
        "covered_obligation_ids": ["OB1"],
    }

    assert len(dedupe_candidates([candidate, duplicate])) == 1


def test_set_cover_covers_all_hard_obligations() -> None:
    obligations = [
        _pending("OB_HARD_A", priority="hard"),
        _pending("OB_HARD_B", priority="hard"),
        _pending("OB_NORMAL", priority="normal"),
    ]
    candidates = [
        {"id": "CAND_1", "covered_obligation_ids": ["OB_HARD_A"], "coverage_signature": {}},
        {"id": "CAND_2", "covered_obligation_ids": ["OB_HARD_B", "OB_NORMAL"], "coverage_signature": {}},
    ]

    result = greedy_set_cover(candidates, obligations)

    selected_ids = {item["id"] for item in result["selected_candidates"]}
    assert selected_ids == {"CAND_1", "CAND_2"}
    assert result["uncovered_obligations"] == []


def test_same_input_output_is_deterministic() -> None:
    obligations = _obligations([
        _pending("OB_A", priority="hard", constraints={"expr": {"op": "eq", "var": "VAR_ENUM", "value": "A"}}),
        _pending("OB_B", priority="high", constraints={"expr": {"op": "eq", "var": "VAR_ENUM", "value": "B"}}),
    ])

    first = solve_from_docs(_snapshot(), obligations, {"decision": "approve"})
    second = solve_from_docs(_snapshot(), obligations, {"decision": "approve"})

    assert first["deduped_candidates"] == second["deduped_candidates"]
    assert first["selected_candidates"] == second["selected_candidates"]


def test_single_unsat_does_not_break_other_obligations() -> None:
    contract = _contract(typed_constraints=[{"id": "CON_FORCE_A", "expr": {"op": "eq", "var": "VAR_ENUM", "value": "A"}}])
    obligations = _obligations([
        _pending("OB_UNSAT", constraints={"expr": {"op": "eq", "var": "VAR_ENUM", "value": "B"}}),
        _pending("OB_SAT", constraints={"expr": {"op": "eq", "var": "VAR_ENUM", "value": "A"}}),
    ])
    result = solve_from_docs(_snapshot(contract), obligations, {"decision": "approve"})

    assert [item["status"] for item in result["solve_results"]] == ["unsat", "sat"]
    assert result["candidates"]


def test_tg_solve_does_not_generate_csv_or_execute_operator(tmp_path: Path) -> None:
    repo = _repo_with_phase1(tmp_path, _contract(), _obligations([_pending("OB_A")]))

    tg_solve(repo, "DemoOp")

    root = repo / ".testcase-generator" / "DemoOp"
    assert not list(root.rglob("*.csv"))
    assert not (root / "run" / "operator_execution.yaml").exists()
    assert (root / "solve" / "constraint_ir.yaml").exists()


def test_tg_solve_requires_approval(tmp_path: Path) -> None:
    repo = _repo_with_phase1(tmp_path, _contract(), _obligations([_pending("OB_A")]), {"version": 1, "decision": "revise"})

    with pytest.raises(TgSolveError):
        tg_solve(repo, "DemoOp")


def test_tg_solve_rejects_legacy_coverage_plan_filename(tmp_path: Path) -> None:
    repo = _repo_with_phase1(tmp_path, _contract(), _obligations([_pending("OB_A")]))
    root = repo / ".testcase-generator" / "DemoOp" / "plan"
    legacy = read_yaml(root / "coverage_obligations.yaml")
    (root / "coverage_obligations.yaml").unlink()
    write_yaml(root / "coverage_plan.yaml", legacy)

    with pytest.raises(TgSolveError, match="coverage_obligations.yaml"):
        tg_solve(repo, "DemoOp")


def test_tg_solve_writes_outputs(tmp_path: Path) -> None:
    repo = _repo_with_phase1(tmp_path, _contract(), _obligations([_pending("OB_A")]))

    tg_solve(repo, "DemoOp")

    root = repo / ".testcase-generator" / "DemoOp" / "solve"
    assert read_yaml(root / "solver_report.yaml")["total_obligations"] == 1
    assert (root / "candidates.yaml").exists()
    assert (root / "selected_candidates.yaml").exists()
    assert (root / "unsat_obligations.yaml").exists()


def test_hard_targetless_obligation_is_error() -> None:
    obligation = _pending("OB_NO_TARGET", priority="hard", constraints={}, kind="unknown_kind", target_refs=[])
    result = compile_obligation_target(obligation, {"variables": []})

    assert result.status == "error"
    assert result.code == "OBLIGATION_TARGET_NOT_COMPILED"


def test_normal_targetless_obligation_is_skipped() -> None:
    obligation = _pending("OB_NO_TARGET", priority="normal", constraints={}, kind="unknown_kind", target_refs=[])
    result = compile_obligation_target(obligation, {"variables": []})

    assert result.status == "skipped"
    assert result.code == "OBLIGATION_TARGET_NOT_COMPILED"


def test_pipeline_resource_mode_compiles() -> None:
    obligation = _pending("OB_PIPE", kind="pipeline_resource_mode", target_refs=["PIPE_SHARED"])
    result = compile_obligation_target(obligation, {"variables": [{"id": "VAR_PIPELINE_RESOURCE_MODE"}]})

    assert result.status == "ok"
    assert result.expr == {"op": "eq", "var": "VAR_PIPELINE_RESOURCE_MODE", "value": "PIPE_SHARED"}


def test_relation_mutex_and_implies_compile() -> None:
    mutex = _pending("OB_MUTEX", kind="tiling_key_relation", constraints={"relation_type": "mutex", "fields": ["VAR_A", "VAR_B"]})
    implies = _pending("OB_IMPLIES", kind="tiling_key_relation", constraints={"relation_type": "implies", "source": "VAR_A", "target": "VAR_B"})
    ir = {"variables": [{"id": "VAR_A"}, {"id": "VAR_B"}]}

    assert compile_obligation_target(mutex, ir).status == "ok"
    assert compile_obligation_target(implies, ir).expr["op"] == "and"


def test_insufficient_relation_information_does_not_solve_sat() -> None:
    obligation = _pending("OB_PAIRWISE", priority="high", kind="tiling_key_relation", constraints={"relation_type": "pairwise", "fields": ["VAR_A", "VAR_B"]})
    result = solve_from_docs(_snapshot(), _obligations([obligation]), {"decision": "approve"})

    assert result["solve_results"][0]["status"] == "error"
    assert result["solve_results"][0]["code"] == "OBLIGATION_TARGET_NOT_COMPILED"
    assert not result["candidates"]


def test_one_model_can_cover_multiple_obligations() -> None:
    obligations = _obligations(
        [
            _pending("OB_FAMILY", priority="hard", kind="family", target_refs=["FAM_A"]),
            _pending("OB_PATH", priority="hard", kind="kernel_path", target_refs=["KPATH_A"]),
            _pending("OB_BRANCH", priority="high", kind="kernel_branch", target_refs=["KBR_HAS_TAIL"], constraints={"expr": {"op": "eq", "var": "VAR_KBR_HAS_TAIL", "value": True}}),
        ]
    )
    contract = _contract(
        variables=[{"id": "VAR_FAMILY", "type": "enum", "domain": ["FAM_A"]}, {"id": "VAR_KERNEL_PATH", "type": "enum", "domain": ["KPATH_A"]}, {"id": "VAR_KBR_HAS_TAIL", "type": "bool"}],
        typed_constraints=[{"id": "CON_BRANCH_TRUE", "expr": {"op": "eq", "var": "VAR_KBR_HAS_TAIL", "value": True}}],
    )

    result = solve_from_docs(_snapshot(contract), obligations, {"decision": "approve"})

    assert any(set(candidate["covered_obligation_ids"]) == {"OB_BRANCH", "OB_FAMILY", "OB_PATH"} for candidate in result["deduped_candidates"])
    assert len(result["selected_candidates"]) == 1


def test_coverage_signature_excludes_obligation_ids_after_dedupe() -> None:
    obligations = _obligations(
        [
            _pending("OB_A", constraints={"expr": {"op": "eq", "var": "VAR_ENUM", "value": "A"}}),
            _pending("OB_A2", constraints={"expr": {"op": "eq", "var": "VAR_ENUM", "value": "A"}}),
        ]
    )
    result = solve_from_docs(_snapshot(), obligations, {"decision": "approve"})

    assert len(result["deduped_candidates"]) == 1
    candidate = result["deduped_candidates"][0]
    assert "covered_obligation_ids" not in candidate["coverage_signature"]
    assert candidate["source_obligation_ids"] == ["OB_A", "OB_A2"]


def test_unknown_variable_reference_fails_in_ir() -> None:
    contract = _contract(typed_constraints=[{"id": "CON_UNKNOWN", "expr": {"op": "eq", "var": "VAR_MISSING", "value": 1}}])
    result = build_constraint_ir(_snapshot(contract), _obligations([]), {"decision": "approve"})

    assert any(error["code"] == "UNKNOWN_VARIABLE_REFERENCE" and error["variable_id"] == "VAR_MISSING" for error in result.errors)


def test_context_slice_entities_create_ir_variables_without_top_level_variables() -> None:
    snapshot = _snapshot(_contract(variables=[]))
    snapshot["context_slice"] = {"entities": [{"id": "KEY_SPLIT_AXIS", "data_type": "int", "values": [0, 1]}, {"id": "KBR_HAS_TAIL", "data_type": "bool"}]}
    result = build_constraint_ir(snapshot, _obligations([]), {"decision": "approve"})
    variables = {item["id"]: item for item in result.ir["variables"]}

    assert variables["VAR_KEY_SPLIT_AXIS"]["type"] == "int"
    assert variables["VAR_KBR_HAS_TAIL"]["type"] == "bool"


def test_tg_solve_rejects_stale_approval_and_plan_hash(tmp_path: Path) -> None:
    repo = _repo_with_phase1(tmp_path, _contract(), _obligations([_pending("OB_A")]))
    root = repo / ".testcase-generator" / "DemoOp"
    supplement = read_yaml(root / "plan" / "human_supplement.yaml")
    supplement["approved_plan_hash"] = "stale"
    write_yaml(root / "plan" / "human_supplement.yaml", supplement)

    with pytest.raises(TgSolveError, match="APPROVAL_PLAN_MISMATCH"):
        tg_solve(repo, "DemoOp")


def test_tg_solve_rejects_blocked_unresolved(tmp_path: Path) -> None:
    repo = _repo_with_phase1(tmp_path, _contract(), _obligations([_pending("OB_A")]))
    root = repo / ".testcase-generator" / "DemoOp"
    unresolved = read_yaml(root / "plan" / "unresolved.yaml")
    unresolved["status"] = "blocked"
    unresolved["blocking_hard_obligations"] = [{"id": "OB_A"}]
    plan_hash = semantic_plan_hash(
        read_yaml(root / "plan" / "coverage_obligations.yaml")["snapshot_hash"],
        read_yaml(root / "plan" / "coverage_obligations.yaml")["obligations"],
        read_yaml(root / "plan" / "coverage_matrix.yaml"),
        unresolved,
    )
    obligations_doc = read_yaml(root / "plan" / "coverage_obligations.yaml")
    matrix = read_yaml(root / "plan" / "coverage_matrix.yaml")
    supplement = read_yaml(root / "plan" / "human_supplement.yaml")
    obligations_doc["plan_hash"] = plan_hash
    matrix["plan_hash"] = plan_hash
    unresolved["plan_hash"] = plan_hash
    supplement["approved_plan_hash"] = plan_hash
    write_yaml(root / "plan" / "coverage_obligations.yaml", obligations_doc)
    write_yaml(root / "plan" / "coverage_matrix.yaml", matrix)
    write_yaml(root / "plan" / "unresolved.yaml", unresolved)
    write_yaml(root / "plan" / "human_supplement.yaml", supplement)

    with pytest.raises(TgSolveError, match="PLAN_BLOCKED"):
        tg_solve(repo, "DemoOp")


def test_snapshot_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_phase1(tmp_path, _contract(), _obligations([_pending("OB_A")]))
    root = repo / ".testcase-generator" / "DemoOp"
    snapshot = read_yaml(root / "snapshot" / "understand_contract.json")
    snapshot["files"]["quality.yaml"]["status"] = "warn"
    write_json(root / "snapshot" / "understand_contract.json", snapshot)

    with pytest.raises(TgSolveError, match="SNAPSHOT_HASH_MISMATCH"):
        tg_solve(repo, "DemoOp")


def test_strict_bool_literal_parser() -> None:
    assert parse_bool_literal("false") is False
    assert parse_bool_literal("true") is True
    with pytest.raises(Exception, match="INVALID_BOOL_LITERAL"):
        parse_bool_literal("nope")


def test_branch_signature_recognizes_kbr_and_kdec_variables() -> None:
    true_sig = coverage_signature({"VAR_KBR_HAS_TAIL": True, "VAR_KDEC_USE_MULTI_CORE": False})
    false_sig = coverage_signature({"VAR_KBR_HAS_TAIL": False, "VAR_KDEC_USE_MULTI_CORE": False})

    assert true_sig["branch_truth"] == {"KBR_HAS_TAIL": True, "KDEC_USE_MULTI_CORE": False}
    assert false_sig["branch_truth"]["KBR_HAS_TAIL"] is False
    assert true_sig != false_sig
    assert branch_stable_key("VAR_BRANCH_LEGACY") == "LEGACY"


def test_branch_true_false_candidates_do_not_dedupe() -> None:
    candidates = [
        {"id": "CAND_TRUE", "coverage_signature": coverage_signature({"VAR_KBR_HAS_TAIL": True}), "source_obligation_ids": ["OB_TRUE"], "covered_obligation_ids": ["OB_TRUE"]},
        {"id": "CAND_FALSE", "coverage_signature": coverage_signature({"VAR_KBR_HAS_TAIL": False}), "source_obligation_ids": ["OB_FALSE"], "covered_obligation_ids": ["OB_FALSE"]},
    ]

    assert len(dedupe_candidates(candidates)) == 2


def test_unknown_int_domain_does_not_limit_to_zero_one() -> None:
    contract = _contract(variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int"}])
    obligation = _pending("OB_AXIS_2", constraints={"expr": {"op": "eq", "var": "VAR_KEY_SPLIT_AXIS", "value": 2}})
    result = solve_from_docs(_snapshot(contract), _obligations([obligation]), {"decision": "approve"})
    variables = {item["id"]: item for item in result["constraint_ir"]["variables"]}

    assert variables["VAR_KEY_SPLIT_AXIS"]["domain"]["explicit"] is False
    assert result["solve_results"][0]["status"] == "sat"
    assert result["solve_results"][0]["model"]["VAR_KEY_SPLIT_AXIS"] == 2


def test_obligation_values_do_not_expand_explicit_int_domain() -> None:
    contract = _contract(variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int", "domain": {"min": 0, "max": 1}}])
    obligation = _pending("OB_AXIS_3", kind="tiling_key_field_value", target_refs=["KEY_SPLIT_AXIS"], constraints={"field": "split_axis", "values": [0, 1, 2, 3]})
    result = build_constraint_ir(_snapshot(contract), _obligations([obligation]), {"decision": "approve"})
    variables = {item["id"]: item for item in result.ir["variables"]}

    assert variables["VAR_KEY_SPLIT_AXIS"]["domain"]["max"] == 1
    assert any(error["code"] == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN" for error in result.errors)


def test_explicit_enum_domain_rejects_coverage_value_outside_domain() -> None:
    contract = _contract(variables=[{"id": "VAR_KEY_MODE", "type": "enum", "domain": ["A", "B"]}])
    obligation = _pending("OB_MODE_C", kind="tiling_key_field_value", target_refs=["KEY_MODE"], constraints={"field": "mode", "values": ["C"]})
    result = build_constraint_ir(_snapshot(contract), _obligations([obligation]), {"decision": "approve"})
    variable = next(item for item in result.ir["variables"] if item["id"] == "VAR_KEY_MODE")

    assert variable["domain"] == ["A", "B"]
    assert any(error["code"] == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN" for error in result.errors)


def test_target_outside_explicit_domain_does_not_solve_sat() -> None:
    contract = _contract(variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int", "domain": {"min": 0, "max": 1}}])
    obligation = _pending("OB_AXIS_2", priority="high", constraints={"expr": {"op": "eq", "var": "VAR_KEY_SPLIT_AXIS", "value": 2}})
    result = solve_from_docs(_snapshot(contract), _obligations([obligation]), {"decision": "approve"})

    assert result["solve_results"][0]["status"] == "error"
    assert result["solve_results"][0]["code"] == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN"


def test_branch_conflict_uses_obligation_metadata_not_id_text() -> None:
    candidate = {"id": "CAND_MERGED", "coverage_signature": {"same": True}, "source_obligation_ids": ["unrelated_one"], "covered_obligation_ids": ["unrelated_one"]}
    duplicate = {"id": "CAND_DUP", "coverage_signature": {"same": True}, "source_obligation_ids": ["unrelated_two"], "covered_obligation_ids": ["unrelated_two"]}
    obligations = [
        _pending("unrelated_one", kind="kernel_branch", target_refs=["KBR_HAS_TAIL"]),
        {**_pending("unrelated_two", kind="kernel_branch", target_refs=["KBR_HAS_TAIL"]), "target_value": False},
    ]
    obligations[0]["target_value"] = True

    with pytest.raises(CandidateError, match="CONTRADICTORY_BRANCH_COVERAGE"):
        dedupe_candidates([candidate, duplicate], obligations)


def test_nested_relation_schema_and_nonsemantic_combination_deduplication() -> None:
    files = {
        "contracts/testcase.yaml": _contract(),
        "tiling/coverage_model.yaml": {
            "family_obligations": [],
            "key_field_obligations": {},
            "key_relation_obligations": [{"id": "REL", "constraints": {"relation_type": "compatible_set", "combinations": [{"KEY_A": 0, "notes": "first"}, {"KEY_A": 0, "notes": "second"}]}}],
        },
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})
    relations = [item for item in plan["obligations"] if item["kind"] == "tiling_key_relation"]

    assert len(relations) == 1
    assert relations[0]["constraints"]["relation_type"] == "compatible_set"


def test_compatible_set_must_be_atomic_for_target_compiler() -> None:
    obligation = _pending(
        "OB_COMPAT",
        priority="high",
        kind="tiling_key_relation",
        constraints={"relation_type": "compatible_set", "combinations": [{"VAR_A": 0}, {"VAR_A": 1}]},
    )
    result = compile_obligation_target(obligation, {"variables": [{"id": "VAR_A"}]})

    assert result.status == "error"
    assert result.code == "RELATION_NOT_ATOMIC"


def test_implies_witness_requires_antecedent_true() -> None:
    contract = _contract(variables=[{"id": "VAR_A", "type": "bool"}, {"id": "VAR_B", "type": "bool"}])
    obligation = _pending("OB_IMPLIES", kind="tiling_key_relation", constraints={"relation_type": "implies", "source": "VAR_A", "target": "VAR_B"})
    result = solve_from_docs(_snapshot(contract), _obligations([obligation]), {"decision": "approve"})

    assert result["solve_results"][0]["status"] == "sat"
    assert result["solve_results"][0]["model"]["VAR_A"] is True
    assert result["solve_results"][0]["model"]["VAR_B"] is True


def test_obligation_domain_error_is_local_and_does_not_skip_valid_obligation() -> None:
    contract = _contract(variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int", "domain": {"min": 0, "max": 1}}])
    valid = _pending("OB_VALID", constraints={"expr": {"op": "eq", "var": "VAR_KEY_SPLIT_AXIS", "value": 1}})
    invalid = _pending("OB_INVALID", constraints={"expr": {"op": "eq", "var": "VAR_KEY_SPLIT_AXIS", "value": 2}})

    result = solve_from_docs(_snapshot(contract), _obligations([valid, invalid]), {"decision": "approve"})
    by_id = {item["obligation_id"]: item for item in result["solve_results"]}

    assert result["constraint_ir"]["compile_errors"]["global"] == []
    assert by_id["OB_VALID"]["status"] == "sat"
    assert by_id["OB_INVALID"]["status"] == "error"
    assert by_id["OB_INVALID"]["code"] == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN"
    assert any(candidate["source_obligation_ids"] == ["OB_VALID"] for candidate in result["candidates"])
    assert all("OB_INVALID" not in candidate["covered_obligation_ids"] for candidate in result["candidates"])


def test_explicit_int_domains_intersect_and_conflict_globally() -> None:
    snapshot = _snapshot(
        _contract(
            variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int", "domain": {"min": 0, "max": 1}}],
        )
    )
    snapshot["context_slice"] = {"entities": [{"id": "KEY_SPLIT_AXIS", "data_type": "int", "min": 0, "max": 3}]}
    result = build_constraint_ir(snapshot, _obligations([]), {"decision": "approve"})
    variable = next(item for item in result.ir["variables"] if item["id"] == "VAR_KEY_SPLIT_AXIS")

    assert variable["domain"]["min"] == 0
    assert variable["domain"]["max"] == 1
    assert result.global_errors == []

    conflict_snapshot = _snapshot(_contract(variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int", "domain": {"min": 3, "max": 5}}]))
    conflict_snapshot["context_slice"] = {"entities": [{"id": "KEY_SPLIT_AXIS", "data_type": "int", "min": 0, "max": 1}]}
    conflict = build_constraint_ir(conflict_snapshot, _obligations([]), {"decision": "approve"})

    assert any(error["code"] == "DOMAIN_CONFLICT" and error["scope"] == "global" for error in conflict.global_errors)


def test_explicit_enum_domains_intersect_and_type_only_int_is_inferred() -> None:
    snapshot = _snapshot(_contract(variables=[{"id": "VAR_ENUM", "type": "enum", "domain": ["B", "C"]}, {"id": "VAR_FREE_INT", "type": "int"}]))
    snapshot["context_slice"] = {"entities": [{"id": "VAR_ENUM", "type": "enum", "domain": ["A", "B", "C"]}]}
    result = build_constraint_ir(snapshot, _obligations([]), {"decision": "approve"})
    variables = {item["id"]: item for item in result.ir["variables"]}

    assert variables["VAR_ENUM"]["domain"] == ["B", "C"]
    assert variables["VAR_FREE_INT"]["domain_authority"] == "inferred"
    assert variables["VAR_FREE_INT"]["domain"] == {"kind": "range", "min": None, "max": None, "explicit": False, "authority": "inferred", "sources": ["contracts/testcase.yaml.variables.type_only"]}

    conflict_snapshot = _snapshot(_contract(variables=[{"id": "VAR_ENUM", "type": "enum", "domain": ["B"]}]))
    conflict_snapshot["context_slice"] = {"entities": [{"id": "VAR_ENUM", "type": "enum", "domain": ["A"]}]}
    conflict = build_constraint_ir(conflict_snapshot, _obligations([]), {"decision": "approve"})

    assert any(error["code"] == "DOMAIN_CONFLICT" for error in conflict.global_errors)


def test_interface_dtype_domain_is_explicit_and_not_expanded_by_obligation() -> None:
    contract = _contract(interface={**_contract()["interface"], "dtype_layout_domains": [{"id": "FP16_TND"}, {"id": "BF16_ND"}]})
    obligation = _pending("OB_FP32", kind="dtype_layout_class", target_refs=["FP32_NHWC"])

    result = build_constraint_ir(_snapshot(contract), _obligations([obligation]), {"decision": "approve"})
    variable = next(item for item in result.ir["variables"] if item["id"] == "VAR_DTYPE_LAYOUT_CLASS")

    assert variable["domain_authority"] == "explicit"
    assert variable["domain"] == ["BF16_ND", "FP16_TND"]
    assert result.global_errors == []
    assert result.obligation_errors["OB_FP32"][0]["code"] == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN"


def test_branch_validation_runs_before_dedupe_and_set_cover() -> None:
    obligations = [
        {**_pending("OB_TRUE", kind="kernel_branch", target_refs=["KBR_HAS_TAIL"]), "target_value": True},
        {**_pending("OB_FALSE", kind="kernel_branch", target_refs=["KBR_HAS_TAIL"]), "target_value": False},
    ]
    conflicting_candidate = {
        "id": "CAND_CONFLICT",
        "coverage_signature": coverage_signature({"VAR_KBR_HAS_TAIL": True}),
        "source_obligation_ids": ["OB_TRUE"],
        "covered_obligation_ids": ["OB_TRUE", "OB_FALSE"],
    }

    with pytest.raises(CandidateError, match="CONTRADICTORY_BRANCH_COVERAGE"):
        dedupe_candidates([conflicting_candidate], obligations)
    with pytest.raises(CandidateError, match="CONTRADICTORY_BRANCH_COVERAGE"):
        greedy_set_cover([conflicting_candidate], obligations)


def test_context_bucket_entities_are_aggregated_as_explicit_enum_domains() -> None:
    snapshot = _snapshot(_contract(variables=[]))
    snapshot["context_slice"] = {
        "entities": [
            {"id": "FAM_A"},
            {"id": "FAM_B"},
            {"id": "KPATH_A"},
            {"id": "KPATH_B"},
            {"id": "KTPL_A"},
            {"id": "KTPL_B"},
            {"id": "NUM_FAST"},
            {"id": "NUM_PRECISE"},
        ]
    }
    result = build_constraint_ir(snapshot, _obligations([]), {"decision": "approve"})
    variables = {item["id"]: item for item in result.ir["variables"]}

    assert variables["VAR_FAMILY"]["domain"] == ["FAM_A", "FAM_B"]
    assert variables["VAR_KERNEL_PATH"]["domain"] == ["KPATH_A", "KPATH_B"]
    assert variables["VAR_TEMPLATE"]["domain"] == ["KTPL_A", "KTPL_B"]
    assert variables["VAR_NUMERICAL_MODE"]["domain"] == ["NUM_FAST", "NUM_PRECISE"]
    assert variables["VAR_FAMILY"]["domain_authority"] == "explicit"
    assert result.global_errors == []


def test_context_bucket_enum_intersects_with_contract_domain_and_conflicts_globally() -> None:
    snapshot = _snapshot(_contract(variables=[{"id": "VAR_FAMILY", "type": "enum", "domain": ["FAM_A", "FAM_B"]}]))
    snapshot["context_slice"] = {"entities": [{"id": "FAM_A"}, {"id": "FAM_B"}, {"id": "FAM_C"}]}
    result = build_constraint_ir(snapshot, _obligations([]), {"decision": "approve"})
    variable = next(item for item in result.ir["variables"] if item["id"] == "VAR_FAMILY")

    assert variable["domain"] == ["FAM_A", "FAM_B"]
    assert result.global_errors == []

    conflict_snapshot = _snapshot(_contract(variables=[{"id": "VAR_FAMILY", "type": "enum", "domain": ["FAM_Z"]}]))
    conflict_snapshot["context_slice"] = {"entities": [{"id": "FAM_A"}, {"id": "FAM_B"}]}
    conflict = build_constraint_ir(conflict_snapshot, _obligations([]), {"decision": "approve"})

    assert any(error["code"] == "DOMAIN_CONFLICT" and error["scope"] == "global" for error in conflict.global_errors)


def test_family_path_template_numerical_coverage_targets_are_local_errors() -> None:
    contract = _contract(
        variables=[
            {"id": "VAR_FAMILY", "type": "enum", "domain": ["FAM_A"]},
            {"id": "VAR_KERNEL_PATH", "type": "enum", "domain": ["KPATH_A"]},
            {"id": "VAR_TEMPLATE", "type": "enum", "domain": ["KTPL_A"]},
            {"id": "VAR_NUMERICAL_MODE", "type": "enum", "domain": ["NUM_A"]},
        ]
    )
    obligations = [
        _pending("OB_FAM_A", kind="family", target_refs=["FAM_A"]),
        _pending("OB_FAM_B", kind="family", target_refs=["FAM_B"]),
        _pending("OB_PATH_B", kind="kernel_path", target_refs=["KPATH_B"]),
        _pending("OB_TPL_B", kind="compile_template", target_refs=["KTPL_B"]),
        _pending("OB_NUM_B", kind="numerical_mode", target_refs=["NUM_B"]),
    ]
    result = solve_from_docs(_snapshot(contract), _obligations(obligations), {"decision": "approve"})
    by_id = {item["obligation_id"]: item for item in result["solve_results"]}

    assert result["constraint_ir"]["compile_errors"]["global"] == []
    assert by_id["OB_FAM_A"]["status"] == "sat"
    for oid in ("OB_FAM_B", "OB_PATH_B", "OB_TPL_B", "OB_NUM_B"):
        assert by_id[oid]["status"] == "error"
        assert by_id[oid]["code"] == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN"
    assert any(candidate["source_obligation_ids"] == ["OB_FAM_A"] for candidate in result["candidates"])
    assert all("OB_FAM_B" not in candidate["covered_obligation_ids"] for candidate in result["candidates"])


def test_discrete_int_domain_restricts_z3_and_target_check() -> None:
    contract = _contract(variables=[{"id": "VAR_KEY_AXIS", "type": "int", "values": [0, 2, 4]}])
    obligations = [
        _pending("OB_AXIS_0", constraints={"expr": {"op": "eq", "var": "VAR_KEY_AXIS", "value": 0}}),
        _pending("OB_AXIS_2", constraints={"expr": {"op": "eq", "var": "VAR_KEY_AXIS", "value": 2}}),
        _pending("OB_AXIS_4", constraints={"expr": {"op": "eq", "var": "VAR_KEY_AXIS", "value": 4}}),
        _pending("OB_AXIS_1", constraints={"expr": {"op": "eq", "var": "VAR_KEY_AXIS", "value": 1}}),
    ]
    result = solve_from_docs(_snapshot(contract), _obligations(obligations), {"decision": "approve"})
    variable = next(item for item in result["constraint_ir"]["variables"] if item["id"] == "VAR_KEY_AXIS")
    by_id = {item["obligation_id"]: item for item in result["solve_results"]}

    assert variable["domain"] == {"kind": "discrete", "values": [0, 2, 4], "explicit": True, "authority": "explicit", "sources": ["contracts/testcase.yaml.variables"]}
    assert by_id["OB_AXIS_0"]["status"] == "sat"
    assert by_id["OB_AXIS_2"]["status"] == "sat"
    assert by_id["OB_AXIS_4"]["status"] == "sat"
    assert by_id["OB_AXIS_1"]["status"] == "error"
    assert by_id["OB_AXIS_1"]["code"] == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN"
    assert all(candidate["abstract_model"]["tiling_key_fields"].get("axis") in {None, 0, 2, 4} for candidate in result["candidates"])


def test_discrete_int_domain_merge_rules_and_legacy_compatibility() -> None:
    snapshot = _snapshot(_contract(variables=[{"id": "VAR_KEY_AXIS", "type": "int", "values": [0, 2, 4]}]))
    snapshot["context_slice"] = {"entities": [{"id": "VAR_KEY_AXIS", "type": "int", "domain": [2, 4, 6]}]}
    discrete = build_constraint_ir(snapshot, _obligations([]), {"decision": "approve"})
    variable = next(item for item in discrete.ir["variables"] if item["id"] == "VAR_KEY_AXIS")
    assert variable["domain"]["kind"] == "discrete"
    assert variable["domain"]["values"] == [2, 4]

    empty_snapshot = _snapshot(_contract(variables=[{"id": "VAR_KEY_AXIS", "type": "int", "values": [0]}]))
    empty_snapshot["context_slice"] = {"entities": [{"id": "VAR_KEY_AXIS", "type": "int", "domain": [2]}]}
    empty = build_constraint_ir(empty_snapshot, _obligations([]), {"decision": "approve"})
    assert any(error["code"] == "DOMAIN_CONFLICT" for error in empty.global_errors)

    range_snapshot = _snapshot(_contract(variables=[{"id": "VAR_KEY_AXIS", "type": "int", "domain": {"min": 0, "max": 4}}]))
    range_snapshot["context_slice"] = {"entities": [{"id": "VAR_KEY_AXIS", "type": "int", "domain": [0, 2, 6]}]}
    range_discrete = build_constraint_ir(range_snapshot, _obligations([]), {"decision": "approve"})
    variable = next(item for item in range_discrete.ir["variables"] if item["id"] == "VAR_KEY_AXIS")
    assert variable["domain"]["kind"] == "discrete"
    assert variable["domain"]["values"] == [0, 2]

    legacy_list = build_constraint_ir(_snapshot(_contract(variables=[{"id": "VAR_LEGACY", "type": "int", "domain": [0, 2, 4]}])), _obligations([]), {"decision": "approve"})
    legacy_range = build_constraint_ir(_snapshot(_contract(variables=[{"id": "VAR_RANGE", "type": "int", "domain": {"min": 0, "max": 4}}])), _obligations([]), {"decision": "approve"})
    assert next(item for item in legacy_list.ir["variables"] if item["id"] == "VAR_LEGACY")["domain"]["kind"] == "discrete"
    assert next(item for item in legacy_range.ir["variables"] if item["id"] == "VAR_RANGE")["domain"]["kind"] == "range"


def test_branch_and_optional_bool_type_conflicts_are_local() -> None:
    contract = _contract(
        variables=[
            {"id": "VAR_KBR_HAS_TAIL", "type": "int", "domain": {"min": 0, "max": 1}},
            {"id": "VAR_OPTIONAL_MASK", "type": "enum", "domain": ["present", "absent"]},
            {"id": "VAR_FAMILY", "type": "enum", "domain": ["FAM_A"]},
        ],
        interface={**_contract()["interface"], "optional_inputs": []},
    )
    obligations = [
        _pending("OB_FAM_A", kind="family", target_refs=["FAM_A"]),
        {**_pending("OB_BRANCH", kind="kernel_branch", target_refs=["KBR_HAS_TAIL"]), "target_value": True},
        {**_pending("OB_OPTIONAL", kind="optional_input_mode", target_refs=["MASK"]), "target_value": True},
    ]
    result = solve_from_docs(_snapshot(contract), _obligations(obligations), {"decision": "approve"})
    by_id = {item["obligation_id"]: item for item in result["solve_results"]}

    assert result["constraint_ir"]["compile_errors"]["global"] == []
    assert by_id["OB_FAM_A"]["status"] == "sat"
    for oid in ("OB_BRANCH", "OB_OPTIONAL"):
        assert by_id[oid]["status"] == "error"
        assert by_id[oid]["code"] == "VARIABLE_TYPE_CONFLICT"
        assert by_id[oid]["errors"][0]["obligation_id"] == oid
    assert all("OB_BRANCH" not in candidate["covered_obligation_ids"] for candidate in result["candidates"])
