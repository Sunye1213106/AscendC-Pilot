"""TG owns contract/testcase.yaml; UO contracts are ignored."""

from __future__ import annotations

from pathlib import Path

from testcase_agent.build_tg_contract import build_tg_contract, load_tg_contract, resolve_plan_contract
from testcase_agent.io import write_yaml
from testcase_agent.kb_semantics import assemble_key_determinants


def test_assemble_key_determinants_from_kb_layers() -> None:
    files = {
        "tiling/key_space.yaml": {
            "fields": [
                {
                    "id": "KEY_IsTnd",
                    "role": "layout_flag",
                    "csv_determinants": ["input_layout"],
                    "input_derivable": True,
                    "needs_binding": True,
                }
            ]
        },
        "ir/input_derivable.yaml": {
            "keys": {
                "KEY_Local": {
                    "input_derivable": False,
                    "not_input_derivable": True,
                    "host_parent": None,
                }
            }
        },
    }
    dets = assemble_key_determinants(files)
    assert dets["KEY_IsTnd"]["input_derivable"] is True
    assert dets["KEY_Local"]["not_input_derivable"] is True


def test_build_tg_contract_writes_under_testcase_generator(tmp_path: Path) -> None:
    out = tmp_path / ".testcase-generator" / "DemoOp"
    (out / "realization").mkdir(parents=True)
    snapshot = {
        "op_name": "DemoOp",
        "snapshot_hash": "abc",
        "files": {
            "tiling/key_space.yaml": {"fields": [{"id": "KEY_A", "values": [0, 1], "needs_binding": True}]},
            "ir/input_derivable.yaml": {"keys": {"KEY_A": {"input_derivable": True}}},
            "kernel/branches.yaml": {"branches": [{"id": "KBR_1"}]},
            "tiling/coverage_model.yaml": {"family_obligations": []},
            "flow/golden_model.yaml": {},
        },
    }
    schema = {
        "fields": [
            {
                "id": "VAR_CSV_Enable",
                "name": "Enable",
                "domain": ["Enable"],
                "type": "string",
            }
        ],
        "columns": ["Enable"],
    }
    contract = build_tg_contract(
        out,
        op_name="DemoOp",
        consumer_schema=schema,
        snapshot=snapshot,
    )
    path = out / "contract" / "testcase.yaml"
    assert path.is_file()
    assert contract["version"] == 2
    assert contract["owner"] == "testcase-agent"
    assert contract["variables"][0]["domain_authority"] == "consumer_csv"
    assert "KEY_A" in contract["key_determinants"]
    loaded = load_tg_contract(out)
    assert loaded["op_name"] == "DemoOp"


def test_resolve_plan_contract_prefers_tg_over_legacy(tmp_path: Path) -> None:
    out = tmp_path / ".testcase-generator" / "DemoOp"
    write_yaml(
        out / "contract" / "testcase.yaml",
        {"version": 2, "op_name": "DemoOp", "variables": [{"id": "VAR_CSV_X"}], "owner": "testcase-agent"},
    )
    snapshot = {
        "files": {
            "contracts/testcase.yaml": {
                "version": 2,
                "variables": [{"id": "VAR_LEGACY"}],
            }
        }
    }
    contract, source = resolve_plan_contract(snapshot, out_root=out)
    assert source == "tg_contract"
    assert contract["variables"][0]["id"] == "VAR_CSV_X"
