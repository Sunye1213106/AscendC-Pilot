# -*- coding: utf-8 -*-
"""AscendC / CANN synchronization catalog for Kernel Execution.

Source of truth:
  cann-asc-devkit/.../impl/kernel_event.h          HardEvent (src_dst pipes)
  cann-asc-devkit/.../interface/kernel_operator_block_sync_intf.h
      SetFlag/WaitFlag, PipeBarrier, DataSyncBarrier,
      IBSet/IBWait, SyncAll, CrossCoreSetFlag/WaitFlag, TQueSync
  cann-asc-devkit/.../interface/kernel_common.h
      Mutex::Lock / Mutex::Unlock, AllocMutexID / ReleaseMutexID

Mechanisms (not operator-specific names):
  hard_event   — SetFlag/WaitFlag<HardEvent::SRC_DST>
  cross_core   — CrossCoreSetFlag/WaitFlag
  barrier      — PipeBarrier / DataSyncBarrier / SyncAll
  inter_block  — IBSet / IBWait
  mutex        — Mutex::Lock/Unlock (+ wrapper LockProd/...)
"""

from __future__ import annotations

import re
from typing import Any

# pipe token → execution engine (CANN pipe_t family).
PIPE_TO_ENGINE: dict[str, str] = {
    "S": "SCALAR",
    "PIPE_S": "SCALAR",
    "V": "VECTOR",
    "PIPE_V": "VECTOR",
    "M": "CUBE",
    "PIPE_M": "CUBE",
    "MTE1": "MTE",
    "PIPE_MTE1": "MTE",
    "MTE2": "MTE",
    "PIPE_MTE2": "MTE",
    "MTE3": "MTE",
    "PIPE_MTE3": "MTE",
    "FIX": "FIX",
    "PIPE_FIX": "FIX",
    "ALL": "ALL",
    "PIPE_ALL": "ALL",
}

# HardEvent enumerators from kernel_event.h (src_dst).
# Kept as an explicit set so typos do not invent pipes.
HARD_EVENTS: frozenset[str] = frozenset(
    {
        "MTE2_MTE1",
        "MTE1_MTE2",
        "MTE1_M",
        "M_MTE1",
        "MTE2_V",
        "V_MTE2",
        "MTE3_V",
        "V_MTE3",
        "M_V",
        "V_M",
        "V_V",
        "MTE3_MTE1",
        "MTE1_MTE3",
        "MTE1_V",
        "MTE2_M",
        "M_MTE2",
        "V_MTE1",
        "M_FIX",
        "FIX_M",
        "MTE3_MTE2",
        "MTE2_MTE3",
        "S_V",
        "V_S",
        "S_MTE2",
        "MTE2_S",
        "S_MTE3",
        "MTE3_S",
        "MTE2_FIX",
        "FIX_MTE2",
        "FIX_S",
        "M_S",
        "FIX_MTE3",
        "MTE1_FIX",
        "FIX_MTE1",
        "FIX_FIX",
        "FIX_V",
        "V_FIX",
    }
)

_HARD_EVENT_RE = re.compile(
    r"(?:HardEvent(?:Aic|Aiv)?::)?(?P<evt>" + "|".join(sorted(HARD_EVENTS, key=len, reverse=True)) + r")\b"
)
_PIPE_RE = re.compile(r"\b(?P<pipe>PIPE_[A-Z0-9]+|[SMV]|MTE[123]|FIX|ALL)\b")

# MutexBufferInfo-style default pipes by BufferType / memory_space (CANN).
# Prod = writer side, Cons = reader side.
MUTEX_PIPES_BY_SPACE: dict[str, tuple[str, str]] = {
    "L1": ("PIPE_MTE2", "PIPE_MTE1"),
    "L0A": ("PIPE_MTE1", "PIPE_M"),
    "L0B": ("PIPE_MTE1", "PIPE_M"),
    "C2": ("PIPE_MTE1", "PIPE_M"),
    "L0C": ("PIPE_M", "PIPE_FIX"),
    "UB": ("PIPE_MTE2", "PIPE_V"),
    "GM": ("PIPE_MTE2", "PIPE_S"),
}


def mutex_pipe_for(callee: str, memory_space: str) -> str:
    """Resolve pipe for LockProd/UnlockCons-style calls from storage space."""
    space = str(memory_space or "")
    pipes = MUTEX_PIPES_BY_SPACE.get(space)
    if not pipes:
        return ""
    prod, cons = pipes
    name = str(callee or "").split("::")[-1]
    if "Prod" in name:
        return prod
    if "Cons" in name:
        return cons
    return ""


# Callee → sync mechanism (registry category still comes from sync.yaml).
# True AscendC roots only (kernel_operator_block_sync_intf.h + kernel_common.h Mutex).
SYNC_MECHANISM: dict[str, str] = {
    "SetFlag": "hard_event",
    "WaitFlag": "hard_event",
    "PipeBarrier": "barrier",
    "DataSyncBarrier": "barrier",
    "SyncAll": "barrier",
    "CrossCoreSetFlag": "cross_core",
    "CrossCoreWaitFlag": "cross_core",
    "IBSet": "inter_block",
    "IBWait": "inter_block",
    "TQueSync": "queue_sync",
    "AllocMutexID": "mutex",
    "ReleaseMutexID": "mutex",
    "Lock": "mutex",
    "Unlock": "mutex",
}

# Project / policy wrappers that forward to AscendC Mutex::Lock/Unlock.
# Not AscendC roots — root-trace must land on Lock/Unlock.
SYNC_WRAPPER_TO_ROOT: dict[str, str] = {
    "LockProd": "Lock",
    "UnlockProd": "Unlock",
    "LockCons": "Lock",
    "UnlockCons": "Unlock",
}


def pipe_engine(pipe: str) -> str:
    text = str(pipe or "").strip()
    if not text:
        return "UNKNOWN"
    if text in PIPE_TO_ENGINE:
        return PIPE_TO_ENGINE[text]
    upper = text.upper()
    if upper in PIPE_TO_ENGINE:
        return PIPE_TO_ENGINE[upper]
    # Strip PIPE_ prefix variants already covered; last resort token after ::
    token = upper.split("::")[-1]
    return PIPE_TO_ENGINE.get(token, "UNKNOWN")


def parse_hard_event(text: str) -> tuple[str, str, str] | None:
    """Return (event_name, src_pipe, dst_pipe) or None."""
    m = _HARD_EVENT_RE.search(str(text or ""))
    if not m:
        return None
    evt = m.group("evt")
    parts = evt.split("_", 1)
    if len(parts) != 2:
        return None
    return evt, parts[0], parts[1]


def parse_pipe_token(text: str) -> str:
    m = _PIPE_RE.search(str(text or ""))
    if not m:
        return ""
    tok = m.group("pipe")
    return tok if tok.startswith("PIPE_") else f"PIPE_{tok}" if tok in {"S", "V", "M", "FIX", "ALL"} or tok.startswith("MTE") else tok


def resolve_sync_site(
    callee: str,
    args: list[str] | None = None,
    targs: list[str] | None = None,
) -> dict[str, Any]:
    """Classify one sync call site from callee + template/args (CANN-aligned)."""
    name = str(callee or "").split("::")[-1]
    args = [str(a) for a in (args or [])]
    targs = [str(a) for a in (targs or [])]
    joined = " ".join(targs + args)

    mechanism = SYNC_MECHANISM.get(name, "")
    if not mechanism and name in SYNC_WRAPPER_TO_ROOT:
        mechanism = SYNC_MECHANISM.get(SYNC_WRAPPER_TO_ROOT[name], "mutex")
    cross = name.startswith("CrossCore") or mechanism == "cross_core"

    if "SetFlag" in name:
        skind = "SetFlag"
    elif "WaitFlag" in name:
        skind = "WaitFlag"
    elif name in {"PipeBarrier", "DataSyncBarrier", "SyncAll"}:
        skind = "BARRIER"
    elif name in {"IBSet"}:
        skind = "IBSet"
    elif name in {"IBWait"}:
        skind = "IBWait"
    elif name in {"Lock", "LockProd", "LockCons", "AllocMutexID"}:
        skind = "MutexLock"
    elif name in {"Unlock", "UnlockProd", "UnlockCons", "ReleaseMutexID"}:
        skind = "MutexUnlock"
    else:
        skind = name

    hard = parse_hard_event(joined)
    event = hard[0] if hard else ""
    src_pipe = hard[1] if hard else ""
    dst_pipe = hard[2] if hard else ""

    pipe = ""
    for t in targs:
        p = parse_pipe_token(t)
        if p:
            pipe = p
            break
    if not pipe:
        pipe = parse_pipe_token(joined)
    if not pipe and src_pipe and dst_pipe:
        # Represent HardEvent as SRC_DST pipe label for pairing/debug.
        pipe = f"{src_pipe}_{dst_pipe}"

    flag = ""
    if args:
        # CrossCore / SetFlag / WaitFlag: flag id is typically args[0]
        # IBSet/IBWait: args are gm, ub, blockIdx, eventID — flag = eventID
        if skind in {"IBSet", "IBWait"} and len(args) >= 4:
            flag = args[3]
        else:
            flag = args[0]

    src_engine = pipe_engine(src_pipe) if src_pipe else "UNKNOWN"
    dst_engine = pipe_engine(dst_pipe) if dst_pipe else "UNKNOWN"
    if src_engine == "UNKNOWN" and dst_engine == "UNKNOWN" and pipe:
        eng = pipe_engine(pipe)
        # Barriers / mutex / cross-core often have a single pipe.
        if skind == "SetFlag" or skind == "MutexLock":
            src_engine = eng
        elif skind == "WaitFlag" or skind == "MutexUnlock":
            dst_engine = eng
        elif skind == "BARRIER":
            src_engine = eng
            dst_engine = eng
        elif cross:
            if "Set" in name:
                src_engine = eng
            else:
                dst_engine = eng

    if not mechanism:
        if cross:
            mechanism = "cross_core"
        elif event:
            mechanism = "hard_event"
        elif skind.startswith("Mutex"):
            mechanism = "mutex"
        elif skind.startswith("IB"):
            mechanism = "inter_block"
        elif skind == "BARRIER":
            mechanism = "barrier"

    # Primary engine for OPERATION.engine field.
    if skind in {"SetFlag", "MutexLock", "IBSet"} or (cross and "Set" in name):
        primary = src_engine if src_engine != "UNKNOWN" else dst_engine
    elif skind in {"WaitFlag", "MutexUnlock", "IBWait"} or (cross and "Wait" in name):
        primary = dst_engine if dst_engine != "UNKNOWN" else src_engine
    else:
        primary = src_engine if src_engine != "UNKNOWN" else dst_engine

    return {
        "kind": skind,
        "mechanism": mechanism or "unknown",
        "flag": str(flag),
        "pipe": str(pipe),
        "event": str(event),
        "cross_core": bool(cross),
        "src_pipe": src_pipe,
        "dst_pipe": dst_pipe,
        "src_engine": src_engine,
        "dst_engine": dst_engine,
        "engine": primary if primary != "UNKNOWN" else "UNKNOWN",
    }
