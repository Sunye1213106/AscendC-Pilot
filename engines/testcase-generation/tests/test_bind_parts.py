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
    assert bind["mapping"]["Dtype"]["role"] == ""
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
    doc["mapping"]["Forged"] = {"role": "api_arg"}
    doc["mapping"]["Dtype"]["encoding"] = "TND: sum(s1)"
    doc["mapping"]["Dtype"]["role"] = "api_arg"
    doc["call"]["kind"] = "pta"
    bind_path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    restored = BP.restore_and_dump_parts(parts)
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    assert bind["run_id"] == "RUN_1"
    assert "Forged" not in bind["mapping"]
    assert bind["mapping"]["Dtype"]["encoding"] == "TND: sum(s1)"
    assert bind["mapping"]["Dtype"]["role"] == "api_arg"
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
