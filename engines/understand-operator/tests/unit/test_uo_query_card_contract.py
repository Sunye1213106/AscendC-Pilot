from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _product(cm: CodeMap, tmp_path: Path) -> None:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)


def test_around_empty_line_is_not_unindexed(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="MTH_cal",
            kind=EntityKind.METHOD,
            name="CalBandDeterIndex",
            attrs={"owner": "FlashAttentionScoreGradKernelDeter", "source_definition": True},
            file="op_kernel/arch35/k.cpp",
            line_start=10,
            line_end=40,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(file="op_kernel/arch35/k.cpp", line=999)
    assert out.get("ok") is False
    hint = str(out.get("hint") or out.get("error") or "")
    assert "not proof the file is unindexed" in hint.lower() or "added identifiers" in hint.lower()
    assert "format-only" in hint.lower() or "form-1" in hint.lower()


def test_method_card_has_callers_callees_and_field_readers(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    process = cm.upsert(
        EntityKind.METHOD,
        "Process",
        eid="MTH_process",
        attrs={"owner": "FlashAttentionScoreGradKernelDeter", "source_definition": True},
        file="op_kernel/arch35/k.cpp",
        line=4,
        line_end=8,
        status="confirmed",
    )
    cal = cm.upsert(
        EntityKind.METHOD,
        "CalBandDeterIndex",
        eid="MTH_cal",
        attrs={"owner": "FlashAttentionScoreGradKernelDeter", "source_definition": True},
        file="op_kernel/arch35/k.cpp",
        line=10,
        line_end=40,
        status="confirmed",
    )
    cm.link(
        RelationKind.CALLS,
        process.id,
        cal.id,
        attrs={"file": "op_kernel/arch35/k.cpp", "line": 5, "provenance": "source_kernel_call_bound_v2"},
        status="confirmed",
    )
    field = cm.upsert(
        EntityKind.TILING_FIELD,
        "result.mode",
        eid="TDF_mode",
        attrs={
            "owner": "TilingData",
            "write_sites": [
                {"file": "op_host/tiling.cpp", "line": 115, "rhs": "BAND"},
                {"file": "op_host/tiling.cpp", "line": 128, "rhs": "DENSE"},
            ],
        },
        file="op_host/tiling.cpp",
        line=115,
        status="confirmed",
    )
    cm.link(
        RelationKind.READS,
        cal.id,
        field.id,
        attrs={"file": "op_kernel/arch35/k.cpp", "line": 20},
        status="confirmed",
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    method_card = q.agent_query(pattern="CalBandDeterIndex")
    assert method_card.get("ok") is True
    cards = list(method_card.get("cards") or [])
    hit = next(row for row in cards if str(row.get("kind") or "") == "METHOD")
    extras = hit.get("extras") or {}
    assert extras.get("callers")
    assert any(str(row.get("name") or "") == "Process" for row in extras.get("callers") or [])
    span = hit.get("definition_span") or {}
    assert int(span.get("line_end") or 0) >= 40
    field_card = q.agent_query(pattern="result.mode")
    fhit = next(
        row
        for row in (field_card.get("cards") or [])
        if str(row.get("kind") or "") in {"TILING_FIELD", "FIELD"}
    )
    fextras = fhit.get("extras") or {}
    assert "readers" in fextras
    assert any(str(row.get("name") or "") == "CalBandDeterIndex" for row in fextras.get("readers") or [])
