# -*- coding: utf-8 -*-
"""CANN public sync roots — more than block_sync + Mutex."""

from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.kernel_root_trace import finalize_kernel_root_trace
from uo_init.semantics import registry as semreg
from uo_init.semantics.ascendc_sync import (
    SYNC_MECHANISM,
    canonical_sync_name,
    is_flag_sync,
    is_sync_root,
    resolve_sync_site,
)
from tests.unit.test_kernel_root_trace import _seed


def test_cann_sync_roots_cover_public_headers() -> None:
    missing = {
        "SetFlag",
        "WaitFlag",
        "PipeBarrier",
        "DataSyncBarrier",
        "SyncAll",
        "CrossCoreSetFlag",
        "CrossCoreWaitFlag",
        "IBSet",
        "IBWait",
        "Lock",
        "Unlock",
        "AllocMutexID",
        "ReleaseMutexID",
        "WaitPreBlock",
        "NotifyNextBlock",
        "InitDetermineComputeWorkspace",
        "SetNextTaskStart",
        "WaitPreTaskEnd",
        "AllocEventID",
        "ReleaseEventID",
        "FetchEventID",
        "LocalMemBar",
        "Arrive",
        "asc_syncthreads",
        "asc_threadfence",
        "asc_threadfence_block",
        "ffts_cross_core_sync",
        "wait_flag_dev",
    } - set(SYNC_MECHANISM)
    assert not missing, f"CANN sync roots missing: {sorted(missing)}"
    assert "Wait" not in SYNC_MECHANISM
    assert "LockProd" not in SYNC_MECHANISM
    assert "sync" not in SYNC_MECHANISM
    assert not is_sync_root("Wait")
    assert not is_sync_root("LockProd")


def test_cce_intrinsics_alias_to_public_names() -> None:
    assert canonical_sync_name("set_flag") == "SetFlag"
    assert canonical_sync_name("wait_flag") == "WaitFlag"
    assert canonical_sync_name("pipe_barrier") == "PipeBarrier"
    assert is_flag_sync("set_flag")
    assert is_flag_sync("wait_flag")
    site = resolve_sync_site("set_flag", ["PIPE_MTE2", "PIPE_S", "EVENT_ID0"])
    assert site["kind"] == "SetFlag"
    assert site["mechanism"] == "hard_event"
    assert site["flag"] == "EVENT_ID0"
    assert site["src_pipe"] == "MTE2"
    assert site["dst_pipe"] == "S"
    wait = resolve_sync_site("WaitPreBlock", ["gmWorkspace", "ubWorkspace"])
    assert wait["mechanism"] == "determine_compute"
    sk = resolve_sync_site("SetNextTaskStart")
    assert sk["mechanism"] == "superkernel"
    bar = resolve_sync_site("LocalMemBar", targs=["MemType::VEC_STORE", "MemType::VEC_LOAD"])
    assert bar["mechanism"] == "membar"
    cc = resolve_sync_site("ffts_cross_core_sync", ["PIPE_MTE3", "flagId"])
    assert cc["mechanism"] == "cross_core"
    assert cc["cross_core"] is True


def test_extra_cann_sync_calls_are_roots(tmp_path: Path) -> None:
    root = tmp_path / "sync_roots"
    arch = root / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (arch / "process.h").write_text(
        """
        class Process {
         public:
          __aicore__ inline void Process() {
            InitDetermineComputeWorkspace(gm, ub);
            WaitPreBlock(gm, ub);
            NotifyNextBlock(gm, ub);
            SetNextTaskStart();
            WaitPreTaskEnd();
            LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();
            pipe_barrier(PIPE_ALL);
            set_flag(PIPE_MTE2, PIPE_S, EVENT_ID0);
            wait_flag(PIPE_MTE2, PIPE_S, EVENT_ID0);
            ffts_cross_core_sync(PIPE_MTE3, flagId);
            wait_flag_dev(PIPE_S, flagId);
            asc_syncthreads();
            event_t evt = static_cast<event_t>(GetTPipePtr()->AllocEventID<HardEvent::MTE2_S>());
            GetTPipePtr()->ReleaseEventID<HardEvent::MTE2_S>(evt);
          }
        };
        """,
        encoding="utf-8",
    )
    cm = CodeMap(op_name="sync_roots", architecture="arch35")
    _seed(cm, root)
    semreg.load_registry.cache_clear()
    finalize_kernel_root_trace(cm, root, architecture="arch35")

    ops = {e.name: e for e in cm.by_kind(EntityKind.OPERATION)}
    for name in (
        "WaitPreBlock",
        "NotifyNextBlock",
        "SetNextTaskStart",
        "WaitPreTaskEnd",
        "LocalMemBar",
        "AllocEventID",
        "ReleaseEventID",
        "asc_syncthreads",
        "ffts_cross_core_sync",
        "wait_flag_dev",
    ):
        assert name in ops, f"missing OPERATION {name}"
        assert ops[name].attrs.get("root_status") == "REACHED", name
        assert str(ops[name].attrs.get("root") or "").startswith("AscendC::"), name

    # CCE intrinsics alias onto the public SetFlag / WaitFlag / PipeBarrier roots.
    assert ops["set_flag"].attrs.get("root_status") == "REACHED"
    assert ops["set_flag"].attrs.get("root") == "AscendC::SetFlag"
    assert ops["wait_flag"].attrs.get("root_status") == "REACHED"
    assert ops["wait_flag"].attrs.get("root") == "AscendC::WaitFlag"
    assert ops["pipe_barrier"].attrs.get("root_status") == "REACHED"
    assert ops["pipe_barrier"].attrs.get("root") == "AscendC::PipeBarrier"

    waits = [e for e in cm.by_kind(EntityKind.OPERATION) if e.name == "Wait"]
    assert not waits
    assert ops["WaitPreBlock"].attrs.get("mechanism") == "determine_compute"
    assert ops["SetNextTaskStart"].attrs.get("mechanism") == "superkernel"
    assert ops["LocalMemBar"].attrs.get("mechanism") == "membar"
