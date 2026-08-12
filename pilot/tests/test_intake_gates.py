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


def test_start_intake_gate_requires_architecture_from_tree(tmp_path: Path):
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
