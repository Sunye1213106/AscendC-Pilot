"""Tests for shape derivation closure and bind consumption."""

from __future__ import annotations

from pathlib import Path

from testcase_agent.atom_bind import BindContext, bind_atom
from testcase_agent.io import read_yaml, write_yaml
from testcase_agent.shape_derivation import (
    build_and_write_shape_derivation,
    build_shape_derivation_graph,
    check_shape_chain_consistent,
    check_shape_graph_built,
    check_unbound_reducible,
)
from testcase_agent.uo_resolve_merge import merge_uo_resolve


def test_closure_propagates_csv_key_kvar() -> None:
    lexicon = {
        "key_derivations": [
            {
                "id": "VAR_KEY_ISDROP",
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_keep_prob", "value": 1.0},
                    "then": 0,
                    "else": 1,
                },
            }
        ]
    }
    rmap = {
        "csv_variables": [
            {"id": "VAR_CSV_keep_prob", "column": "keep_prob", "domain": [1.0, 0.9]},
            {"id": "VAR_CSV_B", "column": "B", "domain": {"kind": "range", "min": 1, "max": 8}},
        ]
    }
    # Fake resolve file content via tmp files in build_and_write — use in-memory path list empty
    # and injection via derivation_chain through a temp resolve.
    graph = build_shape_derivation_graph(
        lexicon=lexicon,
        rmap=rmap,
        resolve_files=[],
        snapshot={
            "files": {
                "kernel/variables.yaml": {
                    "runtime_variables": [
                        {
                            "id": "VAR_KVAR_DROPFLAG",
                            "name": "dropFlag",
                            "set_by": {"key": "KEY_ISDROP"},
                        },
                        {
                            "id": "VAR_KVAR_LOOP_LOCAL_taskId",
                            "name": "taskId",
                            "classification": "loop_local",
                            "set_by": {"csv": "B"},
                        },
                    ]
                }
            }
        },
    )
    closure = set(graph["closure"])
    assert "VAR_CSV_keep_prob" in closure
    assert "VAR_KEY_ISDROP" in closure
    assert "VAR_KVAR_DROPFLAG" in closure
    assert "VAR_KVAR_LOOP_LOCAL_taskId" not in closure
    assert any("LOOP" in x or "taskId" in x for x in (graph.get("out_of_scope") or []) ) or "VAR_KVAR_LOOP_LOCAL_taskId" in (
        graph.get("out_of_scope") or []
    )


def test_merge_writes_shape_graph(tmp_path: Path) -> None:
    out = tmp_path / "op"
    realization = out / "realization"
    resolve = realization / "uo_query_resolve"
    resolve.mkdir(parents=True)
    write_yaml(
        realization / "realization_map.yaml",
        {
            "csv_variables": [
                {"id": "VAR_CSV_keep_prob", "column": "keep_prob", "domain": [1.0, 0.9, 0.8]},
                {"id": "VAR_CSV_B", "column": "B", "domain": {"kind": "range", "min": 1, "max": 64}},
            ]
        },
    )
    write_yaml(realization / "binding_lexicon.yaml", {"version": 1, "key_derivations": []})
    write_yaml(
        resolve / "KEY_ISDROP.yaml",
        {
            "key_id": "KEY_ISDROP",
            "status": "resolved",
            "confidence": "high",
            "shape_expr": "keepProb < 1.0",
            "shape_determined": ["VAR_CSV_keep_prob"],
            "derivation_chain": [
                {"id": "VAR_KEY_ISDROP", "deps": ["VAR_CSV_keep_prob"], "via": "set_by"},
                {"id": "VAR_KVAR_ISDROPMODE", "deps": ["VAR_KEY_ISDROP"], "via": "neighbors_of"},
            ],
            "key_derivation": {
                "id": "VAR_KEY_ISDROP",
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_keep_prob", "value": 1.0},
                    "then": 0,
                    "else": 1,
                },
            },
        },
    )
    report = merge_uo_resolve(out)
    assert report["status"] == "pass"
    graph = read_yaml(out / "bind" / "shape_derivation_graph.yaml")
    assert graph["status"] == "built"
    assert "VAR_KEY_ISDROP" in graph["closure"]
    assert "VAR_KVAR_ISDROPMODE" in graph["closure"]
    det = read_yaml(out / "bind" / "shape_determined.yaml")
    ids = {item["id"] if isinstance(item, dict) else item for item in det["variables"]}
    assert "VAR_KEY_ISDROP" in ids
    assert "VAR_KVAR_ISDROPMODE" in ids
    assert check_shape_graph_built(out)["status"] == "pass"
    assert check_shape_chain_consistent(out)["status"] == "pass"


def test_bind_atom_uses_shape_closure() -> None:
    ctx = BindContext(
        None,
        lexicon={
            "key_derivations": [
                {
                    "id": "VAR_KEY_ISDROP",
                    "expr": {"op": "eq", "var": "VAR_CSV_keep_prob", "value": 1.0},
                }
            ]
        },
        shape_closure={"VAR_CSV_keep_prob", "VAR_KEY_ISDROP"},
    )
    bound = bind_atom({"kind": "ident", "name": "ISDROP", "raw": "ISDROP"}, ctx)
    assert bound["status"] == "bound"
    assert bound["target"]["var"] == "VAR_KEY_ISDROP"
    assert bound["via"] == "shape_closure"

    platform = bind_atom({"kind": "ident", "name": "ASC_DEVKIT_CORETYPE", "raw": "ASC_DEVKIT_CORETYPE"}, ctx)
    assert platform["status"] == "unbound"
    assert platform["reason"] == "PLATFORM_MACRO"


def test_unbound_reducible_detects_closure_leak(tmp_path: Path) -> None:
    out = tmp_path / "op"
    (out / "bind").mkdir(parents=True)
    (out / "realization").mkdir(parents=True)
    write_yaml(
        out / "bind" / "shape_derivation_graph.yaml",
        {"version": 1, "status": "built", "closure": ["VAR_KEY_ISDROP"], "roots": [], "edges": [], "nodes": []},
    )
    write_yaml(
        out / "realization" / "realization_map.yaml",
        {
            "abstract_branches": [
                {
                    "branch_ref": "KBR_X",
                    "unbound_atoms": [
                        {"name": "ISDROP", "raw": "ISDROP", "reason": "UNBOUND_ATOM"},
                    ],
                }
            ]
        },
    )
    result = check_unbound_reducible(out)
    assert result["status"] == "fail"
    assert result["hits"]


def test_build_and_write_with_derivation_chain(tmp_path: Path) -> None:
    out = tmp_path / "op"
    realization = out / "realization"
    resolve = realization / "uo_query_resolve"
    resolve.mkdir(parents=True)
    write_yaml(
        realization / "realization_map.yaml",
        {"csv_variables": [{"id": "VAR_CSV_B", "column": "B", "domain": {"kind": "range", "min": 1, "max": 4}}]},
    )
    write_yaml(realization / "binding_lexicon.yaml", {"key_derivations": []})
    write_yaml(
        resolve / "KEY_FOO.yaml",
        {
            "key_id": "KEY_FOO",
            "status": "resolved",
            "shape_determined": ["VAR_CSV_B"],
            "derivation_chain": [
                {"id": "VAR_KEY_FOO", "deps": ["VAR_CSV_B"], "via": "set_by"},
                {"id": "LOOP_LOCAL_taskId", "deps": ["VAR_CSV_B"], "via": "LOOP_LOCAL"},
            ],
            "key_derivation": {
                "id": "VAR_KEY_FOO",
                "expr": {"op": "eq", "var": "VAR_CSV_B", "value": 1},
            },
        },
    )
    graph = build_and_write_shape_derivation(out)
    assert "VAR_KEY_FOO" in graph["closure"]
    assert "LOOP_LOCAL_taskId" not in graph["closure"]
