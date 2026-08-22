# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.source_resolution import resolve_source_gaps


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "toy"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    return root


def test_runtime_member_line_when_brace_at_eol(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/entry.h"\n'
        "template <bool A>\n"
        "__global__ __aicore__ void toy_kernel(\n"
        "    __gm__ uint8_t *q, __gm__ uint8_t *out,\n"
        "    __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {}\n",
        encoding="utf-8",
    )
    header = (
        "class MutexBuffer {\n"
        "    using TensorType = LocalTensor<uint8_t>;\n"
        "    TensorType tensor_;\n"
        "    uint32_t size_ = 0;\n"
        "    MutexBufferManager<BufferType::L1> l1BufferManager;\n"
        "    typename std::conditional<IS_PRELOAD_TWO_TIMES, MutexBuffersPolicyDB<BufferType::L1>,\n"
        "                              MutexBuffersPolicySingleBuffer<BufferType::L1>>::type pL1Buf;\n"
        "    __aicore__ inline void Init() { tensor_.GetSize(); }\n"
        "};\n"
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(header, encoding="utf-8")
    lines = header.splitlines()
    tensor_line = next(i + 1 for i, row in enumerate(lines) if "tensor_;" in row)
    mgr_line = next(i + 1 for i, row in enumerate(lines) if "l1BufferManager" in row)
    pl1_line = next(i + 1 for i, row in enumerate(lines) if "pL1Buf;" in row)
    init_line = next(i + 1 for i, row in enumerate(lines) if "void Init()" in row)

    cm = CodeMap(op_name="toy", architecture="arch35")
    resolve_source_gaps(cm, root, architecture="arch35")

    using_fields = [e for e in cm.by_kind(EntityKind.FIELD) if e.name == "TensorType"]
    assert not using_fields
    tensor = next(e for e in cm.by_kind(EntityKind.FIELD) if e.name == "tensor_")
    mgr = next(e for e in cm.by_kind(EntityKind.FIELD) if e.name == "l1BufferManager")
    pl1 = next(e for e in cm.by_kind(EntityKind.FIELD) if e.name == "pL1Buf")
    assert int(tensor.line_start or 0) == tensor_line
    assert int(mgr.line_start or 0) == mgr_line
    assert int(pl1.line_start or 0) == pl1_line
    init = next(e for e in cm.by_kind(EntityKind.METHOD) if e.name == "Init")
    assert int(init.line_start or 0) == init_line
    owner = next(e for e in cm.by_kind(EntityKind.TYPE) if e.name == "MutexBuffer")
    declared = {
        cm.entities[r.dst].name
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.DECLARES.value and r.src == owner.id
    }
    assert "Init" in declared
    assert "tensor_" in declared
