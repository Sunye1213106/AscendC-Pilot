# -*- coding: utf-8 -*-
"""Sequential uo-query battery (>=150). One operator live at a time."""
from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]

OPS = {
    "FAG": Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"),
    "IFA": Path(r"d:\TEST\ops-transformer\attention\incre_flash_attention"),
    "GMM": Path(r"d:\TEST\ops-transformer\gmm\grouped_matmul"),
    "NSA": Path(r"d:\TEST\ops-transformer\attention\nsa_compress"),
}
ARCH = "arch35"
OUT = REPO / "docs" / "test" / "results" / "uo-cannbot" / "query_battery.json"

IDENTIFIERS = {
    "FAG": [
        "s1Inner", "IsTnd", "pipeBase", "pipePost", "pipeIn", "Init", "Process",
        "TPipe", "tilingData", "ASCENDC_TPL_ARGS_DECL", "GET_TPL_TILING_KEY",
        "LocalTensor", "TQue", "HardEvent", "PIPE_MTE3", "coreNum",
        "FlashAttentionScoreGradTilingData", "s2Inner", "dInner",
    ],
    "IFA": [
        "HasAttenMask", "tPipe", "tPipe1", "Init", "Process", "TPipe",
        "tilingData", "LocalTensor", "TQue", "IncreFlashAttentionTilingDataRegbase",
        "HasRope", "QuantMode", "Config", "actualSeqLengths", "attenMask",
    ],
    "GMM": [
        "TRANS_B", "TRANS_A", "groupNum", "D_T_A", "D_T_B", "D_T_Y",
        "Init", "Process", "TPipe", "LocalTensor", "TQue", "grouped_matmul",
        "IS_STATIC_TILING_API", "GROUP_LIST_TYPE",
    ],
    "NSA": [
        "pipe", "Init", "Process", "TPipe", "tiling_data", "nsa_compress",
        "LocalTensor", "TQue", "KernelNASCompress", "PerCoreOutputNum",
    ],
}


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / 1e6
    except Exception:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(pmc),
            pmc.cb,
        )
        return float(pmc.WorkingSetSize) / 1e6


def _run(q, *, pattern: str = "", file: str = "", line: int = 0) -> dict:
    t0 = time.perf_counter()
    payload = q.agent_query(pattern=pattern, file=file, line=line)
    dt = time.perf_counter() - t0
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    n = len(raw.encode("utf-8"))
    return {
        "ms": round(dt * 1000, 1),
        "bytes": n,
        "tokens": max(1, round(n / 4)),
        "ok": bool(payload.get("ok")),
        "shape": payload.get("shape") or payload.get("mode"),
        "count": payload.get("count") or payload.get("matching_block_count") or 0,
        "hint": (payload.get("hint") or "")[:120],
        "file": ((payload.get("cards") or payload.get("phases") or [{}])[0] or {}).get("file")
        if isinstance(payload.get("cards") or payload.get("phases"), list)
        else "",
        "line": int(
            ((payload.get("cards") or payload.get("phases") or [{}])[0] or {}).get("line")
            or ((payload.get("cards") or payload.get("phases") or [{}])[0] or {}).get("line_start")
            or 0
        ),
        "rss_mb": round(_rss_mb(), 1),
    }


def _cover_budget(op: str) -> int:
    return 4 if op == "IFA" else 10


def main() -> int:
    import argparse

    from uo_init.query.legal_key_cache import clear_legal_key_cache
    from uo_init.query.sql import _TEMPLATE_BLOCKS_CACHE
    from uo_init.store.reader import close_uo_connections
    from uo_init.uo_query import open_query

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(OUT),
        help="JSON result path. Do not overwrite the cannbot baseline unless asked.",
    )
    args = parser.parse_args()
    out_path = Path(args.out)

    os.environ["UO_ARCH"] = ARCH
    rows: list[dict] = []
    peak = _rss_mb()
    start_rss = peak
    t_all = time.perf_counter()
    for op, root in OPS.items():
        print(f"==== {op} rss={_rss_mb():.0f}MB ====", flush=True)
        q = open_query(root, architecture=ARCH)
        idx = _run(q)
        idx["op"] = op
        idx["morph"] = "index"
        idx["argv"] = "(none)"
        idx["scene"] = "index/launch"
        rows.append(idx)
        print(f"  index {idx['ms']}ms {idx['bytes']}B", flush=True)
        payload = q.agent_query()
        dims = [str(x) for x in (payload.get("dim_names") or []) if str(x)]
        phases = list(payload.get("phases") or [])
        n_cover = _cover_budget(op)
        for dim in dims[:n_cover]:
            r = _run(q, pattern=f"Dim={dim}")
            r.update(op=op, morph="Dim=", argv=f"Dim={dim}", scene="tilingkey/domain")
            rows.append(r)
            cov = q.agent_query(pattern=f"Dim={dim}")
            values = list((cov.get("dim_coverage") or {}).get(dim) or [])
            if values:
                combo = f"{dim}={values[0]}"
                r2 = _run(q, pattern=combo)
                r2.update(op=op, morph="Name=Value", argv=combo, scene="tilingkey/combo")
                rows.append(r2)
        for ident in IDENTIFIERS[op]:
            r = _run(q, pattern=ident)
            kind = "name"
            if ident in {"TPipe", "pipe", "pipeBase", "pipePost", "pipeIn", "tPipe", "tPipe1"}:
                scene = "sync/pipe"
            elif ident in {"LocalTensor", "TQue", "HardEvent"}:
                scene = "buffer"
            elif ident in {"ASCENDC_TPL_ARGS_DECL", "GET_TPL_TILING_KEY"}:
                scene = "template/macro"
            elif ident in {"Init", "Process"}:
                scene = "host/kernel"
            elif ident in {"s1Inner", "groupNum", "s2Inner", "dInner", "tilingData", "tiling_data"}:
                scene = "tilingdata"
            else:
                scene = "identifier"
            r.update(op=op, morph="identifier", argv=ident, scene=scene)
            rows.append(r)
            if r.get("file") and r.get("line"):
                around = _run(q, file=str(r["file"]), line=int(r["line"]))
                around.update(
                    op=op,
                    morph="--file --line",
                    argv=f"{r['file']}:{r['line']}",
                    scene="around",
                )
                rows.append(around)
        for ph in phases[:3]:
            f = str(ph.get("file") or "")
            ln = int(ph.get("line") or 0)
            if f and ln:
                around = _run(q, file=f, line=ln)
                around.update(
                    op=op,
                    morph="--file --line",
                    argv=f"{f}:{ln}",
                    scene="launch-around",
                )
                rows.append(around)
        q.close()
        clear_legal_key_cache()
        _TEMPLATE_BLOCKS_CACHE.clear()
        close_uo_connections()
        gc.collect()
        peak = max(peak, _rss_mb())
        print(f"  {op} done n={len(rows)} rss={_rss_mb():.0f}MB", flush=True)

    elapsed = round(time.perf_counter() - t_all, 2)
    summary = {
        "n": len(rows),
        "elapsed_s": elapsed,
        "rss_start_mb": round(start_rss, 1),
        "rss_end_mb": round(_rss_mb(), 1),
        "rss_peak_mb": round(peak, 1),
        "ok": sum(1 for r in rows if r.get("ok")),
        "p50_ms": sorted(r["ms"] for r in rows)[len(rows) // 2] if rows else 0,
        "p95_ms": sorted(r["ms"] for r in rows)[int(len(rows) * 0.95)] if rows else 0,
        "max_ms": max((r["ms"] for r in rows), default=0),
        "avg_bytes": int(sum(r["bytes"] for r in rows) / max(len(rows), 1)),
        "avg_tokens": int(sum(r["tokens"] for r in rows) / max(len(rows), 1)),
        "max_tokens": max((r["tokens"] for r in rows), default=0),
        "max_payload_tokens": 6000,
        "morphs": {},
        "scenes": {},
        "ops": {},
    }
    for r in rows:
        summary["morphs"].setdefault(r["morph"], 0)
        summary["morphs"][r["morph"]] += 1
        summary["scenes"].setdefault(r["scene"], 0)
        summary["scenes"][r["scene"]] += 1
        summary["ops"].setdefault(r["op"], 0)
        summary["ops"][r["op"]] += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if len(rows) >= 150 else 1


if __name__ == "__main__":
    raise SystemExit(main())
