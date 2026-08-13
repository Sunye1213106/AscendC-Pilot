from pathlib import Path

import yaml

from code_engineering.ledger import Ledger, load_ledger, save_ledger


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def test_ledger_roundtrip_recomputes_vx_from_evidence(tmp_path: Path) -> None:
    root = tmp_path / ".ascendc-pilot" / "arch20"
    _write(
        root / "ce" / "impact" / "change_capture.yaml",
        {"base_sha": "base", "head_sha": "head", "diff": "diff"},
    )
    _write(
        root / "ce" / "impact" / "obligations.yaml",
        {
            "obligations": [
                {"id": "a", "risk_class": "contract"},
                {"id": "b", "risk_class": "precision"},
                {"id": "c", "risk_class": "coverage"},
            ]
        },
    )
    _write(
        root / "ce" / "verify" / "code_review.yaml",
        {
            "schema": "ce-code-review-evidence/v1",
            "change_head_sha": "head",
            "reviewer_id": "ce-reviewer",
            "verified_obligations": [
                {
                    "obligation_id": "a",
                    "verdict": "VERIFIED",
                    "evidence_tier": "A",
                    "evidence_refs": ["x.h:1-3"],
                }
            ],
        },
    )
    _write(
        root / "ce" / "verify" / "external_evidence.yaml",
        {
            "receipts": [
                {
                    "schema": "ce-external-evidence/v1",
                    "change_head_sha": "head",
                    "id": "perf-run",
                    "verified_obligations": ["b"],
                    "declared_path": "/tmp/evidence.yaml",
                }
            ]
        },
    )
    _write(
        root / "ce" / "verify" / "exclusion_review.yaml",
        {
            "schema": "ce-exclusion-review/v1",
            "change_head_sha": "head",
            "referee_id": "ce-change-referee",
            "verdicts": [
                {
                    "obligation_id": "c",
                    "verdict": "approve",
                    "evidence_tier": "A",
                    "proof_refs": ["y.h:10-20"],
                }
            ],
        },
    )

    ledger = Ledger(O={"a", "b", "c"}, V={"a", "b", "c"}, X={"a", "b", "c"})
    path = save_ledger(ledger, tmp_path, architecture="arch20")
    loaded = load_ledger(tmp_path, architecture="arch20")

    assert path == root / "ce" / "impact" / "ledger.yaml"
    assert loaded.V == {"a", "b"}
    assert loaded.X == {"c"}
    assert loaded.Open == set()
    assert loaded.closure_evidence["a"][0]["type"] == "reviewed_source_proof"
    assert loaded.closure_evidence["c"][0]["type"] == "referee_exclusion"


def test_unbacked_transitions_are_rejected(tmp_path: Path) -> None:
    ledger = Ledger(O={"a", "b"}, V={"a"}, X={"b"})
    save_ledger(ledger, tmp_path, architecture="arch20")

    assert ledger.V == set()
    assert ledger.X == set()
    assert ledger.Open == {"a", "b"}
    kinds = {row["kind"] for row in ledger.transition_audit}
    assert "rejected_unbacked_V" in kinds
    assert "rejected_unbacked_X" in kinds


def test_stale_evidence_is_not_replayed_across_change_heads(tmp_path: Path) -> None:
    root = tmp_path / ".ascendc-pilot" / "arch20"
    _write(
        root / "ce" / "impact" / "change_capture.yaml",
        {"base_sha": "base", "head_sha": "new-head", "diff": "diff"},
    )
    _write(
        root / "ce" / "impact" / "obligations.yaml",
        {"obligations": [{"id": "a", "risk_class": "contract"}]},
    )
    _write(
        root / "ce" / "verify" / "code_review.yaml",
        {
            "schema": "ce-code-review-evidence/v1",
            "change_head_sha": "old-head",
            "reviewer_id": "ce-reviewer",
            "verified_obligations": [
                {
                    "obligation_id": "a",
                    "verdict": "VERIFIED",
                    "evidence_tier": "A",
                    "evidence_refs": ["x.h:1-3"],
                }
            ],
        },
    )
    ledger = Ledger(O={"a"})
    save_ledger(ledger, tmp_path, architecture="arch20")
    assert ledger.V == set()
    assert ledger.Open == {"a"}
