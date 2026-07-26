from __future__ import annotations

from ascendc_pilot.recovery import (
    KERNEL_DISPATCH_REWORK,
    recoveries_for_closure_gaps,
    resolve_recovery,
)


def test_kernel_dispatch_recovery_reruns_deterministic_entrypoint_stage() -> None:
    resolved = resolve_recovery(
        KERNEL_DISPATCH_REWORK,
        workflow_id="uo-init",
        current_phase="extract",
    )
    assert resolved["ok"] is True
    recovery = resolved["recovery"]
    if recovery["type"] == "transition":
        assert recovery["next_action"] == "detect_score_pre"
    else:
        assert recovery["action_id"] == "detect_score_pre"


def test_kernel_only_no_progress_does_not_add_llm_loop() -> None:
    payload = recoveries_for_closure_gaps(
        host_closed=True,
        kernel_closed=False,
        blocking_gap_count=0,
        unconsumed_patch_count=0,
        no_progress=True,
        workflow_id="uo-init",
        current_phase="extract",
    )
    assert payload["reason_codes"] == [KERNEL_DISPATCH_REWORK]
    assert "adjudicate_llm_tasks" not in payload["recovery_actions"]
