#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query-side latency for the ``.uo`` product, cold start separated from steady state.

"How fast is a query" is two different numbers and quoting either alone
misleads. A one-shot process pays for the interpreter, the imports and the first
page faults against a 50 MB file before it answers anything; a resident daemon
pays that once and then answers from a warm cache. This measures both, and
per-case so the slow questions can be named rather than averaged away.

Cases are the answer gate's, so latency is reported over the same query surface
whose answers are pinned -- a speedup that changed an answer would show up
there.

    python tools/uo_query_bench.py
    python tools/uo_query_bench.py --rounds 8 --daemon
    python tools/uo_query_bench.py --cold-runs 3
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
REPO = ENGINE.parents[1]
sys.path[:0] = [str(ENGINE / "src"), str(REPO / "engines" / "common"), str(REPO / "pilot")]
sys.path.insert(0, str(Path(__file__).resolve().parent))

COLD_CHILD = r"""
import json, os, sys, time
t_start = time.perf_counter()
sys.path.insert(0, os.environ["UO_BENCH_SRC"])
sys.path.insert(0, os.environ["UO_BENCH_TOOLS"])
from pathlib import Path
t_import = time.perf_counter()
from uo_init.uo_query import open_query
t_import_query = time.perf_counter()
q = open_query(Path(os.environ["UO_OP_DIR"]), architecture=os.environ["UO_ARCH"])
t_open = time.perf_counter()
payload = q.agent_query(pattern=os.environ.get("UO_BENCH_PATTERN") or "keep_prob")
t_first = time.perf_counter()
payload2 = q.agent_query(pattern="Init")
t_second = time.perf_counter()
q.close()
print(json.dumps({
    "interp_and_path_s": t_import - t_start,
    "import_uo_query_s": t_import_query - t_import,
    "open_query_s": t_open - t_import_query,
    "first_query_s": t_first - t_open,
    "second_query_s": t_second - t_first,
    "total_to_first_answer_s": t_first - t_start,
    "ok": bool(payload.get("ok")),
}))
"""


def measure_cold(op: Path, arch: str, runs: int, daemon: bool) -> list[dict[str, Any]]:
    """Interpreter start -> first answer, in a fresh process each time."""
    env = dict(os.environ)
    env.update(
        {
            "UO_BENCH_SRC": str(ENGINE / "src"),
            "UO_BENCH_TOOLS": str(ENGINE / "tools"),
            "UO_OP_DIR": str(op),
            "UO_ARCH": arch,
            "PYTHONIOENCODING": "utf-8",
        }
    )
    if daemon:
        env["UO_QUERY_DAEMON"] = "1"
    else:
        env.pop("UO_QUERY_DAEMON", None)
    out: list[dict[str, Any]] = []
    for _ in range(runs):
        proc = subprocess.run(
            [sys.executable, "-c", COLD_CHILD],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        line = (proc.stdout or "").strip().splitlines()
        if not line:
            raise RuntimeError((proc.stderr or "no output").strip()[-2000:])
        out.append(json.loads(line[-1]))
    return out


def measure_warm(op: Path, arch: str, rounds: int, daemon: bool) -> dict[str, Any]:
    """Per-case latency inside one process, first round kept separate."""
    if daemon:
        os.environ["UO_QUERY_DAEMON"] = "1"
    else:
        os.environ.pop("UO_QUERY_DAEMON", None)

    from uo_answer_gate import build_cases

    from uo_init.uo_query import open_query

    q = open_query(op, architecture=arch)
    per_case: dict[str, list[float]] = {}
    try:
        cases = build_cases()
        for round_i in range(rounds):
            for case in cases:
                cid = case["id"]
                t0 = time.perf_counter()
                try:
                    q.agent_query(**case["argv"])
                except Exception:  # noqa: BLE001
                    continue
                dt = (time.perf_counter() - t0) * 1000.0
                per_case.setdefault(cid, []).append(dt)
            if round_i == 0:
                first_round = {k: v[0] for k, v in per_case.items()}
    finally:
        q.close()

    warm = {k: v[1:] for k, v in per_case.items() if len(v) > 1}
    return {"first_round_ms": first_round, "warm_ms": warm}


def profile_one(op: Path, arch: str, pattern: str, repeat: int, top: int) -> None:
    """cProfile one query, ranked over uo's own frames.

    Reached for after the clock says a case is slow, to answer where the time
    went. The daemon PRAGMA experiment showed the cost is not in reading pages,
    so the answer is expected to be Python frames -- this names which.
    """
    import cProfile
    import pstats

    from uo_init.uo_query import open_query

    q = open_query(op, architecture=arch)
    try:
        q.agent_query(pattern=pattern)  # warm whatever caches exist
        prof = cProfile.Profile()
        prof.enable()
        for _ in range(repeat):
            q.agent_query(pattern=pattern)
        prof.disable()
    finally:
        q.close()

    stats = pstats.Stats(prof)
    rows = []
    for func, (_cc, nc, tt, ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]
        filename, lineno, name = func
        norm = filename.replace("\\", "/")
        where = norm.split("/uo_init/")[-1] if "/uo_init/" in norm else norm.split("/")[-1]
        rows.append((ct / repeat * 1000, tt / repeat * 1000, nc / repeat, f"{where}:{lineno} {name}"))
    rows.sort(key=lambda r: -r[0])
    print(f"\nprofile of pattern={pattern!r}, {repeat} runs, per-run ms (profiler-inflated)")
    print(f"{'cum ms':>9}  {'tot ms':>9}  {'calls':>9}  where")
    print("-" * 78)
    for cum, tot, calls, where in rows[:top]:
        print(f"{cum:>9.2f}  {tot:>9.2f}  {calls:>9.0f}  {where}")


def _dist(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    return {
        "n": len(s),
        "p50": round(statistics.median(s), 2),
        "p95": round(s[max(0, int(len(s) * 0.95) - 1)], 2),
        "max": round(s[-1], 2),
        "mean": round(statistics.fmean(s), 2),
        "total": round(sum(s), 1),
    }


def _compare_mcp(op: Path, arch: str, rounds: int) -> int:
    """In-process SQLite vs optional daemon hop; MCP defaults to in-process."""
    from uo_init.query.sql import UoSqlQuery
    from uo_init.store.reader import find_uo_product

    product = find_uo_product(op, architecture=arch)
    if product is None or not Path(product).is_file():
        print("no .uo product")
        return 2
    pattern = "keep_prob"
    q = UoSqlQuery(product)
    try:
        q.agent_query(pattern=pattern)
        times: list[float] = []
        for _ in range(max(1, rounds)):
            t0 = time.perf_counter()
            q.agent_query(pattern=pattern)
            times.append((time.perf_counter() - t0) * 1000)
    finally:
        q.close()
    d = _dist(times)
    print(
        f"in-process UoSqlQuery (MCP default)  p50={d['p50']:.2f}ms  "
        f"p95={d['p95']:.2f}ms  n={d['n']}"
    )

    from uo_init.query_client import try_agent_query

    hop = try_agent_query(Path(product), pattern=pattern, architecture=arch)
    if hop is None:
        print("daemon hop: unavailable (CLI daemon not running; MCP still in-process)")
        return 0
    hops: list[float] = []
    for _ in range(max(1, rounds)):
        t0 = time.perf_counter()
        try_agent_query(Path(product), pattern=pattern, architecture=arch)
        hops.append((time.perf_counter() - t0) * 1000)
    hd = _dist(hops)
    print(
        f"daemon hop                           p50={hd['p50']:.2f}ms  "
        f"p95={hd['p95']:.2f}ms  n={hd['n']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="uo query latency")
    ap.add_argument("--op", type=Path, default=None)
    ap.add_argument("--arch", default=None)
    ap.add_argument("--rounds", type=int, default=6, help="warm rounds over all cases")
    ap.add_argument("--cold-runs", type=int, default=3)
    ap.add_argument("--daemon", action="store_true", help="set UO_QUERY_DAEMON=1")
    ap.add_argument(
        "--compare-mcp",
        action="store_true",
        help="time in-process UoSqlQuery vs daemon hop (same pattern)",
    )
    ap.add_argument("--slowest", type=int, default=10)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--profile", default=None, metavar="PATTERN", help="cProfile one query instead of benching")
    ap.add_argument("--repeat", type=int, default=10, help="runs inside --profile")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args(argv)

    op = args.op or Path(os.environ.get("UO_OP_DIR") or "")
    arch = args.arch or os.environ.get("UO_ARCH") or ""
    if not op.is_dir() or not arch:
        print("pass --op/--arch or set UO_OP_DIR/UO_ARCH")
        return 2

    if args.profile is not None:
        profile_one(op, arch, args.profile, args.repeat, args.top)
        return 0

    if args.compare_mcp:
        return _compare_mcp(op, arch, args.rounds)

    mode = "daemon PRAGMA (cache 32MB, mmap 64MB)" if args.daemon else "one-shot PRAGMA (cache 8MB, mmap 8MB)"
    print(f"op={op.name} arch={arch}  {mode}\n")

    cold = measure_cold(op, arch, args.cold_runs, args.daemon)
    print("cold start, fresh process each time (seconds)")
    keys = (
        "interp_and_path_s",
        "import_uo_query_s",
        "open_query_s",
        "first_query_s",
        "second_query_s",
        "total_to_first_answer_s",
    )
    for key in keys:
        vals = [float(r[key]) for r in cold]
        print(
            f"  {key:<26}{statistics.fmean(vals):7.3f}  "
            + " / ".join(f"{v:.3f}" for v in vals)
        )

    warm = measure_warm(op, arch, args.rounds, args.daemon)
    first = list(warm["first_round_ms"].values())
    steady = [v for vals in warm["warm_ms"].values() for v in vals]
    print(f"\nin-process latency over {len(warm['first_round_ms'])} cases (ms)")
    d1, d2 = _dist(first), _dist(steady)
    print(f"  first touch   p50={d1['p50']:>7.2f}  p95={d1['p95']:>7.2f}  max={d1['max']:>7.2f}  sum={d1['total']:.0f}ms")
    print(f"  repeated      p50={d2['p50']:>7.2f}  p95={d2['p95']:>7.2f}  max={d2['max']:>7.2f}")

    ranked = sorted(
        ((cid, statistics.median(v)) for cid, v in warm["warm_ms"].items()),
        key=lambda kv: -kv[1],
    )[: args.slowest]
    print(f"\nslowest {len(ranked)} cases (repeated median, ms)")
    for cid, ms in ranked:
        firstms = warm["first_round_ms"].get(cid, 0.0)
        print(f"  {ms:>8.2f}   (first touch {firstms:>8.2f})   {cid}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"cold": cold, "warm": warm}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
