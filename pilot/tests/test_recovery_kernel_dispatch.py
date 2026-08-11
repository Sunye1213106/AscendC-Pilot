from __future__ import annotations

from ascendc_pilot.recovery import (
    KEY_DERIVATION_REWORK,
    KERNEL_DISPATCH_REWORK,
    SEMANTIC_PATCH_REWORK,
    SCOPE_EXPANSION_REWORK,
    is_registered_action_id,
    recoveries_for_closure_gaps,
    resolve_recovery,
)


def _target(reason: str, phase: str) -> tuple[str, str]:
    resolved = resolve_recovery(reason, workflow_id="uo-init", current_phase=phase)
    assert resolved["ok"] is True, resolved
    recovery = resolved["recovery"]
    if recovery["type"] == "action":
        return phase, str(recovery["action_id"])
    assert recovery["type"] == "transition"
    return str(recovery["target_phase"]), str(recovery["next_action"])


def test_kernel_dispatch_recovery_reruns_public_extract_stage() -> None:
    phase, action = _target(KERNEL_DISPATCH_REWORK, "resolve")
    assert phase == "extract"
    assert action == "extract"
    assert is_registered_action_id(action)


def test_key_derivation_recovery_reruns_public_analyze_stage() -> None:
    phase, action = _target(KEY_DERIVATION_REWORK, "resolve")
    assert phase == "analyze"
    assert action == "analyze"


def test_semantic_patch_recovery_returns_to_public_analyze_stage() -> None:
    phase, action = _target(SEMANTIC_PATCH_REWORK, "verify")
    assert phase == "analyze"
    assert action == "analyze"


def test_scope_expansion_recovery_returns_to_prepare() -> None:
    phase, action = _target(SCOPE_EXPANSION_REWORK, "analyze")
    assert phase == "prepare"
    assert action == "prepare"


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
    assert payload["recovery_actions"] == ["extract"]
    assert all(is_registered_action_id(action) for action in payload["recovery_actions"])
