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
