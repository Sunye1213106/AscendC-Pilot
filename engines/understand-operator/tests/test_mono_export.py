from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.export_human_views import export_human_views
from uo.scripts.export_kb_graph import export_kb_graph
from uo.scripts.kb_graph_query import query_kb_graph
from uo.scripts.kb_query_export import (
    ARTIFACT_HASHES_REL,
    RUNTIME_SAMPLE_LIMIT,
    materialize_testcase_contract_files,
)


def _mini_graph() -> dict:
    return {
        "op_name": "DemoMono",
        "tilingkey": {
            "dimensions": [{"name": "IsTnd", "values": [0, 1]}],
            "template_blocks": [
                {"id": "KTPL_A", "name": "A", "flags": {"IsTnd": 0}, "condition": "true"},
                {"id": "KTPL_B", "name": "B", "flags": {"IsTnd": 1}, "condition": "true"},
            ],
            "args_sel_count": 2,
        },
        "nodes": [
            {
                "id": "KEY_IsTnd",
                "node_type": "TilingKey",
                "name": "IsTnd",
                "file_path": "op_host/tiling.h",
                "start_line": 10,
            },
            {
                "id": "KTPL_A",
                "node_type": "KernelTemplateArgument",
                "name": "A",
                "template_flags": {"IsTnd": 0},
                "condition": "true",
                "file_path": "op_kernel/tpl.h",
                "start_line": 20,
            },
            {
                "id": "KTPL_B",
                "node_type": "KernelTemplateArgument",
                "name": "B",
                "template_flags": {"IsTnd": 1},
                "condition": "true",
                "file_path": "op_kernel/tpl.h",
                "start_line": 21,
            },
            {
                "id": "SYM::SetIsTnd",
                "node_type": "Helper",
                "name": "SetIsTnd",
                "file_path": "op_host/tiling.cpp",
                "start_line": 40,
            },
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
        "edges": [
            {"source_id": "KTPL_A", "target_id": "KEY_IsTnd", "edge_type": "fixes_flag", "value": 0},
            {"source_id": "KTPL_B", "target_id": "KEY_IsTnd", "edge_type": "fixes_flag", "value": 1},
            {"source_id": "SYM::SetIsTnd", "target_id": "KEY_IsTnd", "edge_type": "writes"},
        ],
    }


def test_mono_materialize_externalizes_hashes_and_stub_exhaustive(tmp_path: Path) -> None:
    uo_root = tmp_path / ".ascendc-pilot" / "uo"
    (uo_root / "ir").mkdir(parents=True)
    graph = _mini_graph()
    write_yaml(uo_root / "ir" / "operator_graph.yaml", graph)

    files = materialize_testcase_contract_files(uo_root, graph)

    assert "contracts/testcase.yaml" not in files
    assert not (uo_root / "contracts" / "testcase.yaml").exists()
    assert not (uo_root / "tiling" / "key_cards").exists()

    artifact = files[ARTIFACT_HASHES_REL]
    assert "contracts/testcase.yaml" not in artifact["hashes"]
    assert "tiling/key_space.yaml" in artifact["hashes"]
    assert "export_profile" not in artifact
    assert (uo_root / ARTIFACT_HASHES_REL).is_file()

    exhaustive = files["tiling/exhaustive_key_space.yaml"]
    assert exhaustive.get("template_blocks") == []
    assert "lean_truncated" not in exhaustive
    assert exhaustive.get("ktpl_instance_count") == 2 or exhaustive["summary"].get("ktpl_instance_count") == 2

    test_contract = files["test/contract.yaml"]
    assert test_contract.get("canonical_ref") == "tiling/key_space.yaml"
    assert test_contract.get("role") == "kb_export_stub"

    runtime = files["kernel/runtime_conditions.yaml"]
    assert runtime["sample_limit"] == RUNTIME_SAMPLE_LIMIT
    for cond in runtime["conditions"]:
        assert len(cond["sample_branch_ids"]) <= RUNTIME_SAMPLE_LIMIT

    routes = files["query/routes.yaml"]
    assert "contracts/**" in routes["never_default"]
    assert "tiling/key_cards/**" in routes["never_default"]
    assert "summary/human_overview.md" in routes["default_hot"]
    assert "tiling/key_cards/index.yaml" not in routes["default_hot"]


def test_ktpl_graph_fixes_flag_and_query_patterns(tmp_path: Path) -> None:
    repo = tmp_path
    op = "DemoMono"
    uo_root = repo / ".ascendc-pilot" / "uo"
    (uo_root / "ir").mkdir(parents=True)
    graph = _mini_graph()
    write_yaml(uo_root / "ir" / "operator_graph.yaml", graph)
    write_yaml(
        uo_root / "ir" / "tilingkey_space.yaml",
        {
            "version": 1,
            "op_name": op,
            "template_aliases": [
                {"name": "A", "flags": {"IsTnd": 0}, "condition": "true", "line": 20},
                {"name": "B", "flags": {"IsTnd": 1}, "condition": "true", "line": 21},
            ],
            "nodes": graph["nodes"][:3],
            "edges": [
                {"source_id": "KTPL_A", "target_id": "KEY_IsTnd", "edge_type": "fixes_flag", "value": 0},
                {"source_id": "KTPL_B", "target_id": "KEY_IsTnd", "edge_type": "fixes_flag", "value": 1},
            ],
            "dimensions": [{"name": "IsTnd", "values": [0, 1]}],
        },
    )
    write_yaml(uo_root / "manifest.yaml", {"op_name": op})
    materialize_testcase_contract_files(uo_root, graph)
    export_kb_graph(repo, op, write=True)

    listed = query_kb_graph(uo_root, pattern="list_templates", limit=50)
    assert listed.get("index_status") == "fresh"
    assert listed.get("ktpl_count") == 2
    ids = {e["id"] for e in listed.get("resolved_entities") or []}
    assert ids == {"KTPL_A", "KTPL_B"}

    for_key = query_kb_graph(uo_root, pattern="templates_for_key", target="KEY_IsTnd", limit=50)
    tpl_ids = {t["id"] for t in for_key.get("templates") or []}
    assert tpl_ids == {"KTPL_A", "KTPL_B"}
    assert any(r.get("type") == "fixes_flag" for r in for_key.get("direct_relations") or [])

    neigh = query_kb_graph(uo_root, pattern="neighbors_of", target="KEY_IsTnd", depth=1, limit=50)
    neighbor_ids = {n["id"] for n in neigh.get("neighbors") or []}
    assert "SYM::SetIsTnd" in neighbor_ids or any(
        r.get("type") in {"writes", "determined_by", "derives"} for r in neigh.get("direct_relations") or []
    )
    key_ent = (neigh.get("resolved_entities") or [{}])[0]
    assert key_ent.get("file_path") or any(
        n.get("file_path") for n in neigh.get("neighbors") or []
    )


def test_export_human_views_from_mono_kb(tmp_path: Path) -> None:
    uo_root = tmp_path / ".ascendc-pilot" / "uo"
    (uo_root / "ir").mkdir(parents=True)
    graph = _mini_graph()
    write_yaml(uo_root / "ir" / "operator_graph.yaml", graph)
    write_yaml(
        uo_root / "ir" / "tilingkey_space.yaml",
        {
            "op_name": "DemoMono",
            "template_aliases": [
                {"name": "A", "flags": {"IsTnd": 0}},
                {"name": "B", "flags": {"IsTnd": 1}},
            ],
            "args_sel_count": 2,
        },
    )
    materialize_testcase_contract_files(uo_root, graph)
    write_yaml(uo_root / "manifest.yaml", {"op_name": "DemoMono"})

    result = export_human_views(uo_root, write=True)
    assert result["keys_table"]["key_count"] >= 1
    assert result["ktpl_count"] == 2
    assert "export_profile" not in result
    overview = (uo_root / "summary" / "human_overview.md").read_text(encoding="utf-8")
    assert "human overview" in overview
    assert "How to read this KB" in overview
    assert "list_templates" in overview or "KTPL" in overview
    assert "--profile" not in overview
    assert "key_cards" in overview  # mentioned as never dump
    assert (uo_root / "summary" / "keys_table.yaml").is_file()
