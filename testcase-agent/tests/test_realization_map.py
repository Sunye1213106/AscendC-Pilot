from __future__ import annotations

import csv
from pathlib import Path

from testcase_agent.constraint_ir import build_constraint_ir, compile_obligation_target
from testcase_agent.io import read_yaml
from testcase_agent.realization_map import build_realization_map
from testcase_agent.realization_schema import extract_consumer_schema
from testcase_agent.realize import realize_candidates_to_csv


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
    realization_map = build_realization_map(_snapshot(), schema)
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
    schema = extract_consumer_schema(_consumer_root(tmp_path))
    realization_map = build_realization_map(_snapshot(), schema)
    out_root = tmp_path / "out"
    candidate = {
        "id": "CAND_TND",
        "model": {
            "VAR_CSV_Input_Layout": "TND",
            "VAR_CSV_B": 3,
            "VAR_CSV_S1": 17,
            "VAR_CSV_S2": 19,
            "VAR_CSV_D": 64,
            "VAR_CSV_D_V": 128,
            "VAR_CSV_rope": 1,
            "VAR_CSV_Atten_mask_shape": "BNSS",
        },
        "covered_obligation_ids": ["OB_TND"],
    }
    obligations = [{"id": "OB_TND", "kind": "kernel_branch", "target_refs": ["KBR_TND"], "target_value": True}]

    report = realize_candidates_to_csv(
        out_root,
        [candidate],
        _snapshot(),
        realization_map=realization_map,
        obligations=obligations,
        level="L1",
        case_name="mapped",
    )

    csv_path = Path(report["csv_path"])
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["Input_Layout"] == "TND"
    assert row["D_V"] == "128"
    assert row["Actual_Result"] == ""
    assert row["rope"] == "1"
    assert row["seqlens_list_q"] == "[6, 6, 5]"
    assert row["cu_seqlens_q"] == "[0, 6, 12, 17]"
    coverage = read_yaml(Path(report["coverage_path"]))
    covered = coverage["rows"][0]["covered"][0]
    assert covered["branch_ref"] == "KBR_TND"
    assert covered["condition"] == "IS_TND"
    assert covered["source"] == "kernel.cpp"
