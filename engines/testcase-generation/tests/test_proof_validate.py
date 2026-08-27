# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import yaml

from testcase_agent.proof_validate import validate, validate_review_accept

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "skills" / "source-proof" / "examples"


def _host_cert(**overrides):
    doc = {
        "schema": "source-proof/v1",
        "claim": {
            "layer": "host",
            "premise": "host sees dataType == ge::DT_FLOAT",
            "conclusion": "Host writes schMode == ELEMENTWISE_TPL_SCH_MODE_0",
        },
        "coverage": {"declared": [], "product": [], "completeness": "first_hit"},
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
        "reasoning": [
            {"step": "Host SetTilingKey writes ELEMENTWISE_TPL_SCH_MODE_0 for DT_FLOAT", "cites": ["EV_host"]}
        ],
        "evidence": [{"id": "EV_host", "source": "add_example_tiling.cpp", "role": "host write"}],
        "counterexample": {"checked": True, "result": "none"},
        "completeness": {
            "writers": {"status": "partial", "source": ""},
            "calls": {"status": "partial", "source": ""},
            "macros": {"status": "unknown", "source": ""},
        },
    }
    doc.update(overrides)
    return doc


def test_proved_requires_applicable_obligations_closed():
    bad = _host_cert()
    bad["obligations"]["writes"] = "OPEN"
    out = validate(bad)
    assert out["ok"] is False
    assert any("OPEN" in e for e in out["errors"])


def test_proved_rejects_blocked_applicable_obligation():
    bad = _host_cert()
    bad["obligations"]["control"] = "BLOCKED"
    out = validate(bad)
    assert out["ok"] is False
    assert any("BLOCKED" in e for e in out["errors"])


def test_proved_allows_na_obligations():
    assert validate(_host_cert())["ok"] is True


def test_missing_premise_is_invalid():
    bad = _host_cert()
    bad["claim"]["premise"] = ""
    out = validate(bad)
    assert out["ok"] is False
    assert any("premise" in e for e in out["errors"])


def test_layer_full_is_invalid():
    bad = _host_cert()
    bad["claim"]["layer"] = "full"
    out = validate(bad)
    assert out["ok"] is False
    assert any("layer" in e for e in out["errors"])


def test_proved_requires_counterexample_checked():
    bad = _host_cert()
    bad["counterexample"] = {"checked": False, "result": "none"}
    out = validate(bad)
    assert out["ok"] is False
    assert any("counterexample" in e for e in out["errors"])


def test_proved_requires_evidence_ids_to_resolve():
    bad = _host_cert()
    bad["reasoning"] = [{"step": "missing cite", "cites": ["EV_missing"]}]
    out = validate(bad)
    assert out["ok"] is False
    assert any("EV_missing" in e or "resolve" in e for e in out["errors"])


def test_full_completeness_requires_machine_receipt():
    bad = _host_cert()
    bad["completeness"]["writers"] = {"status": "full", "source": ""}
    out = validate(bad)
    assert out["ok"] is False
    assert any("receipt" in e or "source" in e for e in out["errors"])


def test_calls_full_rejects_writer_closure_receipt():
    bad = _host_cert()
    bad["completeness"]["calls"] = {
        "status": "full",
        "source": "UO_WRITER_CLOSURE_RECEIPT",
    }
    out = validate(bad)
    assert out["ok"] is False
    assert any("UO_CALL_CLOSURE_RECEIPT" in e or "calls" in e for e in out["errors"])


def test_calls_full_accepts_call_closure_receipt():
    ok = _host_cert()
    ok["completeness"]["calls"] = {
        "status": "full",
        "source": "UO_CALL_CLOSURE_RECEIPT",
    }
    assert validate(ok)["ok"] is True


def test_insufficient_may_leave_obligations_open():
    doc = _host_cert(
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
        reasoning=[{"step": "Grep miss", "cites": []}],
        evidence=[],
        counterexample={"checked": False, "result": "none"},
    )
    assert validate(doc)["ok"] is True


def test_review_accept_requires_schema_valid():
    bad = _host_cert()
    bad["obligations"]["calls"] = "OPEN"
    out = validate_review_accept(bad, {"verdict": "accept"})
    assert out["ok"] is False
    assert any("schema" in e or "accept" in e for e in out["errors"])


def test_review_accept_passes_on_valid_certificate():
    out = validate_review_accept(_host_cert(), {"verdict": "accept"})
    assert out["ok"] is True


def test_review_reject_allowed_on_invalid_certificate():
    bad = _host_cert()
    bad["claim"]["premise"] = ""
    out = validate_review_accept(bad, {"verdict": "reject"})
    assert out["ok"] is True


def test_gold_examples_are_schema_valid():
    paths = sorted(EXAMPLES.glob("**/expected/*.yaml"))
    assert paths, "expected source-proof examples"
    for path in paths:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        out = validate(doc)
        assert out["ok"] is True, f"{path}: {out['errors']}"


def test_gold_proved_example_is_not_cross_layer():
    proved = list((EXAMPLES / "add_example_dtype_key_proved" / "expected").glob("*.yaml"))
    assert len(proved) >= 2
    layers = set()
    for path in proved:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        layer = str((doc.get("claim") or {}).get("layer") or "")
        layers.add(layer)
        conclusion = str((doc.get("claim") or {}).get("conclusion") or "").lower()
        evidence_roles = " ".join(str(e.get("role") or "") for e in doc.get("evidence") or [])
        if layer == "host":
            assert "kernel" not in conclusion
            assert "kernel" not in evidence_roles
        if layer == "kernel":
            assert "host writes" not in conclusion
    assert {"host", "kernel"} <= layers
