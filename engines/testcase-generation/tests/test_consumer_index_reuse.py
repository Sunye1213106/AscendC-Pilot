"""Consumer index reuse across TG evidence passes — semantic equivalence."""

from __future__ import annotations

import copy
from pathlib import Path

from testcase_agent.consumer_evidence import build_consumer_evidence
from testcase_agent.consumer_index import load_or_build_consumer_index


def _consumer_script(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "gen_csv.py").write_text(
        "COLUMNS = ['Input_Layout', 'keep_prob']\n"
        "def get_column_index(df, name):\n"
        "    return COLUMNS.index(name)\n"
        "def read_row(row):\n"
        "    layout = row['Input_Layout']\n"
        "    kp = row.get('keep_prob', 1.0)\n"
        "    return int(layout), kp\n",
        encoding="utf-8",
    )
    return consumer


def _strip_counters(evidence: dict) -> dict:
    out = copy.deepcopy(evidence)
    out.pop("evidence_hash", None)
    # Normalize file sha fields order only — keep semantic content.
    return out


def test_consumer_index_reuse_zero_bytes_on_hit(tmp_path: Path) -> None:
    consumer = _consumer_script(tmp_path)
    out_root = tmp_path / "tg"
    (out_root / "realization").mkdir(parents=True)

    first = load_or_build_consumer_index(out_root, consumer)
    assert first.bytes_read_count >= 1
    assert first.ast_parse_count >= 1
    assert first.required_optional_evidence
    assert any(
        r.get("kind") == "required_read"
        for refs in first.required_optional_evidence.values()
        for r in refs
    )
    assert any(
        r.get("kind") == "optional_read"
        for refs in first.required_optional_evidence.values()
        for r in refs
    )
    # Must not mix required/optional into field_accesses kinds incorrectly as sole store.
    for refs in first.field_accesses.values():
        for r in refs:
            assert r.get("kind") not in {"required_read", "optional_read"}

    second = load_or_build_consumer_index(out_root, consumer)
    assert second.bytes_read_count == 0
    assert second.ast_parse_count == 0
    assert second.stat_only_hits >= 1
    assert second.files == first.files
    assert second.required_optional_evidence == first.required_optional_evidence
    assert second.field_accesses == first.field_accesses


def test_consumer_index_verify_hash_env(tmp_path: Path, monkeypatch) -> None:
    consumer = _consumer_script(tmp_path)
    out_root = tmp_path / "tg"
    (out_root / "realization").mkdir(parents=True)
    load_or_build_consumer_index(out_root, consumer)
    monkeypatch.setenv("TG_CONSUMER_CACHE_VERIFY_HASH", "1")
    hit = load_or_build_consumer_index(out_root, consumer)
    assert hit.ast_parse_count == 0
    assert hit.bytes_read_count >= 1  # hash verification re-reads bytes
    assert hit.required_optional_evidence


def test_consumer_evidence_index_paths_equivalent(tmp_path: Path) -> None:
    consumer = _consumer_script(tmp_path)
    out_root = tmp_path / "tg"
    (out_root / "realization").mkdir(parents=True)
    snapshot = {"snapshot_hash": "s1"}
    obligations = {"plan_hash": "p1", "obligations": []}

    no_index = build_consumer_evidence(
        consumer,
        snapshot=snapshot,
        obligations_doc=obligations,
        out_root=None,
    )
    first = build_consumer_evidence(
        consumer,
        snapshot=snapshot,
        obligations_doc=obligations,
        out_root=out_root,
    )
    second = build_consumer_evidence(
        consumer,
        snapshot=snapshot,
        obligations_doc=obligations,
        out_root=out_root,
    )

    a = _strip_counters(no_index)
    b = _strip_counters(first)
    c = _strip_counters(second)

    # Semantic fields must match (ignore consumer_root absolute path string only via normalize).
    for key in (
        "ordered_header_candidates",
        "field_accesses",
        "required_optional_evidence",
        "type_conversion_evidence",
    ):
        assert a.get(key) == b.get(key) == c.get(key), key

    assert a["required_optional_evidence"]
    kinds = {
        r.get("kind")
        for refs in a["required_optional_evidence"].values()
        for r in refs
    }
    assert "required_read" in kinds
    assert "optional_read" in kinds
