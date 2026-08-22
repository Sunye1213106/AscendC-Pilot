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
    assert "format-only" in hint.lower()


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


def test_name_card_lists_homonym_definition_sites(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    for idx, line in enumerate((10, 40, 80, 120, 200), start=1):
        cm.add_entity(
            Entity(
                id=f"MTH_sync_{idx}",
                kind=EntityKind.METHOD,
                name="SyncALLCores",
                attrs={"source_definition": True},
                file=f"op_kernel/arch35/k{idx}.h",
                line_start=line,
                line_end=line + 3,
                status="confirmed",
            )
        )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="SyncALLCores")
    card = (out.get("cards") or [{}])[0]
    extras = card.get("extras") or {}
    sites = extras.get("definition_sites") or []
    assert len(sites) == 5
    assert extras.get("definition_sites_complete") is True
    files = {str(row.get("file") or "") for row in sites}
    assert len(files) == 5
    assert int((out.get("coverage") or {}).get("definition_sites_count") or 0) >= 5


def test_alias_card_has_packing_and_value_writes(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="KEY_flag",
            kind=EntityKind.TILING_KEY,
            name="IsBn2MultiBlk",
            attrs={
                "source_declared": True,
                "packing_value_sites": [
                    {
                        "file": "op_host/arch35/td.cpp",
                        "line": 10,
                        "kind": "assignment",
                        "function": "SetSplitAxis",
                        "rhs": "s1 > 1 && s2 > 1",
                    }
                ],
            },
            file="op_kernel/key.h",
            line_start=4,
            status="confirmed",
        )
    )
    field = Entity(
        id="FLD_flag",
        kind=EntityKind.FIELD,
        name="fBaseParams.isBn2MultiBlk",
        attrs={
            "write_sites": [
                {"file": "op_host/arch35/td.cpp", "line": 10, "rhs": "s1 > 1 && s2 > 1"},
                {"file": "op_host/arch35/td.cpp", "line": 40, "rhs": "false"},
            ]
        },
        file="op_host/arch35/td.cpp",
        line_start=10,
        status="confirmed",
    )
    cm.add_entity(field)
    packer = cm.upsert(
        EntityKind.FUNCTION,
        "GetTilingKey",
        eid="FN_pack",
        file="op_host/arch35/td.cpp",
        line=80,
        status="confirmed",
    )
    cm.link(
        RelationKind.WRITES,
        packer.id,
        "KEY_flag",
        attrs={"file": "op_host/arch35/td.cpp", "line": 80, "rhs": "static_cast<uint8_t>(fBaseParams.isBn2MultiBlk)"},
        status="confirmed",
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="isBn2MultiBlk")
    cards = list(out.get("cards") or [])
    assert cards
    extras = (cards[0].get("extras") or {})
    value_lines = {int(row.get("line") or 0) for row in extras.get("value_writes") or []}
    pack_lines = {int(row.get("line") or 0) for row in extras.get("packing_writes") or []}
    assert 10 in value_lines
    assert 40 in value_lines
    assert 80 in pack_lines


def test_buffer_card_lifts_identity_facts(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="BUF_ds",
            kind=EntityKind.BUFFER,
            name="dSL1Buf",
            attrs={
                "wrapper": "MutexBuffer",
                "type_name": "MutexBuffer",
                "memory_space": "L1",
                "role": "storage_wrapper",
                "allocated": True,
                "wraps_lock": True,
            },
            file="op_kernel/arch35/kernel.h",
            line_start=60,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="dSL1Buf")
    card = next(row for row in (out.get("cards") or []) if str(row.get("kind") or "") == "BUFFER")
    extras = card.get("extras") or {}
    assert extras.get("wrapper") == "MutexBuffer"
    assert extras.get("memory_space") == "L1"
    assert extras.get("allocated") is True
    assert card.get("wrapper") == "MutexBuffer"


def test_compile_var_card_lists_same_value_neighbors(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    for name, line, expr in (
        ("SYNC_DETER_FIX_FLAG", 41, "10"),
        ("SYNC_V2_TO_C1_FLAG", 45, "{10, 11}"),
        ("SYNC_UB2L1_DS_FLAG", 58, "10"),
        ("UNRELATED_ZERO", 90, "0"),
    ):
        cm.add_entity(
            Entity(
                id=f"CV_{name}",
                kind=EntityKind.COMPILE_VAR,
                name=name,
                attrs={"value_expr": expr},
                file="op_kernel/arch35/common.h",
                line_start=line,
                status="confirmed",
            )
        )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="SYNC_DETER_FIX_FLAG")
    card = next(
        row for row in (out.get("cards") or []) if str(row.get("kind") or "") == "COMPILE_VAR"
    )
    extras = card.get("extras") or {}
    names = {str(row.get("name") or "") for row in extras.get("same_value") or []}
    assert "SYNC_V2_TO_C1_FLAG" in names
    assert "SYNC_UB2L1_DS_FLAG" in names
    assert "UNRELATED_ZERO" not in names


def test_index_orders_pipes_by_destroy_not_line(tmp_path: Path) -> None:
    src = tmp_path / "op_kernel" / "arch35"
    src.mkdir(parents=True)
    header = src / "toy_entry_regbase.h"
    header.write_text(
        """
#define PHASES \\
  pipeIn.Destroy(); \\
  TPipe pipeBase; \\
  pipeBase.Destroy(); \\
  TPipe pipePost;

inline void Launch() {
  TPipe pipeIn;
  PHASES
}
""",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    for name, line, ordinal in (("pipeBase", 4, 1), ("pipePost", 6, 2), ("pipeIn", 9, 3)):
        cm.add_entity(
            Entity(
                id=f"PIPE_{name}",
                kind=EntityKind.PIPE,
                name=name,
                attrs={
                    "role": "launch_instance",
                    "pipe_ordinal": ordinal,
                    "scope": "Launch",
                    "pointer": 0,
                },
                file="op_kernel/arch35/toy_entry_regbase.h",
                line_start=line,
                status="confirmed",
            )
        )
    for recv, line in (("pipeIn", 3), ("pipeBase", 5)):
        cm.add_entity(
            Entity(
                id=f"OP_Destroy_{recv}_{line}",
                kind=EntityKind.OPERATION,
                name="Destroy",
                attrs={"callee": "Destroy", "receiver": recv},
                file="op_kernel/arch35/toy_entry_regbase.h",
                line_start=line,
                status="extracted",
            )
        )
    cm.add_entity(
        Entity(
            id="FN_Launch",
            kind=EntityKind.FUNCTION,
            name="Launch",
            file="op_kernel/arch35/toy_entry_regbase.h",
            line_start=8,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="MTH_scope",
            kind=EntityKind.METHOD,
            name="toy_entry_regbase:source_scope",
            file="op_kernel/arch35/toy_entry_regbase.h",
            line_start=2,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    index = q.agent_query()
    names = [str(row.get("pipe") or "") for row in (index.get("phases") or [])]
    assert names == ["pipeIn", "pipeBase", "pipePost"]
    entry = index.get("entry") or {}
    assert str(entry.get("name") or "") == "Launch"
    assert "source_scope" not in str(entry.get("name") or "")
