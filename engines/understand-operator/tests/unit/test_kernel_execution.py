# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from collections import Counter

from uo_init.ids import operation_site_id
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_data_deps import finalize_kernel_data_deps
from uo_init.passes.kernel_execution import finalize_kernel_execution
from uo_init.passes.kernel_pipeline import finalize_kernel_pipeline
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
            LocalTensor<T> tmpUb;
            GlobalTensor<T> outGm;
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


def _toy_cross_file(tmp_path: Path) -> Path:
    root = tmp_path / "toy_cross"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "helper.h").write_text(
        """
        template <typename T>
        __aicore__ inline void HelperCopy(LocalTensor<T> dst, GlobalTensor<T> src) {
          DataCopy(dst, src);
        }
        """,
        encoding="utf-8",
    )
    (arch / "process.h").write_text(
        """
        #include "helper.h"
        template <typename T>
        class Process {
         public:
          __aicore__ inline void Process() {
            LocalTensor<T> qUb;
            GlobalTensor<T> qGm;
            LocalTensor<T> tmpUb;
            SetFlag(HARD_EVENT, PIPE_MTE2, EVENT_ID0);
            HelperCopy(qUb, qGm);
            WaitFlag(HARD_EVENT, PIPE_MTE2, EVENT_ID0);
            Exp(tmpUb, qUb);
          }
        };
        """,
        encoding="utf-8",
    )
    return root


def _seed_kernel(cm: CodeMap, root: Path, *, files: list[str] | None = None) -> None:
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
    # this->dyGm[...] must resolve to dyGm, not "this".
    reads2, writes2 = semreg.arg_effects(
        "DataCopy", ["dyL1Tensor", "this->dyGm[runInfo.dyOffset]"]
    )
    assert writes2 == ["dyL1Tensor"]
    assert reads2 == ["dyGm"]
    assert semreg.classify("WaitFlag")[0] == "sync_wait"


def test_kernel_execution_extracts_ops_buffers_sync_and_order(tmp_path: Path) -> None:
    root = _toy_kernel(tmp_path)
    cm = CodeMap(op_name="toy", architecture="arch35")
    _seed_kernel(cm, root)

    finalize_kernel_execution(cm, root, architecture="arch35")
    finalize_kernel_data_deps(cm)
    finalize_kernel_pipeline(cm)

    ops = cm.by_kind(EntityKind.OPERATION)
    assert ops, "expected AscendC operations from lexical/clang path"
    callees = [e.name for e in ops]
    assert "DataCopy" in callees
    assert "Exp" in callees
    assert "SetFlag" in callees
    assert "WaitFlag" in callees

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
    assert isinstance(meta.get("quality"), dict)
    assert int((meta.get("quality") or {}).get("ops") or 0) >= 4

    q = CodeMapQuery(codemap=cm)
    overview = q.kernel_overview()
    assert overview["operations"] >= 4
    life = q.buffer_lifecycle("qUb")
    assert life is not None
    assert life.get("status") != "AMBIGUOUS" or life.get("candidates")
    assert life.get("buffer") == "qUb" or (
        life.get("status") == "AMBIGUOUS"
        and any(c.get("buffer") == "qUb" for c in life.get("candidates") or [])
    )
    assert "buffer_slots" in life or life.get("status") == "AMBIGUOUS"
    assert "double_buffer" not in (life if life.get("status") != "AMBIGUOUS" else {})


def test_sync_pairing_emits_happens_before_when_unambiguous(tmp_path: Path) -> None:
    root = _toy_kernel(tmp_path)
    cm = CodeMap(op_name="toy", architecture="arch35")
    _seed_kernel(cm, root)
    finalize_kernel_execution(cm, root, architecture="arch35")
    assert cm.by_kind(EntityKind.SYNC_EVENT)
    meta = cm.meta.get("kernel_execution") or {}
    assert int(meta.get("sync_paired") or 0) == 1
    assert int(meta.get("emits_sync") or 0) >= 2
    kinds = {r.kind_name() for r in cm.relations.values()}
    assert RelationKind.EMITS_SYNC.value in kinds
    assert RelationKind.HAPPENS_BEFORE.value in kinds
    assert RelationKind.SIGNALS.value in kinds


def test_data_deps_raw_datacopy_to_exp(tmp_path: Path) -> None:
    root = _toy_kernel(tmp_path)
    cm = CodeMap(op_name="toy", architecture="arch35")
    _seed_kernel(cm, root)
    finalize_kernel_execution(cm, root, architecture="arch35")
    finalize_kernel_data_deps(cm)

    raw = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.DATA_DEPENDS_ON.value
        and str(r.attrs.get("hazard") or "") == "RAW"
    ]
    assert raw, "expected RAW DATA_DEPENDS_ON on shared buffer"
    # DataCopy writes qUb, Exp reads qUb → RAW or HB via data dep.
    ops = {e.id: e for e in cm.by_kind(EntityKind.OPERATION)}
    found = False
    for rel in raw:
        src = ops.get(rel.src)
        dst = ops.get(rel.dst)
        if not src or not dst:
            continue
        if src.name == "Exp" and dst.name == "DataCopy":
            found = True
            break
    assert found, "expected Exp DATA_DEPENDS_ON DataCopy (RAW on qUb)"

    hb = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.HAPPENS_BEFORE.value
        and str(r.attrs.get("provenance") or "") == "kernel_data_dep_raw"
    ]
    assert hb


def test_pipeline_copy_direction_and_no_raw_overlap(tmp_path: Path) -> None:
    root = _toy_kernel(tmp_path)
    cm = CodeMap(op_name="toy", architecture="arch35")
    _seed_kernel(cm, root)
    finalize_kernel_execution(cm, root, architecture="arch35")
    finalize_kernel_data_deps(cm)
    finalize_kernel_pipeline(cm)

    pipe = cm.meta.get("kernel_execution_pipeline") or {}
    assert int(pipe.get("copy_in_hints") or 0) >= 1
    assert int(pipe.get("copy_out_hints") or 0) >= 1
    stages = pipe.get("stages") or {}
    assert "CopyIn" in stages or any(
        str(e.attrs.get("pipeline_stage_hint") or "") == "CopyIn"
        for e in cm.by_kind(EntityKind.OPERATION)
    )

    names = Counter(e.name for e in cm.by_kind(EntityKind.OPERATION))
    assert names.get("InitBuffer", 0) >= 1
    assert names.get("AllocTensor", 0) >= 1
    assert any(
        b.attrs.get("queue_depth") == 2 for b in cm.by_kind(EntityKind.BUFFER)
    ), "InitBuffer(..., 2, ...) must stamp queue_depth"

    raw_pairs = {
        (r.src, r.dst)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.DATA_DEPENDS_ON.value
        and str(r.attrs.get("hazard") or "") == "RAW"
    }
    for pair in pipe.get("overlap_capable_pairs") or []:
        a, b = pair.get("a"), pair.get("b")
        assert (a, b) not in raw_pairs and (b, a) not in raw_pairs


def test_cross_file_exec_rank_follows_call_order(tmp_path: Path) -> None:
    root = _toy_cross_file(tmp_path)
    cm = CodeMap(op_name="toy_cross", architecture="arch35")
    files = [
        str(root / "op_kernel" / "arch35" / "process.h"),
        str(root / "op_kernel" / "arch35" / "helper.h"),
    ]
    _seed_kernel(cm, root, files=files)
    # CALLS edge so exec_order can expand HelperCopy under Process.
    process = cm.upsert(
        EntityKind.FUNCTION,
        "Process",
        attrs={"short_name": "Process"},
        file="op_kernel/arch35/process.h",
        line=5,
    )
    helper = cm.upsert(
        EntityKind.FUNCTION,
        "HelperCopy",
        attrs={"short_name": "HelperCopy"},
        file="op_kernel/arch35/helper.h",
        line=3,
    )
    cm.link(
        RelationKind.CALLS,
        process.id,
        helper.id,
        attrs={
            "provenance": "source_kernel_call_bound",
            # Must sit after SetFlag and before WaitFlag in process.h lexical lines.
            "line": 12,
            "sites": [{"line": 12, "column": 1}],
        },
        status="confirmed",
    )

    finalize_kernel_execution(cm, root, architecture="arch35")
    ops = {e.name: e for e in cm.by_kind(EntityKind.OPERATION)}
    # Prefer last occurrence names; ranks must respect call expand order.
    set_op = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "SetFlag")
    copy_op = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "DataCopy")
    wait_op = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "WaitFlag")
    exp_op = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "Exp")
    ranks = {
        "SetFlag": int(set_op.attrs.get("exec_rank")),
        "DataCopy": int(copy_op.attrs.get("exec_rank")),
        "WaitFlag": int(wait_op.attrs.get("exec_rank")),
        "Exp": int(exp_op.attrs.get("exec_rank")),
    }
    assert ranks["SetFlag"] < ranks["DataCopy"] < ranks["WaitFlag"] < ranks["Exp"], ranks
    # Without exec_rank, helper.h DataCopy would sort before process.h SetFlag by path.
    assert copy_op.file.endswith("helper.h") or "helper" in copy_op.file
    assert set_op.file.endswith("process.h") or "process" in set_op.file
