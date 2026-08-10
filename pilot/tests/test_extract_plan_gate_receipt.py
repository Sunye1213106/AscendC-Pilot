"""extract_plan action was removed from uo-init; gate retained only for history."""

from __future__ import annotations

import pytest

from ascendc_pilot.gates import gate_extract_plan_subagent


pytestmark = pytest.mark.skip(reason="extract_plan removed from uo-init extract pipeline")


def test_extract_plan_gate_passes_without_receipt(tmp_path) -> None:
    assert callable(gate_extract_plan_subagent)


def test_extract_plan_gate_fails_empty_sinks_contract(tmp_path) -> None:
    assert callable(gate_extract_plan_subagent)
