from pathlib import Path

import pytest
import yaml

from code_engineering.certificate import write_certificate
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


def test_missing_source_revision_with_capture_is_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        freshness_module,
        "meta",
        lambda *_args, **_kwargs: {
            "cm_graph_fingerprint": "g",
            "source_revision": "",
        },
    )
    _write(
        tmp_path
        / ".ascendc-pilot"
        / "arch35"
        / "ce"
        / "impact"
        / "change_capture.yaml",
        {"base_sha": "base", "head_sha": "head", "diff": "diff --git a/x b/x"},
    )
    result = freshness_module.check_freshness(tmp_path, "g", architecture="arch35")
    assert result["mode"] == "stale"
    assert result["reason"] == "uo_source_revision_missing"


def test_promote_feature_decomposition_writes_canonical(tmp_path: Path) -> None:
    from code_engineering.intent import promote_feature_decomposition

    scope = tmp_path / ".ascendc-pilot" / "arch35"
    _write(
        scope / "ce" / "intent" / "plan_review.yaml",
        {
            "status": "pass",
            "accepted": [{"id": "F1", "goal": "fix cast", "candidate_anchors": [{"name": "Cast"}]}],
        },
    )
    out = promote_feature_decomposition(tmp_path, architecture="arch35")
    assert out["ok"] is True
    path = scope / "ce" / "intent" / "feature_decomposition.yaml"
    assert path.is_file()
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["schema"] == "ce-feature-decomposition/v1"
    assert doc["features"][0]["id"] == "F1"


def test_promote_feature_decomposition_requires_review(tmp_path: Path) -> None:
    from code_engineering.intent import promote_feature_decomposition

    out = promote_feature_decomposition(tmp_path, architecture="arch35")
    assert out["ok"] is False
    assert out["error"] == "plan_review_not_accepted"


def test_write_codemap_stamps_source_revision(tmp_path: Path, monkeypatch) -> None:
    from uo_init.ir.codemap import CodeMap
    from uo_init.store import writer as writer_mod
    from uo_init.store.reader import read_meta
    from uo_init.store.writer import write_codemap

    monkeypatch.setattr(writer_mod, "detect_source_revision", lambda _root: "deadbeef")
    cm = CodeMap(op_name="toy", architecture="arch35")
    path = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, path)
    meta = read_meta(path)
    assert meta.get("source_revision") == "deadbeef"


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


def test_buffer_anchor_does_not_create_dispatch() -> None:
    rows = evaluate_risks(
        [{"id": "BUF", "kind": "BUFFER", "evidence_tier": "A"}]
    )
    classes = {str(row["risk_class"]) for row in rows}
    assert "dispatch" not in classes
    assert "sync" in classes
    assert "perf" in classes


def test_cast_operation_attaches_precision_not_dispatch() -> None:
    rows = evaluate_risks(
        [{"id": "OP", "kind": "OPERATION", "name": "Cast", "evidence_tier": "A"}]
    )
    classes = {str(row["risk_class"]) for row in rows}
    assert classes == {"precision"}


def test_slice_projects_nodes_and_defaults_useful_edges(tmp_path: Path) -> None:
    from code_engineering.primitives import slice_forward
    from uo_init.ir.codemap import CodeMap
    from uo_init.ir.entity import EntityKind
    from uo_init.ir.relation import RelationKind
    from uo_init.store.writer import write_codemap

    cm = CodeMap(op_name="toy", architecture="arch35")
    src = cm.upsert(EntityKind.TILING_KEY, "SplitAxis", eid="TK", file="h.cpp", line=1)
    dst = cm.upsert(
        EntityKind.BUFFER,
        "local_q",
        eid="BUF",
        attrs={"memory_space": "UB"},
        file="k.cpp",
        line=2,
    )
    noise = cm.upsert(EntityKind.FUNCTION, "helper", eid="FN")
    cm.link(RelationKind.SELECTS, src.id, dst.id)
    cm.link(RelationKind.CONTAINS, src.id, noise.id)
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)

    out = slice_forward([src.id], [], 2, project_root=tmp_path, architecture="arch35")
    ids = {row["id"] for row in out["nodes"]}
    assert "TK" in ids
    assert "BUF" in ids
    assert "FN" not in ids
    kinds = {row["kind"] for row in out["relations"]}
    assert "SELECTS" in kinds
    assert "CONTAINS" not in kinds
    assert "facts" in out["nodes"][0]


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


def test_tier_c_anchor_does_not_poison_peer_obligation() -> None:
    rows = evaluate_risks(
        [
            {"id": "hot", "kind": "BUFFER", "evidence_tier": "A"},
            {"id": "hint", "kind": "BUFFER", "evidence_tier": "C"},
        ]
    )
    sync_rows = [row for row in rows if row["risk_class"] == "sync"]
    assert len(sync_rows) == 2
    by_anchor = {tuple(row["anchors"]): row["max_verdict"] for row in sync_rows}
    assert by_anchor[("hot",)] == "runtime"
    assert by_anchor[("hint",)] == "open_only"


def test_intent_tokens_ignore_leftover_change_capture(tmp_path: Path) -> None:
    from code_engineering.primitives import _intent_source_tokens

    scope = tmp_path / ".ascendc-pilot" / "arch35"
    _write(
        scope / "ce" / "impact" / "change_capture.yaml",
        {"schema": "ce-change-capture/v1", "diff": "leftover"},
    )
    _write(
        scope / "ce" / "intent" / "feature_decomposition.yaml",
        {"features": [{"candidate_anchors": [{"name": "DoTilingImpl"}]}]},
    )
    _write(
        scope / "ce" / "intent" / "intent.yaml",
        {"intent": "rewrite everything", "targets": ["ShouldNotWin"]},
    )
    assert _intent_source_tokens(scope) == ["DoTilingImpl"]


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
    out = write_certificate(
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
