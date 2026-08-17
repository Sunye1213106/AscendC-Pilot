"""UO output contracts must match engine/gate product paths (no legacy stubs)."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_NONEMPTY_GLOBS, OUTPUT_CONTRACT_PATHS


def _joined(contract_id: str) -> str:
    return ",".join(OUTPUT_CONTRACT_PATHS[contract_id])


def test_uo_init_contracts_aligned() -> None:
    assert "uo-prepare-v1" in OUTPUT_CONTRACT_PATHS
    assert "uo-extract-v1" in OUTPUT_CONTRACT_PATHS
    assert "uo-analyze-v1" in OUTPUT_CONTRACT_PATHS
    assert "uo/*.uo" in OUTPUT_CONTRACT_PATHS["uo-commit-v1"]
    assert OUTPUT_CONTRACT_PATHS["uo-verify-v1"] == [
        "uo/checks/integrity.yaml",
        "uo/checks/quality.yaml",
    ]
    assert "input-derivable-patch-v1" not in OUTPUT_CONTRACT_PATHS
    assert "key-triage-v1" not in OUTPUT_CONTRACT_PATHS
    assert "extract-plan-v1" not in OUTPUT_CONTRACT_PATHS


def test_uo_update_contracts_aligned() -> None:
    assert "update-plan-v1" in OUTPUT_CONTRACT_PATHS
    assert "update-apply-v1" in OUTPUT_CONTRACT_PATHS
    assert _joined("change-detect-v1") == "uo/diff/change_set.yaml"
    assert "uo/summary/update_plan.yaml" in _joined("update-plan-v1")
    assert "uo/runs/{run_id}/update/receipt.yaml" in _joined("update-apply-v1")
    assert "uo/diff/index.yaml" in _joined("diff-summary-v1")
    for cid in ("change-detect-v1", "update-plan-v1", "update-apply-v1", "diff-summary-v1"):
        assert cid in OUTPUT_CONTRACT_NONEMPTY_GLOBS


def test_uo_update_write_paths_cover_contracts() -> None:
    from ascendc_pilot.agents_registry import path_matches_scope
    from ascendc_pilot.ownership import ACTION_WRITE_PATHS
    from ascendc_pilot.workflows import WORKFLOWS

    mapping = {
        "detect_changes": "change-detect-v1",
        "plan_update": "update-plan-v1",
        "apply_update": "update-apply-v1",
        "export_integrity": "integrity-v1",
        "diff_summary": "diff-summary-v1",
        "diff_only": "diff-summary-v1",
    }
    actions = {a["id"]: a for a in WORKFLOWS["uo-update"]["actions"]}
    for aid, cid in mapping.items():
        writes = list(actions[aid].get("allowed_write_paths") or [])
        assert writes == ACTION_WRITE_PATHS["uo-update"][aid], aid
        for rel in OUTPUT_CONTRACT_PATHS[cid]:
            assert path_matches_scope(rel, writes), (aid, rel, writes)


def test_detect_changes_outputs_writable(tmp_path) -> None:
    from ascendc_pilot.actions.runtime import _check_required_outputs_writable, prepare_action
    from ascendc_pilot.paths import ensure_agent_layout, uo_root
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.workflows import WORKFLOWS

    action = next(a for a in WORKFLOWS["uo-update"]["actions"] if a["id"] == "detect_changes")
    writes = list(action.get("allowed_write_paths") or [])
    ok = _check_required_outputs_writable(
        workflow_id="uo-update",
        action_id="detect_changes",
        actor_id="deterministic-uo-engine",
        contract_id="change-detect-v1",
        output_mode="direct",
        write_paths=writes,
        run_id="r1",
        project_root=tmp_path,
    )
    assert ok.get("ok") is True, ok

    blocked = _check_required_outputs_writable(
        workflow_id="uo-update",
        action_id="detect_changes",
        actor_id="deterministic-uo-engine",
        contract_id="change-detect-v1",
        output_mode="direct",
        write_paths=[],
        run_id="r1",
        project_root=tmp_path,
    )
    assert blocked.get("error") == "OUTPUT_NOT_WRITABLE"

    ensure_agent_layout(tmp_path, arch="arch35")
    uo = uo_root(tmp_path, arch="arch35")
    (uo / "Toy.arch35.uo").write_bytes(b"SQLite format 3\x00")
    (uo / "manifest.yaml").write_text(
        "op_name: Toy\narchitecture: arch35\n",
        encoding="utf-8",
    )
    start_workflow(tmp_path, "uo-update", architecture="arch35", op_name="Toy")
    prepared = prepare_action(tmp_path, "detect_changes")
    assert prepared.get("ok") is True, prepared
    assert prepared.get("error") != "OUTPUT_NOT_WRITABLE"


def test_uo_query_review_ready_contracts_not_bare_dirs() -> None:
    # kb-answer is the Action payload under lease, not a uo/checks readiness gate.
    assert _joined("kb-answer-v1") == "runs/{run_id}/actions/kb_lookup/answer.yaml"
    assert "ce/review/index.yaml" in _joined("code-review-v1")
    assert _joined("uo-ready-v1") == "runs/{run_id}/receipts/uo_ready.yaml"
    assert "z" + "3-solve-v1" not in OUTPUT_CONTRACT_PATHS
    assert "cover-confirm-v1" not in OUTPUT_CONTRACT_PATHS
    assert "csv-contract-v1" not in OUTPUT_CONTRACT_PATHS


def test_no_legacy_uo_summary_stub_contracts() -> None:
    blob = ",".join(p for paths in OUTPUT_CONTRACT_PATHS.values() for p in paths)
    assert "change_detect.yaml" not in blob
    assert "diff_summary.md" not in blob
    assert "kb_review.yaml" not in blob


def test_no_bare_single_segment_contracts_without_nonempty() -> None:
    bare_ok_with_nonempty = {"plan-build-v1"}
    for cid, paths in OUTPUT_CONTRACT_PATHS.items():
        for rel in paths:
            if "/" not in rel and "*" not in rel:
                assert False, f"{cid} still uses bare segment {rel!r}"
            if rel in {"uo", "tg"} or rel.endswith("/"):
                assert False, f"{cid} uses bare/trailing-slash path {rel!r}"
            looks_dir = "*" not in rel and not Path(rel).suffix
            if looks_dir and cid not in bare_ok_with_nonempty:
                assert cid in OUTPUT_CONTRACT_NONEMPTY_GLOBS, (
                    f"{cid} path {rel!r} is directory-only without NONEMPTY_GLOBS"
                )
    for cid in bare_ok_with_nonempty:
        assert cid in OUTPUT_CONTRACT_NONEMPTY_GLOBS
