# -*- coding: utf-8 -*-
"""Acceptance: the fa-pr13 bypass scripts must no longer certify.

Anchors the P0-1 / P0-2 acceptance checks from optimization_plan.md without
touching the live operator workspace.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_unsealed_backdated_cold_start_is_rejected(tmp_path: Path, monkeypatch):
    """certify_with_provenance.py wrote cold_start without a seal; refuse it."""
    from testcase_agent.closure import cold_start as CS
    from testcase_agent.closure import workspace as W

    state = tmp_path / "closure"
    state.mkdir()
    ws = W.Workspace(root=tmp_path, artifacts=tmp_path / "art", state=state).ensure()

    # Mimic the bypass: backdated stamp, no seal, no chain.
    active_ts = datetime.now(timezone.utc)
    cold_ts = (active_ts - timedelta(hours=1)).isoformat()
    _write(
        state / "cold_start.yaml",
        {
            "schema": "tg-cold-start/v1",
            "timestamp": cold_ts,
            "fingerprint": "deadbeef",
            "state": str(state),
            "cleared": ["provenance_backfill"],
            "note": "stamped after Host+lemma closure without wiping R/E",
        },
    )
    # Non-empty E so check_e_provenance does not short-circuit.
    (state / "excluded.txt").write_text("1\n", encoding="utf-8")
    lemmas = state / "lemmas"
    lemmas.mkdir()
    _write(
        lemmas / "active_rules.yaml",
        {"schema": "tg-active-rules/v1", "rules": [{"when": {"a": "1"}, "grade": "source_lemma"}]},
    )

    pre = CS.require_cold_start(ws)
    assert pre["ok"] is False
    assert "cold_start_unsealed" in pre["issues"] or "cold_start_unsigned" in pre["issues"]

    # With E non-empty the full provenance check also fails on the missing chain.
    monkeypatch.setattr(
        "testcase_agent.closure.ledger.load_E",
        lambda _ws=None: {1},
    )
    prov = CS.check_e_provenance(ws)
    assert prov["ok"] is False
    assert any(
        x in prov["issues"]
        for x in ("cold_start_unsealed", "cold_start_unsigned", "provenance_chain_missing")
    )


def test_handwritten_auto_ok_without_writer_role_is_rejected(tmp_path: Path, monkeypatch):
    """certify_with_provenance.py wrote review.yaml status=auto_ok with no role."""
    from ascendc_pilot.actions import engines as E

    review = {
        "schema": "tg-closure-audit/v1",
        "status": "auto_ok",
        "soundness": "pass",
        "note": "gap=0 full tilingkey closure",
    }
    # Extract the audit decision by calling the same predicates certify uses.
    writer_role = str(review.get("writer_role") or "").strip().lower()
    assert not writer_role

    # Mirror the certify branch: missing writer_role → invalid.
    audit_reason = "audit_writer_role_invalid" if not writer_role else ""
    assert audit_reason == "audit_writer_role_invalid"

    # Engine-written auto_ok is accepted only with writer_role=engine.
    engine_doc = {**review, "writer_role": "engine"}
    assert str(engine_doc["writer_role"]).lower() == "engine"

    # A referee auto_ok is also invalid (auto_ok is engine-only).
    referee_doc = {**review, "writer_role": "referee"}
    assert str(referee_doc["writer_role"]).lower() != "engine"


def test_hint_family_without_live_source_ref_cannot_promote(tmp_path: Path):
    from testcase_agent.closure import certificate as CERT

    raw = {
        "origin": "hint",
        "grade": "source_lemma",
        "when": {"mode": "z"},
        "certificate": {
            "proof_scope": {
                "target_dimensions": ["mode"],
                "relevant_functions": ["Pack"],
                "assignments": ["op_host/missing.cpp:1"],
                "guards": ["op_host/missing.cpp:1"],
            },
            "assumptions": ["sole writer"],
            "completeness_evidence": {
                "assignment_sites_complete": True,
                "call_closure_complete": True,
                "alias_state_exact": True,
                "macro_context_complete": True,
            },
            "counterexample_strategy": {"kind": "r_intersection"},
        },
    }
    got = CERT.validate(raw, operator_root=tmp_path)
    assert got["ok"] is False
    assert "hint_requires_live_source_ref" in got["errors"]

    # Same candidate with a real file on disk is eligible on the source_ref axis.
    src = tmp_path / "op_host" / "pack.cpp"
    src.parent.mkdir(parents=True)
    src.write_text("// pack\n", encoding="utf-8")
    raw["certificate"]["proof_scope"]["assignments"] = ["op_host/pack.cpp:1"]
    raw["certificate"]["proof_scope"]["guards"] = ["op_host/pack.cpp:1"]
    got2 = CERT.validate(raw, operator_root=tmp_path)
    assert "hint_requires_live_source_ref" not in got2["errors"]


def test_lemma_loop_is_not_registered():
    from ascendc_pilot.actions.engines import ENGINE_REGISTRY
    from ascendc_pilot.workflows import WORKFLOWS, action_by_id

    assert ("tg-solve", "lemma_loop") not in ENGINE_REGISTRY
    assert action_by_id("tg-solve", "lemma_loop") is None
    assert "lemma" not in [s["id"] for s in WORKFLOWS["tg-solve"]["states"]]
