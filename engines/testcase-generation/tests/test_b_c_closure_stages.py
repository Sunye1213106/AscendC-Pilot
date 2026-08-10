# -*- coding: utf-8 -*-
"""Focused unit tests for B1/B2/B4/C1 adapter pack, cold-start, lemma-evidence, kernel."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
for p in (
    REPO / "engines" / "testcase-generation",
    REPO / "engines" / "understand-operator" / "src",
    REPO / "pilot",
    REPO / "scripts",
):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


@pytest.fixture()
def closure_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("UO_OP_DIR", str(tmp_path))
    state = tmp_path / ".ascendc-pilot" / "arch0" / "tg" / "closure"
    state.mkdir(parents=True)
    monkeypatch.setenv("TG_CLOSURE_STATE", str(state))
    from testcase_agent.closure import workspace as W

    ws = W.Workspace(root=tmp_path, artifacts=state, state=state).ensure()
    ws.r_path.write_text("1,seed\n2,seed\n", encoding="utf-8")
    ws.e_path.write_text("", encoding="utf-8")
    ws.open_path.write_text("3\n4\n", encoding="utf-8")
    (state / "lemmas").mkdir(exist_ok=True)
    (state / "lemmas" / "active_rules.yaml").write_text("rules: []\n", encoding="utf-8")
    return ws


def test_cold_start_clears_and_stamps(closure_ws):
    from testcase_agent.closure import cold_start as CS

    out = CS.cold_start(closure_ws, clear_rounds=True)
    assert out["ok"] is True
    assert closure_ws.r_path.read_text(encoding="utf-8") == ""
    assert closure_ws.e_path.read_text(encoding="utf-8") == ""
    assert not (closure_ws.state / "lemmas" / "active_rules.yaml").is_file()
    doc = yaml.safe_load((closure_ws.state / "cold_start.yaml").read_text(encoding="utf-8"))
    assert doc["fingerprint"]
    assert doc["timestamp"]

    # Nonempty E without post-cold-start promotion fails provenance.
    closure_ws.e_path.write_text("9\n", encoding="utf-8")
    prov = CS.check_e_provenance(closure_ws)
    assert prov["ok"] is False
    assert any("active_rules" in i or "proof_rules" in i for i in prov["issues"])


def test_lemma_evidence_smoke(closure_ws, tmp_path: Path):
    from testcase_agent.closure import lemma_evidence as LE

    # Seed a tiny source file for regex collection.
    src = tmp_path / "op_host"
    src.mkdir()
    (src / "tiling.cpp").write_text(
        "void SetLayout() {\n"
        "  if (Layout == 1) return;\n"
        "  layoutType = 1;\n"
        "}\n",
        encoding="utf-8",
    )
    out = LE.collect("Layout=1", ws=closure_ws)
    assert out["ok"] is True
    assert out["entry_count"] >= 1
    assert Path(out["yaml"]).is_file()
    assert out["entry_ids"]
    pack = yaml.safe_load(Path(out["yaml"]).read_text(encoding="utf-8"))
    assert pack["review_template"]["proof"]["evidence_entry_ids"]

    from testcase_agent.closure.certificate import validate

    # Soft: pack present without citations → warning, hard fields still required.
    soft = validate({"certificate": {
        "proof_scope": {
            "target_dimensions": ["Layout"],
            "relevant_functions": ["SetLayout"],
            "assignments": ["a.cpp:1"],
            "guards": ["a.cpp:2"],
        },
        "assumptions": [],
        "completeness_evidence": {
            "assignment_sites_complete": True,
            "call_closure_complete": True,
            "alias_state_exact": True,
            "macro_context_complete": True,
        },
        "counterexample_strategy": {"finite_D": "enumerate"},
    }}, evidence_pack=pack)
    assert soft["ok"] is False
    assert "evidence_entry_ids_missing_while_pack_present" in soft["errors"]


def test_kernel_domain_tiny_fixture(closure_ws, monkeypatch: pytest.MonkeyPatch):
    from testcase_agent.closure import kernel_domain as KD
    from testcase_agent.closure import workspace as W

    uo = closure_ws.root / ".ascendc-pilot" / "arch0" / "uo"
    (uo / "views").mkdir(parents=True)
    (uo / "views" / "kernel.yaml").write_text(
        yaml.safe_dump({
            "schema": "uo-view-kernel/v1",
            "branches": [
                {
                    "id": "KB_LAYOUT1",
                    "condition": "Layout == 1",
                    "dimensions": ["Layout"],
                    "stage": "constexpr",
                    "finite_predicate": {"op": "eq", "field": "Layout", "value": 1},
                },
                {
                    "id": "KB_LAYOUT0",
                    "condition": "Layout == 0",
                    "dimensions": ["Layout"],
                    "stage": "constexpr",
                    "finite_predicate": {"op": "eq", "field": "Layout", "value": 0},
                },
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(W, "decode", lambda k: {"Layout": 1 if int(k) == 1 else 0})
    monkeypatch.setattr(
        "testcase_agent.closure.ledger.load_R",
        lambda ws=None: {1, 2},
    )
    out = KD.compute_r_kernel(closure_ws, write=True)
    assert out["ok"] is True
    assert out["branches"] == 2
    assert out["R_kernel"]["KB_LAYOUT1"] == 1
    assert Path(out["path"]).is_file()
    # C3: the per-key inversion the closure rows join on.
    assert out["branches_by_key"] == {1: ["KB_LAYOUT1"], 2: ["KB_LAYOUT0"]}


def _seed_toy_tpl_header(ws) -> None:
    """The declared set comes from the kernel header; certify reads it."""
    header = ws.root / "op_kernel" / "arch0" / "_synthetic_toy_template_tiling_key.h"
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text(
        "ASCENDC_TPL_ARGS_DECL(_synthetic_toy,\n"
        "    ASCENDC_TPL_UINT_DECL(A, ASCENDC_TPL_3_BW, ASCENDC_TPL_UI_LIST, 0, 1, 2),\n"
        ")\n"
        "ASCENDC_TPL_ARGS_SEL(\n"
        "    ASCENDC_TPL_UINT_SEL(A, ASCENDC_TPL_UI_LIST, 0, 1, 2),\n"
        ")\n",
        encoding="utf-8",
    )


def _seed_kernel_and_tilingdata_views(ws) -> Path:
    uo = ws.root / ".ascendc-pilot" / "arch0" / "uo" / "views"
    uo.mkdir(parents=True, exist_ok=True)
    (uo / "kernel.yaml").write_text(
        yaml.safe_dump({
            "branches": [
                {
                    "id": "KB_A1",
                    "condition": "A == 1",
                    "dimensions": ["A"],
                    "stage": "constexpr",
                    "finite_predicate": {"op": "eq", "field": "A", "value": 1},
                }
            ]
        }),
        encoding="utf-8",
    )
    (uo / "tilingdata.yaml").write_text(
        yaml.safe_dump({
            "structs": [
                {
                    "name": "ToyTiling",
                    "fields": [
                        {
                            "name": "tileLen",
                            "writers": [
                                {
                                    "dimensions": ["A"],
                                    "finite_predicate": {"op": "eq", "field": "A", "value": 1},
                                }
                            ],
                            "readers": [{"function": "Process"}],
                        },
                        {"name": "unwritten", "writers": [], "readers": [{"function": "Process"}]},
                    ],
                }
            ]
        }),
        encoding="utf-8",
    )
    return uo


def test_closure_rows_name_the_kernel_branches_and_fields(closure_ws, monkeypatch: pytest.MonkeyPatch):
    """C3: each TilingKey row carries the branches and fields it reaches."""
    import csv as _csv

    from testcase_agent.closure import report as R
    from testcase_agent.closure import workspace as W

    _seed_kernel_and_tilingdata_views(closure_ws)
    monkeypatch.setattr(W, "dim_names", lambda: ["A"])
    monkeypatch.setattr(W, "decode", lambda k: {"A": int(k)})
    monkeypatch.setattr("testcase_agent.closure.ledger.declared", lambda: {1, 2})
    monkeypatch.setattr("testcase_agent.closure.ledger.load_R", lambda ws=None: {1, 2})

    doc = R.report(closure_ws, refresh=True)
    assert doc["domain_errors"] == [], doc["domain_errors"]
    with open(doc["path"], encoding="utf-8", newline="") as fh:
        rows = {r["tiling_key"]: r for r in _csv.DictReader(fh)}
    assert "kernel_branches" in rows["1"] and "tilingdata_fields" in rows["1"]
    assert rows["1"]["kernel_branches"] == "KB_A1"
    assert rows["1"]["tilingdata_fields"] == "tileLen"
    # Key 2 satisfies neither the branch condition nor the writer guard.
    assert rows["2"]["kernel_branches"] == ""
    assert rows["2"]["tilingdata_fields"] == ""


def test_certificate_requires_every_domain_invariant(closure_ws, monkeypatch: pytest.MonkeyPatch):
    """A three-domain report must not certify on the TilingKey domain alone."""
    from replay import package_data
    from testcase_agent.closure import report as R

    _seed_toy_tpl_header(closure_ws)
    _seed_kernel_and_tilingdata_views(closure_ws)
    package_data.clear_caches()
    cert = R.certify_invariants(closure_ws)
    for name in ("I1_kernel", "I4_kernel", "I8_kernel",
                 "I1_tilingdata", "I4_tilingdata", "I8_tilingdata"):
        assert name in cert["checks"], name

    # A failing domain check must sink the certificate, not be computed and dropped.
    monkeypatch.setattr(
        "testcase_agent.closure.tilingdata_domain.compute_tilingdata_coverage",
        lambda ws=None, write=True: {
            "tilingdata_fields": [{"name": "bad", "exclude": True, "status": "no_writer"}],
            "over_approximated": True,
            "fields": 1,
            "defects": [],
        },
    )
    bad = R.certify_invariants(closure_ws)
    assert bad["checks"]["I1_tilingdata"]["ok"] is False
    assert bad["ok"] is False


def test_tilingdata_observed_values_come_from_driver_state_marks(closure_ws):
    """C2: the real-machine口径 reads what the driver actually dumped."""
    from testcase_agent.closure import tilingdata_domain as TD

    (Path(closure_ws.artifacts) / "batch1_log.txt").write_text(
        "###CASE c0\n"
        "###STATE tileLen=128\n"
        "###STATE tileLen=256\n"
        "###DONE c0 ok=1 key=1\n",
        encoding="utf-8",
    )
    observed = TD.observed_values(closure_ws)
    assert observed.get("tileLen") == {"128", "256"}


def test_adapter_pack_from_minimal_host_derivation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("UO_OP_DIR", str(tmp_path))

    uo = tmp_path / ".ascendc-pilot" / "arch0" / "uo"
    (uo / "ir").mkdir(parents=True)
    (uo / "manifest.yaml").write_text(
        "op_name: _synthetic_toy\narchitecture: arch0\n",
        encoding="utf-8",
    )
    (uo / "ir" / "host_derivation.yaml").write_text(
        yaml.safe_dump({
            "fields": [
                {
                    "name": "Layout",
                    "root_vars": ["INPUT_layout", "VAR_x"],
                    "var_roots": {"VAR_x": "INPUT_layout"},
                    "status": "derived",
                }
            ]
        }),
        encoding="utf-8",
    )

    from uo_init.adapter_pack import export_adapter_pack, gate_sampling_grid

    # Gate: unknown grid key fails when schema present.
    # With synthetic toy schema, inventing a bad key should fail.
    bad = export_adapter_pack(
        tmp_path,
        arch="arch0",
        sampling_grid={"not_a_real_knob": [1]},
    )
    # If knob_schema available → fail; if not (import issues) → ok with empty gate.
    if bad.get("gate") == "sampling_grid_knob_schema":
        assert bad["ok"] is False
    else:
        assert gate_sampling_grid({"not_a_real_knob": [1]}, {"n": {}}) == ["not_a_real_knob"]

    out = export_adapter_pack(tmp_path, arch="arch0")
    assert out["ok"] is True
    adapter = Path(out["adapter_dir"])
    for name in (
        "bridge_spec.yaml",
        "feature_bindings.yaml",
        "search_hints.yaml",
        "construction_hints.yaml",
    ):
        assert (adapter / name).is_file(), name

    # Loader prefers uo/adapter over package.
    from replay import package_data

    package_data.clear_caches()
    features = package_data.load_yaml("feature_bindings.yaml", refresh=True)
    assert features.get("source") == "export_adapter_pack"


def test_resolve_gaps_llm_default_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("UO_RESOLVE_GAPS_LLM", raising=False)
    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "ir"
    uo.mkdir(parents=True)
    (uo / "unresolved.yaml").write_text(
        "version: 1\nstatus: open\nblocker_count: 25\n"
        "derivation_blocker_count: 5\nblockers: [{id: BLK_1}]\n",
        encoding="utf-8",
    )
    from uo_init.pilot_engines import resolve_gaps

    out = resolve_gaps(tmp_path, {"run_id": "r1"})
    assert out["ok"] is True
    assert out.get("need_subagent") is False
    assert out.get("llm_enabled") is False

    monkeypatch.setenv("UO_RESOLVE_GAPS_LLM", "1")
    out2 = resolve_gaps(tmp_path, {"run_id": "r2"})
    assert out2.get("llm_enabled") is True
    assert out2.get("need_subagent") is True


def _wide(path: Path, header: list[str], rows: list[list[str]]) -> None:
    import csv as _csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def test_wide_witnesses_do_not_require_a_tag_column(closure_ws):
    """corpus.commit writes no `tag`; requiring it made search rounds unledgered."""
    from testcase_agent.closure import ledger

    _wide(
        Path(closure_ws.artifacts) / "round_0001_model_key_cases.csv",
        ["layout", "dtype", "n", "ok", "tiling_key", "reject"],
        [["FLAT", "FLOAT", "4", "1", "7", ""], ["FLAT", "FLOAT", "8", "0", "-1", "REJECT"]],
    )
    found = ledger.from_wide(closure_ws)
    assert 7 in found
    assert -1 not in found


def test_key_zero_is_a_witness_not_a_missing_key(closure_ws):
    """Keys encode value indices, so 0 is legal; -1 is the no-key marker."""
    from testcase_agent.closure import ledger

    _wide(
        Path(closure_ws.artifacts) / "round_0002_model_key_cases.csv",
        ["ok", "tiling_key"],
        [["1", "0"], ["1", "-1"]],
    )
    found = ledger.from_wide(closure_ws)
    assert 0 in found, "an all-first-value key can never be witnessed otherwise"
    assert -1 not in found


def test_kernel_and_tilingdata_load_from_db_without_yaml(closure_ws):
    """D3/C1/C2: domain loaders must prefer the DB product when YAML is gone."""
    import json
    import sqlite3

    from testcase_agent.closure import kernel_domain as KD
    from testcase_agent.closure import tilingdata_domain as TD

    uo = closure_ws.root / ".ascendc-pilot" / "arch0" / "uo"
    db = uo / "indexes" / "kb_graph.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    kernel_doc = {
        "schema": "uo-view-kernel/v1",
        "branches": [
            {
                "id": "KB_DB",
                "condition": "A == 1",
                "dimensions": ["A"],
                "stage": "constexpr",
                "finite_predicate": {"op": "eq", "field": "A", "value": 1},
            }
        ],
    }
    tiling_doc = {
        "schema": "uo-view-tilingdata/v1",
        "structs": [{"name": "Tile", "fields": [{"name": "M", "writers": [], "readers": []}]}],
    }
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE view_blob(name TEXT PRIMARY KEY, schema_id TEXT, data TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO view_blob(name, schema_id, data) VALUES(?,?,?)",
            ("views/kernel.yaml", "uo-view-kernel/v1", json.dumps(kernel_doc)),
        )
        conn.execute(
            "INSERT INTO view_blob(name, schema_id, data) VALUES(?,?,?)",
            ("views/tilingdata.yaml", "uo-view-tilingdata/v1", json.dumps(tiling_doc)),
        )
        conn.commit()
    finally:
        conn.close()

    branches = KD.load_kernel_branches(uo)
    assert [b["id"] for b in branches] == ["KB_DB"]
    fields = TD.load_tilingdata_fields(uo)
    assert [f["name"] for f in fields] == ["M"]


def test_acceptance_harness_closes_the_toy_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """B6: the harness must prove the loop closes a gap, not that steps ran."""
    import closure_acceptance_harness as H
    from replay import package_data

    # run_dry points the process at the toy operator. Register the vars through
    # monkeypatch first so teardown restores them for the rest of the session.
    for var in ("UO_OPERATOR", "UO_ARCH", "ASCENDC_PROJECT_ROOT", "UO_OP_DIR", "TG_CLOSURE_STATE"):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("TG_CLOSURE_CI", "1")
    try:
        report = H.run_dry(tmp_path / "op", budget=8, seed=0)
    finally:
        package_data.clear_caches()
    assert report["gate_failures"] == [], report["gate_failures"]
    assert report["ok"] is True
    assert report["initial_gap"] == report["declared"] > 0
    assert report["final_gap"] == 0
    assert report["oracle_calls"] > 0
    assert report["oracle_judged_cases"] > 0
    # Tri-domain columns must be populated from the seeded UO views/DB.
    tri = next(s for s in report["steps"] if s.get("step") == "tri_domain_report")
    assert (
        int(tri.get("keys_with_kernel_branches") or 0)
        + int(tri.get("keys_with_tilingdata_fields") or 0)
    ) > 0
