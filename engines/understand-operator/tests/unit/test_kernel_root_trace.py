# -*- coding: utf-8 -*-
"""Kernel Root Trace unit tests — source graph → fixed-point → AscendC roots."""

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


def _type(cm: CodeMap, name: str):
    return next((e for e in cm.by_kind(EntityKind.TYPE) if e.name == name), None)


def _wraps_path(cm: CodeMap, start_name: str, end_name: str) -> bool:
    """True if start can reach end along WRAPS edges."""
    start = _type(cm, start_name)
    if start is None:
        return False
    adj: dict[str, set[str]] = {}
    for r in cm.relations.values():
        if r.kind_name() != RelationKind.WRAPS.value:
            continue
        adj.setdefault(r.src, set()).add(r.dst)
    seen = {start.id}
    stack = [start.id]
    while stack:
        cur = stack.pop()
        ent = cm.entities.get(cur)
        if ent and ent.name == end_name:
            return True
        if ent and ent.attrs.get("catalog") == "ascendc" and end_name in ent.name:
            return True
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def test_three_layer_wrapper_and_arbitrary_names(tmp_path: Path) -> None:
    root = tmp_path / "wrap3"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Banana {
         public:
          MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> hello;
        };

        class Orange {
         public:
          Banana foo;
        };

        class Top {
         public:
          Orange bar;
        };

        class Process {
         public:
          Top outer;
          __aicore__ inline void Process() {
            LocalTensor<float> banana;
            GlobalTensor<float> gm;
            DataCopy(banana, gm);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="wrap3", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    for name in ("Banana", "Orange", "Top"):
        ent = _type(cm, name)
        assert ent is not None, f"expected TYPE {name}"
        assert ent.attrs.get("root_status") == "REACHED", f"{name} attrs={ent.attrs}"
        assert "LocalTensor" in str(ent.attrs.get("root") or "")

    assert _wraps_path(cm, "Top", "Orange")
    assert _wraps_path(cm, "Orange", "Banana")
    assert _wraps_path(cm, "Banana", "MutexBuffer") or _wraps_path(cm, "Banana", "LocalTensor")
    assert _wraps_path(cm, "Top", "LocalTensor") or _wraps_path(cm, "Top", "MutexBuffer")

    banana = next(b for b in cm.by_kind(EntityKind.BUFFER) if b.name == "banana")
    assert banana.attrs.get("root_status") == "REACHED"
    assert banana.file
    assert int(banana.line_start or 0) > 0


def test_alias_chain_and_typedef(tmp_path: Path) -> None:
    root = tmp_path / "alias"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        using Mid = AscendC::LocalTensor<float>;
        using MyTensor = Mid;
        typedef AscendC::GlobalTensor<float> MyGm;

        class Process {
         public:
          MyTensor ub;
          MyGm gm;
          __aicore__ inline void Process() {
            DataCopy(ub, gm);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="alias", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    for name in ("Mid", "MyTensor", "MyGm"):
        ent = _type(cm, name)
        assert ent is not None
        assert ent.attrs.get("root_status") == "REACHED"
    aliases = [r for r in cm.relations.values() if r.kind_name() == RelationKind.ALIASES.value]
    assert aliases


def test_alias_plus_nested_wrapper(tmp_path: Path) -> None:
    root = tmp_path / "mix"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        using StorageT = MutexBuffer<BufferType::UB, SyncType::NO_SYNC>;
        class Inner {
         public:
          StorageT storage;
        };
        class Outer {
         public:
          Inner inner;
        };
        class Process {
         public:
          Outer x;
          __aicore__ inline void Process() {}
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="mix", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    assert _type(cm, "Inner").attrs.get("root_status") == "REACHED"
    assert _type(cm, "Outer").attrs.get("root_status") == "REACHED"
    assert _type(cm, "StorageT").attrs.get("root_status") == "REACHED"


def test_unknown_class_unresolved(tmp_path: Path) -> None:
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
    orphan = _type(cm, "OrphanHolder")
    assert orphan is None or orphan.attrs.get("root_status") != "REACHED"
    ub = next(b for b in cm.by_kind(EntityKind.BUFFER) if b.name == "ub")
    assert ub.attrs.get("root_status") == "REACHED"


def test_fake_ub_gm_name_not_reached(tmp_path: Path) -> None:
    """Variable/class names with Ub/Gm must not imply STORAGE/REACHED."""
    root = tmp_path / "fake"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class FakeUb {
         public:
          int x;
        };
        class Process {
         public:
          FakeUb fakeGm;
          int fooL1;
          __aicore__ inline void Process() {
            FakeUb fooUb;
            (void)fooUb;
            (void)fakeGm;
            (void)fooL1;
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="fake", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    fake = _type(cm, "FakeUb")
    assert fake is None or fake.attrs.get("root_status") != "REACHED"
    for b in cm.by_kind(EntityKind.BUFFER):
        if b.name in {"fakeGm", "fooUb", "fooL1"}:
            assert b.attrs.get("root_status") != "REACHED"
            assert b.attrs.get("root_kind") != "STORAGE" or b.attrs.get("root_status") != "REACHED"


def test_method_forwarding_arbitrary_names(tmp_path: Path) -> None:
    root = tmp_path / "fwd"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Inner {
         public:
          MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> storage;
          void Seize() { storage.LockProd(); }
        };
        class Outer {
         public:
          Inner inner;
          void Grab() { inner.Seize(); }
        };
        class Top {
         public:
          Outer outer;
          void Acquire() { outer.Grab(); }
        };
        class Process {
         public:
          Top holder;
          __aicore__ inline void Process() {
            holder.Acquire();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="fwd", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    assert _type(cm, "Inner").attrs.get("root_status") == "REACHED"
    assert _type(cm, "Outer").attrs.get("root_status") == "REACHED"
    assert _type(cm, "Top").attrs.get("root_status") == "REACHED"

    calls = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.CALLS.value
        and str(r.attrs.get("provenance") or "") == "kernel_root_trace"
    ]
    assert calls, "expected source CALLS edges"

    # Distinct method names must each appear with CALLS edges between them.
    methods = {e.name: e for e in cm.by_kind(EntityKind.METHOD)}
    for name in ("Acquire", "Grab", "Seize"):
        assert name in methods, f"missing METHOD {name}"

    method_calls = {
        (cm.entities[r.src].name, cm.entities[r.dst].name)
        for r in calls
        if r.src in cm.entities
        and r.dst in cm.entities
        and cm.entities[r.src].kind_name() == EntityKind.METHOD.value
        and cm.entities[r.dst].kind_name() == EntityKind.METHOD.value
    }
    assert ("Acquire", "Grab") in method_calls
    assert ("Grab", "Seize") in method_calls

    lock_ops = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "LockProd" and e.attrs.get("root_status") == "REACHED"
    ]
    assert lock_ops, "LockProd on MutexBuffer must bridge to AscendC::Lock"
    assert all("Lock" in str(e.attrs.get("root") or "") for e in lock_ops)

    assert methods["Acquire"].attrs.get("root_status") == "REACHED"
    assert methods["Seize"].attrs.get("root_status") == "REACHED"


def test_source_evidence_and_no_execution_semantics(tmp_path: Path) -> None:
    root = tmp_path / "ev"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            LocalTensor<float> ub;
            GlobalTensor<float> gm;
            DataCopy(ub, gm);
            SetFlag<HardEvent::MTE2_V>(EVENT_ID0);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="ev", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    ops = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "DataCopy"]
    assert ops
    assert ops[0].file
    assert int(ops[0].line_start or 0) > 0
    assert ops[0].attrs.get("provenance")

    forbidden = {
        "HAPPENS_BEFORE",
        "DATA_DEPENDS_ON",
        "PRECEDES",
        "READS_BUFFER",
        "WRITES_BUFFER",
        "SIGNALS",
        "WAITS_ON",
        "SYNCHRONIZES_WITH",
        "EXECUTES_ON",
        "EMITS_SYNC",
    }
    for r in cm.relations.values():
        assert r.kind_name() not in forbidden
    assert "kernel_execution_pipeline" not in cm.meta
    for e in cm.entities.values():
        assert "exec_rank" not in e.attrs


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

    assert _type(cm, "MyTensor").attrs.get("root_status") == "REACHED"
    assert _type(cm, "Inner").attrs.get("root_status") == "REACHED"
    assert _type(cm, "Outer").attrs.get("root_status") == "REACHED"
    ops = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "DataCopy"]
    assert ops and ops[0].attrs.get("root_status") == "REACHED"
    ub = next(b for b in cm.by_kind(EntityKind.BUFFER) if b.name == "ub")
    assert ub.attrs.get("root_status") == "REACHED"


def test_mutexbuffer_get_bridges_without_policy_catalog(tmp_path: Path) -> None:
    """Arbitrary policy-like class must close via composition, not name lists."""
    root = tmp_path / "view"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class WidgetHolder {
         public:
          MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> buffer_;
          MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> &Get() { return buffer_; }
        };
        class Process {
         public:
          WidgetHolder commonL1Buf;
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

    assert _type(cm, "WidgetHolder").attrs.get("root_status") == "REACHED"
    assert _type(cm, "L1MutexBufT").attrs.get("root_status") == "REACHED"

    gts = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "GetTensor" and e.attrs.get("receiver") == "dyL1Buffer"
    ]
    assert gts
    assert all(e.attrs.get("root") == "AscendC::LocalTensor" for e in gts)

    lps = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "LockProd"]
    assert lps and all(e.attrs.get("root") == "AscendC::Lock" for e in lps)
