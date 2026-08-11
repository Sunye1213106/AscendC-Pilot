# -*- coding: utf-8 -*-
"""Kernel Root Trace unit tests — wrappers / aliases → AscendC root."""

from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_root_trace import finalize_kernel_root_trace
from uo_init.semantics import registry as semreg


def _seed(cm: CodeMap, root: Path, *, files: list[str] | None = None) -> None:
    cm.upsert(
        EntityKind.KERNEL,
        "Process",
        attrs={"source_signature": True, "source_definition": True},
        file="op_kernel/arch35/process.h",
        line=4,
    )
    selected = files or [str(root / "op_kernel" / "arch35" / "process.h")]
    cm.meta["kernel_tiling_closure"] = {
        "selected_kernel_files": selected,
        "kernel_reachable_scopes": 1,
    }


def test_nested_wrapper_and_alias_reach_localtensor(tmp_path: Path) -> None:
    root = tmp_path / "wrap"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        using MyTensor = AscendC::LocalTensor<float>;

        class Inner {
         public:
          MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> storage;
          void Lock() { storage.LockProd(); }
        };

        class Outer {
         public:
          Inner inner;
          void Lock() { inner.Lock(); }
        };

        class Process {
         public:
          Outer x;
          MyTensor ub;
          GlobalTensor<float> gm;
          __aicore__ inline void Process() {
            DataCopy(ub, gm);
            x.Lock();
            SetFlag<HardEvent::MTE2_V>(EVENT_ID0);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="wrap", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    meta = cm.meta.get("kernel_root_trace") or {}
    assert int(meta.get("operations") or 0) >= 1
    assert int(meta.get("buffers") or 0) >= 1

    # Alias MyTensor → AscendC LocalTensor
    aliases = [
        e
        for e in cm.by_kind(EntityKind.TYPE)
        if e.name == "MyTensor" and e.attrs.get("role") == "type_alias"
    ]
    assert aliases, "expected MyTensor alias TYPE"
    assert aliases[0].attrs.get("root_status") == "REACHED"

    # Nested WRAPS: Outer → Inner → MutexBuffer path should mark Outer REACHED
    outer = next((e for e in cm.by_kind(EntityKind.TYPE) if e.name == "Outer"), None)
    assert outer is not None
    wraps = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.WRAPS.value
    ]
    assert wraps, "expected WRAPS edges from class members"

    # DataCopy call rooted at AscendC
    ops = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "DataCopy"]
    assert ops
    assert ops[0].attrs.get("root_status") == "REACHED"
    rooted = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.ROOTED_AT.value and r.src == ops[0].id
    ]
    assert rooted

    # Variable rename / wrapper rename should not matter — ub still LocalTensor-rooted
    ub = next((b for b in cm.by_kind(EntityKind.BUFFER) if b.name == "ub"), None)
    assert ub is not None
    assert ub.attrs.get("root_status") == "REACHED"

    # No execution pairing / pipeline meta
    assert "kernel_execution_pipeline" not in cm.meta
    assert meta.get("gap_counts") is not None


def test_unknown_project_type_without_path_is_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "unk"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class OrphanHolder {
         public:
          int not_a_buffer;
        };
        class Process {
         public:
          OrphanHolder h;
          __aicore__ inline void Process() {
            LocalTensor<float> ub;
            GlobalTensor<float> gm;
            DataCopy(ub, gm);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="unk", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    # Non-storage class members are not modeled as wrapper TYPEs.
    orphan = next((e for e in cm.by_kind(EntityKind.TYPE) if e.name == "OrphanHolder"), None)
    assert orphan is None or orphan.attrs.get("root_status") != "REACHED"
    ub = next(b for b in cm.by_kind(EntityKind.BUFFER) if b.name == "ub")
    assert ub.attrs.get("root_status") == "REACHED"


def test_policy_get_and_template_gettensor_root_at_localtensor(tmp_path: Path) -> None:
    root = tmp_path / "view"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class MutexBuffersPolicySingleBuffer {
         public:
          MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> buffer_;
          MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> &Get() { return buffer_; }
        };
        class Process {
         public:
          MutexBuffersPolicySingleBuffer commonL1Buf;
          using L1MutexBufT = MutexBuffer<BufferType::L1, SyncType::NO_SYNC>;
          L1MutexBufT dyL1Buffer;
          __aicore__ inline void Process() {
            dyL1Buffer = commonL1Buf.Get();
            LocalTensor<float> dyL1Tensor = dyL1Buffer.template GetTensor<float>();
            GlobalTensor<float> gm;
            DataCopy(dyL1Tensor, gm);
            dyL1Buffer.LockProd();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="view", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    gets = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver")
    ]
    assert gets, "expected policy Get call with receiver"
    assert all(e.attrs.get("root") == "AscendC::LocalTensor" for e in gets)
    assert all(e.attrs.get("wrapper") == "Get" for e in gets)

    gts = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "GetTensor" and e.attrs.get("receiver") == "dyL1Buffer"
    ]
    assert gts, "expected .template GetTensor call site"
    assert all(e.attrs.get("root") == "AscendC::LocalTensor" for e in gts)

    lps = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "LockProd"]
    assert lps and all(e.attrs.get("root") == "AscendC::Lock" for e in lps)
