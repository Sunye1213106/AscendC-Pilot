"""CSV runnable quality: alias fold, no underscore, plan gates, review copy, slim artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.domain_policy import (
    expand_enum_domain,
    fold_shape_layout_columns,
    probability_domain_values,
    sanitize_cell_value,
    shape_range_domain,
)
from testcase_agent.planner import apply_realization_review_gates, build_review
from testcase_agent.realization_schema import build_consumer_schema_from_evidence, _shape_default
from testcase_agent.realize import materialize_row_from_contract
from testcase_agent.solve import write_solve_outputs


def test_fold_layout_into_shape() -> None:
    cols, aliases = fold_shape_layout_columns(
        ["Input_Layout", "PSE_shape", "PSE_layout", "Atten_mask_shape", "Atten_mask_layout", "B"]
    )
    assert "PSE_layout" not in cols
    assert "Atten_mask_layout" not in cols
    assert "PSE_shape" in cols and "Atten_mask_shape" in cols
    assert aliases["PSE_layout"] == "PSE_shape"
    assert "Input_Layout" in cols


def test_secondary_layout_domain_has_no_underscore() -> None:
    assert "_" not in expand_enum_domain("PSE_layout", ["_"])
    assert "_" not in expand_enum_domain("Input_Layout", [])


def test_probability_domain_excludes_zero() -> None:
    vals = probability_domain_values([0, 0.0, 1, 0.9], column="keep_prob")
    assert 0 not in vals and 0.0 not in vals
    assert all(v > 0 for v in vals)


def test_shape_default_not_always_one() -> None:
    dom = shape_range_domain("S1", sample_ints=[])
    assert _shape_default(dom) != 1 or dom["max"] == 1


def test_schema_folds_aliases_and_skips_underscore(tmp_path: Path) -> None:
    evidence = {
        "ordered_header_candidates": [
            {"columns": ["Input_Layout", "PSE_shape", "PSE_layout", "B", "keep_prob"]}
        ],
        "field_accesses": {},
        "sample_values": {},
        "domain_hints": {},
        "warnings": [],
    }
    schema = build_consumer_schema_from_evidence(evidence, tmp_path)
    assert "PSE_layout" not in schema["columns"]
    assert "PSE_shape" in schema["columns"]
    by_name = {f["name"]: f for f in schema["fields"]}
    assert "_" not in str(by_name["PSE_shape"].get("domain"))
    assert by_name["keep_prob"]["role"] in {"probability", "solver_input"} or "values" in str(
        by_name["keep_prob"]["domain"]
    )
    domain = by_name["keep_prob"]["domain"]
    vals = domain.get("values") if isinstance(domain, dict) else domain
    assert 0 not in (vals or [])


def test_realize_sanitizes_underscore() -> None:
    schema = {
        "fields": [
            {"name": "PSE_shape", "order": 0, "role": "solver_input", "required": False, "default": "NONE", "serializer": "string"},
            {"name": "blob", "order": 1, "role": "emit_skip", "required": False, "default": "", "serializer": "string"},
        ]
    }
    row = materialize_row_from_contract(
        {"id": "CAND_1"},
        {"VAR_CSV_PSE_shape": "_"},
        schema,
        {},
        1,
    )
    assert row["PSE_shape"] != "_"
    assert sanitize_cell_value("_", role="emit_skip") == ""


def test_plan_gates_block_pending_domain(tmp_path: Path) -> None:
    from testcase_agent.io import write_yaml

    out = tmp_path / "op"
    real = out / "realization"
    real.mkdir(parents=True)
    write_yaml(real / "domain_review.yaml", {"status": "pending", "pending_columns": ["B", "S1"]})
    write_yaml(real / "unresolved.yaml", {"binding_gaps": []})
    unresolved = {"status": "ready_for_manual_review", "blocking_hard_obligations": [], "contract_gaps": []}
    apply_realization_review_gates(out, unresolved)
    assert unresolved["status"] == "blocked"
    assert any("DOMAIN_REVIEW" in g.get("reason", "") for g in unresolved["contract_gaps"])


def test_review_copy_explains_checkpoints_not_family() -> None:
    from testcase_agent.planner import build_matrix, make_obligation, decorate_obligation

    item = make_obligation(
        "tiling_key_field_value",
        {"id": "OB1", "field": "X", "target_value": 1, "status": "pending", "priority": "high"},
        target_refs=["KEY_X"],
        priority="high",
    )
    decorate_obligation(item, "L0", {"artifact": "test", "entity_ref": "KEY_X", "reason": "unit"}, "", {})
    obligations = [item]
    text = build_review(
        {"op_name": "Demo", "snapshot_hash": "abc"},
        obligations,
        build_matrix(obligations),
        {"blocking_hard_obligations": [], "contract_gaps": [], "status": "ready_for_manual_review"},
        level="L0",
        semantic_focus={},
    )
    assert "覆盖检查点" in text
    assert "不等于" in text and "CSV" in text
    assert "family/kernel_path" not in text
    assert "Hard / High / Normal" not in text


def test_write_solve_outputs_slim_by_default(tmp_path: Path) -> None:
    solve_root = tmp_path / "solve"
    solve_root.mkdir()
    result = {
        "snapshot_hash": "x",
        "constraint_ir": {"variables": [{"id": "a"}], "constraints": []},
        "candidates": [],
        "deduped_candidates": [],
        "selected_candidates": [{"id": "C1"}],
        "uncovered_obligations": [],
        "unsat_obligations": [],
        "unknown_obligations": [],
        "errors": [],
        "dedupe_enabled": False,
        "solver_report": {"chinese_report": "# ok\n"},
    }
    write_solve_outputs(solve_root, result, debug_artifacts=False)
    assert (solve_root / "constraint_ir_summary.yaml").is_file()
    assert not (solve_root / "constraint_ir.yaml").is_file()
    assert not (solve_root / "candidates.yaml").is_file()
    assert (solve_root / "solver_report.md").is_file()
