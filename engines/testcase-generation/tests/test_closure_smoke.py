# -*- coding: utf-8 -*-
"""Smoke tests for the precipitated TilingKey closure package."""

from __future__ import annotations

import os

import pytest

# Replay needs a distro name even when we only decode keys.
os.environ.setdefault("UO_REPLAY_DISTRO", "Ubuntu-2204")


@pytest.fixture(scope="module")
def ws():
    from testcase_agent.closure import workspace as W
    return W.default_workspace().ensure()


def test_declared_is_8705():
    from testcase_agent.closure import workspace as W
    assert len(W.declared()) == 8705


def test_features_cover_known_hints():
    from testcase_agent.closure import features as F
    cov = F.coverage_of(["bn1s1s2", "qkv_bytes", "s1_mod128", "band"])
    assert cov["missing"] == []
    assert set(cov["built"]) == {"bn1s1s2", "qkv_bytes", "s1_mod128", "band"}


def test_coverage_from_codemap_includes_floor():
    from testcase_agent.closure import features as F
    cov = F.coverage_from_codemap()
    for term in ("bn1s1s2", "qkv_bytes", "s1_mod128", "band", "dtype_is_fp32"):
        assert term in cov["built"] or term in F.DERIVED_TERMS
    assert "dtype_is_fp32" in F.DERIVED_TERMS
    assert set(cov["missing"]).isdisjoint(
        {"bn1s1s2", "qkv_bytes", "s1_mod128", "band", "dtype_is_fp32"}
    )


def test_soundness_and_gap_zero(ws):
    from testcase_agent.closure import ledger
    from testcase_agent.closure import lemma

    st = ledger.state(ws)
    assert st["violation"] == 0
    assert st["gap"] == 0
    assert st["R"] >= 4227
    assert st["E"] >= 4536
    assert lemma.soundness_ok(ws)


def test_report_gap_zero(ws):
    from testcase_agent.closure import report

    doc = report.report(ws, refresh=True)
    assert doc["ok"] is True
    assert doc["gap_zero"] is True
    assert doc["open"] == 0
    assert doc["problem_count"] == 0


def test_tk_cover_derive_without_probe_cache(tmp_path):
    """derive_fields must not require .probe_cache/fag_derive.json."""
    from uo_init.tk_cover_engines import derive_fields

    uo = tmp_path / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    (uo / "ir" / "host_codemap.yaml").write_text(
        "schema: host_codemap/v1\nwrites:\n"
        "  - {path: fBaseParams.splitAxis, function: SetSplitAxis, "
        "file: x.cpp, line: 1, rhs: '0', guards: []}\n"
        "calls: []\nfunctions: []\n",
        encoding="utf-8",
    )
    doc = derive_fields(tmp_path, {"uo_root": str(uo)})
    assert doc["ok"] is True
    assert doc["fields"] >= 1
