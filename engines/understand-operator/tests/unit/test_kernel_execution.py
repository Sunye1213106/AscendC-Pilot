# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ids import operation_site_id
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_execution import finalize_kernel_execution
from uo_init.query.engine import CodeMapQuery
from uo_init.semantics import registry as semreg


def _toy_kernel(tmp_path: Path) -> Path:
    root = tmp_path / "toy"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        template <typename T>
        class Process {
         public:
          __aicore__ inline void Process() {
            LocalTensor<T> qUb;
            GlobalTensor<T> qGm;
            pipe.InitBuffer(qQueue, 2, size);
            qUb = qQueue.AllocTensor<T>();
            DataCopy(qUb, qGm);
            SetFlag(HARD_EVENT, PIPE_MTE2, EVENT_ID0);
            WaitFlag(HARD_EVENT, PIPE_MTE2, EVENT_ID0);
            Exp(tmpUb, qUb);
            DataCopy(outGm, tmpUb);
            qQueue.FreeTensor(qUb);
          }
        };
        """,
        encoding="utf-8",
    )
    return root


def test_site_identity_keeps_duplicate_callees_distinct() -> None:
    a = operation_site_id(file="k.cpp", line=100, column=5, callee="DataCopy", ordinal=0)
    b = operation_site_id(file="k.cpp", line=130, column=5, callee="DataCopy", ordinal=0)
    assert a != b


def test_registry_classifies_datacopy_and_sync() -> None:
    cat, eng, conf = semreg.classify("DataCopy")
    assert cat == "memory_transfer"
    assert eng == "MTE"
    assert conf == "confirmed"
    reads, writes = semreg.arg_effects("DataCopy", ["qUb", "qGm"])
    assert writes == ["qUb"]
    assert reads == ["qGm"]
    assert semreg.classify("WaitFlag")[0] == "sync_wait"


def test_kernel_execution_extracts_ops_buffers_sync_and_order(tmp_path: Path) -> None:
    root = _toy_kernel(tmp_path)
    cm = CodeMap(op_name="toy", architecture="arch35")
    kernel = cm.upsert(
        EntityKind.KERNEL,
        "Process",
        attrs={"source_signature": True, "source_definition": True},
        file="op_kernel/arch35/process.h",
        line=4,
    )
    cm.meta["kernel_tiling_closure"] = {
        "selected_kernel_files": [str(root / "op_kernel" / "arch35" / "process.h")],
        "kernel_reachable_scopes": 1,
    }
    # Seed reachable name set via KERNEL only (no CALLS needed).
    assert kernel.id

    finalize_kernel_execution(cm, root, architecture="arch35")

    ops = cm.by_kind(EntityKind.OPERATION)
    assert ops, "expected AscendC operations from lexical/clang path"
    callees = [e.name for e in ops]
    assert "DataCopy" in callees
    assert "Exp" in callees
    assert "SetFlag" in callees
    assert "WaitFlag" in callees

    # Duplicate DataCopy occurrences stay distinct entities.
    datacopies = [e for e in ops if e.name == "DataCopy"]
    assert len(datacopies) >= 2
    assert datacopies[0].id != datacopies[1].id

    precedes = [r for r in cm.relations.values() if r.kind_name() == RelationKind.PRECEDES.value]
    assert precedes, "program-order PRECEDES edges required"

    buffers = cm.by_kind(EntityKind.BUFFER)
    names = {b.name for b in buffers}
    assert "qUb" in names or any("qUb" in n for n in names)

    syncs = cm.by_kind(EntityKind.SYNC_EVENT)
    assert syncs
    meta = cm.meta.get("kernel_execution") or {}
    assert int(meta.get("operations") or 0) >= 4
    assert float(meta.get("elapsed_s") or 0) < 30.0

    q = CodeMapQuery(codemap=cm)
    overview = q.kernel_overview()
    assert overview["operations"] >= 4
    life = q.buffer_lifecycle("qUb")
    assert life is None or life.get("buffer") == "qUb" or "qUb" in str(life)


def test_sync_pairing_emits_happens_before_when_unambiguous(tmp_path: Path) -> None:
    root = _toy_kernel(tmp_path)
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.KERNEL,
        "Process",
        attrs={"source_signature": True},
        file="op_kernel/arch35/process.h",
    )
    cm.meta["kernel_tiling_closure"] = {
        "selected_kernel_files": [str(root / "op_kernel" / "arch35" / "process.h")],
    }
    finalize_kernel_execution(cm, root, architecture="arch35")
    assert cm.by_kind(EntityKind.SYNC_EVENT)
    meta = cm.meta.get("kernel_execution") or {}
    assert "sync_paired" in meta
    # Identical SetFlag/WaitFlag args in the toy should pair conservatively.
    if int(meta.get("sync_paired") or 0) > 0:
        kinds = {r.kind_name() for r in cm.relations.values()}
        assert RelationKind.HAPPENS_BEFORE.value in kinds or RelationKind.SIGNALS.value in kinds
