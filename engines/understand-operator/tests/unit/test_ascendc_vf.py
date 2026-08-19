# -*- coding: utf-8 -*-
"""CANN VF / Reg compute API catalog loaded from headers."""

from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.kernel_root_trace import (
    _prove_ascendc_api_root,
    finalize_kernel_root_trace,
)
from uo_init.semantics import registry as semreg
from uo_init.semantics.ascendc_vf import (
    architecture_has_vf,
    architecture_npu_arch,
    cann_vf_api_names,
    cann_vf_reg_api_names,
    is_ambiguous_vf_name,
    is_cann_vf_api,
    is_vf_only_api,
    vf_root_spelling,
)
from tests.unit.test_kernel_root_trace import _seed


def test_vf_aliases_and_ambiguous_or() -> None:
    assert vf_root_spelling("FusedExpSub") == "ExpSub"
    assert vf_root_spelling("FusedMulDstAdd") == "MulDstAdd"
    assert vf_root_spelling("ExpSub") == "ExpSub"
    assert is_cann_vf_api("ExpSub")
    assert is_cann_vf_api("FusedExpSub")
    assert is_cann_vf_api("Or")
    assert is_ambiguous_vf_name("Or")
    assert not is_ambiguous_vf_name("ExpSub")
    names = cann_vf_api_names()
    assert "ExpSub" in names
    assert "Or" in names


def test_vf_non_void_returns_are_scanned() -> None:
    """CreateMask / CreateAddrReg return MaskReg/AddrReg, not void."""
    names = cann_vf_reg_api_names()
    for spell in (
        "CreateMask",
        "UpdateMask",
        "CreateAddrReg",
        "MoveMask",
        "LoadAlign",
        "StoreUnAlign",
        "StoreAlign",
        "LoadUnAlign",
        "Pack",
        "Arange",
        "Histograms",
        "LocalMemBar",
        "GatherB",
        "DataCopyScatter",
    ):
        assert spell in names, spell
    assert is_vf_only_api("LoadAlign")
    assert is_vf_only_api("CreateMask")
    assert is_vf_only_api("DataCopyScatter")
    assert is_vf_only_api("GatherB")
    assert not is_vf_only_api("Add")
    assert not is_vf_only_api("Duplicate")
    assert not is_vf_only_api("DataCopy")


def test_vf_gated_by_architecture() -> None:
    assert architecture_has_vf("arch35") is True
    assert architecture_has_vf("arch22") is False
    assert architecture_has_vf("") is True
    assert architecture_npu_arch("arch-920r1") == 9201
    assert architecture_npu_arch("arch920r1") == 9201
    assert architecture_has_vf("arch-920r1") is True
    assert architecture_has_vf("9201") is True
    assert is_cann_vf_api("LoadAlign", architecture="arch35") is True
    assert is_cann_vf_api("LoadAlign", architecture="arch-920r1") is True
    assert is_cann_vf_api("CreateMask", architecture="arch35") is True
    assert is_cann_vf_api("LoadAlign", architecture="arch22") is False
    assert is_cann_vf_api("CreateMask", architecture="arch22") is False
    assert is_cann_vf_api("DataCopyScatter", architecture="arch22") is False
    assert is_cann_vf_api("LocalMemBar", architecture="arch22") is False
    # Level-2 LocalTensor APIs remain on arch22.
    assert is_cann_vf_api("Add", architecture="arch22") is True
    assert is_cann_vf_api("Duplicate", architecture="arch22") is True


def test_registry_classifies_vf_spellings() -> None:
    semreg.load_registry.cache_clear()
    cat, engine, conf = semreg.classify("ExpSub")
    assert cat == "reg_compute"
    assert engine == "VECTOR"
    assert conf == "confirmed"
    assert (semreg.lookup("ExpSub") or {}).get("requires_vf") is True
    cat_or, engine_or, _ = semreg.classify("Or")
    assert cat_or in {"vector_compute", "reg_compute"}
    assert engine_or == "VECTOR"
    cat_fused, _, _ = semreg.classify("FusedMulDstAdd")
    assert cat_fused in {"vector_compute", "reg_compute"}
    load = semreg.lookup("LoadAlign") or {}
    assert load.get("requires_vf") is True
    add = semreg.lookup("Add") or {}
    assert not add.get("requires_vf")


def test_loadalign_not_a_root_on_arch22(tmp_path: Path) -> None:
    root = tmp_path / "vf22"
    arch = root / "op_kernel" / "arch22"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch22").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            LoadAlign(vreg, ptr);
            CreateMask<float, MaskPattern::ALL>();
            Add(dst, src0, src1, n);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="vf22", architecture="arch22")
    _seed(cm, root, files=[str(arch / "process.h")])
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch22")
    ops = {e.name: e for e in cm.by_kind(EntityKind.OPERATION)}
    assert "LoadAlign" not in ops or ops["LoadAlign"].attrs.get("root_status") != "REACHED"
    assert "CreateMask" not in ops or ops["CreateMask"].attrs.get("root_status") != "REACHED"
    assert ops["Add"].attrs.get("root_status") == "REACHED"


def test_popstackbuffer_allocates_without_initbuffer(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          TPipe pipe;
          LocalTensor<uint8_t> tmp;
          __aicore__ inline void Process() {
            PopStackBuffer<uint8_t, TPosition::LCM>(tmp);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="stack", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    pop = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "PopStackBuffer")
    assert pop.attrs.get("root_status") == "REACHED"
    assert pop.attrs.get("root") == "AscendC::PopStackBuffer"
    assert pop.attrs.get("mechanism") == "stack"
    buf = next(e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "tmp")
    assert buf.attrs.get("allocated") is True
    assert buf.attrs.get("stack_pop") is True
    inits = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "InitBuffer"]
    assert not inits


def test_initsharebuf_is_share_root_not_initbuffer(tmp_path: Path) -> None:
    root = tmp_path / "share"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          TPipe pipe;
          __aicore__ inline void Process() {
            uint32_t lens[2] = {0, 0};
            InitShareBufStart(&pipe, 0, lens, 2, 0);
            InitShareBufEnd(&pipe);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="share", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    ops = {e.name: e for e in cm.by_kind(EntityKind.OPERATION)}
    start = ops["InitShareBufStart"]
    end = ops["InitShareBufEnd"]
    assert start.attrs.get("root_status") == "REACHED"
    assert end.attrs.get("root_status") == "REACHED"
    assert start.attrs.get("mechanism") == "share"
    assert end.attrs.get("mechanism") == "share"
    assert not [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "InitBuffer"]


def test_prove_loadalign_without_arch_still_open() -> None:
    lex_load, spell_load = _prove_ascendc_api_root(callee="LoadAlign")
    assert lex_load and spell_load == "LoadAlign"
