# -*- coding: utf-8 -*-
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.tiling_gaps import record_unresolved_tiling


def test_unresolved_tiling_does_not_mint_other() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    kernel = cm.upsert(
        EntityKind.KERNEL,
        "k",
        attrs={"source_signature": True},
        file="op_kernel/k.h",
        line=1,
        status="extracted",
    )
    record_unresolved_tiling(
        cm,
        kernel,
        role="tilingdata_read_unresolved",
        file="op_kernel/k.h",
        line=8,
        expression="td->foo",
    )
    assert list(cm.by_kind(EntityKind.OTHER)) == []
    sites = kernel.attrs.get("tiling_unresolved_sites") or []
    assert len(sites) == 1
    assert sites[0]["role"] == "tilingdata_read_unresolved"
