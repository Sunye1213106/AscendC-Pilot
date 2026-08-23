# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import yaml

from testcase_agent import bind_parts as BP


def test_schemas_declare_engine_and_llm_owned() -> None:
    bind = BP.load_schema("bind-part")
    harness = BP.load_schema("harness-part")
    init = BP.load_schema("init")
    assert bind["schema"] == "tg-bind-part/v1"
    assert "run_id" in bind["engine_owned"]
    assert "artifact_identity" in bind["engine_owned"]
    assert "llm_edit" in bind["engine_owned"]
    assert "llm_edit" in harness["engine_owned"]
    assert "call" in bind["llm_owned"] or "call.kind" in bind["llm_owned"]
    assert "golden" in harness["llm_owned"] or "golden.match" in harness["llm_owned"]
    assert "schema" in init["engine_owned"]
    assert "uo_digest" in init["engine_owned"]


def test_emit_prefilled_parts_lock_columns_and_identity(tmp_path: Path) -> None:
    scan = {
        "kind": "script_repo",
        "contract": {
            "kind": "script_repo",
            "entry": "run_x.py",
            "case_arg": "--case",
            "columns": ["Dtype", "B"],
            "mode_candidates": [{"flag": "--pta_mode", "values": ["only_grad", "profiler"]}],
        },
        "inventory": {
            "tables": [
                {
                    "columns": ["Dtype", "B"],
                    "kind": "csv",
                    "profile": {"columns": {"Dtype": {"inferred_type": "enum-string"}}},
                }
            ]
        },
    }
    identity = {
        "run_id": "RUN_1",
        "workflow_id": "tg-init",
        "action_id": "bind_init",
        "produced_by": "pilot-finalizer",
    }
    parts = tmp_path / "parts"
    BP.emit_bind_parts(parts, scan=scan, identity=identity)
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    harness = yaml.safe_load((parts / "harness.yaml").read_text(encoding="utf-8"))
    assert bind["schema"] == "tg-bind-part/v1"
    assert bind["run_id"] == "RUN_1"
    assert bind["artifact_identity"]["run_id"] == "RUN_1"
    assert bind["columns"] == [{"name": "Dtype"}, {"name": "B"}]
    assert set(bind["mapping"]) == {"Dtype", "B"}
    assert "role" not in bind["mapping"]["Dtype"]
    assert bind["mapping"]["Dtype"]["control"]["status"] == ""
    assert bind["call"]["kind"] == ""
    assert bind["llm_edit"] is False
    assert harness["llm_edit"] is False
    assert yaml.safe_load((parts / ".engine" / "bind.owned.yaml").read_text(encoding="utf-8"))[
        "llm_edit"
    ] is False
    assert harness["modes"]["precision"] == []
    assert harness["modes"]["perf"] == []
    flags = [row["flag"] for row in harness["modes"]["candidates"]]
    assert "--pta_mode" in flags
    assert "--wait" not in flags
    assert (parts / ".engine" / "bind.owned.yaml").is_file()
    assert (parts / ".engine" / "harness.owned.yaml").is_file()


def test_restore_engine_owned_keeps_semantic_colon_and_identity(tmp_path: Path) -> None:
    scan = {
        "kind": "script_repo",
        "contract": {
            "entry": "run_x.py",
            "case_arg": "--case",
            "columns": ["Dtype"],
            "mode_candidates": [],
        },
        "inventory": {"tables": [{"columns": ["Dtype"], "kind": "csv", "profile": {}}]},
    }
    identity = {"run_id": "RUN_1", "workflow_id": "tg-init", "action_id": "bind_init"}
    parts = tmp_path / "parts"
    BP.emit_bind_parts(parts, scan=scan, identity=identity)
    bind_path = parts / "bind.yaml"
    doc = yaml.safe_load(bind_path.read_text(encoding="utf-8"))
    doc["run_id"] = "LLM_FORGED"
    doc["mapping"]["Forged"] = {"control": {"status": "active"}}
    doc["mapping"]["Dtype"]["encoding"] = "TND: sum(s1)"
    doc["mapping"]["Dtype"]["control"] = {"status": "active"}
    doc["mapping"]["Dtype"]["relation"] = "direct"
    doc["call"]["kind"] = "pta"
    bind_path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    restored = BP.restore_and_dump_parts(parts)
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    assert bind["run_id"] == "RUN_1"
    assert "Forged" not in bind["mapping"]
    assert bind["mapping"]["Dtype"]["encoding"] == "TND: sum(s1)"
    assert bind["mapping"]["Dtype"]["control"]["status"] == "active"
    assert "role" not in bind["mapping"]["Dtype"]
    assert bind["call"]["kind"] == "pta"
    assert restored["ok"] is True
    assert bind["llm_edit"] is True
    owned = yaml.safe_load((parts / ".engine" / "bind.owned.yaml").read_text(encoding="utf-8"))
    assert owned["llm_edit"] is True
    raw = (parts / "bind.yaml").read_text(encoding="utf-8")
    assert "TND: sum(s1)" in raw


def test_is_llm_edited_false_on_engine_skeleton_true_after_mark(tmp_path: Path) -> None:
    scan = {
        "kind": "script_repo",
        "contract": {"entry": "run_x.py", "case_arg": "--case", "columns": ["Dtype"]},
        "inventory": {"tables": [{"columns": ["Dtype"], "kind": "csv"}]},
    }
    parts = tmp_path / "parts"
    BP.emit_bind_parts(parts, scan=scan, identity={"run_id": "RUN_1"})
    bind_path = parts / "bind.yaml"
    harness_path = parts / "harness.yaml"
    assert BP.is_llm_edited(bind_path) is False
    assert BP.is_llm_edited(harness_path) is False
    BP.mark_llm_edited(bind_path)
    assert BP.is_llm_edited(bind_path) is True
    assert BP.is_llm_edited(harness_path) is False


def test_apply_bind_fill_merges_llm_cells_keeps_profile(tmp_path: Path) -> None:
    scan = {
        "kind": "script_repo",
        "contract": {
            "entry": "run_x.py",
            "case_arg": "--case",
            "columns": ["Dtype", "B"],
        },
        "inventory": {
            "tables": [
                {
                    "columns": ["Dtype", "B"],
                    "kind": "csv",
                    "profile": {"columns": {"B": {"inferred_type": "int", "min": 1}}},
                }
            ]
        },
    }
    parts = tmp_path / "parts"
    BP.emit_bind_parts(parts, scan=scan, identity={"run_id": "RUN_1"})
    fill = {
        "call": {"kind": "pta", "api": "torch_npu.foo", "site": "a.py:1"},
        "call_args": [{"name": "batch", "sources": [{"column": "B", "relation": "direct"}]}],
        "mapping": {
            "B": {
                "control": {"status": "active"},
                "relation": "direct",
                "confidence": "confirmed",
                "uo": {"id": "b", "candidate": ""},
                "encoding": "int",
                "evidence": "a.py:1",
            },
            "Dtype": {
                "control": {"status": "active"},
                "relation": "tensor_dtype",
                "confidence": "unresolved",
                "uo": {"id": "", "candidate": ""},
                "encoding": "enum",
                "evidence": "a.py:2",
            },
            "Forged": {
                "control": {"status": "active"},
                "relation": "direct",
                "uo": {"id": "nope"},
            },
        },
        "domains": {
            "B": {"operator": "b", "compare": "match", "profile": {"hack": True}},
        },
        "findings": [{"code": "partial_uo_id", "column": "Dtype"}],
        "run_id": "LLM_FORGED",
    }
    (parts / "bind.fill.yaml").write_text(yaml.safe_dump(fill, allow_unicode=True), encoding="utf-8")
    out = BP.apply_bind_fill(parts / "bind.yaml")
    assert out["ok"] is True
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    assert bind["run_id"] == "RUN_1"
    assert bind["call"] == {"kind": "pta", "api": "torch_npu.foo", "site": "a.py:1"}
    assert bind["call_args"] == [{"name": "batch", "sources": [{"column": "B", "relation": "direct"}]}]
    assert bind["mapping"]["B"]["uo"]["id"] == "b"
    assert bind["mapping"]["Dtype"]["control"]["status"] == "active"
    assert "Forged" not in bind["mapping"]
    assert bind["domains"]["B"]["operator"] == "b"
    assert bind["domains"]["B"]["compare"] == "match"
    assert bind["domains"]["B"]["profile"] == {"inferred_type": "int", "min": 1}
    assert bind["findings"][0]["column"] == "Dtype"
    assert bind["llm_edit"] is True


def test_restore_rejects_illegal_call_kind(tmp_path: Path) -> None:
    scan = {
        "kind": "script_repo",
        "contract": {"entry": "run_x.py", "case_arg": "--case", "columns": ["Dtype"]},
        "inventory": {"tables": [{"columns": ["Dtype"], "kind": "csv"}]},
    }
    parts = tmp_path / "parts"
    BP.emit_bind_parts(parts, scan=scan, identity={"run_id": "RUN_1"})
    bind_path = parts / "bind.yaml"
    doc = yaml.safe_load(bind_path.read_text(encoding="utf-8"))
    doc["call"]["kind"] = "pta_direct"
    bind_path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    out = BP.restore_and_dump_parts(parts)
    assert out["ok"] is False
    assert any("call.kind" in str(e) for e in out.get("errors") or [])


def test_chunk_column_names_sixty_is_three_groups() -> None:
    names = [f"C{i}" for i in range(60)]
    chunks = BP.chunk_column_names(names, 20)
    assert len(chunks) == 3
    assert chunks[0][0] == "C0" and chunks[0][-1] == "C19"
    assert chunks[2][0] == "C40" and chunks[2][-1] == "C59"


def test_expand_bind_fanout_axes_sixty_columns_four_tasks() -> None:
    axes = [
        {"id": "harness", "capability_id": "bind-init", "artifact": "h.yaml"},
        {
            "id": "bind",
            "capability_id": "bind-init",
            "artifact": "runs/{run_id}/actions/bind_init/parts/bind.yaml",
            "chunk_size": 20,
        },
    ]
    names = [f"C{i:02d}" for i in range(60)]
    out = BP.expand_bind_fanout_axes(axes, columns=names, run_id="R1")
    assert [row["id"] for row in out] == ["harness", "bind0", "bind1", "bind2"]
    assert out[1]["artifact"].endswith("bind0.yaml")
    assert len(out[1]["column_names"]) == 20
    assert out[3]["column_names"][-1] == "C59"


def test_merge_bind_chunks_unions_mapping_and_call_args(tmp_path: Path) -> None:
    names = [f"C{i}" for i in range(25)]
    scan = {
        "kind": "script_repo",
        "contract": {"entry": "run.py", "case_arg": "--case", "columns": names},
        "inventory": {"tables": [{"columns": names, "kind": "csv"}]},
    }
    parts = tmp_path / "parts"
    BP.emit_bind_parts(parts, scan=scan, identity={"run_id": "RUN_1"})
    assert (parts / "bind0.yaml").is_file()
    assert (parts / "bind1.yaml").is_file()
    c0 = yaml.safe_load((parts / "bind0.yaml").read_text(encoding="utf-8"))
    c0["call"] = {"kind": "pta", "api": "torch_npu.foo", "site": "a.py:1"}
    c0["call_args"] = [{"name": "x", "sources": [{"column": "C0", "relation": "direct"}]}]
    c0["mapping"]["C0"]["control"] = {"status": "active"}
    c0["mapping"]["C0"]["relation"] = "direct"
    c0["mapping"]["C0"]["confidence"] = "confirmed"
    c0["mapping"]["C0"]["uo"] = {"id": "c0", "candidate": ""}
    (parts / "bind0.yaml").write_text(yaml.safe_dump(c0, allow_unicode=True), encoding="utf-8")
    c1 = yaml.safe_load((parts / "bind1.yaml").read_text(encoding="utf-8"))
    c1["call_args"] = [{"name": "y", "sources": [{"column": "C20", "relation": "direct"}]}]
    c1["mapping"]["C20"]["control"] = {"status": "metadata"}
    c1["mapping"]["C20"]["relation"] = "candidate"
    (parts / "bind1.yaml").write_text(yaml.safe_dump(c1, allow_unicode=True), encoding="utf-8")
    merged = BP.merge_bind_chunks(parts)
    assert merged["ok"] is True and merged["chunks"] == 2
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    assert bind["call"]["kind"] == "pta"
    names_args = {row["name"] for row in bind["call_args"]}
    assert names_args == {"x", "y"}
    assert bind["mapping"]["C0"]["uo"]["id"] == "c0"
    assert bind["mapping"]["C20"]["control"]["status"] == "metadata"
    restored = BP.restore_and_dump_parts(parts)
    assert restored["ok"] is True
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    assert bind["llm_edit"] is True
    assert bind["run_id"] == "RUN_1"
