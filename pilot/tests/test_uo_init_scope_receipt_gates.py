# -*- coding: utf-8 -*-
"""uo-init complete/phase gates must include scope_receipt (ses_00bf)."""

from __future__ import annotations

from ascendc_pilot.workflows.specs import WORKFLOWS


def test_uo_init_wires_scope_receipt_everywhere() -> None:
    uo = WORKFLOWS["uo-init"]
    assert "scope_receipt" in (uo.get("complete_gates") or [])
    assert "scope_receipt" in (uo.get("gates") or [])
    assert "scope_receipt" in (uo.get("phase_gates") or {}).get("prepare", [])
    prepare = next(a for a in uo["actions"] if a["id"] == "prepare")
    assert "scope_receipt" in (prepare.get("post_gates") or [])


def test_uo_init_wires_integrity_everywhere() -> None:
    """ses_febd: force_new uo-init must settle kb_integrity_passed via integrity."""
    uo = WORKFLOWS["uo-init"]
    assert "integrity" in (uo.get("complete_gates") or [])
    assert "integrity" in (uo.get("gates") or [])
    assert "integrity" in (uo.get("phase_gates") or {}).get("verify", [])
    verify = next(a for a in uo["actions"] if a["id"] == "verify")
    assert "integrity" in (verify.get("post_gates") or [])
    ids = [row["id"] for row in (uo.get("static_obligations") or [])]
    assert "kb_integrity_passed" in ids
    assert "uo/cache" in ((uo.get("reset_policy") or {}).get("reinit_preserve") or [])
