# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.tiling_host_writes import enrich_tiling_host_writes


def test_class_member_receiver_disambiguates_shared_field_names(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    host = op / "op_host"
    host.mkdir(parents=True)
    (host / "tiling.h").write_text(
        "class AlphaTiling { public:\n"
        "  int64_t blockFactor;\n"
        "  void set_blockFactor(int64_t v) { blockFactor = v; }\n"
        "};\n"
        "class BetaTiling { public:\n"
        "  int64_t blockFactor;\n"
        "  void set_blockFactor(int64_t v) { blockFactor = v; }\n"
        "};\n"
        "class AlphaHost {\n"
        "  AlphaTiling tilingData_;\n"
        "  void Fill();\n"
        "};\n"
        "class BetaHost {\n"
        "  BetaTiling tilingData_;\n"
        "  void Fill();\n"
        "};\n",
        encoding="utf-8",
    )
    (host / "alpha.cpp").write_text(
        '#include "tiling.h"\n'
        "void AlphaHost::Fill() { tilingData_.set_blockFactor(4); }\n",
        encoding="utf-8",
    )
    (host / "beta.cpp").write_text(
        '#include "tiling.h"\n'
        "void BetaHost::Fill() { tilingData_.set_blockFactor(8); }\n",
        encoding="utf-8",
    )

    cm = CodeMap(op_name="toy", architecture="arch35")
    alpha = cm.upsert(EntityKind.TILING_DATA, "AlphaTiling")
    beta = cm.upsert(EntityKind.TILING_DATA, "BetaTiling")
    cm.upsert(
        EntityKind.TILING_FIELD,
        "blockFactor",
        eid="F::AlphaTiling::blockFactor",
        attrs={"owner": "AlphaTiling", "qualified_name": "AlphaTiling::blockFactor"},
    )
    cm.upsert(
        EntityKind.TILING_FIELD,
        "blockFactor",
        eid="F::BetaTiling::blockFactor",
        attrs={"owner": "BetaTiling", "qualified_name": "BetaTiling::blockFactor"},
    )

    enrich_tiling_host_writes(cm, op, architecture="arch35")

    unresolved = [
        e for e in cm.by_kind(EntityKind.OTHER)
        if e.attrs.get("role") == "tilingdata_writer_unresolved"
    ]
    assert unresolved == []
    written = [
        e for e in cm.by_kind(EntityKind.PREDICATE)
        if e.attrs.get("predicate_role") == "tilingdata_writer"
    ]
    owners = {e.attrs.get("owner") for e in written}
    assert owners == {"AlphaTiling", "BetaTiling"}
    assert alpha.id and beta.id


def test_clang_host_write_binds_typed_local_not_unique_short_name(tmp_path: Path) -> None:
    from uo_init.clang_walk import LocalDecl
    from uo_init.host_ir import HostIR, WriteEvent

    op = tmp_path / "toy"
    host = op / "op_host" / "arch35"
    host.mkdir(parents=True)
    (host / "host.cpp").write_text("void Fill() {}\n", encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch35")
    a = cm.upsert(EntityKind.TILING_DATA, "AData")
    b = cm.upsert(EntityKind.TILING_DATA, "BData")
    ax = cm.upsert(
        EntityKind.TILING_FIELD,
        "x",
        eid="TDF::AData::x",
        attrs={"owner": "AData", "qualified_name": "AData::x", "cpp_type": "int"},
    )
    bx = cm.upsert(
        EntityKind.TILING_FIELD,
        "x",
        eid="TDF::BData::x",
        attrs={"owner": "BData", "qualified_name": "BData::x", "cpp_type": "int"},
    )
    host_ir = HostIR(
        local_decls=[
            LocalDecl(
                name="td",
                function="Fill",
                type_text="AData *",
                init=None,
                file="op_host/arch35/host.cpp",
                line=1,
            )
        ],
        writes=[
            WriteEvent(
                path="td.x",
                line=2,
                rhs="1",
                file="op_host/arch35/host.cpp",
                function="Fill",
            )
        ],
    )
    enrich_tiling_host_writes(cm, op, architecture="arch35", host_ir=host_ir)
    writes = [
        r
        for r in cm.relations.values()
        if r.kind_name() == "WRITES"
        and r.attrs.get("provenance") == "clang_host_write"
    ]
    assert {r.dst for r in writes} == {ax.id}
    assert bx.id not in {r.dst for r in writes}
    assert a.id and b.id
