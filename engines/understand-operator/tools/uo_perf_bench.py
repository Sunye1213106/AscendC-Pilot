#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repeated cold-run timing for uo-init, with the noise band made explicit.

One sample is not a measurement. The same code on the same machine spreads
several seconds across cold runs, so a single pair of numbers cannot tell a real
change from where in that spread the two runs happened to land -- and reading a
lucky run as a win is exactly how an earlier round booked a `-9.7%` that later
turned out to be net-unclear. This runs a stage set N times, reports the spread,
and when comparing two labels refuses to call anything a change unless it clears
the combined spread.

Each run is a fresh interpreter on purpose: the SourceIndex cache, the resolved
path memo and the compiled-regex tables all live in process memory, so reusing
one would measure a warm cache and call it a cold build.

    python tools/uo_perf_bench.py --runs 3 --label after
    python tools/uo_perf_bench.py --runs 3 --stages prepare,extract,analyze
    python tools/uo_perf_bench.py --compare .perf/before.json .perf/after.json
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
SRC = ENGINE / "src"
DEFAULT_OUT_DIR = ENGINE / ".perf"

#: Stage functions in `codemap_engines`. ``analyze`` alone is the fast loop: it
#: consumes extract's `host_ir.pkl`, so prepare/extract need not be repaid, and
#: a fresh process is all "cold" means for it.
ALL_STAGES = ("prepare", "extract", "analyze", "commit", "verify")

CHILD = r"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, os.environ["UO_BENCH_SRC"])
from uo_init import codemap_engines as ce
from uo_init import perf

op = Path(os.environ["UO_OP_DIR"])
arch = os.environ["UO_ARCH"]
payload = {
    "arch_dir": arch,
    "architecture": arch,
    "run_id": os.environ.get("UO_RUN_ID") or "perf-bench",
    "keep_other_runs": True,
}
rows = {}
for name in os.environ["UO_BENCH_STAGES"].split(","):
    fn = getattr(ce, name)
    t0 = time.perf_counter()
    out = fn(op, payload)
    dt = time.perf_counter() - t0
    ok = bool(out.get("ok"))
    rows[name] = {"ok": ok, "elapsed_s": round(dt, 3), "error": out.get("error")}
    if out.get("op_name"):
        payload["op_name"] = out["op_name"]
    if not ok:
        break
Path(os.environ["UO_BENCH_OUT"]).write_text(
    json.dumps({"stages": rows, "perf": perf.snapshot()}, ensure_ascii=False, default=str),
    encoding="utf-8",
)
"""


def run_once(op: Path, arch: str, stages: tuple[str, ...], *, quiet: bool) -> dict[str, Any]:
    """One cold run in its own interpreter."""
    tmp = DEFAULT_OUT_DIR / f"_run-{int(time.time() * 1000)}.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "UO_BENCH_SRC": str(SRC),
            "UO_BENCH_STAGES": ",".join(stages),
            "UO_BENCH_OUT": str(tmp),
            "UO_OP_DIR": str(op),
            "UO_ARCH": arch,
            "PYTHONIOENCODING": "utf-8",
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", CHILD],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not tmp.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-25:]
        raise RuntimeError("child produced no result:\n" + "\n".join(tail))
    payload = json.loads(tmp.read_text(encoding="utf-8"))
    tmp.unlink(missing_ok=True)
    if not quiet:
        bad = [n for n, r in payload["stages"].items() if not r.get("ok")]
        if bad:
            print(f"    stage FAILED: {bad} {payload['stages']}", flush=True)
    return payload


def _pass_seconds(payload: dict[str, Any]) -> dict[str, float]:
    """Flatten one run into ``name -> seconds``, stages prefixed to stay distinct."""
    out: dict[str, float] = {}
    perf = payload.get("perf") or {}
    for name, row in (perf.get("passes") or {}).items():
        if isinstance(row, dict) and row.get("wall_s") is not None:
            out[str(name)] = float(row["wall_s"])
    for name, row in (payload.get("stages") or {}).items():
        if isinstance(row, dict) and row.get("elapsed_s") is not None:
            out[f"stage:{name}"] = float(row["elapsed_s"])
    return out


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "spread": round(max(values) - min(values), 3),
        "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
    }


def collect(op: Path, arch: str, stages: tuple[str, ...], runs: int) -> dict[str, Any]:
    samples: list[dict[str, float]] = []
    for i in range(runs):
        print(f"  run {i + 1}/{runs} …", flush=True)
        t0 = time.perf_counter()
        payload = run_once(op, arch, stages, quiet=False)
        got = _pass_seconds(payload)
        samples.append(got)
        print(
            f"  run {i + 1}/{runs} done in {time.perf_counter() - t0:.1f}s "
            f"(total pass wall {got.get('total', 0):.2f}s)",
            flush=True,
        )
    names = sorted({k for s in samples for k in s})
    return {
        "schema": "uo-perf-bench/v1",
        "op": str(op),
        "arch": arch,
        "stages": list(stages),
        "runs": runs,
        "samples": samples,
        "by_pass": {n: _stats([s[n] for s in samples if n in s]) for n in names},
    }


def _table(report: dict[str, Any], top: int) -> str:
    rows = sorted(
        report["by_pass"].items(), key=lambda kv: -kv[1]["mean"]
    )[: top or None]
    width = max((len(n) for n, _ in rows), default=4)
    lines = [
        f"{'pass'.ljust(width)}  {'mean':>8}  {'min':>8}  {'max':>8}  {'spread':>8}  samples",
        "-" * (width + 46),
    ]
    for name, st in rows:
        got = [s[name] for s in report["samples"] if name in s]
        lines.append(
            f"{name.ljust(width)}  {st['mean']:>8.3f}  {st['min']:>8.3f}  "
            f"{st['max']:>8.3f}  {st['spread']:>8.3f}  "
            + " / ".join(f"{v:.2f}" for v in got)
        )
    return "\n".join(lines)


def compare(a: dict[str, Any], b: dict[str, Any], top: int) -> str:
    """Delta per pass, with anything inside the combined spread called noise.

    The bar is the two runs' own spreads added together. A move smaller than
    that is something these samples cannot distinguish from run-to-run
    variation, and saying so is the whole point -- a table of unqualified deltas
    invites reading noise as a result.
    """
    names = sorted(set(a["by_pass"]) | set(b["by_pass"]))
    rows = []
    for name in names:
        sa, sb = a["by_pass"].get(name), b["by_pass"].get(name)
        if not sa or not sb:
            continue
        delta = sb["mean"] - sa["mean"]
        band = sa["spread"] + sb["spread"]
        rows.append((name, sa, sb, delta, band))
    rows.sort(key=lambda r: -abs(r[3]))
    rows = rows[: top or None]
    width = max((len(r[0]) for r in rows), default=4)
    out = [
        f"{'pass'.ljust(width)}  {'A mean':>8}  {'B mean':>8}  {'delta':>8}  "
        f"{'band':>7}  verdict",
        "-" * (width + 50),
    ]
    for name, sa, sb, delta, band in rows:
        if abs(delta) <= band:
            verdict = "within noise"
        else:
            pct = (delta / sa["mean"] * 100) if sa["mean"] else 0.0
            verdict = f"{'SLOWER' if delta > 0 else 'FASTER'} {pct:+.1f}%"
        out.append(
            f"{name.ljust(width)}  {sa['mean']:>8.3f}  {sb['mean']:>8.3f}  "
            f"{delta:>+8.3f}  {band:>7.3f}  {verdict}"
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="repeated cold-run timing for uo-init")
    ap.add_argument("--op", type=Path, default=None, help="operator dir (default $UO_OP_DIR)")
    ap.add_argument("--arch", default=None, help="default $UO_ARCH")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument(
        "--stages",
        default="analyze",
        help=f"comma list from {','.join(ALL_STAGES)} (default analyze)",
    )
    ap.add_argument("--label", default=None, help="write .perf/<label>.json")
    ap.add_argument("--top", type=int, default=25, help="0 = all")
    ap.add_argument("--compare", nargs=2, type=Path, default=None, metavar=("A", "B"))
    args = ap.parse_args(argv)

    if args.compare:
        a = json.loads(args.compare[0].read_text(encoding="utf-8"))
        b = json.loads(args.compare[1].read_text(encoding="utf-8"))
        print(f"A = {args.compare[0].name}  ({a['runs']} runs)")
        print(f"B = {args.compare[1].name}  ({b['runs']} runs)\n")
        print(compare(a, b, args.top))
        return 0

    op = args.op or Path(os.environ.get("UO_OP_DIR") or "")
    arch = args.arch or os.environ.get("UO_ARCH") or ""
    if not op.is_dir():
        print("operator dir missing: pass --op or set UO_OP_DIR")
        return 2
    if not arch:
        print("architecture missing: pass --arch or set UO_ARCH")
        return 2
    stages = tuple(s.strip() for s in args.stages.split(",") if s.strip())
    unknown = [s for s in stages if s not in ALL_STAGES]
    if unknown:
        print(f"unknown stages {unknown}; known: {ALL_STAGES}")
        return 2

    print(f"op={op.name} arch={arch} stages={','.join(stages)} runs={args.runs}")
    report = collect(op, arch, stages, args.runs)
    print("\n" + _table(report, args.top))

    if args.label:
        out = DEFAULT_OUT_DIR / f"{args.label}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
