# -*- coding: utf-8 -*-
"""Legacy detect_score_pre was removed from uo-init (extract starts at extract_host).

Kept as a thin contract marker so OUTPUT_CONTRACT_PATHS docs do not silently
drop the historical artifact names if something still references them.
"""

from __future__ import annotations

import pytest

from ascendc_pilot.actions.engines import ENGINE_REGISTRY, OUTPUT_CONTRACT_PATHS


def test_detect_score_pre_removed_from_uo_init_engine() -> None:
    assert ("uo-init", "detect_score_pre") not in ENGINE_REGISTRY


def test_detect_score_pre_contract_paths_still_documented() -> None:
    # Contract id may remain for resume/history; engine path is gone.
    if "detect-score-pre-v1" not in OUTPUT_CONTRACT_PATHS:
        pytest.skip("detect-score-pre-v1 contract fully removed")
    paths = OUTPUT_CONTRACT_PATHS["detect-score-pre-v1"]
    assert "uo/ir/entrypoint_graph.yaml" in paths
    assert "uo/ir/score_report_pre.yaml" in paths
