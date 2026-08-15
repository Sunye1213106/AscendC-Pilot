# -*- coding: utf-8 -*-
from pathlib import Path

from uo_init.diagnostics.product_check import check_cannbot_product
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind


def test_product_check_needles_and_dtype(tmp_path: Path) -> None:
    op = tmp_path / "op"
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35" / "k.h").write_text(
        "void Kernel() { DataCopy(dst, src, n); SetFlag(PIPE_MTE2, PIPE_MTE1, EVENT_ID0); }\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.KERNEL,
        "toy_kernel",
        attrs={"source_signature": True},
        file="op_kernel/arch35/k.h",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.INPUT,
        "x",
        attrs={"api_kind": "tensor", "dtype": ["DT_FLOAT16"], "facts": {"dtype": ["DT_FLOAT16"]}},
        file="op_graph/p.h",
        line=2,
        status="extracted",
    )
    cm.upsert(
        EntityKind.OPERATION,
        "DataCopy",
        attrs={"callee": "DataCopy", "root_status": "REACHED"},
        file="op_kernel/arch35/k.h",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.OPERATION,
        "SetFlag",
        attrs={"callee": "SetFlag", "root_status": "REACHED"},
        file="op_kernel/arch35/k.h",
        line=1,
        status="extracted",
    )
    facts = check_cannbot_product(cm, source_root=op, architecture="arch35")
    assert facts["expected"]["needles_graph_ge_source"] is True, facts
    assert facts["expected"]["kernel_api_sync"] is True
    assert facts["expected"]["input_dtype_declared"] is True
    assert facts["expected"]["other_count_zero"] is True
    assert facts["expected"]["no_dummy_kernel"] is True


def test_product_check_fails_when_graph_drops(tmp_path: Path) -> None:
    op = tmp_path / "op"
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35" / "k.h").write_text(
        "void Kernel() { DataCopy(a, b, n); DataCopy(c, d, n); }\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.KERNEL,
        "toy_kernel",
        attrs={"source_signature": True},
        file="op_kernel/arch35/k.h",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.OPERATION,
        "DataCopy",
        attrs={"callee": "DataCopy", "root_status": "REACHED"},
        file="op_kernel/arch35/k.h",
        line=1,
        status="extracted",
    )
    facts = check_cannbot_product(cm, source_root=op, architecture="arch35")
    assert facts["expected"]["needles_graph_ge_source"] is False
    assert facts["ok"] is False
