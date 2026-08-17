from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from uo_init.diagnostics.quality import codemap_quality
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.evidence import (
    SOURCE_CLANG_AST,
    SOURCE_DSL,
    SOURCE_LEXICAL,
    SOURCE_UNSPECIFIED,
    TRUST_ADVISORY,
    TRUST_AUTHORITATIVE,
    TRUST_DERIVED,
    TRUST_LEGACY_UNKNOWN,
    EvidenceError,
    assert_semantic_mint,
    derive_trust,
    infer_from_provenance,
    stamp_attrs,
    validate_trust_records,
)
from uo_init.ir.relation import RelationKind
from uo_init.query.slice import slice_forward
from uo_init.store.reader import read_codemap
from uo_init.store.schema import SCHEMA_SQL, SCHEMA_VERSION
from uo_init.store.writer import write_codemap


def test_stamp_infers_lexical_advisory_and_clang_authoritative() -> None:
    lexical = stamp_attrs({"provenance": "source_kernel_call_bound"})
    assert lexical["trust"] == TRUST_ADVISORY
    assert lexical["evidence_source"] == SOURCE_LEXICAL
    clang = stamp_attrs({"provenance": "clang_ast"})
    assert clang["trust"] == TRUST_AUTHORITATIVE
    assert clang["evidence_source"] == SOURCE_CLANG_AST


def test_stamp_does_not_rewrite_existing_trust() -> None:
    attrs = stamp_attrs(
        {
            "provenance": "source_kernel_call_bound",
            "trust": TRUST_LEGACY_UNKNOWN,
            "evidence_source": SOURCE_UNSPECIFIED,
        }
    )
    assert attrs["trust"] == TRUST_LEGACY_UNKNOWN
    assert attrs["evidence_source"] == SOURCE_UNSPECIFIED


def test_stamp_never_upgrades_when_explicit_trust_is_weaker() -> None:
    attrs = stamp_attrs(
        {"trust": TRUST_AUTHORITATIVE, "provenance": "clang_ast"},
        trust=TRUST_ADVISORY,
    )
    assert attrs["trust"] == TRUST_ADVISORY


def test_derive_trust_takes_min_input() -> None:
    assert derive_trust([TRUST_AUTHORITATIVE, TRUST_ADVISORY]) == TRUST_ADVISORY
    assert derive_trust([TRUST_AUTHORITATIVE, TRUST_DERIVED]) == TRUST_DERIVED
    assert derive_trust([]) == TRUST_ADVISORY


def test_lexical_cannot_mint_authoritative() -> None:
    with pytest.raises(EvidenceError):
        assert_semantic_mint(source=SOURCE_LEXICAL, trust=TRUST_AUTHORITATIVE)
    cm = CodeMap(op_name="op", architecture="arch35")
    src = cm.upsert(EntityKind.FUNCTION, "A")
    dst = cm.upsert(EntityKind.FUNCTION, "B")
    with pytest.raises(EvidenceError):
        cm.mint_semantic_relation(
            RelationKind.CALLS,
            src.id,
            dst.id,
            provenance="clang_ast",
            source=SOURCE_LEXICAL,
        )


def test_link_stamps_advisory_and_merge_never_upgrades() -> None:
    cm = CodeMap(op_name="op", architecture="arch35")
    src = cm.upsert(EntityKind.FUNCTION, "A")
    dst = cm.upsert(EntityKind.FUNCTION, "B")
    first = cm.link(
        RelationKind.CALLS,
        src.id,
        dst.id,
        attrs={"provenance": "source_kernel_call_bound"},
        status="confirmed",
    )
    assert first.attrs["trust"] == TRUST_ADVISORY
    second = cm.link(
        RelationKind.CALLS,
        src.id,
        dst.id,
        attrs={"provenance": "clang_ast"},
        status="confirmed",
    )
    assert second.id == first.id
    assert second.attrs["trust"] == TRUST_ADVISORY


def test_derive_relation_propagates_and_demotes_authoritative() -> None:
    cm = CodeMap(op_name="op", architecture="arch35")
    src = cm.upsert(EntityKind.INPUT, "x", attrs={"provenance": "clang_ast"})
    dst = cm.upsert(EntityKind.KERNEL, "K", attrs={"provenance": "clang_ast"})
    derived = cm.derive_relation(
        RelationKind.FLOWS_TO,
        src.id,
        dst.id,
        provenance="source_tpl_args",
        rule="abi_position",
        input_ids=[src.id, dst.id],
    )
    assert derived.attrs["trust"] == TRUST_DERIVED
    assert derived.attrs["evidence_source"] == SOURCE_DSL
    assert derived.attrs["derivation"]["rule"] == "abi_position"

    leak = cm.upsert(
        EntityKind.FUNCTION,
        "lex",
        attrs={"provenance": "source_kernel_call_bound"},
    )
    weak = cm.derive_relation(
        RelationKind.CALLS,
        src.id,
        leak.id,
        provenance="source_tpl_args",
        rule="name_match",
        input_ids=[leak.id],
    )
    assert weak.attrs["trust"] == TRUST_ADVISORY


def test_slice_does_not_follow_advisory_edges() -> None:
    cm = CodeMap(op_name="op", architecture="arch35")
    src = cm.upsert(EntityKind.FUNCTION, "A", eid="A", attrs={"provenance": "clang_ast"})
    mid = cm.upsert(EntityKind.FUNCTION, "B", eid="B", attrs={"provenance": "clang_ast"})
    sink = cm.upsert(EntityKind.FUNCTION, "C", eid="C", attrs={"provenance": "clang_ast"})
    cm.mint_semantic_relation(
        RelationKind.CALLS, src.id, mid.id, provenance="clang_ast"
    )
    cm.mint_candidate_relation(
        RelationKind.CALLS, mid.id, sink.id, provenance="source_kernel_call_bound"
    )
    closed = slice_forward(cm, [src.id], edge_kinds=["CALLS"], depth=3)
    assert {row["id"] for row in closed["nodes"]} == {"A", "B"}
    opened = slice_forward(
        cm, [src.id], edge_kinds=["CALLS"], depth=3, include_advisory=True
    )
    assert {row["id"] for row in opened["nodes"]} == {"A", "B", "C"}


def test_writer_rejects_lexical_false_promotion(tmp_path: Path) -> None:
    cm = CodeMap(op_name="op", architecture="arch35")
    src = cm.upsert(EntityKind.FUNCTION, "A")
    dst = cm.upsert(EntityKind.FUNCTION, "B")
    rel = cm.link(RelationKind.CALLS, src.id, dst.id, attrs={"provenance": "clang_ast"})
    rel.attrs["evidence_source"] = SOURCE_LEXICAL
    rel.attrs["trust"] = TRUST_AUTHORITATIVE
    with pytest.raises(ValueError, match="TRUST_INVARIANT"):
        write_codemap(cm, tmp_path / "op.arch35.uo")


def test_v1_product_reads_as_legacy_unknown_not_lexical(tmp_path: Path) -> None:
    dest = tmp_path / "old.arch35.uo"
    conn = sqlite3.connect(str(dest))
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO meta(key, value) VALUES ('schema', 'codemap-uo/v1')")
    conn.execute("INSERT INTO meta(key, value) VALUES ('op_name', 'op')")
    conn.execute("INSERT INTO meta(key, value) VALUES ('architecture', 'arch35')")
    conn.execute(
        "INSERT INTO entity(id, kind, name, status, confidence, file, line_start, line_end, data) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "FN_A",
            "FUNCTION",
            "A",
            "confirmed",
            1.0,
            "a.cpp",
            1,
            1,
            json.dumps({"provenance": "source_kernel_call_bound"}),
        ),
    )
    conn.execute(
        "INSERT INTO entity(id, kind, name, status, confidence, file, line_start, line_end, data) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "FN_B",
            "FUNCTION",
            "B",
            "confirmed",
            1.0,
            "b.cpp",
            1,
            1,
            json.dumps({"provenance": "clang_ast"}),
        ),
    )
    conn.execute(
        "INSERT INTO relation(id, kind, src, dst, status, confidence, data) VALUES (?,?,?,?,?,?,?)",
        (
            "CALLS:FN_A:FN_B",
            "CALLS",
            "FN_A",
            "FN_B",
            "confirmed",
            1.0,
            json.dumps({"provenance": "source_kernel_call_bound"}),
        ),
    )
    conn.commit()
    conn.close()

    loaded = read_codemap(dest)
    assert loaded.meta["trust_model"] == "legacy_unknown"
    ent = loaded.entities["FN_A"]
    assert ent.attrs["trust"] == TRUST_LEGACY_UNKNOWN
    assert ent.attrs["evidence_source"] == SOURCE_UNSPECIFIED
    rel = loaded.relations["CALLS:FN_A:FN_B"]
    assert rel.attrs["trust"] == TRUST_LEGACY_UNKNOWN
    assert rel.attrs["evidence_source"] == SOURCE_UNSPECIFIED
    closed = slice_forward(loaded, ["FN_A"], edge_kinds=["CALLS"], depth=2)
    assert {row["id"] for row in closed["nodes"]} == {"FN_A", "FN_B"}


def test_v2_write_sets_schema_and_quality_exposes_trust(tmp_path: Path) -> None:
    cm = CodeMap(op_name="op", architecture="arch35")
    src = cm.upsert(EntityKind.FUNCTION, "A", attrs={"provenance": "clang_ast"})
    dst = cm.upsert(EntityKind.FUNCTION, "B", attrs={"provenance": "clang_ast"})
    extra = cm.upsert(EntityKind.FUNCTION, "C", attrs={"provenance": "source_kernel_call_bound"})
    cm.mint_semantic_relation(RelationKind.CALLS, src.id, dst.id, provenance="clang_ast")
    cm.mint_candidate_relation(
        RelationKind.CALLS,
        src.id,
        extra.id,
        provenance="source_kernel_call_bound",
    )
    out = tmp_path / "op.arch35.uo"
    written = write_codemap(cm, out)
    assert written["ok"]
    loaded = read_codemap(out)
    conn = sqlite3.connect(str(out))
    rows = {str(r[0]): str(r[1]) for r in conn.execute("SELECT key, value FROM meta")}
    conn.close()
    assert rows["schema"] == SCHEMA_VERSION
    assert rows["trust_model"] == "v2"
    quality = codemap_quality(loaded, integrity_ok=True)
    assert quality["trust"]["lexical_false_promotion_count"] == 0
    assert quality["trust"]["heuristic_semantic_leak_count"] >= 1
    assert loaded.meta.get("trust_model") != "legacy_unknown"


def test_validate_trust_records_flags_false_promotion() -> None:
    errors = validate_trust_records(
        [
            {
                "id": "r1",
                "evidence_source": SOURCE_LEXICAL,
                "trust": TRUST_AUTHORITATIVE,
            }
        ]
    )
    assert errors
    assert "lexical_false_promotion" in errors[0]


def test_regex_closure_provenances_are_advisory_and_dsl_stays_derived() -> None:
    for prov in (
        "source_kernel_abi_position",
        "source_kernel_abi_position_verified",
        "source_host_defuse",
        "source_host_defuse_dependency",
        "source_tilingdata_setter",
        "source_tilingdata_host_write",
        "source_tilingdata_read_qualified",
        "source_single_kernel_selects",
        "source_kernel_frontier_bound",
        "source_untyped_tiling_data_read",
    ):
        source, trust = infer_from_provenance(prov)
        assert trust == TRUST_ADVISORY, prov
        assert source == SOURCE_LEXICAL
    source, trust = infer_from_provenance("source_get_tiling_data")
    assert source == SOURCE_DSL
    assert trust == TRUST_DERIVED
    source, trust = infer_from_provenance("clang_host_write")
    assert source == SOURCE_CLANG_AST
    assert trust == TRUST_AUTHORITATIVE
    source, trust = infer_from_provenance("clang_field_decl")
    assert trust == TRUST_AUTHORITATIVE
    source, trust = infer_from_provenance("clang_kernel_abi")
    assert trust == TRUST_AUTHORITATIVE
