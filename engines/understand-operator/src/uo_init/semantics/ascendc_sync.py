# -*- coding: utf-8 -*-
"""AscendC / CANN synchronization catalog for Kernel Root Trace.

Two CANN contracts, kept separate:

- **Flag sync** (SetFlag/WaitFlag, CrossCore*, IB*): user-visible event identity.
  UO records SIGNALS/AWAITS and identity-level pair appearance. It does **not**
  infer happens-before, engine scheduling, or which call-site waits on which.
- **TQue** (EnQue/DeQue/AllocTensor/FreeTensor): handshake lives inside CANN
  ``TQueBind`` (EnQue → SetFlag, DeQue → WaitFlag). No user event identity;
  these APIs stay outside the flag pair check.
- **TPipe** (InitBuffer, FetchEventID, GetTPipePtr): pipe/allocator, not TQue.

Project wrapper methods are not auto-jumped to roots by name; source CALLS
(or an explicit external framework bridge) must close the path.
"""

from __future__ import annotations

import re
from typing import Any

# HardEvent enumerators from kernel_event.h (src_dst) — literal evidence only.
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
    r"(?:HardEvent(?:Aic|Aiv)?::)?(?P<evt>"
    + "|".join(sorted(HARD_EVENTS, key=len, reverse=True))
    + r")\b"
)
_PIPE_RE = re.compile(r"\b(?P<pipe>PIPE_[A-Z0-9]+|[SMV]|MTE[123]|FIX|ALL)\b")

# True AscendC roots only (kernel_operator_block_sync_intf.h + kernel_common.h).
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

# User-level flag APIs that must appear as signal + wait on the same identity.
# Mate is the other side of the family, not a happens-before edge.
FLAG_PAIR_MATE: dict[str, str] = {
    "SetFlag": "WaitFlag",
    "WaitFlag": "SetFlag",
    "CrossCoreSetFlag": "CrossCoreWaitFlag",
    "CrossCoreWaitFlag": "CrossCoreSetFlag",
    "IBSet": "IBWait",
    "IBWait": "IBSet",
}
FLAG_SYNC_CALLEES: frozenset[str] = frozenset(FLAG_PAIR_MATE)

# TQue programming model (queue.yaml). CANN encapsulates the pipe handshake;
# these names must not enter FLAG_SYNC pairing or SIGNALS/AWAITS.
TQUE_CALLEES: frozenset[str] = frozenset(
    {
        "EnQue",
        "DeQue",
        "AllocTensor",
        "FreeTensor",
    }
)

# TPipe (kernel_tpipe.h / kernel_common.h). InitBuffer binds a TQue/TBuf; not a TQue method.
TPIPE_CALLEES: frozenset[str] = frozenset(
    {
        "InitBuffer",
        "FetchEventID",
        "GetTPipePtr",
    }
)


def _short_callee(name: str) -> str:
    return str(name or "").split("::")[-1]


def is_flag_sync(name: str) -> bool:
    return _short_callee(name) in FLAG_SYNC_CALLEES


def is_tque_callee(name: str) -> bool:
    return _short_callee(name) in TQUE_CALLEES


def is_tpipe_callee(name: str) -> bool:
    return _short_callee(name) in TPIPE_CALLEES


def flag_pair_key(identity: str, sync: dict[str, Any] | None = None) -> tuple[str, str, str]:
    """Group key for identity-level pair appearance (mechanism, id, HardEvent)."""
    sync = sync or {}
    return (
        str(sync.get("mechanism") or ""),
        str(identity or "").strip(),
        str(sync.get("event") or ""),
    )


def parse_hard_event(text: str) -> tuple[str, str, str] | None:
    """Return (event_name, src_pipe, dst_pipe) or None — literal template evidence."""
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
    if tok.startswith("PIPE_"):
        return tok
    if tok in {"S", "V", "M", "FIX", "ALL"} or tok.startswith("MTE"):
        return f"PIPE_{tok}"
    return tok


def resolve_sync_site(
    callee: str,
    args: list[str] | None = None,
    targs: list[str] | None = None,
) -> dict[str, Any]:
    """Classify one sync call site from callee + template/args (catalog only).

    Returns mechanism / flag / event / pipe literals. No engine schedule fields.
    """
    name = str(callee or "").split("::")[-1]
    args = [str(a) for a in (args or [])]
    targs = [str(a) for a in (targs or [])]
    joined = " ".join(targs + args)

    mechanism = SYNC_MECHANISM.get(name, "")
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
    elif name in {"Lock", "AllocMutexID"}:
        skind = "MutexLock"
    elif name in {"Unlock", "ReleaseMutexID"}:
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
        pipe = f"{src_pipe}_{dst_pipe}"

    flag = ""
    if args:
        if skind in {"IBSet", "IBWait"} and len(args) >= 4:
            flag = args[3]
        else:
            flag = args[0]

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

    return {
        "kind": skind,
        "mechanism": mechanism or "unknown",
        "flag": str(flag),
        "pipe": str(pipe),
        "event": str(event),
        "cross_core": bool(cross),
        "src_pipe": src_pipe,
        "dst_pipe": dst_pipe,
    }
