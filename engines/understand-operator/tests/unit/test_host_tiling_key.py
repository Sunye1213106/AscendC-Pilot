from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions


def test_get_tpl_tiling_key_binds_declared_fields_by_position(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    host = op / "op_host" / "arch35"
    host.mkdir(parents=True)
    (host / "tiling.cpp").write_text(
        "uint64_t BuildKey() {\n"
        "  bool isTnd = true;\n"
        "  return GET_TPL_TILING_KEY(0, static_cast<uint8_t>(splitAxis), isTnd);\n"
        "}\n",
        encoding="utf-8",
    )

    cm = CodeMap(op_name="toy", architecture="arch35")
    for order, (name, width) in enumerate((("IsEmpty", 1), ("SplitAxis", 2), ("IsTnd", 1))):
        cm.upsert(
            EntityKind.TILING_KEY,
            name,
            attrs={"source_declared": True, "decl_order": order, "bit_width": width},
        )
    split = cm.upsert(
        EntityKind.VARIABLE,
        "splitAxis",
        attrs={"identity": {"normalized": {"source_name": "splitAxis"}}},
    )

    bind_host_tiling_key_expressions(cm, op, architecture="arch35")

    meta = cm.meta["host_tiling_key_packing"]
    assert meta["calls"] == 1
    assert meta["fields_bound"] == 3
    assert meta["declared"] == 3
    assert meta["argument_count_mismatches"] == []

    keys = {e.name: e for e in cm.by_kind(EntityKind.TILING_KEY)}
    assert keys["IsEmpty"].attrs["host_packing_expressions"] == ["0"]
    assert keys["SplitAxis"].attrs["host_packing_expressions"] == ["static_cast<uint8_t>(splitAxis)"]
    assert keys["IsTnd"].attrs["host_packing_expressions"] == ["isTnd"]

    exprs = [
        e for e in cm.by_kind(EntityKind.PREDICATE)
        if e.attrs.get("predicate_role") == "host_tiling_key_argument"
    ]
    assert len(exprs) == 3
    split_expr = next(e for e in exprs if e.attrs.get("tiling_key") == "SplitAxis")
    assert any(r.src == split.id and r.dst == split_expr.id and r.kind_name() == "DERIVES" for r in cm.relations.values())
    assert any(
        e.kind_name() == EntityKind.COMPILE_VAR.value
        and e.attrs.get("compile_root") is True
        for e in cm.entities.values()
    )


def test_host_key_argument_count_mismatch_does_not_bind_fields(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    host = op / "op_host" / "arch35"
    host.mkdir(parents=True)
    (host / "tiling.cpp").write_text(
        "uint64_t BuildKey() { return GET_TPL_TILING_KEY(0); }\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.TILING_KEY, "A", attrs={"source_declared": True, "decl_order": 0, "bit_width": 1})
    cm.upsert(EntityKind.TILING_KEY, "B", attrs={"source_declared": True, "decl_order": 1, "bit_width": 1})

    bind_host_tiling_key_expressions(cm, op, architecture="arch35")

    meta = cm.meta["host_tiling_key_packing"]
    assert meta["fields_bound"] == 0
    assert len(meta["argument_count_mismatches"]) == 1
    assert not [
        e for e in cm.by_kind(EntityKind.PREDICATE)
        if e.attrs.get("predicate_role") == "host_tiling_key_argument"
    ]
