# -*- coding: utf-8 -*-
"""Legacy detect_score_pre is absent from the active UO runtime graph."""

from __future__ import annotations

from ascendc_pilot.actions.engines import ENGINE_REGISTRY, OUTPUT_CONTRACT_PATHS


def test_detect_score_pre_removed_from_uo_init_engine() -> None:
    assert ("uo-init", "detect_score_pre") not in ENGINE_REGISTRY


def test_detect_score_pre_contract_removed() -> None:
    assert "detect-score-pre-v1" not in OUTPUT_CONTRACT_PATHS
