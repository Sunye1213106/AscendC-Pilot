from __future__ import annotations

import pytest

from testcase_agent.composer import compose_global_legal, merge_composed_into_ir
from testcase_agent.constraint_ir import compile_obligation_target
from testcase_agent.extract import extract_generation_conditions, merge_llm_patches
from testcase_agent.realize import build_case_row, match_realization


def test_extract_marks_key_card_gaps() -> None:
    snapshot = {
        "snapshot_hash": "s",
        "files": {
            "contracts/testcase.yaml": {"typed_constraints": [], "variables": [], "interface": {}},
            "tiling/constraints.yaml": {"relations": [], "input_realization": {}},
            "tiling/coverage_model.yaml": {"key_field_obligations": {}},
            "kernel/branches.yaml": {"branches": []},
            "tiling/key_cards/KEY_DETERTYPE.yaml": {
                "id": "KEY_DETERTYPE",
                "domain": [0, 1],
                "set_by": {"status": "missing"},
                "host_reachable": {"status": "unknown"},
                "hit_recipe": {"status": "unknown", "note": "left for LLM"},
            },
        },
    }
    doc = extract_generation_conditions(snapshot, level="L3", topic="determinism")
    assert doc["needs_llm_completion"]
    assert any(item["code"] == "EXTRACT_GAP" for item in doc["gaps"])
    assert any(item["id"].startswith("GC_KEYCARD_DOMAIN_") for item in doc["conditions"])


def test_llm_patch_merge_rejects_unknown_vars() -> None:
    extract_doc = {"conditions": [], "gaps": [{"id": "GC_X", "code": "EXTRACT_GAP", "priority": "high"}], "topic": "determinism"}
    merged = merge_llm_patches(
        extract_doc,
        [{"id": "GC_LLM_1", "closes_gap": "GC_X", "expr": {"op": "eq", "var": "VAR_UNKNOWN", "value": 1}}],
        declared_variables={"VAR_KEY_DETERTYPE"},
    )
    assert merged["rejected_llm_patches"]
    assert not merged["accepted_llm_patches"]


def test_composer_preserves_implies() -> None:
    extract_doc = {
        "conditions": [
            {
                "id": "GC_1",
                "role": "legal",
                "expr": {
                    "op": "implies",
                    "antecedent": {"op": "eq", "var": "VAR_A", "value": True},
                    "consequent": {"op": "eq", "var": "VAR_B", "value": True},
                },
            }
        ]
    }
    composed = compose_global_legal(extract_doc, {})
    assert composed[0]["expr"]["op"] == "implies"
    ir = merge_composed_into_ir({"constraints": []}, composed)
    assert len(ir["constraints"]) == 1


def test_implies_legal_mode_compiles_to_implies() -> None:
    obligation = {
        "id": "OB",
        "kind": "tiling_key_relation",
        "status": "pending",
        "priority": "high",
        "target_refs": ["VAR_A", "VAR_B"],
        "constraints": {"relation_type": "implies", "source": "VAR_A", "target": "VAR_B", "compile_mode": "legal"},
    }
    result = compile_obligation_target(obligation, {"variables": [{"id": "VAR_A"}, {"id": "VAR_B"}]})
    assert result.status == "ok"
    assert result.expr["op"] == "implies"


def test_realize_legacy_build_case_row_removed() -> None:
    model = {"VAR_KEY_DETERTYPE": 1, "VAR_KEY_ISTND": 0, "VAR_DTYPE_LAYOUT_CLASS": "FP16_BNSD"}
    realization = match_realization(model, {"id": "C1"}, {})
    assert realization["status"] == "blocked"
    assert "DEFAULT_SHAPE" in realization["reason"] or "input_realization" in realization["reason"]
    with pytest.raises(RuntimeError, match="LEGACY_BUILD_CASE_ROW_REMOVED"):
        build_case_row({"id": "C1"}, model, {"status": "ok", "shape": {}}, 1)
