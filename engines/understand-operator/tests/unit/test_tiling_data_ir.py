# -*- coding: utf-8 -*-
"""TilingData IR: macro + regbase parse, writers/readers join, KB materialize."""
from __future__ import annotations

from pathlib import Path

import yaml

from uo_init.assemble_kb import assemble_kb, export_operator_kb
from uo_init.controllability import ClosureMetrics
from uo_init.gaps import GapReport
from uo_init.host_ir import WriteEvent
from uo_init.kb_model import KnowledgeBase
from uo_init.tiling_data_ir import (
    build_tiling_data_ir,
    join_host_writers,
    materialize_tiling_data,
    parse_class_structs,
    parse_constants,
    parse_macro_structs,
    parse_tiling_data_file,
    scan_kernel_readers,
)
from uo_init.uo_query import UoQuery, open_query


MACRO_SRC = """
namespace optiling {
BEGIN_TILING_DATA_DEF(DemoParams)
TILING_DATA_FIELD_DEF(uint32_t, batch);
TILING_DATA_FIELD_DEF(uint64_t, s1);
TILING_DATA_FIELD_DEF(float, scaleValue);
END_TILING_DATA_DEF;
REGISTER_TILING_DATA_CLASS(DemoParamsOp, DemoParams)
constexpr uint32_t MAX_CORE_NUM = 36;
#define DEMO_FLAG 1
}
"""

CLASS_SRC = """
namespace fag {
constexpr uint32_t MAX_CORE_NUM = 36;
class DemoTilingParams {
public:
    int64_t coreNum;
    int64_t s1;
    int64_t s2 = 0;
    bool enablePreSfmg;
    uint32_t get_s1() const { return s1; }
    void set_s1(int64_t v) { this->s1 = v; }
};
}
"""

KERNEL_SRC = """
void Process(const DemoTilingParams* tilingData) {
    if (tilingData->enablePreSfmg) {
        auto x = tilingData->s1;
        (void)x;
    }
    if (tilingData->get_s2() > 0) {
        return;
    }
}
"""


def test_parse_macro_structs():
    structs = parse_macro_structs(MACRO_SRC, file="demo_tiling.h")
    assert len(structs) == 1
    assert structs[0].name == "DemoParams"
    assert structs[0].form == "macro_def"
    names = [f.name for f in structs[0].fields]
    assert names == ["batch", "s1", "scaleValue"]
    assert structs[0].fields[0].ctype == "uint32_t"


def test_parse_regbase_class_and_constants():
    structs = parse_class_structs(CLASS_SRC, file="op_kernel/arch35/demo_tiling_data_regbase.h")
    assert len(structs) == 1
    assert structs[0].name == "DemoTilingParams"
    names = {f.name: f for f in structs[0].fields}
    assert "s1" in names and "enablePreSfmg" in names
    assert names["s2"].default == "0"
    consts = parse_constants(CLASS_SRC, file="demo.h")
    assert any(c.name == "MAX_CORE_NUM" and c.value == "36" for c in consts)


def test_join_writers_and_scan_readers(tmp_path: Path):
    header = tmp_path / "demo_tiling_data_regbase.h"
    header.write_text(CLASS_SRC, encoding="utf-8")
    kernel = tmp_path / "demo_kernel.h"
    kernel.write_text(KERNEL_SRC, encoding="utf-8")
    ir = parse_tiling_data_file(header, op_root=str(tmp_path))
    assert ir.field_names() >= {"s1", "s2", "enablePreSfmg", "coreNum"}

    class _Host:
        writes = [
            WriteEvent(
                path="this.base.s1",
                line=10,
                rhs="shape.s1",
                file="op_host/tiling.cpp",
                function="DoTiling",
            )
        ]
        local_writes = []

    join_host_writers(ir, _Host(), op_root=str(tmp_path))
    assert ir.writers["s1"]
    assert ir.writers["s1"][0].expr == "shape.s1"

    scan_kernel_readers(ir, [kernel], op_root=str(tmp_path))
    assert ir.readers["enablePreSfmg"]
    assert ir.readers["s1"]
    # get_s2() should hit s2
    assert ir.readers["s2"]


def test_materialize_exports_view_and_query(tmp_path: Path):
    header = tmp_path / "demo_tiling_data_regbase.h"
    header.write_text(CLASS_SRC, encoding="utf-8")
    kernel = tmp_path / "k.h"
    kernel.write_text(KERNEL_SRC, encoding="utf-8")
    ir = parse_tiling_data_file(header, op_root=str(tmp_path))

    class _Host:
        writes = [
            WriteEvent(
                path="tiling.s1",
                line=3,
                rhs="b",
                file="host.cpp",
                function="Tiling",
            )
        ]
        local_writes = []
        call_sites = []

    join_host_writers(ir, _Host(), op_root=str(tmp_path))
    scan_kernel_readers(ir, [kernel], op_root=str(tmp_path))

    metrics = ClosureMetrics(total_nodes=0, closed_nodes=0, open_nodes=0)
    kb = assemble_kb(
        op_name="DemoOp",
        architecture="arch35",
        analyses=[],
        records=[],
        metrics=metrics,
        gap=GapReport(),
        tiling_data_ir=ir,
        host_ir=_Host(),
        op_root=str(tmp_path),
    )
    assert kb.by_kind("TilingDataField")
    assert any(n.name == "s1" for n in kb.by_kind("TilingDataField"))
    assert any(
        (n.data or {}).get("value_type") == "named_constant"
        or n.name == "MAX_CORE_NUM"
        for n in kb.by_kind("Variable")
    )
    receipt = export_operator_kb(kb, tmp_path)
    assert receipt.get("ok") is not False
    from uo_init.kb_index import load_view_blob

    view = load_view_blob(Path(receipt["database"]), "views/tilingdata.yaml")
    assert view["schema"] == "uo-view-tilingdata/v1"
    assert view["status"] == "extracted"
    assert view["structs"]
    field_names = [f["name"] for f in view["structs"][0]["fields"]]
    assert "s1" in field_names

    q = UoQuery(Path(receipt["database"]))
    hit = q.field_impact("s1")
    assert hit["ok"] is True
    assert hit["writers"] or hit["field"]
    rows = q.search("enablePreSfmg", kinds=("TilingDataField",), limit=10)
    assert rows

    import pytest

    with pytest.raises(FileNotFoundError):
        open_query(tmp_path / ".ascendc-pilot" / "uo")


def test_fag_header_smoke_if_present():
    """Optional live-header smoke: skip when the TEST tree is absent."""
    root = Path(r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad")
    header = (
        root
        / "op_kernel"
        / "arch35"
        / "flash_attention_score_grad_tiling_data_regbase.h"
    )
    if not header.is_file():
        return
    ir = parse_tiling_data_file(header, op_root=str(root))
    assert len(ir.structs) >= 2
    names = ir.field_names()
    assert {"s1", "s2", "coreNum", "enablePreSfmg"} <= names
    assert any(c.name == "MAX_CORE_NUM" for c in ir.constants)
    kb = KnowledgeBase(op_name="FlashAttentionScoreGrad", architecture="arch35")
    summary = materialize_tiling_data(kb, ir, op_root=str(root))
    assert summary["field_count"] >= 20
    assert not kb.check_invariants()
