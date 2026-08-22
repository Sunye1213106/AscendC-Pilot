# -*- coding: utf-8 -*-
"""Kernel Root Trace unit tests — source graph → fixed-point → AscendC roots."""

from __future__ import annotations

from pathlib import Path
import re

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_root_trace import finalize_kernel_root_trace
from uo_init.semantics import registry as semreg


_WRAPPER_STUB = """
namespace AscendC {
struct Mutex {
  template <typename Pipe>
  static void Lock(int id) {}
  template <typename Pipe>
  static void Unlock(int id) {}
  static int AllocMutexID() { return 0; }
  static void ReleaseMutexID(int) {}
};
}
template <typename BufferT, typename SyncT>
class MutexBuffer {
 public:
  LocalTensor<uint8_t> tensor_;
  int mutexId_;
  void Init() { mutexId_ = AscendC::Mutex::AllocMutexID(); }
  template <typename Pipe>
  void Lock() { AscendC::Mutex::Lock<Pipe>(mutexId_); }
  template <typename Pipe>
  void Unlock() { AscendC::Mutex::Unlock<Pipe>(mutexId_); }
  void LockProd() { Lock<int>(); }
  void UnlockProd() { Unlock<int>(); }
  template <typename T>
  LocalTensor<T> GetTensor() { return tensor_.template ReinterpretCast<T>(); }
};
"""


_BUFFER_STUB = """
template <typename Pos>
class Buffer {
 public:
  LocalTensor<uint8_t> tensor_;
  template <typename Event>
  void Set() { SetFlag<Event>(0); }
  template <typename Event>
  void Wait() { WaitFlag<Event>(0); }
};
"""


def _ensure_wrapper_stub(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    prefix = ""
    if "MutexBuffer" in text and "class MutexBuffer" not in text and "struct MutexBuffer" not in text:
        prefix += _WRAPPER_STUB + "\n"
    if (
        re.search(r"\bBuffer\s*<", text)
        and "class Buffer" not in text
        and "struct Buffer" not in text
    ):
        prefix += _BUFFER_STUB + "\n"
    if prefix:
        path.write_text(prefix + text, encoding="utf-8")


def _seed(cm: CodeMap, root: Path, *, files: list[str] | None = None) -> None:
    cm.upsert(
        EntityKind.KERNEL,
        "Process",
        attrs={"source_signature": True, "source_definition": True},
        file="op_kernel/arch35/process.h",
        line=4,
    )
    selected = files or [str(root / "op_kernel" / "arch35" / "process.h")]
    for path in selected:
        _ensure_wrapper_stub(Path(path))
    cm.meta["kernel_tiling_closure"] = {
        "selected_kernel_files": selected,
        "kernel_reachable_scopes": 1,
    }


def _type(cm: CodeMap, name: str):
    return next((e for e in cm.by_kind(EntityKind.TYPE) if e.name == name), None)


def _methods(cm: CodeMap, name: str, *, receiver: str = ""):
    rows = [e for e in cm.by_kind(EntityKind.METHOD) if e.name == name]
    if not receiver:
        return rows
    return [e for e in rows if receiver in (e.attrs.get("receivers") or [])]


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

    lockprod_ops = [
        e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "LockProd"
    ]
    assert not lockprod_ops, "LockProd is a project METHOD, not a CANN OPERATION root"
    lock_ops = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Lock" and e.attrs.get("root_status") == "REACHED"
    ]
    assert lock_ops, "wrapper LockProd must reach CANN AscendC::Mutex::Lock"
    assert all("Lock" in str(e.attrs.get("root") or "") for e in lock_ops)
    lockprod_methods = _methods(cm, "LockProd")
    assert lockprod_methods, "LockProd must remain a METHOD"
    assert any(e.attrs.get("root_status") == "REACHED" for e in lockprod_methods)

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
            TPipe pipe;
            TQue<QuePosition::VECIN, 1> queue;
            DataCopy(ub, gm);
            SetFlag<HardEvent::MTE2_V>(EVENT_ID0);
            WaitFlag<HardEvent::MTE2_V>(EVENT_ID0);
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
        "READS_BUFFER",
        "WRITES_BUFFER",
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
    signal = next(r for r in cm.relations.values() if r.kind_name() == "SIGNALS")
    event = cm.entities[signal.dst]
    assert event.kind_name() == EntityKind.EVENT.value
    assert event.attrs["identity"] == "EVENT_ID0"
    assert cm.by_kind(EntityKind.PIPE)
    assert cm.by_kind(EntityKind.QUEUE)
    assert any(r.kind_name() == "AWAITS" and r.dst == event.id for r in cm.relations.values())
    assert any(r.kind_name() == "PRECEDES" for r in cm.relations.values())
    sync_op = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "SetFlag")
    assert sync_op.attrs["args"] == ["EVENT_ID0"]
    assert sync_op.attrs["template_args"] == ["HardEvent::MTE2_V"]
    assert "receiver" in sync_op.attrs
    assert "receiver_type" in sync_op.attrs
    assert "receiver_canonical_type" in sync_op.attrs
    assert sync_op.attrs.get("flag_paired") is True
    wait_op = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "WaitFlag")
    assert wait_op.attrs.get("flag_paired") is True
    gaps = (cm.meta.get("kernel_root_trace") or {}).get("gaps") or []
    assert not any(g.get("code") == "UNPAIRED_FLAG_SYNC" for g in gaps)
    hw_pipes = [
        e for e in cm.by_kind(EntityKind.PIPE) if str(e.name or "").startswith("PIPE_")
    ]
    assert hw_pipes
    assert all(e.attrs.get("catalog") == "ascendc" for e in hw_pipes)
    inst = next(e for e in cm.by_kind(EntityKind.PIPE) if e.name == "pipe")
    assert inst.attrs.get("role") == "launch_instance"
    assert inst.attrs.get("kernel_file")


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

    gts = _methods(cm, "GetTensor", receiver="dyL1Buffer")
    assert gts, "GetTensor is a project METHOD, not a CANN OPERATION"
    assert not any(
        e.name == "GetTensor" for e in cm.by_kind(EntityKind.OPERATION)
    )
    casts = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "ReinterpretCast" and e.attrs.get("root_status") == "REACHED"
    ]
    assert casts, "GetTensor body must reach CANN ReinterpretCast"

    lockprod_ops = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "LockProd"]
    assert not lockprod_ops
    lock_ops = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Lock" and e.attrs.get("root_status") == "REACHED"
    ]
    assert lock_ops
    assert all("Lock" in str(e.attrs.get("root") or "") for e in lock_ops)

    # Project WidgetHolder::Get is a METHOD, not an OPERATION.
    project_gets = _methods(cm, "Get", receiver="commonL1Buf")
    assert project_gets, "expected METHOD for commonL1Buf.Get()"
    assert all(e.attrs.get("root_status") != "REACHED" for e in project_gets)
    assert all("AscendC::Get" not in str(e.attrs.get("root") or "") for e in project_gets)
    assert all(e.status == "extracted" for e in project_gets)
    assert all(str(e.attrs.get("qualified_name") or "").endswith("WidgetHolder::Get") for e in project_gets)
    assert not any(e.name == "Get" and e.attrs.get("receiver") == "commonL1Buf" for e in cm.by_kind(EntityKind.OPERATION))


def test_project_get_lock_not_ascendc_root(tmp_path: Path) -> None:
    """Short-name catalog hits on project methods must not prove REACHED."""
    root = tmp_path / "false_root"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Foo {
         public:
          void Get() {}
          void Lock() {}
          void DataCopy() {}
        };
        class Process {
         public:
          Foo foo;
          __aicore__ inline void Process() {
            foo.Get();
            foo.Lock();
            foo.DataCopy();
            LocalTensor<float> ub;
            GlobalTensor<float> gm;
            DataCopy(ub, gm);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="false_root", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    for name in ("Get", "Lock", "DataCopy"):
        member_ops = _methods(cm, name, receiver="foo")
        assert member_ops, f"missing member METHOD {name}"
        assert all(e.attrs.get("root_status") != "REACHED" for e in member_ops), name
        assert all(e.status == "extracted" for e in member_ops), name
        assert all(str(e.attrs.get("qualified_name") or "") == f"Foo::{name}" for e in member_ops), name
        assert not any(
            e.name == name and e.attrs.get("receiver") == "foo" for e in cm.by_kind(EntityKind.OPERATION)
        ), name

    free_dc = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "DataCopy" and not e.attrs.get("receiver")
    ]
    assert free_dc and all(e.attrs.get("root_status") == "REACHED" for e in free_dc)


def test_method_identity_not_merged_by_short_name(monkeypatch, tmp_path: Path) -> None:
    """A::Get and B::Get must remain distinct METHOD entities when identity exists."""
    from uo_init.passes import kernel_scan as kscan

    root = tmp_path / "collision"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {}
        };
        """,
        encoding="utf-8",
    )
    fake_calls = [
        {
            "caller": "Process",
            "caller_qualified": "Process::Process",
            "caller_usr": "c:@S@Process@F@Process#",
            "callee": "Get",
            "callee_qualified": "A::Get",
            "callee_usr": "c:@S@A@F@Get#",
            "callee_decl_file": str(arch / "process.h"),
            "receiver": "a",
            "receiver_type": "A",
            "file": str(arch / "process.h"),
            "line": 10,
            "column": 1,
            "args": [],
            "provenance": "test_inject",
        },
        {
            "caller": "Process",
            "caller_qualified": "Process::Process",
            "caller_usr": "c:@S@Process@F@Process#",
            "callee": "Get",
            "callee_qualified": "B::Get",
            "callee_usr": "c:@S@B@F@Get#",
            "callee_decl_file": str(arch / "process.h"),
            "receiver": "b",
            "receiver_type": "B",
            "file": str(arch / "process.h"),
            "line": 11,
            "column": 1,
            "args": [],
            "provenance": "test_inject",
        },
    ]

    def _fake_walks(*_a, **_k):
        return fake_calls, [], [], "test_inject"

    monkeypatch.setattr(kscan, "collect_call_sites_from_walks", _fake_walks)
    monkeypatch.setattr(kscan, "lexical_source_call_sites", lambda *a, **k: [])
    monkeypatch.setattr(
        kscan, "collect_type_graph_from_walks", lambda *a, **k: {"members": [], "aliases": [], "types": [], "bases": []}
    )

    cm = CodeMap(op_name="collision", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    gets = [e for e in cm.by_kind(EntityKind.METHOD) if e.attrs.get("spelling") == "Get"]
    assert len(gets) >= 2
    quals = {str(e.attrs.get("qualified_name") or "") for e in gets}
    assert "A::Get" in quals and "B::Get" in quals
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)


def test_calls_edge_keeps_multiple_sites(monkeypatch, tmp_path: Path) -> None:
    """Same caller→callee topology must accumulate sites evidence, not drop lines."""
    from uo_init.passes import kernel_scan as kscan

    root = tmp_path / "multisite"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {}
        };
        """,
        encoding="utf-8",
    )
    fake_calls = [
        {
            "caller": "Process",
            "caller_qualified": "Process::Process",
            "caller_usr": "c:@S@Process@F@Process#",
            "callee": "Helper",
            "callee_qualified": "Helper",
            "callee_usr": "c:@F@Helper#",
            "callee_decl_file": str(arch / "process.h"),
            "receiver": "",
            "file": str(arch / "process.h"),
            "line": 10,
            "column": 3,
            "args": [],
            "provenance": "test_inject",
        },
        {
            "caller": "Process",
            "caller_qualified": "Process::Process",
            "caller_usr": "c:@S@Process@F@Process#",
            "callee": "Helper",
            "callee_qualified": "Helper",
            "callee_usr": "c:@F@Helper#",
            "callee_decl_file": str(arch / "process.h"),
            "receiver": "",
            "file": str(arch / "process.h"),
            "line": 50,
            "column": 3,
            "args": [],
            "provenance": "test_inject",
        },
    ]

    def _fake_walks(*_a, **_k):
        return fake_calls, [], [], "test_inject"

    monkeypatch.setattr(kscan, "collect_call_sites_from_walks", _fake_walks)
    monkeypatch.setattr(kscan, "lexical_source_call_sites", lambda *a, **k: [])
    monkeypatch.setattr(
        kscan, "collect_type_graph_from_walks", lambda *a, **k: {"members": [], "aliases": [], "types": [], "bases": []}
    )

    cm = CodeMap(op_name="multisite", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    method_calls = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.CALLS.value
        and str(r.attrs.get("via") or "") == "source_call"
        and str(r.attrs.get("provenance") or "") == "kernel_root_trace"
    ]
    assert method_calls
    sites = method_calls[0].attrs.get("sites") or []
    lines = {int(s.get("line") or 0) for s in sites if isinstance(s, dict)}
    assert 10 in lines and 50 in lines


def test_templated_buffer_wraps_localtensor(tmp_path: Path) -> None:
    """Buffer<TPosition::...> composition must close to LocalTensor (not skip bare Buffer)."""
    root = tmp_path / "buf"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Foo {
         public:
          Buffer<TPosition::VECIN> storage;
        };
        class Process {
         public:
          Foo outer;
          __aicore__ inline void Process() {}
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="buf", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    foo = _type(cm, "Foo")
    assert foo is not None
    assert foo.attrs.get("root_status") == "REACHED"
    assert _wraps_path(cm, "Foo", "LocalTensor") or _wraps_path(cm, "Foo", "Buffer")


def test_prove_root_helpers() -> None:
    from uo_init.passes.kernel_root_trace import _prove_ascendc_api_root

    ok, spell = _prove_ascendc_api_root(
        callee="Get",
        callee_qualified="AscendC::Get",
        callee_decl_file="/cann/ascendc/basic_api.h",
    )
    assert ok and spell == "Get"

    bad, _ = _prove_ascendc_api_root(
        callee="Get",
        callee_qualified="WidgetHolder::Get",
        callee_usr="c:@S@WidgetHolder@F@Get#",
        callee_decl_file="op_kernel/arch35/process.h",
        receiver="commonL1Buf",
        has_identity=True,
    )
    assert not bad

    lex_ok, spell2 = _prove_ascendc_api_root(callee="DataCopy")
    assert lex_ok and spell2 == "DataCopy"

    lex_load, spell_load = _prove_ascendc_api_root(callee="LoadAlign")
    assert lex_load and spell_load == "LoadAlign"

    lex_init, spell_init = _prove_ascendc_api_root(callee="InitOutput")
    assert lex_init and spell_init == "InitOutput"

    lex_bad, _ = _prove_ascendc_api_root(callee="Get", receiver="x")
    assert not lex_bad

    bare_get, _ = _prove_ascendc_api_root(callee="Get")
    assert not bare_get

    or_bare, _ = _prove_ascendc_api_root(callee="Or")
    assert not or_bare

    expsub_lex, spell_exp = _prove_ascendc_api_root(callee="ExpSub")
    assert expsub_lex and spell_exp == "ExpSub"

    fused, spell_fused = _prove_ascendc_api_root(callee="FusedExpSub")
    assert fused and spell_fused == "ExpSub"

    member_sgb, _ = _prove_ascendc_api_root(callee="SetGlobalBuffer", receiver="queryGm")
    assert not member_sgb

    # Clang constructor sites spell qualified as ``RegTensor()`` while the
    # declaration lives under cann-asc-devkit — must still prove REACHED.
    ctor_ok, ctor_spell = _prove_ascendc_api_root(
        callee="RegTensor",
        callee_qualified="RegTensor()",
        callee_usr=(
            "c:kernel_reg_compute_struct_intf.h@N@AscendC@N@Reg@S@RegTensor>"
            "#f#@N@AscendC@N@Reg@RegTraitNumOne@F@RegTensor#"
        ),
        callee_decl_file=(
            "/opt/cann/cann-asc-devkit/x86_64-linux/asc/include/basic_api/"
            "reg_compute/kernel_reg_compute_struct_intf.h"
        ),
        has_identity=True,
    )
    assert ctor_ok and ctor_spell == "RegTensor"

    # Param/config structs in kernel_struct_*.h are framework types, not compute APIs.
    params_ok, params_spell = _prove_ascendc_api_root(
        callee="DataCopyExtParams",
        callee_qualified="DataCopyExtParams()",
        callee_decl_file=(
            "/opt/cann/cann-asc-devkit/x86_64-linux/asc/include/basic_api/"
            "kernel_struct_data_copy.h"
        ),
        has_identity=True,
    )
    assert params_ok and params_spell == "DataCopyExtParams"
    fix_ok, fix_spell = _prove_ascendc_api_root(
        callee="FixpipeParamsC310",
        callee_qualified="FixpipeParamsC310()",
        callee_decl_file=(
            "/opt/cann/cann-asc-devkit/x86_64-linux/asc/include/basic_api/"
            "kernel_struct_fixpipe.h"
        ),
        has_identity=True,
    )
    assert fix_ok and fix_spell == "FixpipeParamsC310"
    cfg_ok, cfg_spell = _prove_ascendc_api_root(
        callee="FixpipeConfig",
        callee_qualified="FixpipeConfig(CO2Layout, bool)",
        callee_decl_file=(
            "/opt/cann/cann-asc-devkit/x86_64-linux/asc/include/basic_api/"
            "kernel_struct_fixpipe.h"
        ),
        has_identity=True,
    )
    assert cfg_ok and cfg_spell == "FixpipeConfig"


def test_tque_enque_deque_outside_flag_pairing(tmp_path: Path) -> None:
    """TQue handshake is CANN-encapsulated; flag pair appearance stays for Set/Wait."""
    root = tmp_path / "tque"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            LocalTensor<float> ub;
            TQue<QuePosition::VECIN, 1> inQue;
            inQue.EnQue(ub);
            ub = inQue.DeQue();
            SetFlag<HardEvent::MTE2_V>(EVENT_ID0);
            WaitFlag<HardEvent::MTE2_V>(EVENT_ID0);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="tque", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    enque = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "EnQue")
    deque = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "DeQue")
    assert enque.attrs.get("mechanism") == "tque"
    assert deque.attrs.get("mechanism") == "tque"
    assert enque.attrs.get("root_status") == "REACHED"
    assert deque.attrs.get("root_status") == "REACHED"
    for op in (enque, deque):
        assert not any(
            r.src == op.id
            and r.kind_name() in {RelationKind.SIGNALS.value, RelationKind.AWAITS.value}
            for r in cm.relations.values()
        )
        assert op.attrs.get("flag_paired") is None
    queues = [
        other
        for _rel, other in cm.neighbors(enque.id, direction="out")
        if other.kind_name() == EntityKind.QUEUE.value
    ]
    assert queues, "EnQue must bind to the TQue QUEUE entity"
    assert queues[0].name == "inQue"

    setf = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "SetFlag")
    wait = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "WaitFlag")
    assert setf.attrs.get("flag_paired") is True
    assert wait.attrs.get("flag_paired") is True
    quality = (cm.meta.get("kernel_root_trace") or {}).get("quality") or {}
    assert int(quality.get("flag_pairs") or 0) >= 1
    assert int(quality.get("unpaired_flag_sync") or 0) == 0
    assert int(quality.get("tque_ops") or 0) >= 2
    gaps = (cm.meta.get("kernel_root_trace") or {}).get("gaps") or []
    assert not any(g.get("code") == "UNPAIRED_FLAG_SYNC" for g in gaps)


def test_arch_header_enque_outside_confirmed_tu(tmp_path: Path) -> None:
    """Preferred-dtype TU omits mixed-dtype headers; arch primitives still map."""
    root = tmp_path / "mixedpath"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    entry = root / "op_kernel" / "entry.cpp"
    entry.write_text("void KernelEntry() { DoFp16(); }\n", encoding="utf-8")
    (arch / "quant.h").write_text(
        """
        class Preprocess {
         public:
          __aicore__ inline void ConvertLinearTile()
          {
            TQue<QuePosition::VECIN, 1> weightQueue_;
            LocalTensor<int8_t> weightLocal;
            weightQueue_.EnQue(weightLocal);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="mixedpath", architecture="arch35")
    _seed(cm, root, files=[str(entry)])
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    enque = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "EnQue")
    assert enque.attrs.get("mechanism") == "tque"
    assert enque.file and "quant.h" in str(enque.file).replace("\\\\", "/")


def test_arch_neutral_kernel_enque_deque_template(tmp_path: Path) -> None:
    """TQue beside the entry TU (not under op_kernel/<arch>/) still maps."""
    root = tmp_path / "apt_style"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "tiling.h").write_text("struct Tiling {};\n", encoding="utf-8")
    entry = root / "op_kernel" / "entry.cpp"
    entry.write_text("void KernelEntry() { DoFp16(); }\n", encoding="utf-8")
    (root / "op_kernel" / "quant.h").write_text(
        """
        class Preprocess {
         public:
          __aicore__ inline void ConvertLinearTile()
          {
            TQue<QuePosition::VECIN, 1> weightQueue_;
            LocalTensor<int8_t> weightLocal;
            weightQueue_.EnQue(weightLocal);
            weightLocal = weightQueue_.DeQue<int8_t>();
          }
        };
        """,
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch22" / "old.h").parent.mkdir(parents=True, exist_ok=True)
    (root / "op_kernel" / "arch22" / "old.h").write_text(
        """
        class OldPath {
         public:
          __aicore__ inline void Convert()
          {
            TQue<QuePosition::VECIN, 1> q;
            LocalTensor<float> t;
            q.EnQue(t);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="apt_style", architecture="arch35")
    _seed(cm, root, files=[str(entry)])
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    enques = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "EnQue"]
    deques = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "DeQue"]
    assert len(enques) == 1
    assert enques[0].attrs.get("mechanism") == "tque"
    assert "quant.h" in str(enques[0].file or "").replace("\\\\", "/")
    assert "arch22" not in str(enques[0].file or "").replace("\\\\", "/")
    assert len(deques) == 1
    assert deques[0].attrs.get("mechanism") == "tque"
    assert deques[0].attrs.get("root_status") == "REACHED"


def test_selected_tu_primitives_survive_strict_reachability(tmp_path: Path) -> None:
    """Confirmed-TU catalog APIs still map when the walk did not reach the method."""
    root = tmp_path / "strict_tu"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {}
          __aicore__ inline void CopyIn() {
            LocalTensor<float> ub;
            TQue<QuePosition::VECIN, 1> inQue;
            inQue.EnQue(ub);
            Cast(dst, src, preg);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="strict_tu", architecture="arch35")
    _seed(cm, root)
    kernel = next(iter(cm.by_kind(EntityKind.KERNEL)))
    for name in ("HelperA", "HelperB", "HelperC"):
        fn = cm.upsert(EntityKind.FUNCTION, name, file="op_kernel/arch35/process.h", line=1)
        cm.link(
            RelationKind.CALLS,
            kernel.id,
            fn.id,
            attrs={"provenance": "source_kernel_call_bound"},
        )
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    enque = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "EnQue")
    cast = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "Cast")
    assert enque.attrs.get("root_status") == "REACHED"
    assert cast.attrs.get("root_status") == "REACHED"


def test_unpaired_flag_is_gap_but_enque_is_not(tmp_path: Path) -> None:
    """Missing WaitFlag is UNPAIRED_FLAG_SYNC; EnQue without DeQue is not."""
    root = tmp_path / "unpaired"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            LocalTensor<float> ub;
            TQue<QuePosition::VECIN, 1> inQue;
            inQue.EnQue(ub);
            SetFlag<HardEvent::MTE2_V>(EVENT_ID0);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="unpaired", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    enque = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "EnQue")
    assert enque.attrs.get("mechanism") == "tque"
    assert not any(
        r.src == enque.id
        and r.kind_name() in {RelationKind.SIGNALS.value, RelationKind.AWAITS.value}
        for r in cm.relations.values()
    )

    gaps = (cm.meta.get("kernel_root_trace") or {}).get("gaps") or []
    unpaired = [g for g in gaps if g.get("code") == "UNPAIRED_FLAG_SYNC"]
    assert unpaired, "SetFlag without WaitFlag must be recorded"
    assert all(g.get("present") == "SetFlag" for g in unpaired)
    assert all(g.get("missing") == "WaitFlag" for g in unpaired)
    assert all(g.get("present") != "EnQue" for g in unpaired)
    setf = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "SetFlag")
    assert setf.attrs.get("flag_paired") is False
    quality = (cm.meta.get("kernel_root_trace") or {}).get("quality") or {}
    assert int(quality.get("unpaired_flag_sync") or 0) >= 1


def test_tpipe_initbuffer_and_fetcheventid(tmp_path: Path) -> None:
    """TPipe::InitBuffer / FetchEventID root at TPipe, not TQue, and not Flag pairing."""
    root = tmp_path / "tpipe"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          TPipe *pipe;
          TQue<QuePosition::VECIN, 1> inQue;
          __aicore__ inline void Process() {
            pipe->InitBuffer(inQue, 1, 1024);
            event_t evt = static_cast<event_t>(GetTPipePtr()->FetchEventID(HardEvent::S_MTE2));
            WaitFlag<HardEvent::S_MTE2>(evt);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="tpipe", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    initb = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "InitBuffer")
    assert initb.attrs.get("root_status") == "REACHED"
    assert initb.attrs.get("mechanism") == "tpipe"
    assert initb.attrs.get("root") == "AscendC::InitBuffer"
    assert not any(
        r.src == initb.id
        and r.kind_name() in {RelationKind.SIGNALS.value, RelationKind.AWAITS.value}
        for r in cm.relations.values()
    )

    fetch = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "FetchEventID")
    assert fetch.attrs.get("root_status") == "REACHED"
    ptr = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "GetTPipePtr")
    assert ptr.attrs.get("root_status") == "REACHED"


def test_reg_loadalign_and_create_mask(tmp_path: Path) -> None:
    root = tmp_path / "reg"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            RegTensor<float> vreg;
            MaskReg preg = CreateMask<float, MaskPattern::ALL>();
            LoadAlign(vreg, ((__ubuf__ float *&)ptr));
            Mul(vreg, vreg, vreg, preg);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="reg", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    load = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "LoadAlign")
    mask = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "CreateMask")
    mul = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "Mul")
    assert load.attrs.get("root_status") == "REACHED"
    assert mask.attrs.get("root_status") == "REACHED"
    assert mul.attrs.get("root_status") == "REACHED"
    assert load.attrs.get("root_kind") == "REGISTER"


def test_setglobalbuffer_member_bridge(tmp_path: Path) -> None:
    root = tmp_path / "gm"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          GlobalTensor<float> queryGm;
          __aicore__ inline void Process(GM_ADDR query) {
            queryGm.SetGlobalBuffer((__gm__ float *)query);
            auto addr = queryGm.GetPhyAddr();
            InitOutput<float>(queryGm, 16, 0);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="gm", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    sgb = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "SetGlobalBuffer")
    phy = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "GetPhyAddr")
    inito = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "InitOutput")
    assert sgb.attrs.get("root_status") == "REACHED"
    assert phy.attrs.get("root_status") == "REACHED"
    assert inito.attrs.get("root_status") == "REACHED"


def test_tque_enque_without_recovered_type(tmp_path: Path) -> None:
    """EnQue on a receiver is TQue in CANN even when the TQue type is not recovered."""
    root = tmp_path / "tque_param"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void CopyIn() {
            LocalTensor<float> ub;
            yInQue.EnQue(ub);
            yInQue.DeQue();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="tque_param", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    enque = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "EnQue")
    deque = next(e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "DeQue")
    assert enque.attrs.get("root_status") == "REACHED"
    assert deque.attrs.get("root_status") == "REACHED"
    assert enque.attrs.get("mechanism") == "tque"
    assert deque.attrs.get("mechanism") == "tque"


def test_min_scalar_unresolved_vector_min_reached(tmp_path: Path) -> None:
    root = tmp_path / "minmax"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            int64_t a = Min(k, b);
            Min(vreg, vregA, vregB, preg);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="minmax", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    mins = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "Min"]
    assert len(mins) == 1
    assert mins[0].attrs.get("root_status") == "REACHED"
    four_arg = mins[0]
    assert len(four_arg.attrs.get("args") or []) >= 3
    scalar = [e for e in cm.by_kind(EntityKind.METHOD) if e.name == "Min"]
    assert scalar
    assert all(e.attrs.get("root_status") != "REACHED" for e in scalar)


def test_policy_get_binds_declaration_not_catalog(tmp_path: Path) -> None:
    """Receiver type + unique method is enough to name Get without AscendC::Get."""
    root = tmp_path / "policy_get"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "policy.h").write_text(
        """
        class MutexBuffer {
         public:
          __aicore__ inline void Init() {}
          template <typename T>
          __aicore__ inline LocalTensor<T> GetTensor() { return tensor_; }
        };
        class MutexBuffersPolicyDB {
         public:
          MutexBuffer<BufferType::L0A, SyncType::INNER_CORE_SYNC> ping_;
          __aicore__ inline MutexBuffer<BufferType::L0A, SyncType::INNER_CORE_SYNC> &Get() {
            return ping_;
          }
          __aicore__ inline void Init() {
            ping_.Init();
          }
        };
        """,
        encoding="utf-8",
    )
    (arch / "process.h").write_text(
        """
        #include "policy.h"
        class Process {
         public:
          __aicore__ inline void Process(
              MutexBuffersPolicyDB<BufferType::L0A, SyncType::INNER_CORE_SYNC> &aL0BuffsDb) {
            auto &l0aBuffer = aL0BuffsDb.Get();
            LocalTensor<float> L0ATensor = l0aBuffer.template GetTensor<float>();
            aL0BuffsDb.Init();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="policy_get", architecture="arch35")
    _seed(cm, root, files=[str(arch / "process.h"), str(arch / "policy.h")])
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    gets = _methods(cm, "Get", receiver="aL0BuffsDb")
    if not gets:
        gets = [
            e
            for e in cm.by_kind(EntityKind.METHOD)
            if e.name == "Get" and "MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "")
        ]
    assert gets
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "") for e in gets)

    inits = [
        e
        for e in cm.by_kind(EntityKind.METHOD)
        if e.name == "Init" and "MutexBuffersPolicyDB::Init" in str(e.attrs.get("qualified_name") or "")
    ]
    assert inits
    assert all(e.status == "extracted" for e in inits)

    ping_inits = [
        e
        for e in cm.by_kind(EntityKind.METHOD)
        if e.name == "Init" and "MutexBuffer::Init" in str(e.attrs.get("qualified_name") or "")
    ]
    assert ping_inits
    assert all("AscendC::Init" not in str(e.attrs.get("root") or "") for e in ping_inits)

    gts = _methods(cm, "GetTensor", receiver="l0aBuffer")
    if not gts:
        gts = _methods(cm, "GetTensor")
    assert gts, "GetTensor is a project METHOD"
    assert not any(e.name == "GetTensor" for e in cm.by_kind(EntityKind.OPERATION))


def test_unique_project_min_is_not_ascendc(tmp_path: Path) -> None:
    root = tmp_path / "proj_min"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        template <typename T1, typename T2>
        __aicore__ inline T1 Min(T1 a, T2 b) { return (a > b) ? b : a; }
        class Process {
         public:
          __aicore__ inline void Process() {
            int64_t a = Min(k, b);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="proj_min", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    mins = _methods(cm, "Min")
    assert mins
    assert all(e.status == "extracted" for e in mins)
    assert all(e.attrs.get("root_status") != "REACHED" for e in mins)
    assert all("Min" in str(e.attrs.get("qualified_name") or e.name) for e in mins)
    assert not any(e.name == "Min" for e in cm.by_kind(EntityKind.OPERATION))


def test_ambiguous_free_min_stays_unbound(tmp_path: Path) -> None:
    root = tmp_path / "ambig_min"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "a.h").write_text(
        """
        __aicore__ inline int Min(int a, int b) { return a < b ? a : b; }
        """,
        encoding="utf-8",
    )
    (arch / "b.h").write_text(
        """
        __aicore__ inline long Min(long a, long b) { return a < b ? a : b; }
        """,
        encoding="utf-8",
    )
    (arch / "process.h").write_text(
        """
        #include "a.h"
        #include "b.h"
        class Process {
         public:
          __aicore__ inline void Process() {
            int64_t a = Min(k, b);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="ambig_min", architecture="arch35")
    _seed(cm, root, files=[str(arch / "process.h"), str(arch / "a.h"), str(arch / "b.h")])
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    mins = _methods(cm, "Min")
    assert mins
    assert all(not e.attrs.get("qualified_name") or "Min" in str(e.attrs.get("qualified_name") or "") for e in mins)
    assert all(e.attrs.get("root_status") != "REACHED" for e in mins)
    assert all(e.status == "extracted" for e in mins)
    assert not any(e.name == "Min" for e in cm.by_kind(EntityKind.OPERATION))


def test_align_to16_unique_free_not_confused_by_calls(tmp_path: Path) -> None:
    root = tmp_path / "align"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "common.h").write_text(
        """
        __aicore__ inline int64_t AlignTo16(int64_t num) { return (num + 15) >> 4 << 4; }
        """,
        encoding="utf-8",
    )
    (arch / "process.h").write_text(
        """
        #include "common.h"
        class Process {
         public:
          __aicore__ inline void Process() {
            uint32_t s1RealSizeAlignTo16 = AlignTo16(s1);
            uint32_t dataSize = count * AlignTo16(dSize);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="align", architecture="arch35")
    _seed(cm, root, files=[str(arch / "process.h"), str(arch / "common.h")])
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    rows = _methods(cm, "AlignTo16")
    assert rows
    assert all(e.status == "extracted" for e in rows)
    assert all(e.attrs.get("root_status") != "REACHED" for e in rows)
    assert all("AlignTo16" in str(e.attrs.get("qualified_name") or e.name) for e in rows)
    assert not any(e.name == "AlignTo16" for e in cm.by_kind(EntityKind.OPERATION))


def test_conditional_member_type_binds_unique_method(tmp_path: Path) -> None:
    root = tmp_path / "cond"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class MutexBuffersPolicyDB {
         public:
          __aicore__ inline MutexBuffer<BufferType::L1> &Get() { return buffer_; }
          MutexBuffer<BufferType::L1> buffer_;
        };
        class Process {
         public:
          typename std::conditional<!IS_L1_REUSE, MutexBuffersPolicyDB<BufferType::L1>, std::nullptr_t>::type commonL1Buf;
          __aicore__ inline void Process() {
            auto &buf = commonL1Buf.Get();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="cond", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    gets = [
        e
        for e in cm.by_kind(EntityKind.METHOD)
        if e.name == "Get" and "MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "")
    ]
    assert gets
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    buf = next((e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "commonL1Buf"), None)
    assert buf is not None
    assert int(buf.line_start or 0) > 0
    assert buf.attrs.get("conditional_flag") is True
    assert "mutex_policy" not in buf.attrs


def test_outofline_method_binds_class_member(tmp_path: Path) -> None:
    """Class-scope fields must be visible inside Owner::Method bodies."""
    root = tmp_path / "outofline"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        template <int Kind = 0>
        class MutexBuffersPolicyDB {
         public:
          __aicore__ inline MutexBuffer<BufferType::L1> &Get() { return buffer_; }
          __aicore__ inline void Init() { buffer_.Init(); }
          MutexBuffer<BufferType::L1> buffer_;
        };
        class Widget {
         public:
          typename std::conditional<!IS_L1_REUSE, MutexBuffersPolicyDB<BufferType::L1>, std::nullptr_t>::type commonL1Buf;
          MutexBuffersPolicyDB<BufferType::L0A> l0aBuf;
          __aicore__ inline void Process();
          __aicore__ inline MutexBuffer<BufferType::L0C> Take();
        };
        __aicore__ inline void Widget<ARGS>::Process() {
            auto &buf = commonL1Buf.Get();
            l0aBuf.Init();
        }
        __aicore__ inline MutexBuffer<BufferType::L0C> Widget<ARGS>::Take() {
            return l0aBuf.Get();
        }
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="outofline", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    gets = _methods(cm, "Get", receiver="commonL1Buf")
    if not gets:
        gets = [
            e
            for e in cm.by_kind(EntityKind.METHOD)
            if e.name == "Get" and "MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "")
        ]
    assert gets
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "") for e in gets)
    inits = _methods(cm, "Init", receiver="l0aBuf")
    if not inits:
        inits = [
            e
            for e in cm.by_kind(EntityKind.METHOD)
            if e.name == "Init" and "MutexBuffersPolicyDB::Init" in str(e.attrs.get("qualified_name") or "")
        ]
    assert inits
    assert all(e.status == "extracted" for e in inits)
    assert all(e.attrs.get("root_status") != "REACHED" for e in inits)
    assert all("MutexBuffersPolicyDB::Init" in str(e.attrs.get("qualified_name") or "") for e in inits)
    takes = _methods(cm, "Get", receiver="l0aBuf")
    if not takes:
        takes = [
            e
            for e in cm.by_kind(EntityKind.METHOD)
            if e.name == "Get" and "MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "")
        ]
    assert takes
    assert all(e.status == "extracted" for e in takes)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "") for e in takes)


def test_multiline_conditional_member_binds_unique_method(tmp_path: Path) -> None:
    root = tmp_path / "multiline"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class MutexBuffersPolicyDB {
         public:
          __aicore__ inline MutexBuffer<BufferType::L1> &Get() { return buffer_; }
          MutexBuffer<BufferType::L1> buffer_;
        };
        class Process {
         public:
          typename std::conditional<IS_L1_REUSE,
                                    MutexBuffersPolicyDB<BufferType::L1>,
                                    std::nullptr_t>::type dYL1Buf;
          __aicore__ inline void Process() {
            auto &buf = dYL1Buf.Get();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="multiline", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    gets = _methods(cm, "Get", receiver="dYL1Buf")
    if not gets:
        gets = [
            e
            for e in cm.by_kind(EntityKind.METHOD)
            if e.name == "Get" and "MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "")
        ]
    assert gets
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("qualified_name") or "") for e in gets)


def test_selector_alias_with_two_gets_stays_unbound(tmp_path: Path) -> None:
    """Nested selector TYPE that names two Get methods must not guess."""
    root = tmp_path / "selector"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class MutexBuffersPolicyDB {
         public:
          __aicore__ inline MutexBuffer<BufferType::L1> &Get() { return a_; }
          MutexBuffer<BufferType::L1> a_;
        };
        class MutexBuffersPolicySingleBuffer {
         public:
          __aicore__ inline MutexBuffer<BufferType::L1> &Get() { return b_; }
          MutexBuffer<BufferType::L1> b_;
        };
        struct Sel {
          using TYPE = std::conditional_t<FLAG, MutexBuffersPolicyDB<BufferType::L1>,
                                          MutexBuffersPolicySingleBuffer<BufferType::L1>>;
        };
        class Process {
         public:
          using L0CType = typename Sel::TYPE;
          typename std::conditional<ON, L0CType, std::nullptr_t>::type mmBuf;
          __aicore__ inline void Process() {
            auto &buf = mmBuf.Get();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="selector", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    gets = _methods(cm, "Get", receiver="mmBuf")
    assert gets
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    assert all(e.status == "extracted" for e in gets)
    assert all("Policy" not in str(e.attrs.get("qualified_name") or "") for e in gets)
    assert not any(
        e.name == "Get" and e.attrs.get("receiver") == "mmBuf" for e in cm.by_kind(EntityKind.OPERATION)
    )


def test_cited_files_from_walk_covers_included_headers() -> None:
    from types import SimpleNamespace

    from uo_init.passes.kernel_root_trace import _cited_files_from_walk

    wr = SimpleNamespace(
        path="op_kernel/flash_attention_score_grad_apt.cpp",
        call_sites=[
            SimpleNamespace(
                file="op_kernel/arch35/foo.h",
                callee_decl_file="op_kernel/arch35/bar.h",
            )
        ],
        local_decls=[SimpleNamespace(file="op_kernel/arch35/baz.h")],
        type_decls=[SimpleNamespace(file="op_kernel/arch35/type.h")],
        alias_decls=[],
        field_decls={("T", "x"): SimpleNamespace(file="op_kernel/arch35/field.h")},
        controls=[SimpleNamespace(file="op_kernel/arch35/ctrl.h")],
        functions={"Process": SimpleNamespace(file="op_kernel/arch35/process.h")},
    )
    dst: set[str] = set()
    _cited_files_from_walk(wr, dst)
    for name in ("foo.h", "bar.h", "baz.h", "type.h", "field.h", "ctrl.h", "process.h"):
        assert name in dst
    assert "flash_attention_score_grad_apt.cpp" in dst


def test_project_type_and_builtin_are_extracted_not_partial(tmp_path: Path) -> None:
    root = tmp_path / "settle"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        struct LoopInfo {
          int step;
        };
        class Process {
         public:
          LoopInfo info;
          __aicore__ inline void Process() {
            LocalTensor<float> ub;
            if (__builtin_expect(1, 1)) {
              (void)ub;
            }
            (void)info;
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="settle", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    loop = _type(cm, "LoopInfo")
    assert loop is not None
    assert loop.attrs.get("root_status") == "PROJECT"
    assert loop.status == "extracted"
    builtins = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "__builtin_expect" or e.attrs.get("root_status") == "BUILTIN"
    ]
    if builtins:
        assert all(e.status == "extracted" for e in builtins)
        assert all(e.attrs.get("root_status") in {"BUILTIN", "REACHED"} for e in builtins)


def test_getvalue_on_local_tensor_reaches(tmp_path: Path) -> None:
    root = tmp_path / "gval"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            LocalTensor<float> ub;
            float x = ub.GetValue(0);
            ub.SetValue(0, x);
            (void)x;
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="gval", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    hits = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name in {"GetValue", "SetValue"}
    ]
    assert hits
    assert all(e.attrs.get("root_status") == "REACHED" for e in hits)
    assert all(e.status == "extracted" for e in hits)
    buf = next(b for b in cm.by_kind(EntityKind.BUFFER) if b.name == "ub")
    assert buf.attrs.get("root_status") == "REACHED"
    assert buf.status == "extracted"


def test_tbuf_indexed_template_get_bridges_localtensor(tmp_path: Path) -> None:
    """mm1ResBuf[i].template Get<T>() is TBuf Get → LocalTensor, located via the buffer."""
    root = tmp_path / "tbuf_get"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          TBuf<TPosition::VECCALC> mm1ResBuf;
          TBuf<TPosition::VECCALC> mm2ResBuf;
          __aicore__ inline void Process() {
            auto a = this->mm1ResBuf[prevRunInfo.commonRunInfo.taskIdMod2].template Get<CALC_TYPE>();
            auto b = this->mm2ResBuf[idx].template Get<float>();
            auto c = dYL1Buf.Get();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="tbuf_get", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    typed = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("root_status") == "REACHED"
    ]
    assert typed, "expected TBuf Get<T> to reach LocalTensor"
    assert all(e.attrs.get("root") == "AscendC::LocalTensor" for e in typed)
    recvs = {e.attrs.get("receiver") for e in typed}
    assert "mm1ResBuf" in recvs
    assert "mm2ResBuf" in recvs
    policy = _methods(cm, "Get", receiver="dYL1Buf")
    assert policy
    assert all(e.attrs.get("root_status") != "REACHED" for e in policy)


def test_multiline_or_reg_call_reached(tmp_path: Path) -> None:
    root = tmp_path / "or_ml"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            Or((RegTensor<uint16_t> &)vregCastRes, (RegTensor<uint16_t> &)vregCastEven,
                (RegTensor<uint16_t> &)vregCastOdd, pregFullExe);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="or_ml", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    ors = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "Or"]
    assert ors
    assert all(e.attrs.get("root_status") == "REACHED" for e in ors)
    assert all(e.attrs.get("root") == "AscendC::Or" for e in ors)


def test_lexical_vf_reg_apis_reached(tmp_path: Path) -> None:
    """Reg-shaped ExpSub/Or/Fused* prove as CANN VF; bare Or does not."""
    root = tmp_path / "vf"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "vf_anti_quant_compute_p_ds.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            ExpSub(vreg_sp1, vreg_sp1, vreg_max, preg_all);
            FusedExpSub(vreg_sp1, vreg_sp1, vreg_max, preg_all);
            FusedMulDstAdd(vreg_out, vreg_a, vreg_b, preg_all);
            Or((RegTensor<uint8_t> &)vreg_p1, (RegTensor<uint8_t> &)vreg_p1, (RegTensor<uint8_t> &)vreg_p3, preg_all8);
            bool flag = Or(mask_a, mask_b);
            DataCopy(dst, src, 16);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="vf", architecture="arch35")
    _seed(cm, root, files=[str(arch / "vf_anti_quant_compute_p_ds.h")])
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    def _ops(name: str):
        return [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == name]

    exps = _ops("ExpSub")
    assert exps and all(e.attrs.get("root_status") == "REACHED" for e in exps)
    assert all(e.attrs.get("root") == "AscendC::ExpSub" for e in exps)

    fused_exp = _ops("FusedExpSub")
    assert fused_exp and all(e.attrs.get("root_status") == "REACHED" for e in fused_exp)
    assert all(e.attrs.get("root") == "AscendC::ExpSub" for e in fused_exp)

    fused_mul = _ops("FusedMulDstAdd")
    assert fused_mul and all(e.attrs.get("root_status") == "REACHED" for e in fused_mul)
    assert all(e.attrs.get("root") == "AscendC::MulDstAdd" for e in fused_mul)

    ors = _ops("Or")
    assert ors and all(e.attrs.get("root_status") == "REACHED" for e in ors)
    assert all(e.attrs.get("root") == "AscendC::Or" for e in ors)
    assert not any(e.attrs.get("root_status") == "PROJECT" for e in ors)


def _reg_shaped(ent) -> bool:
    args = list(ent.attrs.get("args") or [])
    blob = " ".join(args)
    return len(args) >= 3 or "RegTensor" in blob or "preg_" in blob or "vreg_" in blob


def test_lexical_selector_get_binds_receiver_not_policy(tmp_path: Path) -> None:
    """dYL1Buf.Get() without unique Policy decl is PROJECT via the buffer name."""
    root = tmp_path / "dyl1"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "block_cube.h").write_text(
        """
        class Process {
         public:
          typename std::conditional<IS_L1_REUSE,
              typename DyL1BuffSelector<T, IS_L1_REUSE>::TYPE,
              MutexBuffersPolicyDB<BufferType::L1>>::type dYL1Buf;
          typename std::conditional<FLAG, typename Sel::TYPE, std::nullptr_t>::type pL1Buf;
          __aicore__ inline void Process() {
            auto dy = dYL1Buf.Get();
            auto p = pL1Buf.Get();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="dyl1", architecture="arch35")
    _seed(cm, root, files=[str(arch / "block_cube.h")])
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    for recv in ("dYL1Buf", "pL1Buf"):
        gets = _methods(cm, "Get", receiver=recv)
        assert gets, recv
        assert all(e.attrs.get("root_status") != "REACHED" for e in gets), recv
        assert all(e.status == "extracted" for e in gets), recv
        assert all("AscendC::Get" not in str(e.attrs.get("root") or "") for e in gets), recv
        assert all("Policy" not in str(e.attrs.get("qualified_name") or "") for e in gets), recv
        assert not any(
            e.name == "Get" and e.attrs.get("receiver") == recv for e in cm.by_kind(EntityKind.OPERATION)
        ), recv
    dyl1 = next((e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "dYL1Buf"), None)
    if dyl1 is not None:
        assert not dyl1.attrs.get("allocated")
        assert "mutex_policy" not in dyl1.attrs


def test_pipe_kernel_phase_and_sync_ops(tmp_path: Path) -> None:
    root = tmp_path / "phase"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          TPipe pipeIn;
          TPipe pipeBase;
          TPipe pipePost;
          __aicore__ inline void OpPre() {
            SyncALLCores();
            Destroy();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="phase", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    pipes = [
        e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.attrs.get("catalog") != "ascendc"
    ]
    by_name = {e.name: e for e in pipes}
    assert set(by_name) >= {"pipeIn", "pipeBase", "pipePost"}
    ordinals = sorted(int(e.attrs.get("pipe_ordinal") or 0) for e in pipes)
    assert ordinals == [1, 2, 3]
    assert by_name["pipeIn"].attrs.get("pipe_ordinal") == 1
    assert by_name["pipeBase"].attrs.get("pipe_ordinal") == 2
    assert by_name["pipePost"].attrs.get("pipe_ordinal") == 3
    syncs = [e for e in cm.by_kind(EntityKind.METHOD) if e.name in {"SyncALLCores", "Destroy"}]
    assert syncs
    assert "kernel_execution_pipeline" not in cm.meta


def test_pipe_ordinal_follows_destroy_in_define_body(tmp_path: Path) -> None:
    root = tmp_path / "lifetime"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
#define PHASES \\
  pipeA.Destroy(); \\
  TPipe pipeB; \\
  pipeB.Destroy(); \\
  TPipe pipeC;

class Process {
 public:
  __aicore__ inline void Launch() {
    TPipe pipeA;
    PHASES
  }
};
""",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="lifetime", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    pipes = {
        e.name: e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.attrs.get("catalog") != "ascendc" and not e.attrs.get("pointer")
    }
    if not {"pipeA", "pipeB", "pipeC"} <= set(pipes):
        return
    destroys = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if str(e.attrs.get("callee") or e.name) == "Destroy"
    ]
    if not destroys:
        return
    assert int(pipes["pipeA"].attrs.get("pipe_ordinal") or 0) == 1
    assert int(pipes["pipeB"].attrs.get("pipe_ordinal") or 0) == 2
    assert int(pipes["pipeC"].attrs.get("pipe_ordinal") or 0) == 3
    precedes = [
        (cm.entities[r.src].name, cm.entities[r.dst].name)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.PRECEDES.value
        and str(r.attrs.get("via") or "") == "pipe_destroy"
    ]
    assert ("pipeA", "pipeB") in precedes
    assert ("pipeB", "pipeC") in precedes


def test_mutex_policy_on_conditional_buffer(tmp_path: Path) -> None:
    root = tmp_path / "mutex"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          typename std::conditional<IS_PRELOAD_TWO_TIMES, MutexBuffersPolicyDB<BufferType::L1, SyncType::NO_SYNC>,
                                    MutexBuffersPolicySingleBuffer<BufferType::L1, SyncType::NO_SYNC>>::type pL1Buf;
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="mutex", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    buf = next((e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "pL1Buf"), None)
    assert buf is not None
    assert not buf.attrs.get("allocated")
    assert "mutex_policy" not in buf.attrs
    assert buf.attrs.get("conditional_flag") is True
    assert buf.attrs.get("memory_space") == "L1"
    assert "kernel_execution_pipeline" not in cm.meta


def test_unclassified_call_is_project_operation(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            Helper(1);
            DataCopy(dst, src, n);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="proj", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    helpers = _methods(cm, "Helper")
    assert helpers
    assert all(e.attrs.get("root_status") != "REACHED" for e in helpers)
    assert all(e.status == "extracted" for e in helpers)
    assert not any(e.name == "Helper" for e in cm.by_kind(EntityKind.OPERATION))
    copies = [e.name for e in cm.by_kind(EntityKind.OPERATION)]
    assert "DataCopy" in copies


def test_quoted_include_copy_enters_graph(tmp_path: Path) -> None:
    root = tmp_path / "glue"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (root / "inc").mkdir()
    (root / "inc" / "copy.h").write_text(
        "void Impl() { DataCopy(dst, src, n); Copy(a, b); }\n",
        encoding="utf-8",
    )
    (arch / "process.h").write_text(
        '#include "../../inc/copy.h"\n'
        "class Process {\n"
        " public:\n"
        "  __aicore__ inline void Process() {}\n"
        "};\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="glue", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    copies = [e.name for e in cm.by_kind(EntityKind.OPERATION)]
    assert "DataCopy" in copies
    assert "Copy" in copies


def test_template_instantiations_share_one_operation(monkeypatch, tmp_path: Path) -> None:
    from uo_init.passes import kernel_scan as kscan

    root = tmp_path / "dup"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    src = arch / "process.h"
    src.write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() { DataCopy(dst, src, n); }
        };
        """,
        encoding="utf-8",
    )
    fake = [
        {
            "caller": "Process",
            "callee": "DataCopy",
            "file": str(src),
            "line": 5,
            "column": 0,
            "args": ["dst", "src", "n"],
            "template_args": ["float"],
            "provenance": "test_inject",
        },
        {
            "caller": "Process",
            "callee": "DataCopy",
            "file": str(src),
            "line": 5,
            "column": 0,
            "args": ["dst", "src", "n"],
            "template_args": ["half"],
            "provenance": "test_inject",
        },
    ]

    monkeypatch.setattr(kscan, "collect_call_sites_from_walks", lambda *a, **k: (fake, [], [], "test_inject"))
    monkeypatch.setattr(kscan, "lexical_source_call_sites", lambda *a, **k: [])
    monkeypatch.setattr(
        kscan,
        "collect_type_graph_from_walks",
        lambda *a, **k: {"members": [], "aliases": [], "types": [], "bases": []},
    )
    cm = CodeMap(op_name="dup", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    ops = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "DataCopy"]
    assert len(ops) == 1
    assert int(ops[0].attrs.get("instantiation_n") or 0) >= 2
    sets = ops[0].attrs.get("template_arg_sets") or []
    assert ["float"] in sets and ["half"] in sets


def test_builtin_and_helper_are_not_operations(tmp_path: Path) -> None:
    root = tmp_path / "prim"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            if (__builtin_expect(1, 1)) {
              Helper(1);
              DataCopy(dst, src, n);
              q.EnQue(x);
              LoadAlign(vreg, ptr);
              LoadData(a, b, p);
            }
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="prim", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.OPERATION)}
    assert "__builtin_expect" not in names
    assert "Helper" not in names
    assert "DataCopy" in names
    assert "EnQue" in names
    assert "LoadAlign" in names
    assert "LoadData" in names
    snap = (cm.meta.get("kernel_root_trace") or {}).get("source_api_gated") or {}
    assert int(snap.get("LoadData") or 0) >= 1
    assert int(snap.get("EnQue") or 0) >= 1
    assert (cm.meta.get("kernel_root_trace") or {}).get("gated_fill_complete") is True
    assert not any(e.attrs.get("root_status") == "BUILTIN" for e in cm.by_kind(EntityKind.OPERATION))
    assert _methods(cm, "Helper")


def test_sibling_cpp_primitive_keeps_owner(tmp_path: Path) -> None:
    family = tmp_path / "family"
    wrap = family / "wrap"
    sib = family / "sib"
    arch = wrap / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (wrap / "op_host" / "arch35").mkdir(parents=True)
    (sib / "op_kernel").mkdir(parents=True)
    (sib / "op_kernel" / "k.cpp").write_text(
        "void Impl() { q.EnQue(x); DataCopy(dst, src, n); }\n",
        encoding="utf-8",
    )
    (arch / "process.h").write_text(
        '#include "../../sib/op_kernel/k.cpp"\n'
        "class Process {\n"
        " public:\n"
        "  __aicore__ inline void Process() {}\n"
        "};\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="wrap", architecture="arch35")
    _seed(cm, wrap)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, wrap, architecture="arch35")
    enques = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "EnQue"]
    assert enques
    assert all(e.attrs.get("owner") == "sibling_op" for e in enques)


def test_sibling_cpp_enque_is_operation_with_sibling_owner(tmp_path: Path) -> None:
    family = tmp_path / "family"
    wrap = family / "wrap"
    sib = family / "sib"
    arch = wrap / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (wrap / "op_host" / "arch35").mkdir(parents=True)
    (sib / "op_kernel").mkdir(parents=True)
    (sib / "op_kernel" / "k.cpp").write_text(
        "void Impl() { q.EnQue(x); }\n",
        encoding="utf-8",
    )
    (wrap / "op_kernel" / "entry.cpp").write_text(
        '#include "../../sib/op_kernel/k.cpp"\n'
        "class Process {\n"
        " public:\n"
        "  __aicore__ inline void Process() {}\n"
        "};\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="wrap", architecture="arch35")
    cm.upsert(
        EntityKind.KERNEL,
        "Process",
        attrs={"source_signature": True, "source_definition": True},
        file="op_kernel/entry.cpp",
        line=4,
    )
    cm.meta["kernel_tiling_closure"] = {
        "selected_kernel_files": [str(wrap / "op_kernel" / "entry.cpp")],
        "kernel_reachable_scopes": 1,
    }
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, wrap, architecture="arch35")
    enques = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "EnQue"]
    assert enques
    assert any(e.attrs.get("owner") == "sibling_op" for e in enques)


def test_renamed_tpipes_listed_without_pipein_names(tmp_path: Path) -> None:
    root = tmp_path / "pipes"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          TPipe alpha;
          TPipe beta;
          TPipe gamma;
          TQue<QuePosition::VECIN, 1> q0;
          TQue<QuePosition::VECOUT, 1> q1;
          TQue<QuePosition::VECCALC, 1> q2;
          __aicore__ inline void Process() {
            alpha.InitBuffer(q0, 1024);
            beta.InitBuffer(q1, 1024);
            gamma.InitBuffer(q2, 1024);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="pipes", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    pipes = [
        e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.attrs.get("catalog") != "ascendc"
    ]
    names = {e.name for e in pipes}
    assert names == {"alpha", "beta", "gamma"}
    assert "pipeIn" not in names
    ordinals = sorted(int(e.attrs.get("pipe_ordinal") or 0) for e in pipes)
    assert ordinals == [1, 2, 3]
    binds = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value
        and str(r.attrs.get("via") or "") == "InitBuffer"
    ]
    assert len(binds) >= 3
    for qname in ("q0", "q1", "q2"):
        que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == qname)
        assert que.attrs.get("allocated") is True

    from uo_init.store.writer import write_codemap
    from uo_init.uo_query import open_query

    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "pipes.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    launch = open_query(tmp_path).aggregate_kernel_launch()
    got = [row.get("pipe") for row in launch["phases"] if row.get("ok")]
    assert got == ["alpha", "beta", "gamma"]
    assert "pipeIn" not in got


def test_expr_storage_name_strips_this_receiver() -> None:
    from uo_init.passes.kernel_root_trace import (
        _expr_storage_name,
        _identity_scopes,
        _sync_object_kind,
    )

    assert _expr_storage_name("this.pipe") == "pipe"
    assert _expr_storage_name("this->pipe") == "pipe"
    assert _expr_storage_name("(*this).pipe") == "pipe"
    assert _expr_storage_name("(*this)->pipe") == "pipe"
    assert _expr_storage_name("pipe") == "pipe"
    assert _expr_storage_name("this->inQue") == "inQue"
    assert _expr_storage_name("&inQue") == "inQue"
    assert _expr_storage_name("GetTPipePtr()") == ""
    assert _identity_scopes("Init", "FlashPost::Init") == [
        "Init",
        "FlashPost::Init",
        "FlashPost",
    ]
    assert _sync_object_kind("TPipe") == EntityKind.PIPE
    assert _sync_object_kind("TPipe *") == EntityKind.PIPE
    assert _sync_object_kind("TPipe*") == EntityKind.PIPE
    assert _sync_object_kind("const TPipe *") == EntityKind.PIPE
    assert _sync_object_kind("AscendC::TPipe*") == EntityKind.PIPE


def test_this_pipe_initbuffer_binds_per_callsite(tmp_path: Path) -> None:
    root = tmp_path / "thispipe"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class FlashPost {
         public:
          TPipe pipe;
          TQue<QuePosition::VECIN, 1> inQue;
          TQue<QuePosition::VECOUT, 1> outQue;
          __aicore__ inline void Init() {
            this->pipe.InitBuffer(inQue, 1, 1024);
            this.pipe.InitBuffer(outQue, 1, 1024);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="thispipe", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    pipe = next(
        e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.attrs.get("catalog") != "ascendc" and e.name == "pipe"
    )
    binds = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value
        and str(r.attrs.get("via") or "") == "InitBuffer"
        and r.src == pipe.id
    ]
    dst_names = {cm.entities[r.dst].name for r in binds}
    assert dst_names == {"inQue", "outQue"}
    for qname in ("inQue", "outQue"):
        que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == qname)
        assert que.attrs.get("allocated") is True
        assert cm.entities[pipe.id].kind_name() == EntityKind.PIPE.value


def test_this_pipe_initbuffer_does_not_cross_classes(tmp_path: Path) -> None:
    root = tmp_path / "twopipe"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class PhasePre {
         public:
          TPipe pipe;
          TQue<QuePosition::VECIN, 1> preQue;
          __aicore__ inline void Init() { this.pipe.InitBuffer(preQue, 1, 64); }
        };
        class PhasePost {
         public:
          TPipe pipe;
          TQue<QuePosition::VECOUT, 1> postQue;
          __aicore__ inline void Init() { this->pipe.InitBuffer(postQue, 1, 64); }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="twopipe", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    pipes = [
        e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.attrs.get("catalog") != "ascendc" and e.name == "pipe"
    ]
    pre_pipe = next(e for e in pipes if e.attrs.get("scope") == "PhasePre")
    post_pipe = next(e for e in pipes if e.attrs.get("scope") == "PhasePost")
    pre_que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == "preQue")
    post_que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == "postQue")
    binds = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value
        and str(r.attrs.get("via") or "") == "InitBuffer"
    ]
    pairs = {(r.src, r.dst) for r in binds}
    assert (pre_pipe.id, pre_que.id) in pairs
    assert (post_pipe.id, post_que.id) in pairs
    assert (pre_pipe.id, post_que.id) not in pairs
    assert (post_pipe.id, pre_que.id) not in pairs
    assert pre_que.attrs.get("allocated") is True
    assert post_que.attrs.get("allocated") is True


def test_tpipe_pointer_this_pipe_binds_instance(tmp_path: Path) -> None:
    root = tmp_path / "ptrpipe"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class PhasePost {
         public:
          TPipe *pipe;
          TQue<QuePosition::VECIN, 1> postQue;
          __aicore__ inline void Init(TPipe *pipe_in) {
            pipe = pipe_in;
            this->pipe.InitBuffer(postQue, 1, 64);
          }
        };
        class Process {
         public:
          __aicore__ inline void Process() {
            TPipe pipePost;
            PhasePost opPost;
            opPost.Init(&pipePost);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="ptrpipe", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    ptr = next(
        e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.name == "pipe" and e.attrs.get("catalog") != "ascendc"
    )
    inst = next(
        e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.name == "pipePost" and e.attrs.get("catalog") != "ascendc"
    )
    que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == "postQue")
    assert ptr.attrs.get("pointer") is True
    assert not inst.attrs.get("pointer")
    binds = {
        (r.src, r.dst)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value
        and str(r.attrs.get("via") or "") == "InitBuffer"
    }
    assert (ptr.id, que.id) in binds
    assert (inst.id, que.id) in binds
    aliases = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.ALIASES.value
        and str(r.attrs.get("via") or "") == "pipe_ptr"
    ]
    assert any(r.src == ptr.id and r.dst == inst.id for r in aliases)
    assert que.attrs.get("allocated") is True

    from uo_init.store.writer import write_codemap
    from uo_init.uo_query import open_query

    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "ptrpipe.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    launch = open_query(tmp_path).aggregate_kernel_launch()
    got = [row.get("pipe") for row in launch["phases"] if row.get("ok")]
    assert "pipePost" in got
    assert "pipe" not in got


def test_initbuffer_after_file_banner_allocates_all_queues(tmp_path: Path) -> None:
    """Copyright banner must not drop later ``InitBuffer`` queues."""
    root = tmp_path / "bannerque"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    banner = "/**\n" + "\n".join(f" * copyright {i}" for i in range(8)) + "\n */\n"
    (arch / "process.h").write_text(
        banner
        + """
        class Process {
         public:
          TPipe *pipe;
          TQue<QuePosition::VECIN, 1> input1Que;
          TQue<QuePosition::VECIN, 1> input2Que;
          TQue<QuePosition::VECOUT, 1> out1Que;
          __aicore__ inline void Init() {
            pipe->InitBuffer(input1Que, 1, 64);
            pipe->InitBuffer(input2Que, 1, 64);
            pipe->InitBuffer(out1Que, 2, 64);
          }
          __aicore__ inline void Process() { Init(); }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="bannerque", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    ques = {
        e.name: e
        for e in cm.by_kind(EntityKind.QUEUE)
        if e.attrs.get("catalog") != "ascendc"
    }
    assert set(ques) >= {"input1Que", "input2Que", "out1Que"}
    assert all(ques[n].attrs.get("allocated") is True for n in ("input1Que", "input2Que", "out1Que"))


def test_macro_init_pipe_aliases_entry_instance(tmp_path: Path) -> None:
    """``opPost.Init(&pipePost)`` inside a #define body still ALIASES the pointer."""
    root = tmp_path / "macropipe"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        #define INVOKE_POST() \\
            do { \\
                TPipe pipePost; \\
                PhasePost opPost; \\
                opPost.Init(dq, user, &pipePost); \\
            } while (0)

        class PhasePre {
         public:
          TPipe *pipe;
          TQue<QuePosition::VECIN, 1> preQue;
          __aicore__ inline void Init(TPipe *pipe_in) {
            pipe = pipe_in;
            this->pipe.InitBuffer(preQue, 1, 64);
          }
        };
        class PhasePost {
         public:
          TPipe *pipe;
          TQue<QuePosition::VECIN, 1> postQue;
          __aicore__ inline void Init(TPipe *pipe_in) {
            pipe = pipe_in;
            this->pipe.InitBuffer(postQue, 1, 64);
          }
        };
        class Process {
         public:
          TPipe pipeIn;
          __aicore__ inline void Process() {
            PhasePre opPre;
            opPre.Init(&pipeIn);
            INVOKE_POST();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="macropipe", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    def _pipe(name: str, *, pointer: bool | None = None):
        rows = [
            e
            for e in cm.by_kind(EntityKind.PIPE)
            if e.name == name and e.attrs.get("catalog") != "ascendc"
        ]
        if pointer is None:
            return rows
        return [e for e in rows if bool(e.attrs.get("pointer")) is pointer]

    pre_ptr = next(e for e in _pipe("pipe", pointer=True) if "Pre" in str(e.attrs.get("scope") or ""))
    post_ptr = next(e for e in _pipe("pipe", pointer=True) if "Post" in str(e.attrs.get("scope") or ""))
    pipe_in = next(iter(_pipe("pipeIn", pointer=False)))
    pipe_post = next(iter(_pipe("pipePost", pointer=False)))
    pre_que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == "preQue")
    post_que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == "postQue")
    aliases = {
        (r.src, r.dst)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.ALIASES.value
        and str(r.attrs.get("via") or "") == "pipe_ptr"
    }
    binds = {
        (r.src, r.dst)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value
        and str(r.attrs.get("via") or "") == "InitBuffer"
    }
    assert (post_ptr.id, pipe_post.id) in aliases
    assert (pre_ptr.id, pipe_in.id) in aliases
    assert (post_ptr.id, pipe_in.id) not in aliases
    assert (pre_ptr.id, pipe_post.id) not in aliases
    assert (pipe_post.id, post_que.id) in binds
    assert (pipe_in.id, pre_que.id) in binds


def test_macro_init_pipe_aliases_inherited_base(tmp_path: Path) -> None:
    """``op.Init(&pipeBase)`` ALIASES ``KernelBase::pipe`` via inheritance."""
    root = tmp_path / "inheritpipe"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        #define INVOKE_MAIN() \\
            do { \\
                TPipe pipeBase; \\
                typename std::conditional<true, Kernel, KernelDeter>::type op; \\
                op.Init(key, tilingData, &pipeBase); \\
            } while (0)

        class KernelBase {
         public:
          TPipe *pipe;
          TQue<QuePosition::VECIN, 1> mainQue;
          __aicore__ inline void Bind() {
            this->pipe.InitBuffer(mainQue, 1, 64);
          }
        };
        class Kernel : public KernelBase {
         public:
          __aicore__ inline void Init(TPipe *pipe_in) {
            pipe = pipe_in;
            Bind();
          }
        };
        class KernelDeter : public KernelBase {
         public:
          __aicore__ inline void Init(TPipe *pipe_in) {
            pipe = pipe_in;
            Bind();
          }
        };
        class Process {
         public:
          __aicore__ inline void Process() {
            INVOKE_MAIN();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="inheritpipe", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    ptr = next(
        e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.name == "pipe"
        and e.attrs.get("catalog") != "ascendc"
        and e.attrs.get("pointer")
    )
    inst = next(
        e
        for e in cm.by_kind(EntityKind.PIPE)
        if e.name == "pipeBase" and e.attrs.get("catalog") != "ascendc"
    )
    que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == "mainQue")
    aliases = {
        (r.src, r.dst)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.ALIASES.value
        and str(r.attrs.get("via") or "") == "pipe_ptr"
    }
    binds = {
        (r.src, r.dst)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value
        and str(r.attrs.get("via") or "") == "InitBuffer"
    }
    assert (ptr.id, inst.id) in aliases
    assert (inst.id, que.id) in binds


def test_local_decl_owners_from_macro_chunk() -> None:
    from uo_init.passes.kernel_root_trace import (
        _ADDR_IDENT_RE,
        _backslash_logical_lines,
        _inherit_pairs_from_text,
        _local_decl_owners,
        _paren_arg_text,
        _RECV_INIT_RE,
    )

    text = """
        #define INVOKE() \\
            do { \\
                using CubeBlockType = typename std::conditional<true, FAGBlockCube, FAGBlockCubeDummy>::type; \\
                typename std::conditional<true, Kernel, KernelDeter>::type op; \\
                op.Init(key, &pipeBase); \\
                if constexpr (!IS_NZ_OUT) { \\
                    FlashAttentionScoreGradPost<T> \\
                        opPost; \\
                    opPost.Init(dq, user, &pipePost); \\
                } \\
            } while (0)
        class Kernel : public KernelBase<Cube, Vec> {
        };
        """
    logical = next(chunk for _line, chunk in _backslash_logical_lines(text) if "opPost.Init" in chunk)
    posts = list(_RECV_INIT_RE.finditer(logical))
    assert [m.group("recv") for m in posts] == ["op", "opPost"]
    op_m, post_m = posts
    assert _local_decl_owners(logical, "op", op_m.start()) == ["Kernel", "KernelDeter"]
    assert _local_decl_owners(logical, "opPost", post_m.start()) == [
        "FlashAttentionScoreGradPost"
    ]
    args = _paren_arg_text(logical, post_m.end() - 1)
    assert [m.group("name") for m in _ADDR_IDENT_RE.finditer(args)] == ["pipePost"]
    assert ("Kernel", "KernelBase") in _inherit_pairs_from_text(text)


def test_tque_without_initbuffer_is_not_allocated(tmp_path: Path) -> None:
    root = tmp_path / "tque"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          TQue<QuePosition::VECIN, 1> x;
          __aicore__ inline void Process() {}
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="tque", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    que = next(e for e in cm.by_kind(EntityKind.QUEUE) if e.name == "x")
    assert que.attrs.get("allocated") is False
    binds = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value
        and str(r.attrs.get("via") or "") == "InitBuffer"
    ]
    assert not binds


def test_wrapper_class_body_proves_storage_and_lock(tmp_path: Path) -> None:
    root = tmp_path / "wrapbody"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Basket {
         public:
          LocalTensor<uint8_t> payload;
          int gate;
          template <typename Pipe>
          void Latch() { AscendC::Mutex::Lock<Pipe>(gate); }
          void Grab() { Latch<int>(); }
        };
        class Process {
         public:
          Basket box;
          TPipe p;
          TQue<QuePosition::VECIN, 1> q;
          __aicore__ inline void Process() {
            p.InitBuffer(q, 64);
            box.Grab();
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="wrapbody", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    basket = _type(cm, "Basket")
    assert basket is not None
    assert basket.attrs.get("wraps_storage") is True
    assert basket.attrs.get("wraps_lock") is True
    assert _wraps_path(cm, "Basket", "LocalTensor")
    grab = _methods(cm, "Grab")
    assert grab
    lock_ops = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Lock" and e.attrs.get("root_status") == "REACHED"
    ]
    assert lock_ops
    assert not any(e.name == "Grab" for e in cm.by_kind(EntityKind.OPERATION))
    assert not any(e.name == "Latch" for e in cm.by_kind(EntityKind.OPERATION))


def test_contains_targets_member_instance_not_member_type(tmp_path: Path) -> None:
    root = tmp_path / "contains"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class MutexBuffersPolicyDB {
         public:
          MutexBuffer<BufferType::L1> a_;
          MutexBuffer<BufferType::L1> b_;
        };
        class MutexBuffer {
         public:
          LocalTensor<uint8_t> tensor_;
        };
        class Process {
         public:
          MutexBuffersPolicyDB policy;
          __aicore__ inline void Process() { auto &buf = policy.a_; }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="contains", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    mutex = _type(cm, "MutexBuffer")
    assert mutex is not None
    contains_dst = [
        cm.entities.get(r.dst)
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.CONTAINS.value and r.src == mutex.id
    ]
    assert all(
        e is not None and e.kind_name() != EntityKind.TYPE.value for e in contains_dst
    )
    assert not any(e is not None and "Policy" in (e.name or "") for e in contains_dst)
    a_bufs = [e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "a_"]
    for buf in a_bufs:
        wraps_mutex = [
            r
            for r in cm.relations.values()
            if r.kind_name() == RelationKind.WRAPS.value
            and r.src == buf.id
            and r.dst == mutex.id
        ]
        assert not wraps_mutex
    assert _wraps_path(cm, "MutexBuffersPolicyDB", "MutexBuffer") or _wraps_path(
        cm, "MutexBuffersPolicyDB", "LocalTensor"
    )


def _conditional_branch_wraps(cm: CodeMap, buf) -> list[Any]:
    return [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.WRAPS.value
        and r.src == buf.id
        and str(r.attrs.get("via") or "") == "conditional_branch"
    ]


def test_divergent_conditional_wrappers_are_not_collapsed(tmp_path: Path) -> None:
    """Different Then/Else storage wrappers must not become one canonical wrapper."""
    root = tmp_path / "divergent"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        template <typename T>
        class SomeWrapper {
         public:
          LocalTensor<T> tensor_;
        };
        template <typename T>
        class SomeOtherWrapper {
         public:
          TQue<QuePosition::VECIN, 1> queue_;
        };
        class Process {
         public:
          typename std::conditional<COND, SomeWrapper<LocalTensor<int>>,
                                    SomeOtherWrapper<TQue<QuePosition::VECIN, 1>>>::type mixedBuf;
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="divergent", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    buf = next((e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "mixedBuf"), None)
    assert buf is not None
    assert buf.attrs.get("conditional_flag") is True
    wrapper = str(buf.attrs.get("wrapper") or "")
    assert wrapper not in {"SomeWrapper", "SomeOtherWrapper"}
    assert buf.attrs.get("root_status") in {"UNRESOLVED", "GUARDED"}
    branches = _conditional_branch_wraps(cm, buf)
    names = {
        (cm.entities[r.dst].name if r.dst in cm.entities else "")
        for r in branches
    }
    assert "SomeWrapper" in names
    assert "SomeOtherWrapper" in names
    polarities = {str(r.attrs.get("polarity") or "") for r in branches}
    assert "then" in polarities
    assert "else" in polarities
    assert all(str(r.attrs.get("cond") or "") for r in branches)


def test_common_conditional_root_is_derived(tmp_path: Path) -> None:
    """Same AscendC storage root on both branches may become the common root."""
    root = tmp_path / "commonroot"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class WrapA {
         public:
          LocalTensor<uint8_t> a_;
        };
        class WrapB {
         public:
          LocalTensor<uint8_t> b_;
        };
        class Process {
         public:
          typename std::conditional<FLAG, WrapA, WrapB>::type sharedBuf;
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="commonroot", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    buf = next((e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "sharedBuf"), None)
    assert buf is not None
    assert buf.attrs.get("conditional_flag") is True
    assert "LocalTensor" in str(buf.attrs.get("root") or "")
    assert buf.attrs.get("root_status") == "REACHED"
    assert not buf.attrs.get("wrapper")


def test_conditional_t_alias_keeps_both_branches(tmp_path: Path) -> None:
    root = tmp_path / "condt"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class WrapA {
         public:
          LocalTensor<uint8_t> a_;
        };
        class WrapB {
         public:
          TQue<QuePosition::VECIN, 1> q_;
        };
        using Mixed = std::conditional_t<ON, WrapA, WrapB>;
        class Process {
         public:
          Mixed aliasBuf;
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="condt", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    buf = next((e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "aliasBuf"), None)
    assert buf is not None
    assert buf.attrs.get("conditional_flag") is True
    names = {
        (cm.entities[r.dst].name if r.dst in cm.entities else "")
        for r in _conditional_branch_wraps(cm, buf)
    }
    assert "WrapA" in names
    assert "WrapB" in names


def test_nested_conditional_does_not_pick_first_wrapper(tmp_path: Path) -> None:
    root = tmp_path / "nested"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class WrapA {
         public:
          LocalTensor<uint8_t> a_;
        };
        class WrapB {
         public:
          TQue<QuePosition::VECIN, 1> q_;
        };
        class WrapC {
         public:
          GlobalTensor<uint8_t> g_;
        };
        class Process {
         public:
          typename std::conditional<OUTER, WrapA,
                                    typename std::conditional<INNER, WrapB, WrapC>::type>::type nestBuf;
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="nested", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    buf = next((e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "nestBuf"), None)
    assert buf is not None
    assert buf.attrs.get("conditional_flag") is True
    assert not buf.attrs.get("wrapper")
    names = {
        (cm.entities[r.dst].name if r.dst in cm.entities else "")
        for r in _conditional_branch_wraps(cm, buf)
    }
    assert {"WrapA", "WrapB", "WrapC"} <= names


def test_ifelse_same_member_keeps_divergent_types(tmp_path: Path) -> None:
    """Lexical #if/#else decls of one member must stay guarded alternatives."""
    root = tmp_path / "ifelse"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class WrapA {
         public:
          LocalTensor<uint8_t> a_;
        };
        class WrapB {
         public:
          TQue<QuePosition::VECIN, 1> q_;
        };
        class Process {
         public:
        #if FLAG
          WrapA gatedBuf;
        #else
          WrapB gatedBuf;
        #endif
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="ifelse", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")
    bufs = [e for e in cm.by_kind(EntityKind.BUFFER) if e.name == "gatedBuf"]
    assert len(bufs) == 1
    buf = bufs[0]
    type_name = str(buf.attrs.get("type_name") or "")
    assert "WrapA" in type_name
    assert "WrapB" in type_name
    names = {
        (cm.entities[r.dst].name if r.dst in cm.entities else "")
        for r in _conditional_branch_wraps(cm, buf)
    }
    assert "WrapA" in names
    assert "WrapB" in names
    assert str(buf.attrs.get("wrapper") or "") not in {"WrapA", "WrapB"}





