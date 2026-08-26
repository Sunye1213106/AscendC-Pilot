#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cProfile the analyze stage and rank uo's own frames.

Use this to *locate* hot code, never to size a win. cProfile bills every call,
so removing calls looks far better under the profiler than it does on the clock:
one earlier round watched a profiled total fall 80.8s -> 54.3s while the real
build moved 41.5 -> 39.9. Find the hotspot here, then confirm it with
``uo_perf_bench.py``.

Frames are filtered to `uo_init` by default because a raw ranking is topped by
`re`, `pathlib` and `pickle` internals, which say that string and path work is
expensive without saying which pass asked for it.

    python tools/uo_profile_analyze.py --top 40
    python tools/uo_profile_analyze.py --callers normalize_symbol
    python tools/uo_profile_analyze.py --all-frames --sort tottime
"""
from __future__ import annotations

import argparse
import cProfile
import os
import pstats
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE / "src"))

DEFAULT_PROF = ENGINE / ".perf" / "analyze.prof"


def run_analyze(op: Path, arch: str, out: Path) -> float:
    from uo_init import codemap_engines as ce

    payload = {
        "arch_dir": arch,
        "architecture": arch,
        "run_id": "profile-analyze",
        "keep_other_runs": True,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    prof = cProfile.Profile()
    t0 = time.perf_counter()
    prof.enable()
    result = ce.analyze(op, payload)
    prof.disable()
    elapsed = time.perf_counter() - t0
    prof.dump_stats(str(out))
    if not result.get("ok"):
        print(f"WARNING analyze failed: {str(result.get('error'))[:300]}", flush=True)
    return elapsed


def _rows(stats: pstats.Stats, *, only_uo: bool, sort: str, top: int):
    stats.sort_stats(sort)
    out = []
    for func, (_cc, nc, tt, ct, callers) in stats.stats.items():  # type: ignore[attr-defined]
        filename, lineno, name = func
        norm = filename.replace("\\", "/")
        if only_uo and "/uo_init/" not in norm:
            continue
        where = norm.split("/uo_init/")[-1] if "/uo_init/" in norm else norm.split("/")[-1]
        out.append(
            {
                "where": f"{where}:{lineno}",
                "name": name,
                "calls": nc,
                "tottime": tt,
                "cumtime": ct,
                "callers": callers,
            }
        )
    key = "cumtime" if sort.startswith("cum") else "tottime"
    out.sort(key=lambda r: -r[key])
    return out[: top or None]


def print_table(rows, elapsed: float) -> None:
    print(f"\nprofiled analyze wall: {elapsed:.2f}s (inflated by the profiler)\n")
    head = f"{'cumtime':>9}  {'tottime':>9}  {'calls':>10}  where"
    print(head)
    print("-" * (len(head) + 30))
    for r in rows:
        print(
            f"{r['cumtime']:>9.3f}  {r['tottime']:>9.3f}  {r['calls']:>10,}  "
            f"{r['where']} {r['name']}"
        )


def print_callers(stats: pstats.Stats, needle: str, top: int) -> None:
    """Who spends the time in a function -- the question a flat ranking cannot answer.

    A hot leaf is usually not where the fix goes. `normalize_symbol` showed 2.4M
    calls, but the change that mattered was one caller rebuilding a set on every
    lookup; the leaf itself was already cheap.
    """
    found = []
    for func, (_cc, nc, tt, ct, callers) in stats.stats.items():  # type: ignore[attr-defined]
        if needle in func[2]:
            found.append((func, nc, tt, ct, callers))
    if not found:
        print(f"no function matching {needle!r}")
        return
    for func, nc, tt, ct, callers in sorted(found, key=lambda r: -r[3]):
        filename, lineno, name = func
        short = filename.replace("\\", "/").split("/uo_init/")[-1]
        print(f"\n{short}:{lineno} {name}  calls={nc:,} tottime={tt:.3f} cumtime={ct:.3f}")
        ranked = sorted(callers.items(), key=lambda kv: -(kv[1][3] if isinstance(kv[1], tuple) else 0))
        for cfunc, cval in ranked[:top]:
            cn = cval[0] if isinstance(cval, tuple) else cval
            cct = cval[3] if isinstance(cval, tuple) else 0.0
            cshort = cfunc[0].replace("\\", "/").split("/uo_init/")[-1]
            print(f"    {cn:>10,} calls  {cct:>8.3f}s  {cshort}:{cfunc[1]} {cfunc[2]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="cProfile the uo analyze stage")
    ap.add_argument("--op", type=Path, default=None)
    ap.add_argument("--arch", default=None)
    ap.add_argument("--top", type=int, default=35)
    ap.add_argument("--sort", default="cumtime", choices=("cumtime", "tottime"))
    ap.add_argument("--all-frames", action="store_true", help="do not filter to uo_init")
    ap.add_argument("--callers", default=None, help="rank callers of functions matching this name")
    ap.add_argument("--prof", type=Path, default=DEFAULT_PROF)
    ap.add_argument("--reuse", action="store_true", help="read --prof instead of re-profiling")
    args = ap.parse_args(argv)

    op = args.op or Path(os.environ.get("UO_OP_DIR") or "")
    arch = args.arch or os.environ.get("UO_ARCH") or ""
    elapsed = 0.0
    if args.reuse:
        if not args.prof.is_file():
            print(f"no profile at {args.prof}; drop --reuse")
            return 2
    else:
        if not op.is_dir():
            print("operator dir missing: pass --op or set UO_OP_DIR")
            return 2
        if not arch:
            print("architecture missing: pass --arch or set UO_ARCH")
            return 2
        elapsed = run_analyze(op, arch, args.prof)

    stats = pstats.Stats(str(args.prof))
    if args.callers:
        print_callers(stats, args.callers, args.top)
        return 0
    rows = _rows(stats, only_uo=not args.all_frames, sort=args.sort, top=args.top)
    print_table(rows, elapsed)
    print(f"\nprofile at {args.prof}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
