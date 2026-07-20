from __future__ import annotations

import csv
from pathlib import Path

import yaml

from testcase_agent.binding_lexicon import normalize_lexicon
from testcase_agent.constraint_ir import build_constraint_ir, compile_obligation_target
from testcase_agent.hashing import stable_hash
from testcase_agent.io import read_yaml
from testcase_agent.realization_map import build_realization_map
from testcase_agent.realization_schema import extract_consumer_schema
from testcase_agent.realize import realize_candidates_to_csv
from testcase_agent.realization_validation import validate_contract_artifacts

_FIXTURE_LEXICON = normalize_lexicon(
    yaml.safe_load((Path(__file__).parent / "fixtures" / "sample_binding_lexicon.yaml").read_text(encoding="utf-8"))
)


def _consumer_root(tmp_path: Path) -> Path:
    root = tmp_path / "fag_debug_tools"
    (root / "fag_test").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "fag_test" / "test_utils.py").write_text(
        "\n".join(
            [
                "def use_columns(table):",
                "    get_column_index(table, \"rope\")",
                "    get_column_index(table, \"Atten_mask_shape\")",
                "    get_column_index(table, \"Script_Only\")",
            ]
        ),
        encoding="utf-8",
    )
    (root / "data" / "FASG_PSE_cases.csv").write_text(
        "Testcase_Name,Enable,Input_Layout,B,S1,S2,D,D_V,seqlens_list_q,seqlens_list_kv,cu_seqlens_q,cu_seqlens_kv,Actual_Result\n"
        "case0,Enable,TND,2,16,32,64,128,,,,,PASS\n",
        encoding="utf-8",
    )
    return root


def _snapshot() -> dict:
    return {
        "snapshot_hash": "snap",
        "files": {
            "contracts/testcase.yaml": {"version": 2, "variables": [], "typed_constraints": []},
            "tiling/key_space.yaml": {
                "fields": [
                    {"id": "KEY_ISTND", "values": [0, 1]},
                    {"id": "KEY_ISROPE", "values": [0, 1]},
                    {"id": "KEY_ISDNOEQUAL", "values": [0, 1]},
                    {"id": "KEY_ISATTENMASK", "values": [0, 1]},
                ]
            },
            "kernel/branches.yaml": {
                "branches": [
                    {"id": "KBR_TND", "condition": "IS_TND", "file_path": "kernel.cpp", "start_line": 12},
                    {"id": "KBR_COMPLEX", "condition": "foo && bar", "file_path": "kernel.cpp", "start_line": 34},
                ]
            },
        },
    }


def _consumer_contract() -> tuple[dict, dict, dict]:
    evidence = {
        "version": 1,
        "consumer_root": "",
        "files_read": [],
        "ordered_header_candidates": [{"path": "fixture.csv", "reason": "sample_csv", "columns": ["Testcase_Name", "Enable", "Input_Layout", "B", "rope", "seqlens_list_q"]}],
        "field_accesses": {
            "Enable": [{"path": "fixture.py", "line": 1, "kind": "required_read"}],
            "Input_Layout": [{"path": "fixture.py", "line": 2, "kind": "required_read"}],
            "B": [{"path": "fixture.py", "line": 3, "kind": "required_read"}],
            "rope": [{"path": "fixture.py", "line": 4, "kind": "required_read"}],
            "seqlens_list_q": [{"path": "fixture.py", "line": 5, "kind": "required_read"}],
        },
        "sample_values": {"Enable": ["Enable"], "Input_Layout": ["TND"]},
        "type_conversion_evidence": {},
        "required_optional_evidence": {"rope": [{"path": "fixture.py", "line": 4, "kind": "required_read"}]},
        "test_requirement_refs": [],
        "snapshot_hash": "snap",
        "plan_hash": "plan",
        "warnings": [],
    }
    evidence["evidence_hash"] = stable_hash(
        {
            "ordered_header_candidates": evidence["ordered_header_candidates"],
            "field_accesses": evidence["field_accesses"],
            "sample_values": evidence["sample_values"],
            "snapshot_hash": "snap",
            "plan_hash": "plan",
        }
    )
    schema = {
        "version": 1,
        "evidence_hash": evidence["evidence_hash"],
        "snapshot_hash": "snap",
        "plan_hash": "plan",
        "fields": [
            {"name": "Testcase_Name", "order": 0, "required": True, "role": "case_id", "value_type": "string", "domain": ["*"], "default": "", "serializer": "string", "aliases": [], "source_refs": [{"path": "fixture"}], "confidence": "high", "rationale": "id"},
            {"name": "Enable", "order": 1, "required": True, "role": "constant", "value_type": "string", "domain": ["Enable"], "default": "Enable", "serializer": "string", "aliases": [], "source_refs": [{"path": "fixture"}], "confidence": "high", "rationale": "constant"},
            {"name": "Input_Layout", "order": 2, "required": True, "role": "solver_input", "value_type": "enum", "domain": ["TND"], "default": "TND", "serializer": "string", "aliases": [], "source_refs": [{"path": "fixture"}], "confidence": "high", "rationale": "layout"},
            {"name": "B", "order": 3, "required": True, "role": "solver_input", "value_type": "int", "domain": {"min": 1, "max": 8}, "default": 1, "serializer": "string", "aliases": [], "source_refs": [{"path": "fixture"}], "confidence": "high", "rationale": "batch"},
            {"name": "rope", "order": 4, "required": True, "role": "solver_input", "value_type": "int", "domain": {"values": [0, 1]}, "default": 0, "serializer": "string", "aliases": [], "source_refs": [{"path": "fixture"}], "confidence": "high", "rationale": "rope"},
            {"name": "seqlens_list_q", "order": 5, "required": True, "role": "emit_derived", "value_type": "list_int", "domain": [], "default": [], "serializer": "list_string", "aliases": [], "source_refs": [{"path": "fixture"}], "confidence": "high", "rationale": "derived list"},
        ],
    }
    realization_map = {
        "version": 2,
        "evidence_hash": evidence["evidence_hash"],
        "snapshot_hash": "snap",
        "plan_hash": "plan",
        "consumer": {"columns": ["Testcase_Name", "Enable", "Input_Layout", "B", "rope", "seqlens_list_q"]},
        "csv_variables": [
            {"id": "VAR_CSV_Input_Layout", "column": "Input_Layout", "type": "enum", "domain": ["TND"], "source_refs": [{"path": "fixture"}]},
            {"id": "VAR_CSV_B", "column": "B", "type": "int", "domain": {"min": 1, "max": 8}, "source_refs": [{"path": "fixture"}]},
            {"id": "VAR_CSV_rope", "column": "rope", "type": "int", "domain": {"values": [0, 1]}, "source_refs": [{"path": "fixture"}]},
        ],
        "derived_variables": [],
        "branch_mappings": [{"branch_ref": "KBR_TND", "var": "VAR_KBR_TND", "condition": "IS_TND", "file_path": "kernel.cpp", "start_line": 12, "source_refs": [{"path": "kernel.cpp", "line": 12}]}],
        "abstract_branches": [],
        "emit": {
            "columns": {
                "Testcase_Name": {"op": "template", "template": "{case_id}"},
                "seqlens_list_q": {"op": "list_format", "values": {"op": "balanced_partition", "total": {"op": "constant", "value": 9}, "parts": {"op": "model_var", "var": "VAR_CSV_B"}}},
            }
        },
        "warnings": [],
    }
    return evidence, schema, realization_map


def test_consumer_schema_uses_sample_header_then_script_columns(tmp_path: Path) -> None:
    schema = extract_consumer_schema(_consumer_root(tmp_path))

    assert schema["columns"][:13] == [
        "Testcase_Name",
        "Enable",
        "Input_Layout",
        "B",
        "S1",
        "S2",
        "D",
        "D_V",
        "seqlens_list_q",
        "seqlens_list_kv",
        "cu_seqlens_q",
        "cu_seqlens_kv",
        "Actual_Result",
    ]
    assert schema["columns"][-3:] == ["rope", "Atten_mask_shape", "Script_Only"]
    assert schema["result_columns"] == ["Actual_Result"]
    assert schema["sample_values"]["Input_Layout"] == ["TND"]


def test_realization_map_registers_csv_variables_and_abstract_branches(tmp_path: Path) -> None:
    schema = extract_consumer_schema(_consumer_root(tmp_path))
    realization_map = build_realization_map(_snapshot(), schema, lexicon=_FIXTURE_LEXICON)
    ir_result = build_constraint_ir(_snapshot(), {"obligations": []}, {"decision": "approve"}, realization_map=realization_map)

    variables = {item["id"]: item for item in ir_result.ir["variables"]}
    assert variables["VAR_CSV_Input_Layout"]["type"] == "enum"
    assert variables["VAR_CSV_rope"]["type"] == "int"
    assert variables["VAR_KEY_ISTND"]["free"] is False
    assert "VAR_KBR_TND" in variables
    assert "VAR_KBR_COMPLEX" in ir_result.ir["realization"]["abstract_branch_vars"]

    target = compile_obligation_target(
        {"id": "OB_COMPLEX", "kind": "kernel_branch", "target_refs": ["KBR_COMPLEX"], "target_value": True, "priority": "high"},
        ir_result.ir,
    )
    assert target.status == "skipped"
    assert target.code == "ABSTRACT_BRANCH_NOT_REALIZABLE"


def test_realize_writes_consumer_columns_and_case_coverage(tmp_path: Path) -> None:
    evidence, schema, realization_map = _consumer_contract()
    report = validate_contract_artifacts(evidence, schema, realization_map, snapshot_hash="snap", plan_hash="plan")
    assert report["status"] == "pass"
    out_root = tmp_path / "out"
    candidate = {
        "id": "CAND_TND",
        "model": {
            "VAR_CSV_Input_Layout": "TND",
            "VAR_CSV_B": 3,
            "VAR_CSV_rope": 1,
        },
        "covered_obligation_ids": ["OB_TND"],
    }
    obligations = [{"id": "OB_TND", "kind": "kernel_branch", "target_refs": ["KBR_TND"], "target_value": True}]

    report = realize_candidates_to_csv(
        out_root,
        [candidate],
        _snapshot(),
        consumer_schema=schema,
        realization_map=realization_map,
        obligations=obligations,
        level="L1",
        case_name="mapped",
    )

    csv_path = Path(report["csv_path"])
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["Input_Layout"] == "TND"
    assert row["Enable"] == "Enable"
    assert row["rope"] == "1"
    assert row["seqlens_list_q"] == "[3, 3, 3]"
    coverage = read_yaml(Path(report["coverage_path"]))
    covered = coverage["rows"][0]["covered"][0]
    assert covered["branch_ref"] == "KBR_TND"
    assert covered["condition"] == "IS_TND"
    assert covered["source"] == "kernel.cpp"
