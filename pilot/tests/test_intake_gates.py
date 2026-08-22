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
    # On-disk listing never invents default / arch35.
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "op_host").mkdir()
    assert intake.discover_architectures(empty) == []


def test_parse_uo_product_name_accepts_default_slot(tmp_path: Path):
    path = tmp_path / "toy.default.uo"
    parsed = intake.parse_uo_product_name(path)
    assert parsed["op_name"] == "toy"
    assert parsed["architecture"] == "default"


def test_discover_architectures_includes_hyphenated_920r1(tmp_path: Path):
    (tmp_path / "op_host" / "arch-920r1").mkdir(parents=True)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    (tmp_path / "op_host" / "notes").mkdir()
    assert intake.discover_architectures(tmp_path) == ["arch-920r1", "arch35"]


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


def test_scan_operator_directory_omits_ask_when_pr_pin_unique(tmp_path: Path):
    from ascendc_pilot.run_resume import save_pr_architecture_pin

    (tmp_path / "op_host" / "arch22").mkdir(parents=True)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    (tmp_path / "op_kernel" / "arch35").mkdir(parents=True)
    save_pr_architecture_pin(tmp_path, ["arch35"])
    scanned = intake.scan_operator_directory(tmp_path)
    assert scanned["ok"] is True
    assert scanned.get("architecture") == "arch35"
    assert scanned.get("selected_by") == "pr_changed_files"
    assert not scanned.get("ask_question")
    assert "arch35" in scanned["suggested_command"]


def test_scan_operator_directory_unified_when_no_arch_dirs(tmp_path: Path):
    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_kernel").mkdir()
    scanned = intake.scan_operator_directory(tmp_path)
    assert scanned["ok"] is True
    assert scanned["architecture"] == "default"
    assert scanned["selected_by"] == "unified_implementation"
    assert not scanned.get("ask_question")
    assert scanned.get("error") != "ARCHITECTURE_NOT_FOUND"
    assert "default" in scanned["suggested_command"]


def test_start_intake_gate_unified_when_no_arch_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_kernel").mkdir()
    gate = intake.start_intake_gate(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="",
        project_explicit=True,
    )
    assert gate is None
    prep = intake.prepare_workflow_start(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="",
        project_explicit=True,
    )
    assert prep.get("ok") is True
    assert prep.get("architecture") == "default"
    rejected = intake.start_intake_gate(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="arch35",
        project_explicit=True,
    )
    assert rejected is not None
    assert rejected["reason_code"] == "ARCHITECTURE_NOT_IN_TREE"


def test_discover_uo_products_includes_default_slot(tmp_path: Path):
    product = tmp_path / ".ascendc-pilot" / "default" / "uo" / "toy.default.uo"
    product.parent.mkdir(parents=True)
    product.write_text("x", encoding="utf-8")
    found = intake.discover_uo_products(tmp_path)
    assert len(found) == 1
    assert found[0]["architecture"] == "default"
    assert found[0]["op_name"] == "toy"


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
    assert "pilot_run" in gate["suggested_command"]
    assert "architecture" in gate["suggested_command"]


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


def test_start_intake_gate_accepts_arch920r1_alias(tmp_path: Path):
    (tmp_path / "op_host" / "arch-920r1").mkdir(parents=True)
    gate = intake.start_intake_gate(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="arch920r1",
        project_explicit=True,
    )
    assert gate is None
    prep = intake.prepare_workflow_start(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="arch920r1",
        project_explicit=True,
    )
    assert prep.get("ok") is True
    assert prep.get("architecture") == "arch-920r1"


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
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
    intake.write_last_project_cache(op)
    monkeypatch.chdir(parent)
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    assert intake.default_cli_project() == op.resolve()


def test_default_cli_project_falls_through_non_operator_explicit(
    tmp_path: Path, monkeypatch
):
    shell = tmp_path / "flash_attention_score_grad"
    shell.mkdir()
    (shell / ".ascendc-pilot").mkdir()
    real = tmp_path / "real_op"
    real.mkdir()
    (real / "op_kernel").mkdir()
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(real))
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    assert intake.default_cli_project(shell) == real.resolve()
    assert intake.default_cli_project(real) == real.resolve()


def test_default_cli_project_bare_name_uses_cache_not_missing_relative(
    tmp_path: Path, monkeypatch
):
    op = tmp_path / "flash_attention_score_grad"
    op.mkdir()
    (op / "op_kernel").mkdir()
    cwd = tmp_path / "not_an_op"
    cwd.mkdir()
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
    intake.write_last_project_cache(op)
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    assert intake.default_cli_project("flash_attention_score_grad") == op.resolve()
    assert intake.default_cli_project() == op.resolve()


def test_default_cli_project_ignores_path_under_pilot_checkout(
    tmp_path: Path, monkeypatch
):
    op = tmp_path / "flash_attention_score_grad"
    op.mkdir()
    (op / "op_host").mkdir()
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
    intake.write_last_project_cache(op)
    harness = pilot_checkout_root()
    monkeypatch.chdir(harness)
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    ghost = harness / "flash_attention_score_grad"
    assert intake.default_cli_project("flash_attention_score_grad") == op.resolve()
    assert intake.default_cli_project(ghost) == op.resolve()
    assert intake.default_cli_project(harness) == op.resolve()
    assert intake.default_cli_project(harness, allow_last_project=False) == harness.resolve()


def test_cli_start_auto_empty_host_does_not_land_control_plane(tmp_path: Path, monkeypatch, capsys):
    op = tmp_path / "old_op"
    op.mkdir()
    (op / "op_host").mkdir()
    host = tmp_path / "host_cwd"
    host.mkdir()
    cache = tmp_path / "last-project"
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", cache)
    intake.write_last_project_cache(op)
    monkeypatch.chdir(host)
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    code = main(["start", "auto", "--project", str(host), "--intent", "生成用例"])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out.get("needs_human_decision") is True
    assert out.get("reason_code") == "OPERATOR_WORKDIR_REQUIRED"
    assert not (host / ".ascendc-pilot").exists()
    assert cache.read_text(encoding="utf-8").strip() == str(op.resolve())


def test_default_cli_project_keeps_explicit_operator(tmp_path: Path, monkeypatch):
    a = tmp_path / "op_a"
    b = tmp_path / "op_b"
    for p in (a, b):
        p.mkdir()
        (p / "op_host").mkdir()
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
    intake.write_last_project_cache(a)
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    assert intake.default_cli_project(b) == b.resolve()


def test_default_cli_project_keeps_existing_non_operator_without_env(
    tmp_path: Path, monkeypatch
):
    other = tmp_path / "not_op"
    other.mkdir()
    op = tmp_path / "real"
    op.mkdir()
    (op / "op_host").mkdir()
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
    intake.write_last_project_cache(op)
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    assert intake.default_cli_project(other) == other.resolve()


def test_cli_start_asks_for_architecture(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    code = main(["start", "uo-init", "--project", str(tmp_path)])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["needs_human_decision"] is True
    assert out["reason_code"] == "ARCHITECTURE_REQUIRED"
    assert out["ask_question"]["options"][0]["label"] == "arch35"
    assert "pilot_run" in out["suggested_command"]
    assert "architecture" in out["suggested_command"]


def test_cli_start_with_project_and_arch(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
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


def test_cli_prepare_rejects_pilot_checkout(capsys, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    harness = pilot_checkout_root()
    code = main(["run-action", "prepare", "--project", str(harness)])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["reason_code"] == "OPERATOR_PROJECT_REQUIRED"


def test_cli_start_auto_allows_non_operator(tmp_path: Path, capsys):
    code = main(
        [
            "start",
            "auto",
            "--project",
            str(tmp_path),
            "--intent",
            "帮我给这个 PR 生成针对 case",
            "--force-new",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert out.get("reason_code") != "OPERATOR_PROJECT_REQUIRED"
    assert code == 0 or out.get("ok") is True or out.get("needs_human_decision")
    assert not (tmp_path / ".ascendc-pilot").exists()


def test_cli_run_action_auto_skips_operator_assert(tmp_path: Path, capsys):
    start = main(
        [
            "start",
            "auto",
            "--project",
            str(tmp_path),
            "--intent",
            "生成 case",
            "--force-new",
        ]
    )
    start_out = json.loads(capsys.readouterr().out)
    assert start_out.get("reason_code") != "OPERATOR_PROJECT_REQUIRED"
    if start != 0 and not start_out.get("ok"):
        assert not (tmp_path / ".ascendc-pilot").exists()
        return
    code = main(["run-action", "auto", "--project", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert out.get("reason_code") != "OPERATOR_PROJECT_REQUIRED"
    assert code != 2 or out.get("reason_code") != "OPERATOR_PROJECT_REQUIRED"


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


def test_cli_uo_query_alias_with_project_flag_hints_uo_query(capsys):
    code = main(["uo", "query", "--project", "xxx"])
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"] == "use_uo_query"
    assert "请使用: acp uo-query" in out["message_zh"]


def test_cli_removed_uo_bypass_commands_use_uo_query(capsys):
    for argv in (
        ["uo", "impact", "x"],
        ["uo", "search", "SplitAxis"],
        ["uo", "locate", "SetTiling"],
        ["uo", "explain-host-value", "hv1"],
    ):
        code = main(argv)
        assert code == 2, argv
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False, argv
        assert out["error"] == "use_uo_query", argv
        assert "四种形态" in out["message_zh"], argv


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


def test_cli_uo_query_mode_removed_does_not_list_old_modes(tmp_path: Path, capsys):
    code = main(
        [
            "uo-query",
            "--project",
            str(tmp_path),
            "--mode",
            "locate",
            "s1Inner",
        ]
    )
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "mode_removed"
    blob = json.dumps(out)
    for stale in ("kernel_launch", "template_match", "tiling_key", "compile", "locate"):
        assert stale not in blob
    assert "Dim=V" in blob or "identifier" in blob.lower() or "标识符" in blob


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


def test_architecture_from_intent_unique_and_ambiguous():
    assert intake.architecture_from_intent("对 arch35 建库", ["arch22", "arch35"]) == "arch35"
    assert intake.architecture_from_intent("ARCH35", ["arch35"]) == "arch35"
    assert intake.architecture_from_intent("arch35 和 arch22", ["arch22", "arch35"]) == ""
    assert intake.architecture_from_intent("arch36 建库", ["arch35"]) == ""
    assert intake.architecture_from_intent("", ["arch35"]) == ""
    assert (
        intake.architecture_from_intent("arch920r1 建库", ["arch-920r1", "arch35"])
        == "arch-920r1"
    )
    assert intake.architecture_from_intent("DAV_9201", ["arch-920r1"]) == "arch-920r1"


def test_prepare_workflow_start_adopts_unique_arch_from_intent(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    (tmp_path / "op_host" / "arch22").mkdir(parents=True)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    prep = intake.prepare_workflow_start(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="",
        project_explicit=True,
        intent="帮我为这个算子的 arch35 建库",
    )
    assert prep.get("ok") is True
    assert prep.get("architecture") == "arch35"
    assert prep.get("resolved_from") == "intent"
    assert "arch35" in str(prep.get("message_zh") or "")


def test_prepare_workflow_start_still_asks_when_intent_names_two_archs(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    (tmp_path / "op_host" / "arch22").mkdir(parents=True)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    prep = intake.prepare_workflow_start(
        project=tmp_path,
        workflow_id="uo-init",
        architecture="",
        project_explicit=True,
        intent="arch22 还是 arch35？",
    )
    assert prep.get("ok") is False
    assert prep.get("reason_code") == "ARCHITECTURE_REQUIRED"


def test_cli_start_adopts_unique_arch_from_intent(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    monkeypatch.setattr(intake, "LAST_PROJECT_CACHE", tmp_path / "last-project")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    code = main(
        [
            "start",
            "uo-init",
            "--project",
            str(tmp_path),
            "--intent",
            "对 arch35 建库",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out.get("architecture") == "arch35"
    assert out.get("architecture_resolved_from") == "intent"
    assert "按 arch35 启动" in str(out.get("message_zh") or "")


def test_cli_start_rejects_uo_query(tmp_path: Path, capsys):
    (tmp_path / "op_host").mkdir()
    code = main(["start", "uo-query", "--project", str(tmp_path)])
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out.get("ok") is False
    assert out.get("error") == "UO_QUERY_NOT_HOST_DRIVEN"
    assert "pilot_cli" in str(out.get("message_zh") or "")


def test_cli_inspect_failure_has_top_level_message_zh(tmp_path: Path, capsys):
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import load_state, save_state, start_workflow

    (tmp_path / "op_host").mkdir()
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    st = load_state(tmp_path) or {}
    st["last_failure"] = {
        "error": "CANN_ENV_NOT_READY",
        "message_zh": "CANN 环境未就绪，请设置 UO_CANN_ROOT。",
    }
    save_state(tmp_path, st)
    code = main(["inspect-failure", "--project", str(tmp_path)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out.get("ok") is True
    assert "CANN" in str(out.get("message_zh") or "")


def test_prepare_pins_operator_from_pr_then_uo_gate(tmp_path: Path, monkeypatch):
    import sys

    workspace = tmp_path / "opencode-ws"
    workspace.mkdir()
    op = tmp_path / "FlashAttention"
    (op / "op_host" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import pr_workspace as pw  # noqa: WPS433

    monkeypatch.setattr(
        pw,
        "acquire_pull_request",
        lambda *a, **k: {
            "ok": True,
            "operator_roots": [str(op)],
            "worktree_head": str(op),
            "changed_files": ["op_host/arch35/a.cpp"],
            "operator_targets": [
                {
                    "operator_root": str(op),
                    "operator_name": "FlashAttention",
                    "architecture": "arch35",
                }
            ],
            "changeset": {"changed_files": ["op_host/arch35/a.cpp"]},
        },
    )
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    prep = intake.prepare_workflow_start(
        project=workspace,
        workflow_id="ce-review",
        intent="分析这个 PR https://github.com/org/repo/pull/12",
        project_explicit=True,
    )
    assert Path(str(prep.get("project") or "")).resolve() == op.resolve()
    assert prep.get("reason_code") == "UO_PRODUCT_REQUIRED"


def test_prepare_without_pr_still_requires_operator(tmp_path: Path):
    workspace = tmp_path / "opencode-ws"
    workspace.mkdir()
    prep = intake.prepare_workflow_start(
        project=workspace,
        workflow_id="uo-init",
        intent="帮我建库",
        project_explicit=True,
    )
    assert prep.get("ok") is False
    assert prep.get("reason_code") == "OPERATOR_PROJECT_REQUIRED"


def test_prepare_without_url_does_not_clone(tmp_path: Path, monkeypatch):
    import sys

    workspace = tmp_path / "opencode-ws"
    workspace.mkdir()
    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import pr_workspace as pw  # noqa: WPS433

    def boom(*_a, **_k):
        raise AssertionError("must not clone without a PR URL")

    monkeypatch.setattr(pw, "acquire_pull_request", boom)
    prep = intake.prepare_workflow_start(
        project=workspace,
        workflow_id="ce-review",
        intent="审查当前工作区的本地 diff",
        project_explicit=True,
    )
    assert prep.get("ok") is False
    assert prep.get("reason_code") == "OPERATOR_PROJECT_REQUIRED"


def test_prepare_pr_on_pilot_checkout_forbidden():
    harness = pilot_checkout_root()
    prep = intake.prepare_workflow_start(
        project=harness,
        workflow_id="ce-review",
        intent="分析 https://github.com/org/repo/pull/12",
        project_explicit=True,
    )
    assert prep.get("ok") is False
    assert prep.get("reason_code") == "PILOT_CHECKOUT_FORBIDDEN"
    opts = (prep.get("ask_question") or {}).get("options") or []
    assert len(opts) >= 2
    assert all(o.get("label") and o.get("value") for o in opts)
