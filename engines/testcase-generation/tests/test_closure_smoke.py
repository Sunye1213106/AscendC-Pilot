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

    try:
        return W.default_workspace().ensure()
    except ValueError as exc:
        pytest.skip(f"requires real closure workspace: {exc}")


def _default_workspace_or_skip():
    from testcase_agent.closure import workspace as W

    try:
        return W.default_workspace()
    except ValueError as exc:
        pytest.skip(f"requires real closure workspace: {exc}")


def test_declared_is_8705():
    from testcase_agent.closure import workspace as W

    _default_workspace_or_skip()
    assert len(W.declared()) == 8705


def test_features_cover_known_hints():
    from testcase_agent.closure import features as F
    cov = F.coverage_of(["bn1s1s2", "qkv_bytes", "s1_mod128", "band"])
    assert cov["missing"] == []
    assert set(cov["built"]) == {"bn1s1s2", "qkv_bytes", "s1_mod128", "band"}


def test_coverage_from_codemap_includes_floor(tmp_path):
    from testcase_agent.closure import features as F
    from ascendc_pilot.paths import uo_root

    operator_root = os.environ.get("ASCENDC_PROJECT_ROOT") or os.environ.get("UO_OP_DIR")
    if operator_root:
        root = uo_root(operator_root)
    else:
        root = uo_root(tmp_path)
        (root / "ir").mkdir(parents=True)
        (root / "manifest.yaml").write_text("op_name: closure-smoke\n", encoding="utf-8")
        (root / "ir" / "host_codemap.yaml").write_text(
            "schema: host_codemap/v1\nwrites: []\ncalls: []\nfunctions: []\n",
            encoding="utf-8",
        )
    cov = F.coverage_from_codemap(str(root))
    derived_terms = set((F._feature_bindings().get("derived_terms") or {}).keys())
    for term in ("bn1s1s2", "qkv_bytes", "s1_mod128", "band", "dtype_is_fp32"):
        assert term in cov["built"] or term in derived_terms
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


def test_tg_host_view_hints_without_probe_cache(tmp_path):
    """Host-view projection must not require .probe_cache/fag_derive.json."""
    from testcase_agent.closure import features as F

    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    (uo / "ir").mkdir(parents=True)
    (uo / "ir" / "tg_host_view.yaml").write_text(
        "schema: tg-host-view/v1\n"
        "fields:\n"
        "  - {name: SplitAxis, kind: key_dim, writers: [], reads: []}\n"
        "predicates:\n"
        "  - {feature_hint: bn1s1s2, condition: 'b*n1*s1*s2'}\n"
        "  - {feature_hint: qkv_bytes, condition: 'dtypeBytes'}\n"
        "  - {feature_hint: s1_mod128, condition: 's1 % 128'}\n"
        "  - {feature_hint: band, condition: 'preTokens'}\n"
        "  - {feature_hint: dtype_is_fp32, condition: 'DT_FLOAT'}\n"
        "declared_keys: {}\n"
        "platform_gates: []\n",
        encoding="utf-8",
    )
    cov = F.coverage_from_codemap(str(uo))
    assert isinstance(cov, dict)
    assert "built" in cov or "missing" in cov
