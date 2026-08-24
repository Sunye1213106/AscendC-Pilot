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


def test_function_snippet_keeps_tail_assignment(tmp_path: Path) -> None:
    rel = "op_host/split.cpp"
    lines = [f"    stmt_{i}();" for i in range(1, 80)]
    lines[0] = "void SetSplitAxis() {"
    lines[64] = "    fBaseParams.splitAxis = SplitAxisEnum::BN2;"
    lines[69] = "}"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="FN_split",
            kind=EntityKind.FUNCTION,
            name="SetSplitAxis",
            attrs={"source_definition": True},
            file=rel,
            line_start=1,
            line_end=70,
            status="confirmed",
        )
    )
    other = cm.upsert(
        EntityKind.FUNCTION,
        "CheckAttenMaskShape",
        eid="FN_mask",
        file=rel,
        line=90,
        status="confirmed",
    )
    written = cm.upsert(
        EntityKind.VARIABLE,
        "bnLimit",
        eid="VAR_bn",
        file=rel,
        line=10,
        status="confirmed",
    )
    cm.link(RelationKind.FLOWS_TO, "FN_split", other.id, attrs={"file": rel, "line": 2})
    cm.link(RelationKind.WRITES, "FN_split", written.id, attrs={"file": rel, "line": 10})
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="SetSplitAxis")
    card = next(row for row in (out.get("cards") or []) if row.get("kind") == "FUNCTION")
    snippet = str(card.get("snippet") or "")
    assert "splitAxis" in snippet
    assert "void SetSplitAxis" in snippet
    nxt = [str(n) for n in (out.get("next") or [])]
    assert "CheckAttenMaskShape" not in nxt
    assert "bnLimit" in nxt


def test_field_card_snippet_prefers_value_write(tmp_path: Path) -> None:
    rel = "op_host/arch35/td.cpp"
    body = ["// pad"] * 20
    body[11] = "    fBaseParams.enablePreSfmg = deterSupportPreSfmg && presfmgLimit;"
    body[17] = "    td.enablePreSfmg = fBaseParams.enablePreSfmg;"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TDF_pre",
            kind=EntityKind.TILING_FIELD,
            name="enablePreSfmg",
            attrs={
                "source_declared": True,
                "write_sites": [
                    {
                        "file": rel,
                        "line": 12,
                        "rhs": "deterSupportPreSfmg && presfmgLimit",
                    }
                ],
            },
            file="op_kernel/td.h",
            line_start=4,
            status="confirmed",
        )
    )
    packer = cm.upsert(
        EntityKind.FUNCTION,
        "InitTilingData",
        eid="FN_pack",
        file=rel,
        line=18,
        status="confirmed",
    )
    cm.link(
        RelationKind.WRITES,
        packer.id,
        "TDF_pre",
        attrs={"file": rel, "line": 18, "rhs": "fBaseParams.enablePreSfmg"},
        status="confirmed",
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="enablePreSfmg")
    card = next(
        row
        for row in (out.get("cards") or [])
        if str(row.get("kind") or "") in {"TILING_FIELD", "FIELD", "TILING_KEY"}
    )
    snippet = str(card.get("snippet") or "")
    assert "deterSupportPreSfmg" in snippet
    writes = ((card.get("edges") or {}).get("WRITES") or {}).get("neighbors") or []
    assert writes
    assert int(writes[0].get("line") or 0) == 12
    nxt = [str(n) for n in (out.get("next") or [])]
    assert "deterSupportPreSfmg" in nxt or "presfmgLimit" in nxt


def test_tiling_key_skips_false_decl_for_snippet(tmp_path: Path) -> None:
    rel = "op_host/arch35/td.cpp"
    body = ["// pad"] * 20
    body[5] = "    bool templateSupportCond = condA && false;"
    body[10] = "    tndBaseInfo.isTndSwizzle = fBaseParams.enableSwizzle && templateSupportCond;"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="KEY_sw",
            kind=EntityKind.TILING_KEY,
            name="IsTndSwizzle",
            attrs={
                "source_declared": True,
                "packing_value_sites": [
                    {
                        "file": "op_host/arch35/td.h",
                        "line": 3,
                        "kind": "declaration",
                        "rhs": "false",
                    },
                    {
                        "file": rel,
                        "line": 11,
                        "kind": "assignment",
                        "rhs": "fBaseParams.enableSwizzle && templateSupportCond",
                    },
                ],
            },
            file="op_kernel/key.h",
            line_start=8,
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(pattern="isTndSwizzle")
    card = (out.get("cards") or [{}])[0]
    snippet = str(card.get("snippet") or "")
    assert "templateSupportCond" in snippet
    nxt = [str(n) for n in (out.get("next") or [])]
    assert "templateSupportCond" in nxt


def test_around_is_statement_window(tmp_path: Path) -> None:
    import json

    rel = "op_host/h.cpp"
    body = "\n".join(f"line {i}" for i in range(1, 80)) + "\n"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch35")
    fn = cm.upsert(
        EntityKind.FUNCTION,
        "FnEnclose",
        eid="FN_enclose",
        attrs={"layer": "host"},
        file=rel,
        line=10,
        line_end=40,
        status="confirmed",
    )
    field = cm.upsert(
        EntityKind.FIELD,
        "owner.fldInner",
        eid="FLD_inner",
        attrs={"layer": "host"},
        file=rel,
        line=20,
        status="confirmed",
    )
    cm.link(RelationKind.WRITES, fn.id, field.id, attrs={"file": rel, "line": 20})
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    out = q.agent_query(file=rel, line=20)
    snippet = str(out.get("snippet") or "")
    assert "20:" in snippet
    assert "line 20" in snippet
    assert len((out.get("seeds") or [])) <= 1
    assert (out.get("neighbors") or []) == []
    assert len(json.dumps(out, ensure_ascii=False)) < 8000
    assert str((out.get("seeds") or [{}])[0].get("name") or "") == "FnEnclose"


def test_cover_legal_key_count_not_confused_with_blocks(tmp_path: Path, monkeypatch) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TK_alpha",
            kind=EntityKind.TILING_KEY,
            name="DimAlpha",
            attrs={
                "source_declared": True,
                "decl_order": 0,
                "bit_width": 1,
                "bit_lo": 0,
                "bit_hi": 0,
                "value_domain": ["0", "1"],
                "allowed_values": ["0", "1"],
                "decl_kind": "UINT",
                "kind_tpl": "UINT",
                "provenance": "source_tpl_args_decl",
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="TPL_0",
            kind=EntityKind.TEMPLATE,
            name="ARGS_SEL_0",
            attrs={
                "tpl_role": "args_sel_group",
                "sel_group_index": 0,
                "fixed_fields": {"DimAlpha": "0"},
                "field_domains": {},
                "provenance": "source_tpl_args_sel",
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    monkeypatch.setattr(
        q,
        "legal_key_query",
        lambda **_kwargs: {"ok": True, "total_matched": 32, "count": 32},
    )
    out = q.agent_query(pattern="DimAlpha=0")
    assert int(out.get("matching_block_count") or 0) == 1
    assert int(out.get("total_matched") or -1) == 1
    assert int(out.get("legal_key_count") or 0) == 32
