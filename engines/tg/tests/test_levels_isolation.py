"""L0/L1 isolation, approve gates, and plan-dir read path (ses_07ce fixes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testcase_agent.consumer_evidence import merge_domain_hints_preserving_confirmed
from testcase_agent.io import read_yaml, resolve_plan_dir, write_yaml
from testcase_agent.planner import write_plan_outputs
from testcase_agent.realization_schema import build_consumer_schema_from_evidence
from testcase_agent.review_checkpoint import _approve_block_reason, _commit_plan_decision
from testcase_agent.solve import TgSolveError, tg_solve


def _minimal_plan(level: str, *, plan_hash: str, snapshot_hash: str = "snap") -> dict[str, Any]:
    return {
        "test_level": level,
        "plan_hash": plan_hash,
        "status": "ready_for_manual_review",
        "semantic_focus": {"csv_realization": {"pending_count": 1}},
        "planning_context": {"level": level},
        "obligations": [
            {
                "id": f"OB_{level}",
                "kind": "family",
                "status": "pending",
                "priority": "hard",
                "target_refs": [f"FAM_{level}"],
                "constraints": {},
            }
        ],
        "matrix": {
            "by_kind": {},
            "priority_counts": {"hard": 1},
            "total": 1,
            "unreachable": [],
            "test_points": [],
        },
        "unresolved": {
            "status": "ready_for_manual_review",
            "blocking_hard_obligations": [],
            "unresolved_obligations": [],
            "contract_gaps": [],
        },
        "coverage_inventory": {"variable_count": 1, "value_point_count": 1, "by_kind": {}},
        "review": f"# review {level}\n",
    }


def test_write_plan_outputs_archives_full_levels_without_root_truth(tmp_path: Path) -> None:
    out = tmp_path / "op"
    (out / "plan").mkdir(parents=True)
    snapshot = {"snapshot_hash": "snap-a", "op_name": "DemoOp"}

    write_plan_outputs(out, _minimal_plan("L0", plan_hash="hash-L0"), snapshot)
    write_plan_outputs(out, _minimal_plan("L1", plan_hash="hash-L1"), snapshot)

    l0 = out / "plan" / "levels" / "L0"
    l1 = out / "plan" / "levels" / "L1"
    for level_dir, expected_hash, expected_level in ((l0, "hash-L0", "L0"), (l1, "hash-L1", "L1")):
        for name in (
            "coverage_obligations.yaml",
            "coverage_matrix.yaml",
            "coverage_inventory.yaml",
            "semantic_focus.yaml",
            "unresolved.yaml",
            "human_supplement.yaml",
            "summary.yaml",
            "review.md",
        ):
            assert (level_dir / name).exists(), name
        obl = read_yaml(level_dir / "coverage_obligations.yaml")
        assert obl["test_level"] == expected_level
        assert obl["plan_hash"] == expected_hash
        assert obl["obligations"][0]["id"] == f"OB_{expected_level}"

    assert not (out / "plan" / "coverage_obligations.yaml").exists()
    latest = read_yaml(out / "plan" / "latest_level.yaml")
    assert latest["level"] == "L1"
    assert latest["plan_hash"] == "hash-L1"


def test_resolve_plan_dir_requires_level_archive(tmp_path: Path) -> None:
    out = tmp_path / "op"
    (out / "plan").mkdir(parents=True)
    write_yaml(out / "plan" / "coverage_obligations.yaml", {"plan_hash": "root-only", "obligations": []})

    with pytest.raises(FileNotFoundError, match="PLAN_LEVEL_REQUIRED|Missing coverage plan|Do not Copy"):
        resolve_plan_dir(out, "")

    with pytest.raises(FileNotFoundError, match="Missing coverage plan for L0|Do not Copy"):
        resolve_plan_dir(out, "L0")


def test_approve_uses_matching_level_hash(tmp_path: Path) -> None:
    out = tmp_path / "op"
    (out / "snapshot").mkdir(parents=True)
    snapshot = {"snapshot_hash": "snap-a", "op_name": "DemoOp"}
    write_yaml(out / "snapshot" / "understand_contract.json", snapshot)  # wrong: need json
    from testcase_agent.io import write_json

    write_json(out / "snapshot" / "understand_contract.json", snapshot)
    write_plan_outputs(out, _minimal_plan("L0", plan_hash="hash-L0"), snapshot)
    write_plan_outputs(out, _minimal_plan("L1", plan_hash="hash-L1"), snapshot)

    # Mark domain review confirmed so approve hard-gate does not trip on missing realization.
    write_yaml(
        out / "realization" / "domain_review.yaml",
        {"version": 1, "status": "confirmed", "pending_columns": [], "columns": []},
    )

    payload = _commit_plan_decision(out, op_name="DemoOp", choice="approve", notes="", level="L0")
    assert payload["approved_plan_hash"] == "hash-L0"
    assert "L0" in payload["path"].replace("\\", "/")
    assert read_yaml(out / "plan" / "levels" / "L1" / "human_supplement.yaml").get("status") != "approved"


def test_approve_blocked_when_allow_solve_no(tmp_path: Path) -> None:
    out = tmp_path / "op"
    (out / "snapshot").mkdir(parents=True)
    from testcase_agent.io import write_json

    snapshot = {"snapshot_hash": "snap-a", "op_name": "DemoOp"}
    write_json(out / "snapshot" / "understand_contract.json", snapshot)
    plan = _minimal_plan("L1", plan_hash="hash-L1")
    plan["unresolved"] = {
        "status": "ready_for_manual_review",
        "blocking_hard_obligations": [],
        "unresolved_obligations": [],
        "contract_gaps": [
            {
                "field": "realization/domain_review.yaml",
                "reason": "DOMAIN_REVIEW_REQUIRED: 2 columns unreviewed (e.g. Drop_Out). Continue /tg-init binding/domain phase.",
            }
        ],
    }
    write_plan_outputs(out, plan, snapshot)

    with pytest.raises(ValueError, match="APPROVE_BLOCKED.*DOMAIN_REVIEW_REQUIRED"):
        _commit_plan_decision(out, op_name="DemoOp", choice="approve", notes="", level="L1")

    reason = _approve_block_reason(out, plan["unresolved"])
    assert reason and "DOMAIN_REVIEW_REQUIRED" in reason


def test_solve_missing_levels_errors_without_silent_copy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    root = repo / ".ascendc-agent" / "tg"
    (root / "snapshot").mkdir(parents=True)
    (root / "plan").mkdir(parents=True)
    from testcase_agent.hashing import semantic_snapshot_hash
    from testcase_agent.io import write_json

    snapshot = {
        "op_name": "DemoOp",
        "files": {"quality.yaml": {"status": "pass"}},
        "snapshot_hash": "",
    }
    snapshot["snapshot_hash"] = semantic_snapshot_hash(snapshot)
    write_json(root / "snapshot" / "understand_contract.json", snapshot)
    # Root-only obligations (legacy pollution) must not be used.
    write_yaml(
        root / "plan" / "coverage_obligations.yaml",
        {"version": 1, "plan_hash": "x", "obligations": [], "snapshot_hash": snapshot["snapshot_hash"]},
    )

    with pytest.raises(TgSolveError, match="PLAN_LEVEL_REQUIRED|Missing coverage plan|Do not Copy"):
        tg_solve(repo, "DemoOp", level="L0")


def test_confirmed_domain_hints_survive_merge_and_schema_rebuild() -> None:
    existing = {
        "version": 1,
        "source": "human",
        "columns": {
            "Drop_Out_Possibility": {
                "values": [0.8, 0.9, 1.0],
                "status": "confirmed",
                "source": "human",
            },
            "Other": {"values": [], "status": "pending"},
        },
    }
    stub = {
        "version": 1,
        "source": "domain_hints_stub",
        "columns": {
            "Drop_Out_Possibility": {"values": [], "status": "pending", "source": "needs_llm_or_human"},
            "Other": {"values": [1], "status": "proposed"},
            "NewCol": {"values": [], "status": "pending"},
        },
    }
    merged = merge_domain_hints_preserving_confirmed(existing, stub)
    assert merged["columns"]["Drop_Out_Possibility"]["status"] == "confirmed"
    assert merged["columns"]["Drop_Out_Possibility"]["values"] == [0.8, 0.9, 1.0]
    assert "NewCol" in merged["columns"]

    evidence = {
        "ordered_header_candidates": [{"path": "t.csv", "columns": ["Drop_Out_Possibility", "Enable"]}],
        "field_accesses": {"Drop_Out_Possibility": [{"path": "t.py", "line": 1}]},
        "sample_values": {"Drop_Out_Possibility": ["0.123"]},
        "domain_hints": {"columns": merged["columns"]},
        "warnings": [],
    }
    schema = build_consumer_schema_from_evidence(evidence, Path("."), key_space={}, snapshot_files={})
    field = next(f for f in schema["fields"] if f["name"] == "Drop_Out_Possibility")
    domain = field["domain"]
    values = domain.get("values") if isinstance(domain, dict) else domain
    assert 0.8 in values or "0.8" in {str(v) for v in values}
