from pathlib import Path

import pytest
import yaml

import code_engineering.certificate as certificate_module
import code_engineering.change.freshness as freshness_module
from code_engineering.external_evidence import load_external_evidence
from code_engineering.ledger import Ledger
from code_engineering.primitives import _intent_tokens
from code_engineering.risk.rules import evaluate_risks
from code_engineering.validation import validate_obligations


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def test_freshness_does_not_self_compare_stale_uo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        freshness_module,
        "meta",
        lambda *_args, **_kwargs: {
            "cm_graph_fingerprint": "same-graph",
            "source_revision": "old-source",
        },
    )
    capture = (
        tmp_path
        / ".ascendc-pilot"
        / "arch35"
        / "ce"
        / "impact"
        / "change_capture.yaml"
    )
    _write(
        capture,
        {
            "base_sha": "base-source",
            "head_sha": "new-source",
            "diff": "diff --git a/x b/x",
        },
    )

    result = freshness_module.check_freshness(
        tmp_path, "same-graph", architecture="arch35"
    )
    assert result["mode"] == "stale"
    assert result["reason"] == "source_revision_mismatch"


def test_worktree_change_downgrades_to_lexical(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        freshness_module,
        "meta",
        lambda *_args, **_kwargs: {
            "cm_graph_fingerprint": "g",
            "source_revision": "head",
        },
    )
    _write(
        tmp_path
        / ".ascendc-pilot"
        / "arch35"
        / "ce"
        / "impact"
        / "change_capture.yaml",
        {"base_sha": "head", "head_sha": "head", "diff": "non-empty"},
    )
    result = freshness_module.check_freshness(tmp_path, "g", architecture="arch35")
    assert result["mode"] == "lexical"
    assert result["reason"] == "working_tree_change_after_uo"


@pytest.mark.parametrize(
    ("tier", "expected"),
    [("A", "static"), ("B", "review_only"), ("C", "open_only")],
)
def test_tier_caps_obligation_verdict(tier: str, expected: str) -> None:
    rows = evaluate_risks(
        [{"id": "anchor", "evidence_tier": tier}], ["contract"]
    )
    assert rows[0]["max_verdict"] == expected
    assert validate_obligations(rows)["ok"] is True


def test_external_evidence_cannot_create_x(tmp_path: Path) -> None:
    receipt = tmp_path / "evidence.yaml"
    _write(
        receipt,
        {
            "schema": "ce-external-evidence/v1",
            "verified_obligations": [],
            "excepted_obligations": ["o1"],
        },
    )
    with pytest.raises(ValueError, match="cannot exclude"):
        load_external_evidence(receipt)


def test_intent_token_extraction_is_field_bounded() -> None:
    doc = {
        "features": [
            {
                "goal": "do not use arbitrary prose as a symbol",
                "candidate_anchors": [{"name": "DoTilingImpl"}],
                "targets": ["TILING_FIELD::s1"],
            }
        ]
    }
    assert _intent_tokens(doc) == ["DoTilingImpl", "TILING_FIELD::s1"]


def test_certificate_contains_closure_context(tmp_path: Path) -> None:
    scope = tmp_path / ".ascendc-pilot" / "arch35"
    _write(
        scope / "ce" / "impact" / "impact_slice.yaml",
        {
            "anchors": [{"id": "actual", "evidence_tier": "C", "file": "x.h"}],
            "forward": {"relations": [], "truncated": True},
            "backward": {"relations": [], "truncated": False},
        },
    )
    _write(
        scope / "ce" / "intent" / "anchors.yaml",
        {"anchors": [{"id": "predicted"}]},
    )
    ledger = Ledger(O={"o1"}, V=set(), X=set())
    out = certificate_module.write_certificate(
        tmp_path,
        ledger,
        architecture="arch35",
        path=scope / "ce" / "verify" / "certificate.yaml",
    )

    assert out["Open"] == ["o1"]
    assert out["blind_spots"]["count"] >= 2
    assert out["intent_drift"]["drift"] is True
    assert "analyzability" in out
    assert "closure_evidence" in out
