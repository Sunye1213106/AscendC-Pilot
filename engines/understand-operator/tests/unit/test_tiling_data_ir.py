# -*- coding: utf-8 -*-
"""TilingData IR: macro + regbase parse, writers/readers join."""
from __future__ import annotations

from pathlib import Path

from uo_init.host_ir import WriteEvent
from uo_init.tiling_data_ir import (
    join_host_writers,
    parse_class_structs,
    parse_constants,
    parse_macro_structs,
    parse_tiling_data_file,
    scan_kernel_readers,
)


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


def test_parse_class_structs_does_not_drop_non_tiling_names():
    """Use-site binding decides identity; name/path is candidate_score only."""
    src = """
    class WireAbi {
    public:
        uint32_t blockDim;
        uint32_t usedCoreNum;
    };
    class WireAbiHelper {
    public:
        uint32_t skipMe;
    };
    """
    structs = parse_class_structs(src, file="op_kernel/arch35/layout_types.h")
    names = {st.name: st for st in structs}
    assert "WireAbi" in names
    assert names["WireAbi"].candidate_score == 0
    assert "WireAbiHelper" not in names


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
