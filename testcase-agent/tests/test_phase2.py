from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testcase_agent.candidates import branch_stable_key, coverage_signature, dedupe_candidates, greedy_set_cover
from testcase_agent.constraint_ir import build_constraint_ir, compile_obligation_target, parse_bool_literal
from testcase_agent.hashing import semantic_plan_hash, semantic_snapshot_hash
from testcase_agent.io import read_yaml, write_json, write_yaml
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


def test_obligation_values_expand_int_domain() -> None:
    contract = _contract(variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int", "domain": {"min": 0, "max": 1}}])
    obligation = _pending("OB_AXIS_3", kind="tiling_key_field_value", target_refs=["KEY_SPLIT_AXIS"], constraints={"field": "split_axis", "values": [0, 1, 2, 3]})
    result = build_constraint_ir(_snapshot(contract), _obligations([obligation]), {"decision": "approve"})
    variables = {item["id"]: item for item in result.ir["variables"]}

    assert variables["VAR_KEY_SPLIT_AXIS"]["domain"]["max"] == 3


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
