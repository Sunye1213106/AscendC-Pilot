"""Domain generalization + lexicon + csv_domain_cover (no sample csv/xls scrape)."""

from __future__ import annotations

from pathlib import Path

from testcase_agent.consumer_evidence import build_consumer_evidence, load_domain_hints, propose_domain_hints_stub
from testcase_agent.csv_domain_cover import (
    add_csv_domain_cover_obligations,
    cover_points_for_domain,
    extract_uo_domain_entries_by_column,
)
from testcase_agent.domain_policy import shape_range_domain
from testcase_agent.lexicon_propose import load_lexicon_seed, propose_key_derivations_from_evidence
from testcase_agent.realization_map import build_realization_map
from testcase_agent.realization_schema import build_consumer_schema_from_evidence
from testcase_agent.binding_lexicon import lexicon_from_key_space


def test_shape_domain_is_range_without_samples(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    root.mkdir()
    (root / "run.py").write_text(
        'get_column_index(t, "B")\nget_column_index(t, "S1")\nget_column_index(t, "Input_Layout")\n',
        encoding="utf-8",
    )
    evidence = build_consumer_evidence(root, snapshot={}, obligations_doc={"obligations": []}, out_root=tmp_path)
    assert "Input_Layout" in evidence["field_accesses"] or any(
        "Input_Layout" in (item.get("columns") or []) for item in evidence["ordered_header_candidates"]
    )
    key_space = {
        "dimensions": [
            {"name": "S1TemplateNum", "values": [0, 64, 128, 512]},
            {"name": "DTemplateNum", "values": [0, 64, 128, 192, 256, 768]},
            {"name": "IsTnd", "values": [0, 1]},
        ]
    }
    schema = build_consumer_schema_from_evidence(evidence, root, key_space=key_space)
    by_name = {f["name"]: f for f in schema["fields"]}
    b_dom = by_name["B"]["domain"]
    assert isinstance(b_dom, dict) and b_dom.get("kind") == "range"
    assert b_dom["max"] >= 64
    s1_dom = by_name["S1"]["domain"]
    assert s1_dom["max"] >= 512


def test_uo_domain_entries_drive_sparse_cover() -> None:
    files = {
        "kernel/variables.yaml": {
            "runtime_variables": [
                {
                    "id": "KVAR_SPARSEMODE",
                    "name": "sparseMode",
                    "domain_entries": [
                        {"name": "NO_MASK", "value": 0},
                        {"name": "ALL_MASK", "value": 1},
                        {"name": "LEFT_UP_CAUSAL", "value": 2},
                    ],
                }
            ]
        }
    }
    mapped = extract_uo_domain_entries_by_column(files, ["sparse_mode", "B"])
    assert mapped["sparse_mode"] == [0, 1, 2]
    points = cover_points_for_domain({"values": [0, 1, 2]}, sample_values=[])
    assert points == [0, 1, 2]


def test_domain_hints_stub_and_load(tmp_path: Path) -> None:
    stub = propose_domain_hints_stub(["sparse_mode", "B"], uo_entries={"sparse_mode": [0, 1, 2]})
    assert stub["columns"]["sparse_mode"]["values"] == [0, 1, 2]
    assert stub["columns"]["B"]["status"] == "pending"
    from testcase_agent.io import write_yaml

    hints = tmp_path / "realization"
    hints.mkdir()
    write_yaml(
        hints / "domain_hints.yaml",
        {"source": "human", "columns": {"B": {"min": 1, "max": 16}, "sparse_mode": {"values": [0, 1, 2, 3]}}},
    )
    loaded = load_domain_hints(tmp_path)
    assert loaded["columns"]["sparse_mode"]["values"] == [0, 1, 2, 3]


def test_evidence_proposes_istnd_and_sparse_map() -> None:
    lex = lexicon_from_key_space({"dimensions": [{"name": "IsTnd", "values": [0, 1]}]})
    proposed, gaps = propose_key_derivations_from_evidence(
        lexicon=lex,
        csv_columns=["Input_Layout", "B", "rope", "sparse_mode"],
        sample_values={"Input_Layout": ["BNSD", "TND"]},
        snapshot_files={
            "contracts/testcase.yaml": {
                "key_determinants": {
                    "KEY_ISTND": {
                        "role": "layout_flag",
                        "csv_determinants": [{"column": "Input_Layout", "op": "eq", "value": "TND"}],
                    }
                }
            },
            "kernel/variables.yaml": {
                "runtime_variables": [
                    {
                        "id": "KVAR_SPARSEMODE",
                        "name": "sparseMode",
                        "domain_entries": [
                            {"name": "NO_MASK", "value": 0},
                            {"name": "BAND", "value": 4},
                        ],
                    }
                ]
            },
        },
    )
    ids = {item["id"] for item in proposed["key_derivations"]}
    assert any("ISTND" in i for i in ids)
    assert any("SPARSE" in i.upper() for i in ids)
    istnd = next(item for item in proposed["key_derivations"] if "ISTND" in item["id"])
    assert istnd.get("locked") is not True
    assert not any(g.get("code") == "MISSING_CSV_REF" and "ISTND" in str(g.get("variable_id")) for g in gaps)


def test_lexicon_seed_loads_fixture() -> None:
    path = Path(__file__).parent / "fixtures" / "fag_binding_lexicon.yaml"
    doc = load_lexicon_seed(path)
    assert any(item["id"] == "VAR_KEY_ISTND" for item in doc["key_derivations"])


def test_csv_domain_cover_emits_per_value() -> None:
    rmap = {
        "consumer": {"columns": ["sparse_mode", "B"]},
        "csv_variables": [
            {"id": "VAR_CSV_sparse_mode", "column": "sparse_mode", "type": "int", "domain": {"values": [0, 1, 2]}, "free": True},
            {"id": "VAR_CSV_B", "column": "B", "type": "int", "domain": {"kind": "range", "min": 1, "max": 64}, "free": True},
        ],
    }
    out: list = []
    add_csv_domain_cover_obligations(out, rmap, files={})
    sparse = [o for o in out if o.get("field") == "sparse_mode"]
    assert {o["target_value"] for o in sparse} >= {0, 1, 2}
    b_covers = [o for o in out if o.get("field") == "B"]
    assert len(b_covers) >= 2  # grid points on range
    assert all(o["priority"] == "hard" for o in out)


def test_shape_range_uses_safe_cap() -> None:
    dom = shape_range_domain("S1", sample_ints=[], key_space=None)
    assert dom["kind"] == "range"
    assert dom["min"] == 1
    assert dom["max"] >= 4096


def test_reachability_samples_large_int_range() -> None:
    from testcase_agent.reachability import annotate_reachable_values, csv_domains_from_map

    rmap = {
        "csv_variables": [
            {
                "id": "VAR_CSV_S1",
                "column": "S1",
                "type": "int",
                "domain": {"kind": "range", "min": 1, "max": 4096},
            },
            {
                "id": "VAR_CSV_Input_Layout",
                "column": "Input_Layout",
                "type": "enum",
                "domain": ["BNSD", "TND"],
            },
        ],
        "derived_variables": [
            {
                "id": "VAR_KEY_ISTND",
                "type": "int",
                "domain": [0, 1],
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_Input_Layout", "value": "TND"},
                    "then": 1,
                    "else": 0,
                },
            }
        ],
    }
    domains = csv_domains_from_map(rmap)
    assert 1 in domains["VAR_CSV_S1"]
    assert 4096 in domains["VAR_CSV_S1"]
    assert len(domains["VAR_CSV_S1"]) < 500
    out = annotate_reachable_values(rmap)
    assert set(out["derived_variables"][0]["reachable_values"]) == {0, 1}


def test_realization_map_with_hints(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    root.mkdir()
    (root / "run.py").write_text(
        'get_column_index(t, "Input_Layout")\nget_column_index(t, "B")\nget_column_index(t, "sparse_mode")\n',
        encoding="utf-8",
    )
    from testcase_agent.io import write_yaml

    (tmp_path / "realization").mkdir()
    write_yaml(
        tmp_path / "realization" / "domain_hints.yaml",
        {
            "source": "human",
            "columns": {
                "sparse_mode": {"values": [0, 1, 2, 3, 4, 5, 6]},
                "Input_Layout": {"values": ["BNSD", "TND"]},
            },
        },
    )
    evidence = build_consumer_evidence(root, snapshot={}, obligations_doc={"obligations": []}, out_root=tmp_path)
    assert "TND" in evidence["sample_values"].get("Input_Layout", [])
    files = {
        "kernel/variables.yaml": {
            "runtime_variables": [
                {
                    "id": "KVAR_SPARSEMODE",
                    "name": "sparseMode",
                    "domain_entries": [{"name": "NO_MASK", "value": 0}, {"name": "BAND", "value": 4}],
                }
            ]
        },
        "tiling/key_space.yaml": {"dimensions": [{"name": "IsTnd", "values": [0, 1]}]},
        "kernel/branches.yaml": {"branches": []},
    }
    schema = build_consumer_schema_from_evidence(evidence, root, key_space=files["tiling/key_space.yaml"], snapshot_files=files)
    by_name = {f["name"]: f for f in schema["fields"]}
    assert 6 in (by_name["sparse_mode"]["domain"].get("values") or by_name["sparse_mode"]["domain"])
    lex, _gaps = propose_key_derivations_from_evidence(
        lexicon=lexicon_from_key_space(files["tiling/key_space.yaml"]),
        csv_columns=schema["columns"],
        sample_values=evidence["sample_values"],
        snapshot_files=files,
    )
    snapshot = {"snapshot_hash": "x", "files": files}
    rmap = build_realization_map(snapshot, schema, lexicon=lex, op_name="Demo")
    csv_by_id = {v["id"]: v for v in rmap["csv_variables"]}
    assert "TND" in csv_by_id["VAR_CSV_Input_Layout"]["domain"]


def test_layout_flag_prefers_primary_input_layout() -> None:
    lex = lexicon_from_key_space({"dimensions": [{"name": "IsTnd", "values": [0, 1]}]})
    proposed, gaps = propose_key_derivations_from_evidence(
        lexicon=lex,
        csv_columns=["Atten_mask_layout", "Input_Layout", "B"],
        sample_values={
            "Atten_mask_layout": ["TND", "BSH"],
            "Input_Layout": ["BNSD", "TND"],
        },
    )
    # Name heuristics no longer auto-bind; clues prefer primary layout for LLM.
    unbound = [g for g in gaps if g.get("code") == "UNBOUND_KEY" and "ISTND" in str(g.get("variable_id"))]
    assert unbound
    clues = " ".join(str(c) for c in (unbound[0].get("candidate_columns") or []))
    assert "Input_Layout" in clues
    assert "Atten_mask_layout" not in clues or clues.index("Input_Layout") <= clues.find("Atten")
    assert not any("ISTND" in str(item.get("id")) for item in proposed["key_derivations"])


def test_presence_flag_not_bound_to_tensor_blob() -> None:
    lex = lexicon_from_key_space({"dimensions": [{"name": "IsPse", "values": [0, 1]}]})
    proposed, gaps = propose_key_derivations_from_evidence(
        lexicon=lex,
        csv_columns=["pse", "PSE_shape", "PSE_type", "B"],
        sample_values={"pse": ["_"], "PSE_shape": ["NONE", "BN"], "PSE_type": [0, 1]},
        snapshot_files={
            "contracts/testcase.yaml": {
                "interface": {"optional_inputs": [{"id": "VAR_OPTIONAL_PSE", "name": "pse"}]},
                "key_determinants": {
                    "KEY_ISPSE": {"role": "optional_presence", "csv_determinants": [], "needs_binding": True}
                },
            }
        },
    )
    # Must not auto-lock to tensor blob; leave UNBOUND_KEY with shape/type clues.
    assert not any("ISPSE" in str(item.get("id")) and item.get("locked") for item in proposed["key_derivations"])
    unbound = [g for g in gaps if "ISPSE" in str(g.get("variable_id") or "")]
    assert unbound
    clue_blob = str(unbound)
    assert "PSE_shape" in clue_blob or "PSE_type" in clue_blob or unbound[0].get("code") in {
        "UNBOUND_KEY",
        "MISSING_CSV_REF",
    }


def test_locked_seed_derivation_not_overwritten() -> None:
    from testcase_agent.binding_lexicon import merge_lexicons, normalize_lexicon

    seed = {
        "source": "seed",
        "key_derivations": [
            {
                "id": "VAR_KEY_ISTND",
                "type": "int",
                "domain": [0, 1],
                "expr": {
                    "op": "if_then_else",
                    "condition": {"op": "eq", "var": "VAR_CSV_Input_Layout", "value": "TND"},
                    "then": 1,
                    "else": 0,
                },
                "source_refs": [{"path": "binding_lexicon.yaml", "reason": "migrated_from_prior"}],
            }
        ],
        "key_tokens": {"IS_TND": {"var": "VAR_KEY_ISTND", "true_value": 1}},
    }
    merged = normalize_lexicon(merge_lexicons(lexicon_from_key_space({"dimensions": [{"name": "IsTnd", "values": [0, 1]}]}), seed))
    proposed, _gaps = propose_key_derivations_from_evidence(
        lexicon=merged,
        csv_columns=["Atten_mask_layout", "Input_Layout"],
        sample_values={"Atten_mask_layout": ["TND"], "Input_Layout": ["BNSD"]},
    )
    istnd = next(item for item in proposed["key_derivations"] if item["id"] == "VAR_KEY_ISTND")
    assert istnd["expr"]["condition"]["var"] == "VAR_CSV_Input_Layout"


def test_coverage_inventory_lists_variable_values() -> None:
    from testcase_agent.planner import build_coverage_inventory, build_review_coverage_index

    obligations = [
        {
            "id": "OB1",
            "kind": "csv_domain_cover",
            "field": "Input_Layout",
            "target_refs": ["VAR_CSV_Input_Layout"],
            "target_value": "BSH",
        },
        {
            "id": "OB2",
            "kind": "csv_domain_cover",
            "field": "Input_Layout",
            "target_refs": ["VAR_CSV_Input_Layout"],
            "target_value": "TND",
        },
        {
            "id": "OB3",
            "kind": "tiling_key_field_value",
            "field": "sparse_mode",
            "target_refs": ["KEY_SPARSE"],
            "target_value": 0,
        },
    ]
    inventory = build_coverage_inventory(obligations)
    assert inventory["variable_count"] == 2
    assert inventory["value_point_count"] == 3
    layout = next(item for item in inventory["variables"] if item["variable"] == "Input_Layout")
    assert layout["values"] == ["BSH", "TND"]
    lines = build_review_coverage_index(obligations, level="L1", files={})
    text = "\n".join(lines)
    assert "变量取值覆盖清单" in text
    assert "Input_Layout" in text
    assert "BSH" in text and "TND" in text


def test_uo_determinants_drive_key_derivation() -> None:
    proposed, _gaps = propose_key_derivations_from_evidence(
        lexicon={"key_tokens": {}, "key_derivations": []},
        csv_columns=["Input_Layout", "B"],
        sample_values={},
        snapshot_files={
            "contracts/testcase.yaml": {
                "key_determinants": {
                    "KEY_ISTND": {
                        "role": "layout_flag",
                        "csv_determinants": [{"column": "Input_Layout", "op": "eq", "value": "TND"}],
                        "primary_layout_field": "input_layout",
                    }
                }
            }
        },
    )
    istnd = next(item for item in proposed["key_derivations"] if item["id"] == "VAR_KEY_ISTND")
    assert istnd.get("locked") is not True
    assert istnd.get("status") == "proposed"
    assert istnd["expr"]["condition"]["value"] == "TND"