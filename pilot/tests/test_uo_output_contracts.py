"""UO output contracts must match engine/gate product paths (no legacy stubs)."""

from __future__ import annotations

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_NONEMPTY_GLOBS, OUTPUT_CONTRACT_PATHS


def _joined(contract_id: str) -> str:
    return ",".join(OUTPUT_CONTRACT_PATHS[contract_id])


def test_uo_init_contracts_aligned() -> None:
    assert "uo/summary" not in _joined("extract-plan-v1")
    assert "uo/ir/extract_plan.yaml" in _joined("extract-plan-v1")
    assert "uo/ir/extract_plan_candidates.yaml" in _joined("extract-plan-v1")

    assert _joined("kb-review-v1") == "uo/review/kb_product_review.yaml"
    assert "kb_review.yaml" not in _joined("kb-review-v1")

    assert "uo/ir/input_derivable_patch.yaml" in _joined("input-derivable-patch-v1")
    assert "key_shape_resolve" not in _joined("input-derivable-patch-v1")

    assert "uo/ir/entrypoint_graph.yaml" in _joined("rebuild-ledger-v1")
    assert "uo/ir/operator_graph.yaml" in _joined("rebuild-ledger-v1")

    assert "uo/ir/entrypoint_graph.yaml" in _joined("recheck-closure-v1")
    assert "uo/ir/llm_tasks.yaml" in _joined("recheck-closure-v1")


def test_uo_update_contracts_aligned() -> None:
    assert "update-plan-v1" in OUTPUT_CONTRACT_PATHS
    assert "update-apply-v1" in OUTPUT_CONTRACT_PATHS
    assert _joined("change-detect-v1") == "uo/diff/change_set.yaml"
    assert "change_detect.yaml" not in _joined("change-detect-v1")
    assert "uo/summary/update_plan.yaml" in _joined("update-plan-v1")
    assert "uo/runs/*/update/receipt.yaml" in _joined("update-apply-v1")
    assert "uo/diff/index.yaml" in _joined("diff-summary-v1")
    assert "diff_summary.md" not in _joined("diff-summary-v1")
    for cid in ("change-detect-v1", "update-plan-v1", "update-apply-v1", "diff-summary-v1"):
        assert cid in OUTPUT_CONTRACT_NONEMPTY_GLOBS


def test_uo_query_review_ready_contracts_not_bare_dirs() -> None:
    assert _joined("kb-answer-v1") == "uo/manifest.yaml,uo/checks/integrity.yaml"
    assert "runs" not in OUTPUT_CONTRACT_PATHS["kb-answer-v1"]
    assert "uo/review/index.yaml" in _joined("code-review-v1")
    assert "uo/review/functional_report.yaml" in _joined("code-review-v1")
    assert "uo/review/bug_report.yaml" in _joined("code-review-v1")
    assert _joined("uo-ready-v1") == "uo/manifest.yaml,uo/checks/integrity.yaml"
    assert OUTPUT_CONTRACT_PATHS["uo-ready-v1"] != ["uo"]


def test_no_legacy_uo_summary_stub_contracts() -> None:
    blob = ",".join(p for paths in OUTPUT_CONTRACT_PATHS.values() for p in paths)
    assert "change_detect.yaml" not in blob
    assert "diff_summary.md" not in blob
    assert "kb_review.yaml" not in blob
    assert "uo/summary/scope_confirmed.yaml" not in blob
