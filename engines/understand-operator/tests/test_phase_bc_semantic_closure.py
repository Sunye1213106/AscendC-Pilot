"""Phase B/C: input_derivable closure, severity grades, layer incremental, sqlite freshness."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.export_kb_graph import HASH_PATHS, SCHEMA_VERSION, _source_hashes
from uo.scripts.family_path_obligation import check_family_path_obligation
from uo.scripts.semantic_resolution_ledger import (
    compute_layer_input_fingerprints,
    persist_layer_input_fingerprints,
    select_layers_for_rebuild,
)
from uo.scripts.semantic_severity import (
    RESOLUTION_TG_RESOLVABLE,
    RESOLUTION_UO_BLOCKING,
    grade_task,
    input_derivable_closure,
)
from uo.scripts.semantic_task_triage import classify_task


def _prep_uo(tmp_path: Path) -> Path:
    uo = tmp_path / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    (uo / "checks").mkdir(parents=True)
    write_yaml(uo / "manifest.yaml", {"op_name": "synth", "current_run_id": "RUN_BC"})
    return uo


def test_grade_key_gap_is_tg_resolvable() -> None:
    task = {
        "triage_category": "key_derivation_gap",
        "route": "uo-key-resolve",
        "blocks_extract_advance": False,
        "blocking": True,
        "severity": "blocking",
    }
    assert grade_task(task) == RESOLUTION_TG_RESOLVABLE
    row = classify_task(
        {
            "object_type": "tilingkey_binding",
            "type": "tilingkey_schema_bind",
            "candidates": [{"symbol_ref": "k", "file_path": "a.cpp", "start_line": 1, "snippet": "x"}],
        }
    )
    assert row["category"] == "key_derivation_gap"
    assert row["blocks_extract_advance"] is False


def test_grade_macro_is_uo_blocking() -> None:
    task = {
        "triage_category": "macro_contract_resolvable",
        "route": "macro_semantic_materializer",
        "blocking": True,
        "severity": "blocking",
        "blocks_extract_advance": True,
    }
    assert grade_task(task) == RESOLUTION_UO_BLOCKING


def test_input_derivable_closure_vacuous_and_open(tmp_path: Path) -> None:
    uo = _prep_uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {"version": 1, "keys": {}, "stats": {"unsolved": 0}, "status": "closed"},
    )
    write_yaml(uo / "ir" / "input_derivable_gaps.yaml", {"version": 1, "gaps": [], "status": "closed"})
    assert input_derivable_closure(uo)["ok"] is True

    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {
            "version": 1,
            "keys": {"KEY_A": {"input_derivable": "unsolved"}},
            "stats": {"unsolved": 1},
        },
    )
    write_yaml(
        uo / "ir" / "input_derivable_gaps.yaml",
        {"version": 1, "gaps": [{"id": "IDGAP_A", "target": "KEY_A", "status": "unresolved"}]},
    )
    assert input_derivable_closure(uo)["ok"] is False


def test_family_path_obligation_detects_unknown_ref(tmp_path: Path) -> None:
    uo = _prep_uo(tmp_path)
    write_yaml(
        uo / "tiling" / "families.yaml",
        {"families": [{"id": "FAM_MAIN"}]},
    )
    write_yaml(
        uo / "kernel" / "paths.yaml",
        {"kernel_paths": [{"id": "KPATH_MAIN", "family_refs": ["FAM_MAIN"]}]},
    )
    write_yaml(
        uo / "coverage" / "obligations.yaml",
        {
            "obligations": [
                {
                    "id": "OB_BAD",
                    "kind": "kernel_path",
                    "family_refs": ["FAM_GHOST"],
                    "target_refs": ["KPATH_MAIN"],
                }
            ]
        },
    )
    result = check_family_path_obligation(uo, write=True)
    assert result["ok"] is False
    codes = {i.get("code") for i in result.get("issues") or []}
    assert "FAM_REF_UNKNOWN" in codes


def test_family_path_obligation_pass(tmp_path: Path) -> None:
    uo = _prep_uo(tmp_path)
    write_yaml(uo / "tiling" / "families.yaml", {"families": [{"id": "FAM_MAIN"}]})
    write_yaml(
        uo / "kernel" / "paths.yaml",
        {"kernel_paths": [{"id": "KPATH_MAIN", "family_refs": ["FAM_MAIN"]}]},
    )
    write_yaml(
        uo / "coverage" / "obligations.yaml",
        {
            "obligations": [
                {
                    "id": "OB_OK",
                    "family_refs": ["FAM_MAIN"],
                    "kernel_path_refs": ["KPATH_MAIN"],
                }
            ]
        },
    )
    result = check_family_path_obligation(uo, write=True)
    assert result["ok"] is True
    assert (uo / "checks" / "family_path_obligation.yaml").is_file()


def test_select_layers_selective_on_dirty_host(tmp_path: Path) -> None:
    uo = _prep_uo(tmp_path)
    write_yaml(uo / "ir" / "extract_plan.yaml", {"version": 1, "writers": []})
    write_yaml(uo / "ir" / "operator_capabilities.yaml", {"has_tilingkey": True})
    write_yaml(uo / "ir" / "semantic_resolution_ledger.yaml", {"version": 1, "semantic_patches": []})
    fps = compute_layer_input_fingerprints(uo, architecture="arch35", source_snapshot="snap")
    # Persist all but host as "previous"; mutate host input by changing extract_plan.
    persist_layer_input_fingerprints(uo, fps)
    write_yaml(uo / "ir" / "extract_plan.yaml", {"version": 1, "writers": [{"name": "Foo"}]})
    plan = select_layers_for_rebuild(
        uo, architecture="arch35", source_snapshot="snap", current_run_id="RUN_BC"
    )
    assert plan["mode"] in {"selective", "full"}
    assert "host" in plan["layers"] or plan["mode"] == "full"
    assert "bridge" in plan["layers"]


def test_sqlite_stale_detected(tmp_path: Path) -> None:
    from uo.scripts.kb_graph_query import index_status

    uo = _prep_uo(tmp_path)
    for rel in HASH_PATHS:
        p = uo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        write_yaml(p, {"version": 1}) if rel.endswith(".yaml") else p.write_text("", encoding="utf-8")
    hashes = _source_hashes(uo)
    db = uo / "indexes" / "kb_graph.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("source_hashes", json.dumps(hashes, sort_keys=True)),
        )
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
    assert index_status(uo)["index_status"] == "fresh"
    # Dirty a hashed YAML → stale
    write_yaml(uo / "ir" / "operator_graph.yaml", {"version": 1, "nodes": [{"id": "n1"}]})
    assert index_status(uo)["index_status"] == "stale"
