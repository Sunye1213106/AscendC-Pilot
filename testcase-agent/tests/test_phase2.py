from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testcase_agent.candidates import dedupe_candidates, greedy_set_cover
from testcase_agent.constraint_ir import build_constraint_ir
from testcase_agent.io import read_yaml, write_json, write_yaml
from testcase_agent.solve import TgSolveError, solve_from_docs, tg_solve
from testcase_agent.z3_backend import Z3Backend


def _snapshot(contract: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "op_name": "DemoOp",
        "view": "testcase-contract",
        "snapshot_hash": "snap",
        "files": {
            "contracts/testcase.yaml": contract or _contract(),
            "quality.yaml": {"status": "pass"},
        },
    }


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


def _obligations(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": 1, "snapshot_hash": "snap", "obligations": items}


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
    write_json(root / "snapshot" / "understand_contract.json", _snapshot(contract))
    write_yaml(root / "plan" / "coverage_obligations.yaml", obligations)
    write_yaml(root / "plan" / "human_supplement.yaml", supplement or {"version": 1, "decision": "approve", "supplements": []})
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
        "coverage_signature": {"family_refs": ["FAM_A"], "covered_obligation_ids": ["OB1"]},
        "covered_obligation_ids": ["OB1"],
    }
    duplicate = {
        "id": "CAND_B",
        "coverage_signature": {"family_refs": ["FAM_A"], "covered_obligation_ids": ["OB1"]},
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
