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

    # Project WidgetHolder::Get must NOT be proven as AscendC::Get,
    # but the call site must bind to the unique project declaration.
    project_gets = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver") == "commonL1Buf"
    ]
    assert project_gets, "expected call site for commonL1Buf.Get()"
    assert all(e.attrs.get("root_status") != "REACHED" for e in project_gets)
    assert all("AscendC::Get" not in str(e.attrs.get("root") or "") for e in project_gets)
    assert all(e.status == "extracted" for e in project_gets)
    assert all(str(e.attrs.get("callee_qualified") or "").endswith("WidgetHolder::Get") for e in project_gets)
    assert all(str(e.attrs.get("root_proof") or "").startswith("project_") for e in project_gets)
    binds = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value and r.src in {e.id for e in project_gets}
    ]
    assert binds, "expected BINDS from call site to WidgetHolder::Get"


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
        member_ops = [
            e
            for e in cm.by_kind(EntityKind.OPERATION)
            if e.name == name and e.attrs.get("receiver") == "foo"
        ]
        assert member_ops, f"missing member call {name}"
        assert all(e.attrs.get("root_status") != "REACHED" for e in member_ops), name
        assert all(e.status == "extracted" for e in member_ops), name
        assert all(str(e.attrs.get("callee_qualified") or "") == f"Foo::{name}" for e in member_ops), name

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
    assert len(mins) == 2
    statuses = sorted(str(e.attrs.get("root_status")) for e in mins)
    assert statuses == ["PROJECT", "REACHED"]
    two_arg = next(e for e in mins if len(e.attrs.get("args") or []) <= 2)
    four_arg = next(e for e in mins if len(e.attrs.get("args") or []) >= 3)
    assert two_arg.attrs.get("root_status") == "PROJECT"
    assert two_arg.status == "extracted"
    assert four_arg.attrs.get("root_status") == "REACHED"


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

    gets = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver") == "aL0BuffsDb"
    ]
    assert gets
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("callee_qualified") or "") for e in gets)
    assert all("policy.h" in str(e.attrs.get("callee_decl_file") or "") for e in gets)

    inits = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Init" and e.attrs.get("receiver") == "aL0BuffsDb"
    ]
    assert inits
    assert all(e.status == "extracted" for e in inits)
    assert all(e.attrs.get("root_status") != "REACHED" for e in inits)
    assert all("MutexBuffersPolicyDB::Init" in str(e.attrs.get("callee_qualified") or "") for e in inits)

    ping_inits = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Init" and e.attrs.get("receiver") == "ping_"
    ]
    assert ping_inits
    assert all("MutexBuffer::Init" in str(e.attrs.get("callee_qualified") or "") for e in ping_inits)
    assert all(e.attrs.get("root_status") != "REACHED" for e in ping_inits)

    gts = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "GetTensor" and e.attrs.get("receiver") == "l0aBuffer"
    ]
    assert gts
    assert all(e.attrs.get("root") == "AscendC::LocalTensor" for e in gts)


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

    mins = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "Min"]
    assert mins
    assert all(e.status == "extracted" for e in mins)
    assert all(e.attrs.get("root_status") != "REACHED" for e in mins)
    assert all(e.attrs.get("root_proof") == "project_free" for e in mins)
    assert all("Min" in str(e.attrs.get("callee_qualified") or "") for e in mins)


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

    mins = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "Min"]
    assert mins
    assert all(not e.attrs.get("callee_qualified") for e in mins)
    assert all(e.attrs.get("root_status") != "REACHED" for e in mins)
    assert all(e.status == "extracted" for e in mins)
    assert all(e.attrs.get("root_status") == "PROJECT" for e in mins)


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
    rows = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "AlignTo16"]
    assert rows
    assert all(e.status == "extracted" for e in rows)
    assert all(e.attrs.get("root_status") != "REACHED" for e in rows)
    assert all("AlignTo16" in str(e.attrs.get("callee_qualified") or "") for e in rows)


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
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver") == "commonL1Buf"
    ]
    assert gets
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("callee_qualified") or "") for e in gets)


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
    gets = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver") == "commonL1Buf"
    ]
    assert gets
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("callee_qualified") or "") for e in gets)
    inits = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Init" and e.attrs.get("receiver") == "l0aBuf"
    ]
    assert inits
    assert all(e.status == "extracted" for e in inits)
    assert all(e.attrs.get("root_status") != "REACHED" for e in inits)
    assert all("MutexBuffersPolicyDB::Init" in str(e.attrs.get("callee_qualified") or "") for e in inits)
    takes = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver") == "l0aBuf"
    ]
    assert takes
    assert all(e.status == "extracted" for e in takes)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("callee_qualified") or "") for e in takes)


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
    gets = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver") == "dYL1Buf"
    ]
    assert gets
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("root_status") != "REACHED" for e in gets)
    assert all("MutexBuffersPolicyDB::Get" in str(e.attrs.get("callee_qualified") or "") for e in gets)


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
    gets = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver") == "mmBuf"
    ]
    assert gets
    assert all(not e.attrs.get("callee_qualified") for e in gets)
    assert all(e.attrs.get("root_status") == "PROJECT" for e in gets)
    assert all(e.status == "extracted" for e in gets)
    assert all(e.attrs.get("receiver") == "mmBuf" for e in gets)
    assert all("Policy" not in str(e.attrs.get("callee_qualified") or "") for e in gets)
    binds = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.BINDS.value and r.src in {e.id for e in gets}
    ]
    assert binds
    assert all(str(r.attrs.get("receiver") or "") == "mmBuf" for r in binds)


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
    policy = [
        e
        for e in cm.by_kind(EntityKind.OPERATION)
        if e.name == "Get" and e.attrs.get("receiver") == "dYL1Buf"
    ]
    assert policy and all(e.attrs.get("root_status") == "PROJECT" for e in policy)


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
    assert len(ors) >= 2
    vec_or = [e for e in ors if _reg_shaped(e)]
    scalar_or = [e for e in ors if not _reg_shaped(e)]
    assert vec_or and all(e.attrs.get("root_status") == "REACHED" for e in vec_or)
    assert all(e.attrs.get("root") == "AscendC::Or" for e in vec_or)
    assert scalar_or and all(e.attrs.get("root_status") != "REACHED" for e in scalar_or)


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
        gets = [
            e
            for e in cm.by_kind(EntityKind.OPERATION)
            if e.name == "Get" and e.attrs.get("receiver") == recv
        ]
        assert gets, recv
        assert all(e.attrs.get("root_status") == "PROJECT" for e in gets), recv
        assert all(e.status == "extracted" for e in gets), recv
        assert all(e.attrs.get("root_status") != "REACHED" for e in gets), recv
        assert all("AscendC::Get" not in str(e.attrs.get("root") or "") for e in gets), recv
        assert all("Policy" not in str(e.attrs.get("callee_qualified") or "") for e in gets), recv
        binds = [
            r
            for r in cm.relations.values()
            if r.kind_name() == RelationKind.BINDS.value and r.src in {e.id for e in gets}
        ]
        assert binds, recv
        assert all(str(r.attrs.get("receiver") or "") == recv for r in binds), recv



