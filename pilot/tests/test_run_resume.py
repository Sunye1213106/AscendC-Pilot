"""Interrupted-run continue/reinit behavior for public workflow actions."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.cli import main as acp_main
from ascendc_pilot.paths import agent_root, ce_root, runs_root, state_root, tg_root, uo_root
from ascendc_pilot.run_resume import (
    action_owned_artifacts,
    apply_resume_decision,
    build_run_resume_summary,
    needs_resume_decision,
    normalize_decision,
    resolve_start_architecture,
)
from ascendc_pilot.state import load_state, save_state, start_workflow


def _make_multi_arch_op(root: Path) -> None:
    for arch in ("arch22", "arch35"):
        (root / "op_host" / arch).mkdir(parents=True, exist_ok=True)
        (root / "op_kernel" / arch).mkdir(parents=True, exist_ok=True)


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_start_requires_askquestion_when_multiple_archs(tmp_path: Path, capsys, monkeypatch) -> None:
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)
    _make_multi_arch_op(tmp_path)
    code = acp_main(["start", "uo-init", "--project", str(tmp_path)])
    assert code == 2
    output = capsys.readouterr().out
    assert "ARCHITECTURE_REQUIRED" in output
    assert "ask_question" in output
    assert "arch22" in output
    assert "arch35" in output
    state = load_state(tmp_path) or {}
    assert not state.get("run_id")


def test_start_with_explicit_architecture_when_multiple_archs(tmp_path: Path, capsys) -> None:
    _make_multi_arch_op(tmp_path)
    code = acp_main(
        ["start", "uo-init", "--project", str(tmp_path), "--architecture", "arch22"]
    )
    assert code == 0
    state = load_state(tmp_path)
    assert state is not None
    assert state["architecture"] == "arch22"
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is True
    assert payload.get("fresh_start") is True
    assert payload.get("run_id")


def test_force_new_start_on_virgin_multi_arch(tmp_path: Path, capsys, monkeypatch) -> None:
    """ses_0022: --force-new --architecture on a project with no .ascendc-pilot must start."""
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    _make_multi_arch_op(tmp_path)
    code = acp_main(
        [
            "start",
            "uo-init",
            "--project",
            str(tmp_path),
            "--architecture",
            "arch35",
            "--force-new",
            "--intent",
            "建立知识库",
        ]
    )
    assert code == 0
    state = load_state(tmp_path)
    assert state["architecture"] == "arch35"
    assert state["workflow_id"] == "uo-init"
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is True
    assert payload.get("run_id")


def test_apply_reinit_with_architecture_on_virgin_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    _make_multi_arch_op(tmp_path)
    result = apply_resume_decision(
        tmp_path,
        "uo-init",
        "reinit",
        start_kwargs={"architecture": "arch35"},
        require_receipt=False,
    )
    assert result.get("ok") is True
    assert load_state(tmp_path)["architecture"] == "arch35"


def test_build_run_resume_summary_without_arch_does_not_raise(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("UO_ARCH", raising=False)
    monkeypatch.delenv("ASCENDC_ARCH", raising=False)
    _make_multi_arch_op(tmp_path)
    summary = build_run_resume_summary(tmp_path, workflow_id="uo-init")
    assert summary["has_existing_run"] is False
    assert "ask_question" in summary
    assert "commands" in summary


def test_resolve_start_architecture_pr_pin_unique_skips_ask(tmp_path: Path) -> None:
    from ascendc_pilot.run_resume import save_pr_architecture_pin

    _make_multi_arch_op(tmp_path)
    save_pr_architecture_pin(tmp_path, ["arch35"])
    result = resolve_start_architecture(tmp_path, "", workflow_id="uo-init")
    assert result.get("ok") is True
    assert result.get("architecture") == "arch35"
    assert result.get("selected_by") == "pr_changed_files"
    assert result.get("needs_human_decision") is not True


def test_resolve_start_architecture_sole_arch_auto_selects(tmp_path: Path) -> None:
    (tmp_path / "op_host" / "arch22").mkdir(parents=True)
    result = resolve_start_architecture(tmp_path, "", workflow_id="uo-init")
    assert result["ok"] is True
    assert result["architecture"] == "arch22"
    assert result["selected_by"] == "sole_arch"


def test_resolve_start_architecture_unified_when_no_arch_dirs(tmp_path: Path) -> None:
    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_kernel").mkdir()
    result = resolve_start_architecture(tmp_path, "", workflow_id="uo-init")
    assert result["ok"] is True
    assert result["architecture"] == "default"
    assert result["selected_by"] == "unified_implementation"
    assert result.get("needs_human_decision") is not True
    # Explicit slot is still accepted (reinit / already-pinned product).
    explicit_variant = resolve_start_architecture(tmp_path, "arch35", workflow_id="uo-init")
    assert explicit_variant["ok"] is True
    assert explicit_variant["architecture"] == "arch35"
    explicit = resolve_start_architecture(tmp_path, "default", workflow_id="uo-init")
    assert explicit["ok"] is True
    assert explicit["architecture"] == "default"


def test_reinit_requires_architecture_when_multiple_archs(tmp_path: Path) -> None:
    _make_multi_arch_op(tmp_path)
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    result = apply_resume_decision(
        tmp_path, "uo-init", "reinit", start_kwargs={}, require_receipt=False
    )
    assert result.get("ok") is False
    assert result.get("needs_human_decision") is True
    assert result.get("error") == "ARCHITECTURE_NEEDS_DECISION"
    # Must not wipe / restart before architecture is chosen.
    assert load_state(tmp_path)["architecture"] == "arch35"


def test_answer_then_start_decision_reinit(tmp_path: Path, capsys) -> None:
    """ses_0072: after 删除重开, `acp start --decision reinit` must actually start."""
    import json

    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    (tmp_path / "op_kernel" / "arch35").mkdir(parents=True)
    assert (
        acp_main(
            ["start", "uo-init", "--project", str(tmp_path), "--architecture", "arch35"]
        )
        == 0
    )
    old_run = load_state(tmp_path)["run_id"]
    capsys.readouterr()

    code = acp_main(
        ["start", "uo-init", "--project", str(tmp_path), "--architecture", "arch35"]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("error") == "EXISTING_RUN_NEEDS_DECISION"
    opts = payload.get("ask_question", {}).get("options") or []
    assert any(o.get("value") == "reinit" for o in opts)
    rid = payload["human_interaction_request"]["request_id"]

    assert (
        acp_main(
            ["answer", "--project", str(tmp_path), "--request-id", rid, "--value", "删除重开"]
        )
        == 0
    )
    from ascendc_pilot.human_interaction import pending_path

    pending = yaml.safe_load(pending_path(tmp_path).read_text(encoding="utf-8"))
    assert pending.get("status") == "answered"
    assert pending.get("answered_value") == "reinit"
    capsys.readouterr()

    code = acp_main(
        [
            "start",
            "uo-init",
            "--project",
            str(tmp_path),
            "--architecture",
            "arch35",
            "--decision",
            "reinit",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out.get("ok") is True
    assert out.get("fresh_start") is True
    assert load_state(tmp_path)["run_id"] != old_run


def test_normalize_decision_labels() -> None:
    assert normalize_decision("continue") == "continue"
    assert normalize_decision("继续上次 (Recommended)") == "continue"
    assert normalize_decision("开始 uo-query (Recommended)") == "continue"
    assert normalize_decision("删除重开") == "reinit"
    assert normalize_decision("stay") == "stay"
    assert normalize_decision("继续当前 tg-init (Recommended)") == "stay"
    assert normalize_decision("bogus") is None


def test_start_requires_askquestion_when_running(tmp_path: Path, capsys) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    assert needs_resume_decision(tmp_path, "uo-init") is True
    code = acp_main(["start", "uo-init", "--project", str(tmp_path)])
    assert code == 2
    output = capsys.readouterr().out
    assert "EXISTING_RUN_NEEDS_DECISION" in output
    assert "ask_question" in output
    assert "继续上次" in output


def test_start_uo_init_with_ready_codemap_is_not_a_lock(tmp_path: Path, capsys) -> None:
    import json

    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    (tmp_path / "op_kernel" / "arch35").mkdir(parents=True)
    product = agent_root(tmp_path, arch="arch35") / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    assert needs_resume_decision(tmp_path, "uo-init") is True
    code = acp_main(
        ["start", "uo-init", "--project", str(tmp_path), "--architecture", "arch35"]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("error") == "UO_ALREADY_READY"
    msg = str(payload.get("message_zh") or "")
    assert "锁已释放" in msg
    assert "未完成" not in msg
    opts = payload.get("ask_question", {}).get("options") or []
    assert opts and opts[0].get("value") == "query"
    assert any(o.get("value") == "reinit" for o in opts)


def test_decision_continue_resumes_same_run(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", architecture="arch35")
    result = apply_resume_decision(
        tmp_path, "uo-init", "continue", require_receipt=False
    )
    assert result["ok"] is True
    assert result.get("resumed") is True
    assert load_state(tmp_path)["run_id"] == state["run_id"]


def test_uo_init_reinit_wipes_current_uo_products_but_keeps_historical_runs(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", architecture="arch35")
    old_run_id = state["run_id"]
    legacy_uo = uo_root(tmp_path, arch="arch35")
    _write(legacy_uo / "manifest.yaml", {"op_name": "foo"})
    product = agent_root(tmp_path, arch="arch35") / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    cache_hit = legacy_uo / "cache" / "tu" / "src-hash.pkl"
    _write(cache_hit, "clang-tu-cache")
    historical = runs_root(tmp_path) / "historical-run-keep"
    _write(historical / "marker.yaml", {"keep": True})

    result = apply_resume_decision(
        tmp_path,
        "uo-init",
        "reinit",
        require_receipt=False,
        start_kwargs={"architecture": "arch35"},
    )
    assert result["ok"] is True
    assert result.get("fresh_start") is True
    assert not (legacy_uo / "manifest.yaml").is_file()
    assert not product.is_file()
    assert cache_hit.is_file()
    assert historical.is_dir()
    current = load_state(tmp_path)
    assert current["phase"] == "prepare"
    assert current["status"] == "running"
    assert current["run_id"] != old_run_id


def test_tg_reinit_preserves_committed_uo_product(tmp_path: Path) -> None:
    product = agent_root(tmp_path, arch="arch35") / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    tg = tg_root(tmp_path, arch="arch35")
    _write(tg / "init.yaml", {"schema": "tg-init/v1", "table_kind": "csv", "confirmed": False})

    start_workflow(tmp_path, "tg-init", architecture="arch35")
    result = apply_resume_decision(
        tmp_path,
        "tg-init",
        "reinit",
        require_receipt=False,
        start_kwargs={"architecture": "arch35"},
    )
    assert result["ok"] is True
    assert product.is_file()
    assert not (tg / "init.yaml").is_file()


def test_ce_reinit_keeps_uo_and_tg(tmp_path: Path) -> None:
    product = agent_root(tmp_path, arch="arch35") / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    tg = tg_root(tmp_path, arch="arch35")
    ce = ce_root(tmp_path, arch="arch35")
    _write(tg / "plan.md", "# plan\n")
    _write(ce / "plan" / "sync_plan.md", "# sync\n")

    start_workflow(tmp_path, "ce-review", architecture="arch35")
    result = apply_resume_decision(
        tmp_path,
        "ce-review",
        "reinit",
        require_receipt=False,
        start_kwargs={"architecture": "arch35"},
    )
    assert result["ok"] is True
    assert product.is_file()
    assert (tg / "plan.md").is_file()
    assert (ce / "plan" / "sync_plan.md").is_file()


def test_uo_update_reinit_keeps_committed_uo_product(tmp_path: Path) -> None:
    product = agent_root(tmp_path, arch="arch35") / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    uo = uo_root(tmp_path, arch="arch35")
    _write(uo / "diff" / "change_set.yaml", {"changes": [1]})
    _write(uo / "summary" / "update_plan.yaml", {"plan": "x"})

    start_workflow(tmp_path, "uo-update", architecture="arch35")
    result = apply_resume_decision(
        tmp_path,
        "uo-update",
        "reinit",
        require_receipt=False,
        start_kwargs={"architecture": "arch35"},
    )
    assert result["ok"] is True
    assert product.is_file()
    assert not (uo / "diff" / "change_set.yaml").is_file()
    assert not (uo / "summary" / "update_plan.yaml").is_file()


def test_summary_uses_public_actions_and_resume_hint(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    summary = build_run_resume_summary(tmp_path, workflow_id="uo-init")
    assert summary["has_existing_run"] is True
    public = {
        "prepare",
        "propose_include_heal",
        "heal_promote",
        "extract",
        "analyze",
        "commit",
        "verify",
    }
    artifact_ids = {str(item.get("action_id") or "") for item in summary["artifacts"]}
    assert artifact_ids
    assert artifact_ids.issubset(public)
    assert all(str(item.get("label_zh") or "").strip() for item in summary["artifacts"])
    assert "ask_question" in summary
    assert summary["resume_next_action"] in public


def test_ask_question_uses_current_workflow_name_for_tg_init(tmp_path: Path) -> None:
    start_workflow(tmp_path, "tg-init", architecture="arch35")
    summary = build_run_resume_summary(tmp_path, workflow_id="tg-init")
    question = summary["ask_question"]
    assert "tg-init" in question["header"] or "tg-init" in question["question"]


def test_owned_artifact_map_uses_public_uo_actions() -> None:
    owned = action_owned_artifacts("uo-init")
    for action_id in (
        "prepare",
        "propose_include_heal",
        "heal_promote",
        "extract",
        "analyze",
        "commit",
        "verify",
    ):
        assert action_id in owned
    for retired in (
        "derive_key_fields",
        "export_kb",
        "export_adapter_pack",
        "normalize_predicates",
        "resolve",
        "apply_gap_patch",
        "review",
    ):
        assert retired not in owned
    assert any("codemap_analyze_receipt" in path for path in owned["analyze"])
    assert any("unresolved.yaml" in path for path in owned["analyze"])
    assert not any("derive_key_fields_receipt" in path for path in owned["analyze"])
    assert owned["commit"] == ("uo/*.uo",)
    assert owned["verify"] == ("uo/checks/integrity.yaml", "uo/checks/quality.yaml")


def test_different_family_starts_in_parallel(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", architecture="arch35")
    continue_result = apply_resume_decision(
        tmp_path, "uo-init", "continue", require_receipt=False
    )
    assert continue_result["ok"] is True
    assert needs_resume_decision(tmp_path, "tg-init") is False
    tg = start_workflow(tmp_path, "tg-init", architecture="arch35")
    assert tg.get("ok") is True
    assert tg.get("fresh_start") is True
    uo_live = load_state(tmp_path, workflow_id="uo-init")
    tg_live = load_state(tmp_path, workflow_id="tg-init")
    assert uo_live["workflow_id"] == "uo-init"
    assert uo_live["run_id"] == state["run_id"]
    assert tg_live["workflow_id"] == "tg-init"
    assert tg_live["run_id"] != state["run_id"]


def test_same_family_cross_workflow_still_asks(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    assert needs_resume_decision(tmp_path, "uo-update") is True
    cross = apply_resume_decision(
        tmp_path,
        "uo-update",
        "continue",
        require_receipt=False,
        start_kwargs={"architecture": "arch35"},
    )
    assert cross["ok"] is True
    assert cross.get("switched_from") == "uo-init"
    live = load_state(tmp_path, workflow_id="uo-update")
    assert live["workflow_id"] == "uo-update"


def test_continue_scrubs_failed_analyze_owned_products(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="analyze", force_phase=True, architecture="arch35")
    run_id = state["run_id"]
    uo = uo_root(tmp_path, arch="arch35")
    _write(uo / "ir" / "codemap_analyze_receipt.yaml", {"ok": True})
    _write(uo / "ir" / "unresolved.yaml", {"blockers": ["x"]})
    # Retired products are intentionally not action-owned anymore. They are not
    # consumed by structural analyze/commit and resume must not resurrect their
    # old authority merely to scrub them.
    _write(uo / "ir" / "derive_key_fields_receipt.yaml", {"legacy": True})
    _write(uo / "ir" / "host_extract_receipt.yaml", {"keep": True})
    _write(
        state_root(tmp_path, arch="arch35") / "active_action.yaml",
        {
            "version": 1,
            "run_id": run_id,
            "workflow_id": "uo-init",
            "phase": "analyze",
            "action_id": "analyze",
            "status": "finalize_failed",
        },
    )
    _write(
        runs_root(tmp_path, arch="arch35") / run_id / "actions" / "analyze" / "session.yaml",
        {"status": "finalize_failed", "action_id": "analyze", "run_id": run_id},
    )
    state["status"] = "rework_required"
    save_state(tmp_path, state)

    result = apply_resume_decision(
        tmp_path, "uo-init", "continue", require_receipt=False
    )
    assert result["ok"] is True
    scrubbed = set((result.get("resume_scrub") or {}).get("scrubbed_actions") or [])
    assert "analyze" in scrubbed
    assert not (uo / "ir" / "codemap_analyze_receipt.yaml").is_file()
    assert not (uo / "ir" / "unresolved.yaml").is_file()
    assert (uo / "ir" / "derive_key_fields_receipt.yaml").is_file()
    assert (uo / "ir" / "host_extract_receipt.yaml").is_file()
    assert not (state_root(tmp_path, arch="arch35") / "active_action.yaml").is_file()
    assert load_state(tmp_path)["status"] == "running"


def test_continue_scrubs_failed_verify_session_marker(tmp_path: Path) -> None:
    """Continue scrub clears the failed Action session for public verify."""
    state = start_workflow(tmp_path, "uo-init", phase="verify", force_phase=True, architecture="arch35")
    run_id = state["run_id"]
    session = runs_root(tmp_path, arch="arch35") / run_id / "actions" / "verify" / "session.yaml"
    _write(session, {"status": "finalize_failed", "action_id": "verify", "run_id": run_id})
    _write(
        state_root(tmp_path, arch="arch35") / "active_action.yaml",
        {
            "run_id": run_id,
            "workflow_id": "uo-init",
            "phase": "verify",
            "action_id": "verify",
            "status": "finalize_failed",
        },
    )
    state["status"] = "rework_required"
    save_state(tmp_path, state)

    result = apply_resume_decision(
        tmp_path, "uo-init", "continue", require_receipt=False
    )
    assert result["ok"] is True
    scrubbed = set((result.get("resume_scrub") or {}).get("scrubbed_actions") or [])
    assert "verify" in scrubbed
    assert not (state_root(tmp_path, arch="arch35") / "active_action.yaml").is_file()
    assert load_state(tmp_path)["status"] == "running"


def test_tg_family_conflict_summary_uses_active_next_hint(tmp_path: Path) -> None:
    start_workflow(tmp_path, "tg-init", architecture="arch35")
    summary = build_run_resume_summary(tmp_path, workflow_id="tg-plan")
    assert summary.get("cross_workflow")
    assert summary.get("workflow_id") == "tg-init"
    assert summary.get("requested_workflow_id") == "tg-plan"
    nxt = str(summary.get("resume_next_action") or "")
    assert nxt != "plan_promote"
    assert "继续时下一步: plan_promote" not in str(summary.get("summary_text_zh") or "")
    opts = (summary.get("ask_question") or {}).get("options") or []
    assert opts and opts[0].get("value") == "stay"
    assert any(o.get("value") == "continue" for o in opts)


def test_stay_resumes_occupying_workflow(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "tg-init", architecture="arch35")
    out = apply_resume_decision(
        tmp_path,
        "tg-plan",
        "stay",
        require_receipt=False,
        start_kwargs={"architecture": "arch35"},
    )
    assert out.get("ok") is True
    assert not out.get("switched_from")
    live = load_state(tmp_path)
    assert live["workflow_id"] == "tg-init"
    assert live["run_id"] == state["run_id"]
