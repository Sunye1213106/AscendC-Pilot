from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.export_human_views import export_human_views
from uo.scripts.kb_query_export import (
    ARTIFACT_HASHES_REL,
    RUNTIME_SAMPLE_LIMIT_LEAN,
    materialize_testcase_contract_files,
    resolve_export_profile,
)


def _mini_graph() -> dict:
    return {
        "op_name": "DemoLean",
        "tilingkey": {
            "dimensions": [{"name": "IsTnd", "values": [0, 1]}],
            "template_blocks": [
                {"id": "KTPL_A", "name": "A", "flags": {"IsTnd": 0}, "condition": "true"},
                {"id": "KTPL_B", "name": "B", "flags": {"IsTnd": 1}, "condition": "true"},
            ],
            "args_sel_count": 2,
        },
        "nodes": [
            {"id": "KEY_IsTnd", "node_type": "TilingKey", "name": "IsTnd"},
        ],
        "kernel_branches": [
            {
                "id": f"KBR_{i}",
                "condition": "sparseMode == 0",
                "binding_time": "runtime",
                "determinant_ref": "sparseMode",
            }
            for i in range(10)
        ],
        "golden": {},
        "bridge_diagnostics": [],
        "edges": [],
    }


def test_resolve_export_profile_defaults_lean(monkeypatch) -> None:
    monkeypatch.delenv("UO_KB_EXPORT_PROFILE", raising=False)
    assert resolve_export_profile(None) == "lean"
    monkeypatch.setenv("UO_KB_EXPORT_PROFILE", "full")
    assert resolve_export_profile(None) == "full"
    assert resolve_export_profile("lean") == "lean"


def test_lean_materialize_externalizes_hashes_and_truncates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("UO_KB_EXPORT_PROFILE", raising=False)
    uo_root = tmp_path / ".understand-operator" / "DemoLean"
    (uo_root / "ir").mkdir(parents=True)
    graph = _mini_graph()
    write_yaml(uo_root / "ir" / "operator_graph.yaml", graph)

    files = materialize_testcase_contract_files(uo_root, graph, profile="lean")

    contract = files["contracts/testcase.yaml"]
    assert contract["source"]["canonical_hashes"] == {}
    assert contract["source"]["hashes_ref"] == ARTIFACT_HASHES_REL
    assert contract["source"]["export_profile"] == "lean"

    artifact = files[ARTIFACT_HASHES_REL]
    assert "contracts/testcase.yaml" in artifact["hashes"]
    assert (uo_root / ARTIFACT_HASHES_REL).is_file()

    exhaustive = files["tiling/exhaustive_key_space.yaml"]
    assert exhaustive.get("lean_truncated") is True
    assert exhaustive.get("template_blocks") == []
    assert exhaustive["summary"]["template_block_count"] == 2

    test_contract = files["test/contract.yaml"]
    assert test_contract.get("canonical_ref") == "contracts/testcase.yaml"
    assert test_contract.get("typed_constraints") == []

    runtime = files["kernel/runtime_conditions.yaml"]
    assert runtime["sample_limit"] == RUNTIME_SAMPLE_LIMIT_LEAN
    for cond in runtime["conditions"]:
        assert len(cond["sample_branch_ids"]) <= RUNTIME_SAMPLE_LIMIT_LEAN

    routes = files["query/routes.yaml"]
    assert "contracts/testcase.yaml" in routes["never_default"]
    assert "summary/human_overview.md" in routes["default_hot"]


def test_full_materialize_keeps_hashes_and_blocks(tmp_path: Path) -> None:
    uo_root = tmp_path / ".understand-operator" / "DemoLean"
    (uo_root / "ir").mkdir(parents=True)
    graph = _mini_graph()
    write_yaml(uo_root / "ir" / "operator_graph.yaml", graph)

    files = materialize_testcase_contract_files(uo_root, graph, profile="full")
    contract = files["contracts/testcase.yaml"]
    assert contract["source"]["canonical_hashes"]
    assert files["tiling/exhaustive_key_space.yaml"]["template_blocks"]
    assert files["test/contract.yaml"].get("canonical_ref") is None


def test_export_human_views_from_lean_kb(tmp_path: Path) -> None:
    uo_root = tmp_path / ".understand-operator" / "DemoLean"
    (uo_root / "ir").mkdir(parents=True)
    graph = _mini_graph()
    write_yaml(uo_root / "ir" / "operator_graph.yaml", graph)
    materialize_testcase_contract_files(uo_root, graph, profile="lean")
    write_yaml(uo_root / "manifest.yaml", {"op_name": "DemoLean"})

    result = export_human_views(uo_root, write=True)
    assert result["keys_table"]["key_count"] >= 1
    overview = (uo_root / "summary" / "human_overview.md").read_text(encoding="utf-8")
    assert "human overview" in overview
    assert "How to read this KB" in overview
    assert (uo_root / "summary" / "keys_table.yaml").is_file()
