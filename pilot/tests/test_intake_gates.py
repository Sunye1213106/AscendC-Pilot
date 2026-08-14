# -*- coding: utf-8 -*-
"""Intake gates: arch from tree, pin .ascendc-pilot to operator package."""

from __future__ import annotations

import json
from pathlib import Path

from ascendc_pilot import intake
from ascendc_pilot.cli import main
from ascendc_pilot.paths import pilot_checkout_root


def test_looks_like_operator_package(tmp_path: Path):
    assert not intake.looks_like_operator_package(tmp_path)
    (tmp_path / "op_host").mkdir()
    assert intake.looks_like_operator_package(tmp_path)


def test_discover_architectures_from_tree_only(tmp_path: Path):
    (tmp_path / "op_host" / "arch22").mkdir(parents=True)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    (tmp_path / "op_host" / "notes").mkdir()
    assert intake.discover_architectures(tmp_path) == ["arch22", "arch35"]
    # No invented fallback when tree empty
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "op_host").mkdir()
    assert intake.discover_architectures(empty) == []


def test_describe_architectures_has_source_counts(tmp_path: Path):
    d = tmp_path / "op_host" / "arch35"
    d.mkdir(parents=True)
    (d / "a.cpp").write_text("//", encoding="utf-8")
    (tmp_path / "op_host" / "shared.cpp").write_text("//", encoding="utf-8")
    opts = intake.describe_architectures(tmp_path)
    assert len(opts) == 1
    assert opts[0]["label"] == "arch35"
    assert "op_host/arch35: 1 sources" in opts[0]["description"]
    assert "shared" in opts[0]["description"]


def test_scan_operator_directory_returns_layout_and_arch_options(tmp_path: Path):
    (tmp_path / "op_host" / "arch22").mkdir(parents=True)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    (tmp_path / "op_kernel" / "arch35").mkdir(parents=True)
    (tmp_path / "op_host" / "tiling.cpp").write_text("//", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    scanned = intake.scan_operator_directory(tmp_path)
    assert scanned["ok"] is True
    assert scanned["architectures"] == ["arch22", "arch35"]
    assert "op_host/" in scanned["layout"]["top_level"] or "op_host" in [
        x.rstrip("/") for x in scanned["layout"]["top_level"]
    ]
    assert "arch22/" in scanned["layout"]["op_host"] or "arch22" in [
        x.rstrip("/") for x in scanned["layout"]["op_host"]
    ]
    labels = [o["label"] for o in scanned["ask_question"]["options"]]
    assert labels == ["arch22", "arch35"]
    assert "scan" in scanned["message_zh"].lower() or "architecture" in scanned["message_zh"].lower()


def test_scan_operator_directory_rejects_non_operator(tmp_path: Path):
    (tmp_path / "src").mkdir()
    scanned = intake.scan_operator_directory(tmp_path)
    assert scanned["ok"] is False
    assert scanned["error"] == "not_operator_package"


def test_start_intake_gate_requires_architecture_from_tree(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    (tmp_path / "op_host" / "arch22").mkdir(parents=True)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    gate = intake.start_intake_gate(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="",
        project_explicit=True,
    )
    assert gate is not None
    assert gate["reason_code"] == "ARCHITECTURE_REQUIRED"
    labels = [o["label"] for o in gate["ask_question"]["options"]]
    assert labels == ["arch22", "arch35"]
    assert "arch36" not in labels
    assert "pending_start" not in gate
    assert "acp start" in gate["suggested_command"]
    assert "--architecture" in gate["suggested_command"]


def test_start_intake_gate_rejects_unknown_arch(tmp_path: Path):
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    gate = intake.start_intake_gate(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="arch64",
        project_explicit=True,
    )
    assert gate is not None
    assert gate["reason_code"] == "ARCHITECTURE_NOT_IN_TREE"


def test_start_intake_gate_rejects_pilot_checkout():
    harness = pilot_checkout_root()
    gate = intake.start_intake_gate(
        project=harness,
        workflow_id="uo-init",
        architecture="arch35",
        project_explicit=True,
    )
    assert gate is not None
    assert gate["reason_code"] == "OPERATOR_PROJECT_REQUIRED"


def test_default_cli_project_prefers_cache_over_monorepo_cwd(tmp_path: Path, monkeypatch):
    op = tmp_path / "op"
    parent = tmp_path / "monorepo"
    op.mkdir()
    (op / "op_host").mkdir()
    parent.mkdir()
    intake.write_last_project_cache(op)
    monkeypatch.chdir(parent)
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    assert intake.default_cli_project() == op.resolve()


def test_cli_start_asks_for_architecture(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    code = main(["start", "uo-init", "--project", str(tmp_path)])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["needs_human_decision"] is True
    assert out["reason_code"] == "ARCHITECTURE_REQUIRED"
    assert out["ask_question"]["options"][0]["label"] == "arch35"
    assert "acp start" in out["suggested_command"]
    assert "--architecture" in out["suggested_command"]


def test_cli_start_with_project_and_arch(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    code = main(
        [
            "start",
            "uo-init",
            "--project",
            str(tmp_path),
            "--architecture",
            "arch35",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out.get("workflow_id") == "uo-init"
    assert out.get("architecture") == "arch35"


def test_cli_prepare_rejects_non_operator(tmp_path: Path, capsys):
    code = main(["run-action", "prepare", "--project", str(tmp_path)])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["reason_code"] == "OPERATOR_PROJECT_REQUIRED"


def test_cli_prepare_rejects_pilot_checkout(capsys):
    harness = pilot_checkout_root()
    code = main(["run-action", "prepare", "--project", str(harness)])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["reason_code"] == "OPERATOR_PROJECT_REQUIRED"


def test_start_intake_gate_tg_requires_uo_product(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    gate = intake.start_intake_gate(
        project=tmp_path,
        workflow_id="tg-init",
        architecture="",
        project_explicit=True,
    )
    assert gate is not None
    assert gate["reason_code"] == "UO_PRODUCT_REQUIRED"
    assert "uo-init" in gate["suggested_command"]
    values = [o.get("value") for o in (gate.get("ask_question") or {}).get("options") or []]
    assert "uo-init" in values
    assert "source" not in values


def test_start_intake_gate_uo_query_offers_source_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    gate = intake.start_intake_gate(
        project=tmp_path,
        workflow_id="uo-query",
        architecture="arch35",
        project_explicit=True,
    )
    assert gate is not None
    assert gate["reason_code"] == "UO_PRODUCT_REQUIRED"
    expected = intake.expected_uo_product_path(
        tmp_path, architecture="arch35", op_name=tmp_path.name
    )
    assert gate["expected_path"] == expected
    assert "arch35" in expected
    values = [o.get("value") for o in (gate.get("ask_question") or {}).get("options") or []]
    assert values == ["uo-init", "source"]
    assert "found none" not in str(gate.get("message_zh") or "")
    assert "Glob" in str(gate.get("primary_instruction_zh") or "")


def test_cli_uo_query_missing_product_asks_human(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    code = main(
        [
            "uo-query",
            "--project",
            str(tmp_path),
            "--architecture",
            "arch35",
            "--pattern",
            "IsDNoEqual",
        ]
    )
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["reason_code"] == "UO_PRODUCT_REQUIRED"
    assert out["needs_human_decision"] is True
    values = [o.get("value") for o in (out.get("ask_question") or {}).get("options") or []]
    assert "uo-init" in values
    assert "source" in values
    assert "found none" not in str(out.get("error") or "")
    assert "found none" not in str(out.get("message_zh") or "")
    assert out.get("host_step", {}).get("kind") == "ask_human"
    assert "human_interaction_request" in out


def test_prepare_workflow_start_inherits_arch_from_uo(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    uo_dir = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    uo_dir.mkdir(parents=True)
    (uo_dir / "demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    prep = intake.prepare_workflow_start(
        project=tmp_path,
        workflow_id="tg-init",
        architecture="",
        project_explicit=True,
    )
    assert prep.get("ok") is True
    assert prep.get("architecture") == "arch35"
    assert prep.get("resolved_from") == "uo_product"
