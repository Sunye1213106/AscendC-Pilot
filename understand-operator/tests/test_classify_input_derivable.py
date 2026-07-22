"""Compact input-derivable classify: one-hop parent + graph markers (no full chains)."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.classify_input_derivable import classify_and_write
from uo.scripts.export_kb_graph import _map_edge_type
from uo.scripts.kb_query_export import _apply_input_derivable_overlay, _infer_key_field_role


def _mini_uo(tmp_path: Path) -> Path:
    uo = tmp_path / ".understand-operator" / "demo_op"
    (uo / "ir").mkdir(parents=True)
    (uo / "tiling" / "key_cards").mkdir(parents=True)
    graph = {
        "op_name": "demo_op",
        "nodes": [
            {"id": "HOST_START_INPUTSHAPE", "node_type": "InputShape", "name": "InputShape"},
            {"id": "HOST_ATTR_SPARSEMODE", "node_type": "Attribute", "name": "sparseMode"},
            {"id": "HELPER_ENABLE", "node_type": "HostHelper", "name": "enableSwizzle"},
            {"id": "KEY_ISNZOUT", "node_type": "TilingKey", "name": "isNzOut"},
            {"id": "KVAR_BLOCKID", "node_type": "KernelVariable", "name": "blockId"},
        ],
        "edges": [
            {"source": "HOST_START_INPUTSHAPE", "target": "HELPER_ENABLE", "type": "derives"},
            {"source": "HOST_ATTR_SPARSEMODE", "target": "HELPER_ENABLE", "type": "derives"},
            {"source": "HELPER_ENABLE", "target": "KEY_ISNZOUT", "type": "writes"},
        ],
        "tilingkey": {"dimensions": [{"name": "isNzOut", "values": [0, 1]}]},
    }
    write_yaml(uo / "ir" / "operator_graph.yaml", graph)
    write_yaml(
        uo / "tiling" / "key_cards" / "KEY_ISNZOUT.yaml",
        {
            "id": "KEY_ISNZOUT",
            "key": "isNzOut",
            "set_by": {
                "status": "found",
                "expr_raw": "isNzOut = enableSwizzle;",
                "file_path": "tiling.cpp",
                "start_line": 10,
            },
        },
    )
    return uo


def test_classify_true_emits_parent_and_markers_not_full_chain(tmp_path: Path) -> None:
    uo = _mini_uo(tmp_path)
    payload = classify_and_write(uo)
    entry = payload["keys"]["KEY_ISNZOUT"]
    assert entry["input_derivable"] is True
    assert entry["needs_binding"] is True
    assert entry["host_parent"] == "HELPER_ENABLE"
    assert "HOST_START_INPUTSHAPE" in entry["derivation_roots"] or "HOST_ATTR_SPARSEMODE" in entry[
        "derivation_roots"
    ]
    assert "host_derivation_chain" not in entry
    assert "function_chain" not in entry
    markers = payload["graph_markers"]
    assert any(m["type"] == "determined_by" and m["target"] == "HELPER_ENABLE" for m in markers)
    assert any(m["type"] == "reaches_input" for m in markers)
    assert (uo / "ir" / "input_derivable.yaml").is_file()


def test_classify_kernel_local_false(tmp_path: Path) -> None:
    uo = _mini_uo(tmp_path)
    # Add a KEY that only looks kernel-local via name walk
    graph = {
        "op_name": "demo_op",
        "nodes": [
            {"id": "KEY_BLOCKID", "node_type": "TilingKey", "name": "blockId"},
        ],
        "edges": [],
        "tilingkey": {"dimensions": [{"name": "blockId", "values": [0, 1]}]},
    }
    write_yaml(uo / "ir" / "operator_graph.yaml", graph)
    write_yaml(
        uo / "tiling" / "key_cards" / "KEY_BLOCKID.yaml",
        {
            "id": "KEY_BLOCKID",
            "set_by": {"status": "found", "expr_raw": "blockId = GetBlockIdx();", "file_path": "k.cpp", "start_line": 1},
        },
    )
    payload = classify_and_write(uo)
    # May be unsolved (GetBlockIdx dangling) or false if kernel-local name hits; never silent true without roots
    entry = payload["keys"]["KEY_BLOCKID"]
    assert entry["input_derivable"] is not True


def test_high_confidence_patch_closes_gap(tmp_path: Path) -> None:
    uo = _mini_uo(tmp_path)
    # Isolate: only KEY_ISDROP card (drop leftover KEY_ISNZOUT from fixture).
    for stale in (uo / "tiling" / "key_cards").glob("KEY_*.yaml"):
        stale.unlink()
    write_yaml(
        uo / "ir" / "operator_graph.yaml",
        {
            "op_name": "demo_op",
            "nodes": [{"id": "KEY_ISDROP", "node_type": "TilingKey", "name": "isDrop"}],
            "edges": [],
            "tilingkey": {"dimensions": [{"name": "isDrop", "values": [0, 1]}]},
        },
    )
    write_yaml(
        uo / "tiling" / "key_cards" / "KEY_ISDROP.yaml",
        {"id": "KEY_ISDROP", "set_by": {"status": "missing"}},
    )
    write_yaml(
        uo / "ir" / "input_derivable_patch.yaml",
        {
            "keys": [
                {
                    "key_id": "KEY_ISDROP",
                    "confidence": "high",
                    "input_derivable": True,
                    "host_parent": "SYM::keepProb",
                    "derivation_roots": ["HOST_ATTR_keepProb"],
                }
            ]
        },
    )
    payload = classify_and_write(uo)
    assert payload["keys"]["KEY_ISDROP"]["input_derivable"] is True
    assert payload["keys"]["KEY_ISDROP"]["host_parent"] == "SYM::keepProb"
    assert payload["stats"]["unsolved"] == 0


def test_map_edge_preserves_writes_and_markers() -> None:
    assert _map_edge_type("writes") == "writes"
    assert _map_edge_type("derives") == "derives"
    assert _map_edge_type("determined_by") == "determined_by"
    assert _map_edge_type("reaches_input") == "reaches_input"


def test_infer_role_does_not_own_needs_binding() -> None:
    meta = _infer_key_field_role("IsDrop")
    assert meta.get("role") == "optional_presence"
    assert "needs_binding" not in meta


def test_overlay_sets_compact_fields(tmp_path: Path) -> None:
    uo = _mini_uo(tmp_path)
    classify_and_write(uo)
    fields = [{"id": "KEY_ISNZOUT", "name": "isNzOut", "csv_determinants": [], "needs_binding": False}]
    _apply_input_derivable_overlay(uo, fields)
    assert fields[0]["input_derivable"] is True
    assert fields[0]["needs_binding"] is True
    assert fields[0]["host_parent"] == "HELPER_ENABLE"
    assert "host_derivation_chain" not in fields[0]
