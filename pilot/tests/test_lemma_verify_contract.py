"""lemma_verify must have a registered output contract (finalize fail-closed)."""

from __future__ import annotations

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
from ascendc_pilot.workflows import action_by_id


def test_lemma_verify_has_output_contract() -> None:
    action = action_by_id("tg-solve", "lemma_verify")
    assert action is not None
    cid = str(action.get("output_contract_id") or "")
    assert cid == "lemma-verify-v1"
    paths = OUTPUT_CONTRACT_PATHS.get(cid) or []
    joined = ",".join(paths)
    assert "lemma_verify/verify.yaml" in joined
    assert "tg/closure/lemmas/verify.yaml" in joined
