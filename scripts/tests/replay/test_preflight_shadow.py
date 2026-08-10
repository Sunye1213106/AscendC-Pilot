# -*- coding: utf-8 -*-
"""Preflight is a shadow, not a filter."""

from __future__ import annotations

from replay import inputs as I
from replay import runner as R


def test_preflight_tags_would_reject_without_claiming_the_host_did(monkeypatch):
    class FakeBridge:
        @staticmethod
        def refused_by(case):
            return [{"file": "/x/Check.cpp", "line": 12, "text": "rank != 4"}]

    import replay.bridge as B
    monkeypatch.setattr(B, "refused_by", FakeBridge.refused_by)

    got = R.default().preflight({"c0": I.Case()})
    assert "c0" in got
    assert got["c0"].reject.startswith("PREFLIGHT_WOULD_REJECT")
    assert "Check.cpp:12" in got["c0"].reject
