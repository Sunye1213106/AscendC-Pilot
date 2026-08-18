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
        "void Kernel() {\n  DataCopy(a, b, n);\n  DataCopy(c, d, n);\n}\n",
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


def test_product_check_allows_included_other_arch_header(tmp_path: Path) -> None:
    op = tmp_path / "op"
    (op / "op_kernel" / "arch-920r1").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35" / "shared.h").write_text("struct Shared {};\n", encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch-920r1")
    cm.upsert(
        EntityKind.KERNEL,
        "toy_kernel",
        attrs={"source_signature": True},
        file="op_kernel/arch-920r1/k.cpp",
        line=1,
        status="extracted",
    )
    cm.upsert(
        EntityKind.OTHER,
        "Shared",
        file="op_kernel/arch35/shared.h",
        line=1,
        status="extracted",
    )
    facts = check_cannbot_product(cm, source_root=op, architecture="arch-920r1")
    assert facts["expected"]["no_foreign_arch"] is True
    assert facts["counts"]["foreign_arch"] == 0


def test_product_check_flags_foreign_entry_tu(tmp_path: Path) -> None:
    op = tmp_path / "op"
    (op / "op_kernel" / "arch-920r1").mkdir(parents=True)
    cm = CodeMap(op_name="toy", architecture="arch-920r1")
    cm.upsert(
        EntityKind.KERNEL,
        "old_kernel",
        attrs={"source_signature": True},
        file="op_kernel/arch35/old.cpp",
        line=1,
        status="extracted",
    )
    facts = check_cannbot_product(cm, source_root=op, architecture="arch-920r1")
    assert facts["expected"]["no_foreign_arch"] is False
    assert facts["counts"]["foreign_arch"] == 1
