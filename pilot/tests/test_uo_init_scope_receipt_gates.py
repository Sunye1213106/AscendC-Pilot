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
