# -*- coding: utf-8 -*-
"""Kernel-side uo-query quality probe vs FAG arch35 source ground truth."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(r"d:\TEST\AscendC-Pilot")
OP = Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad")
OUT = REPO / "docs" / "history" / "fag_test" / "uoquery-kernel-cards.json"
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]
from uo_init.uo_query import open_query  # noqa: E402

CATALOG = ["TPipe", "TQue", "LocalTensor", "HardEvent", "PIPE_MTE3", "PIPE_MTE2", "PIPE_FIX", "TBuf"]
INSTANCES = [
    "pipeIn",
    "pipeBase",
    "pipePost",
    "pipe",
    "inQueuePing",
    "helpQue",
    "inputQue",
    "outQue",
    "MutexBuffer",
    "MutexBuffersPolicySingleBuffer",
    "MutexBuffersPolicyDB",
    "MutexBuffersPolicy3buff",
    "MutexBuffersPolicy4buff",
    "MutexBufferManager",
    "AllocMutexID",
    "ReleaseMutexID",
    "InitBuffer",
    "dSL1Buf",
    "pL1Buf",
    "l1BufferManager",
    "SyncALLCores",
    "SyncAll",
    "CrossCoreSetFlag",
    "CrossCoreWaitFlag",
    "SetFlag",
    "WaitFlag",
    "SYNC_DETER_FIX_FLAG",
    "SYNC_V2_TO_C1_FLAG",
    "SetScheduleMode",
    "RegbaseFAG",
    "Destroy",
    "Lock",
    "Unlock",
    "buffer",
]


def short_file(path: str) -> str:
    p = str(path or "").replace("\\", "/")
    for marker in ("flash_attention_score_grad/", "common/op_kernel/", "op_kernel/"):
        if marker in p:
            return p.split(marker, 1)[-1] if marker != "op_kernel/" else p[p.find("op_kernel/") :]
    return p.split("/")[-1] if p else ""


def compact(payload: dict) -> dict:
    cards = payload.get("cards") or payload.get("phases") or payload.get("seeds") or []
    if not isinstance(cards, list):
        cards = []
    slim = []
    for c in cards[:8]:
        if not isinstance(c, dict):
            continue
        snip = str(c.get("snippet") or c.get("snippet_head") or "")
        slim.append(
            {
                "kind": c.get("kind"),
                "name": c.get("name") or c.get("phase") or c.get("id"),
                "file": short_file(str(c.get("file") or "")),
                "line": c.get("line") or c.get("line_start") or 0,
                "truncated": bool(c.get("truncated")),
                "catalog": c.get("catalog"),
                "role": c.get("role"),
                "wrapper": c.get("wrapper") or (c.get("attrs") or {}).get("wrapper") if isinstance(c.get("attrs"), dict) else c.get("wrapper"),
                "tposition": c.get("tposition") or (c.get("facts") or {}).get("tposition") if isinstance(c.get("facts"), dict) else None,
                "snippet_head": " | ".join(snip.splitlines()[:8])[:360],
            }
        )
    extras = {}
    for key in ("seeds", "hits", "neighbors", "phases"):
        val = payload.get(key)
        if isinstance(val, list):
            extras[f"{key}_len"] = len(val)
            if val and isinstance(val[0], dict) and key != "seeds":
                extras[f"{key}_0"] = {
                    "kind": val[0].get("kind"),
                    "name": val[0].get("name"),
                    "file": short_file(str(val[0].get("file") or "")),
                    "line": val[0].get("line") or val[0].get("line_start"),
                    "rel": val[0].get("rel"),
                }
    return {
        "ok": payload.get("ok"),
        "shape": payload.get("shape") or payload.get("mode"),
        "count": payload.get("count"),
        "hint": (payload.get("hint") or "")[:200],
        "next": payload.get("next"),
        "error": payload.get("error") or payload.get("message_zh"),
        "cards": slim,
        **extras,
    }


def main() -> int:
    q = open_query(OP, architecture="arch35")
    rows = []
    print("INDEX", flush=True)
    idx = q.agent_query(pattern="")
    rec = compact(idx)
    rec.update({"group": "index", "query": ""})
    # keep phase names if present
    phases = idx.get("phases") or idx.get("cards") or []
    rec["raw_top_keys"] = list(idx.keys())
    if isinstance(phases, list):
        rec["phase_rows"] = [
            {
                "name": (p.get("name") or p.get("phase") or p.get("kind")),
                "file": short_file(str(p.get("file") or "")),
                "line": p.get("line") or p.get("line_start"),
                "kind": p.get("kind"),
            }
            for p in phases[:12]
            if isinstance(p, dict)
        ]
    rows.append(rec)

    for name in CATALOG:
        print("CATALOG", name, flush=True)
        rec = compact(q.agent_query(pattern=name))
        rec.update({"group": "catalog", "query": name})
        rows.append(rec)

    arounds = []
    for name in INSTANCES:
        print("IDENT", name, flush=True)
        payload = q.agent_query(pattern=name)
        rec = compact(payload)
        rec.update({"group": "ident", "query": name})
        rows.append(rec)
        for c in rec.get("cards") or []:
            f = str(c.get("file") or "")
            line = int(c.get("line") or 0)
            if f and line and name in {
                "MutexBuffer",
                "pipeIn",
                "pipeBase",
                "SyncALLCores",
                "InitBuffer",
                "dSL1Buf",
                "inQueuePing",
                "SYNC_DETER_FIX_FLAG",
            }:
                arounds.append((name, f, line))

    seen = set()
    for name, f, line in arounds:
        key = (f, line)
        if key in seen:
            continue
        seen.add(key)
        print("AROUND", name, f, line, flush=True)
        rec = compact(q.agent_query(file=f, line=line))
        rec.update({"group": "around", "query": f"--file {f} --line {line}", "from": name})
        rows.append(rec)

    OUT.write_text(json.dumps({"n": len(rows), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote", OUT, "n=", len(rows), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
