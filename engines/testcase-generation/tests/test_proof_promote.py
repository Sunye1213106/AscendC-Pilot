# -*- coding: utf-8 -*-
from __future__ import annotations

from testcase_agent.coverage.ledger import seed_ledger
from testcase_agent.proof_promote import pair_items, promote
from testcase_agent.proof_validate import validate


def _cert(**overrides):
    doc = {
        "schema": "source-proof/v1",
        "claim": {
            "layer": "host",
            "premise": "P",
            "conclusion": "Q is unreachable on host",
        },
        "obligations": {
            "entry": "CLOSED",
            "control": "CLOSED",
            "writes": "CLOSED",
            "calls": "NA",
            "overwrite": "CLOSED",
            "alternatives": "CLOSED",
            "completeness": "NA",
        },
        "result": "PROVED",
        "reasoning": [{"step": "host write", "cites": ["EV_h"]}],
        "evidence": [{"id": "EV_h", "source": "host.cpp:10", "role": "host write"}],
        "counterexample": {"checked": True, "result": "none"},
        "completeness": {
            "writers": {"status": "partial", "source": ""},
            "calls": {"status": "partial", "source": ""},
            "macros": {"status": "unknown", "source": ""},
        },
    }
    doc.update(overrides)
    return doc


def test_accept_proved_marks_obligation_unreachable():
    ledger = seed_ledger([{"id": "O7", "status": "MISS"}])
    out = promote(
        items=[{"obligation": "O7", "certificate": _cert(), "review": {"verdict": "accept"}}],
        ledger=ledger,
    )
    assert out["ok"] is True
    assert out["applied"] == ["O7"]
    assert ledger["obligations"]["O7"]["status"] == "PROVED_UNREACHABLE"


def test_accept_invalid_certificate_does_not_exclude():
    bad = _cert()
    bad["obligations"]["writes"] = "OPEN"
    assert validate(bad)["ok"] is False
    ledger = seed_ledger([{"id": "O7", "status": "MISS"}])
    out = promote(
        items=[{"obligation": "O7", "certificate": bad, "review": {"verdict": "accept"}}],
        ledger=ledger,
    )
    assert out["ok"] is False
    assert "O7" not in out["applied"]
    assert ledger["obligations"]["O7"]["status"] == "MISS"


def test_insufficient_never_excludes():
    cert = _cert(
        result="INSUFFICIENT",
        obligations={
            "entry": "OPEN",
            "control": "OPEN",
            "writes": "BLOCKED",
            "calls": "OPEN",
            "overwrite": "OPEN",
            "alternatives": "OPEN",
            "completeness": "BLOCKED",
        },
        reasoning=[{"step": "search miss", "cites": []}],
        evidence=[],
        counterexample={"checked": False, "result": "none"},
    )
    ledger = seed_ledger([{"id": "O7", "status": "UNKNOWN"}])
    out = promote(
        items=[{"obligation": "O7", "certificate": cert, "review": {"verdict": "accept"}}],
        ledger=ledger,
    )
    assert out["ok"] is True
    assert out["applied"] == []
    assert ledger["obligations"]["O7"]["status"] == "UNKNOWN"


def test_reject_does_not_exclude():
    ledger = seed_ledger([{"id": "O7", "status": "MISS"}])
    out = promote(
        items=[{"obligation": "O7", "certificate": _cert(), "review": {"verdict": "reject"}}],
        ledger=ledger,
    )
    assert out["ok"] is True
    assert out["applied"] == []
    assert ledger["obligations"]["O7"]["status"] == "MISS"


def test_composed_obligation_needs_all_accepted_atomic_certs():
    host = _cert()
    kernel = _cert()
    kernel["claim"] = {
        "layer": "kernel",
        "premise": "schMode == 0",
        "conclusion": "float arm selected",
    }
    ledger = seed_ledger([{"id": "O7", "status": "MISS"}])
    partial = promote(
        items=[
            {"obligation": "O7", "certificate": host, "review": {"verdict": "accept"}},
            {"obligation": "O7", "certificate": kernel, "review": {"verdict": "defer"}},
        ],
        ledger=ledger,
    )
    assert partial["applied"] == []
    assert ledger["obligations"]["O7"]["status"] == "MISS"
    full = promote(
        items=[
            {"obligation": "O7", "certificate": host, "review": {"verdict": "accept"}},
            {"obligation": "O7", "certificate": kernel, "review": {"verdict": "accept"}},
        ],
        ledger=ledger,
    )
    assert full["applied"] == ["O7"]
    assert ledger["obligations"]["O7"]["status"] == "PROVED_UNREACHABLE"


def test_pair_items_matches_review_on_obligation():
    items = pair_items(
        certificates=[{"obligation": "O7", **_cert()}],
        reviews=[{"verdict": "accept", "on": "O7"}],
    )
    assert len(items) == 1
    assert items[0]["obligation"] == "O7"
    assert items[0]["review"]["verdict"] == "accept"


def test_pair_items_reads_yaml11_boolean_on_key():
    items = pair_items(
        certificates=[{"obligation": "O7", **_cert()}],
        reviews=[{"verdict": "accept", True: "O7"}],
    )
    assert items[0]["review"]["verdict"] == "accept"


def test_does_not_overwrite_closed_hit():
    ledger = seed_ledger([{"id": "O7", "status": "CLOSED"}])
    out = promote(
        items=[{"obligation": "O7", "certificate": _cert(), "review": {"verdict": "accept"}}],
        ledger=ledger,
    )
    assert out["ok"] is True
    assert out["applied"] == []
    assert ledger["obligations"]["O7"]["status"] == "CLOSED"
