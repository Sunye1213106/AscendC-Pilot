#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uo-init phase timing baseline harness (P1).

Collect wall-clock rows from ``[uo-timing]`` stderr lines emitted when
``UO_TIMING=1`` (default on in ``uo_init.timing``).

Usage (PowerShell)::

    $env:UO_TIMING = "1"
    # Optional: fail a phase over N seconds (default 180)
    $env:UO_PHASE_BUDGET_S = "180"
    acp run-action extract_host 2> uo-timing.err
    python engines/understand-operator/tools/timing_baseline.py \\
        --from-stderr uo-timing.err \\
        --write-doc

Or write the empty markdown template with anecdotal placeholders only::

    python engines/understand-operator/tools/timing_baseline.py --write-doc

The markdown table lands at ``docs/history/benchmarks/uo-timing-baseline.md`` (repo root).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

# [uo-timing]   12.345s SLOW  phase_name  k=v ...
_LINE_RE = re.compile(
    r"^\[uo-timing\]\s+"
    r"(?P<seconds>\d+(?:\.\d+)?)s"
    r"(?P<slow>\s+SLOW)?"
    r"\s+(?P<phase>\S+)"
    r"(?:\s+(?P<extra>.*))?$"
)

# Product actions / known phases for the baseline table template.
ACTIONS = (
    "prepare_layout",
    "scope_validate",
    "scope_confirm",  # alias
    "extract_host",
    "extract_tiling_key",
    "extract_kernel",
    "normalize_variables",
    "derive_key_fields",
    "normalize_predicates",
    "export_kb",
    "export_tg_host_view",
    "quality_gate",
)

# Anecdotal numbers from code comments / FAG execution notes when a full
# measurement pass is unavailable in this environment.
ANECDOTAL = {
    "extract_host": "minutes on FAG (full closure); see assemble_kb closure_mode notes",
    "derive_key_fields": "fields wall can sum to minutes; isolate workers add more (host_derivation)",
    "extract_kernel": "pairwise fold expensive; fold_kernel=false skips harness",
    "export_tg_host_view": "FAG cached export 31.7s → 2.0s (fingerprint reuse)",
}


def repo_root_from_here() -> Path:
    # tools/ -> understand-operator -> engines -> AscendC-Pilot
    return Path(__file__).resolve().parents[3]


def default_doc_path() -> Path:
    return repo_root_from_here() / "docs" / "history" / "benchmarks" / "uo-timing-baseline.md"


def parse_timing_lines(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("[uo-timing]"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            rows.append(
                {
                    "seconds": None,
                    "slow": "SLOW" in line,
                    "phase": line.split("]", 1)[-1].strip() or "?",
                    "extra": "",
                    "raw": line,
                }
            )
            continue
        rows.append(
            {
                "seconds": float(m.group("seconds")),
                "slow": bool(m.group("slow")),
                "phase": m.group("phase"),
                "extra": (m.group("extra") or "").strip(),
                "raw": line,
            }
        )
    return rows


def _by_phase(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Group timed rows by phase, dropping the informational chatter.

    ``uo_init.timing.log`` carries both measurements and notes on one channel.
    A note has no duration, and the ``summary`` lines restate durations already
    counted — keeping either turns the table into a transcript.
    """
    out: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        if row.get("seconds") is None:
            continue
        phase = str(row["phase"])
        if phase == "summary" or phase.startswith("summary"):
            continue
        out.setdefault(phase, []).append(row)
    return out


def _phase_seconds(hits: list[dict[str, object]]) -> float | None:
    """Wall clock for one phase: the summary line, or the sum of its parts."""
    secs = [float(h["seconds"]) for h in hits if h.get("seconds") is not None]
    if not secs:
        return None
    # A phase logged once per sub-step sums; logged once totals.
    return max(secs) if len(secs) == 1 else sum(secs)


def measure_extract_host(
    *,
    cann: Path | None = None,
    ops: Path | None = None,
    op: Path | None = None,
    arch: str = "arch35",
) -> dict[str, Any]:
    """Run host extraction twice — cold caches then warm — capturing timing.

    Both runs share a throwaway ``UO_CACHE_ROOT``, so the first is a genuine
    first-ever parse and the second is a cache hit. Measuring against the real
    cache directory would report two warm runs and call the first one cold.

    Returns ``{"cold": rows, "warm": rows, "cold_s": float, "warm_s": float}``.
    Raises ``FileNotFoundError`` when the CANN / operator trees are absent, so a
    missing environment reads as "not measured here" rather than as a zero.
    """
    import io
    import os
    import tempfile
    import time
    from contextlib import redirect_stderr

    src = repo_root_from_here() / "engines" / "understand-operator" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from uo_init import paths as uo_paths

    cann = cann or uo_paths.cann_root()
    ops = ops or uo_paths.ops_root()
    op = op or uo_paths.op_dir(relative="attention/flash_attention_score_grad")
    missing = [n for n, v in (("cann", cann), ("ops", ops), ("operator", op)) if v is None]
    if missing:
        raise FileNotFoundError(
            "cannot measure without " + ", ".join(missing) + f"\n{uo_paths.explain()}"
        )

    from uo_init.assemble_kb import extract_host_bundle

    os.environ["UO_TIMING"] = "1"
    previous_root = os.environ.get("UO_CACHE_ROOT")
    scratch = tempfile.mkdtemp(prefix="uo_timing_cache_")
    os.environ["UO_CACHE_ROOT"] = scratch
    out: dict[str, Any] = {"cache_root": scratch}
    try:
        for label in ("cold", "warm"):
            buf = io.StringIO()
            started = time.perf_counter()
            with redirect_stderr(buf):
                extract_host_bundle(
                    op_dir=str(op), cann_root=str(cann), ops_root=str(ops), arch_dir=arch
                )
            out[f"{label}_s"] = time.perf_counter() - started
            out[label] = parse_timing_lines(buf.getvalue())
    finally:
        if previous_root is None:
            os.environ.pop("UO_CACHE_ROOT", None)
        else:
            os.environ["UO_CACHE_ROOT"] = previous_root
    return out


def render_markdown(
    rows: list[dict[str, object]] | None = None,
    *,
    measured: bool = False,
    warm_rows: list[dict[str, object]] | None = None,
    totals: dict[str, float] | None = None,
) -> str:
    rows = rows or []
    by_phase = _by_phase(rows)
    warm_by_phase = _by_phase(warm_rows or [])

    def _cell(value: float | None) -> str:
        return "not yet measured" if value is None else f"{value:.3f}"

    lines = [
        "# uo-init timing baseline",
        "",
        "Harness: `engines/understand-operator/tools/timing_baseline.py`.",
        "",
        "## How to measure",
        "",
        "Cold and warm in one pass, against a throwaway cache root so the first",
        "run really is a first-ever parse:",
        "",
        "```powershell",
        "python engines/understand-operator/tools/timing_baseline.py --measure --write-doc",
        "```",
        "",
        "Or from two captured stderr logs of `acp run-action`:",
        "",
        "```powershell",
        '$env:UO_TIMING = "1"',
        "acp run-action extract_host 2> cold.err   # empty UO_CACHE_ROOT",
        "acp run-action extract_host 2> warm.err   # same root, second time",
        "python engines/understand-operator/tools/timing_baseline.py `",
        "    --from-stderr cold.err --warm-stderr warm.err --write-doc",
        "```",
        "",
        "Warm re-run goal (sources unchanged): full uo-init pipeline **≤ 2 minutes**",
        "(`UO_WARM_REPLAY_BUDGET_S`, gated in CI). A cold run may stay slow.",
        "",
        "## Actions",
        "",
        "Wall clock for the whole action. `extract_host` is the one this harness",
        "drives directly; the others are separate `acp run-action` steps and are",
        "measured by capturing their own stderr.",
        "",
        "| Action | Cold (s) | Warm (s) | Notes |",
        "|--------|---------:|---------:|-------|",
    ]

    for action in ACTIONS:
        if action == "extract_host" and totals:
            cold = totals.get("cold_s")
            warm = totals.get("warm_s")
            note = "measured here; caches cold then warm"
        else:
            cold = warm = None
            note = ANECDOTAL.get(action, "separate action; capture its stderr")
        lines.append(f"| `{action}` | {_cell(cold)} | {_cell(warm)} | {note} |")

    phases = sorted(set(by_phase) | set(warm_by_phase))
    if phases:
        lines.extend([
            "",
            "## Inside `extract_host`",
            "",
            "Σ over every occurrence of the phase. Phases that fan out across",
            "translation units sum above the wall clock of the call — that is the",
            "parallelism, not an inconsistency.",
            "",
            "| Phase | Σ cold (s) | Σ warm (s) |",
            "|-------|-----------:|-----------:|",
        ])
        for phase in phases:
            cold = _phase_seconds(by_phase.get(phase) or [])
            warm = _phase_seconds(warm_by_phase.get(phase) or [])
            lines.append(f"| `{phase}` | {_cell(cold)} | {_cell(warm)} |")

    lines.extend(
        [
            "",
            "## Still anecdotal",
            "",
            "Numbers from code comments / execution notes, for the actions this",
            "harness has not driven yet:",
            "",
            "- `derive_key_fields`: per-field seconds can sum to minutes; isolate "
            "workers hide more wall time (`host_derivation.HostDerivation.phase_seconds`).",
            "- Kernel pairwise fold: expensive; disable with `fold_kernel=false`.",
            "- `export_tg_host_view`: FAG cached export **31.7s → 2.0s** after "
            "fingerprint reuse (`docs/history/fag/fag-arch35-static-blocker-execution-20260806.md`).",
            "",
            "## Cache knobs (warm path)",
            "",
            "| Env | Default | Effect |",
            "|-----|---------|--------|",
            "| `UO_TIMING` | `1` | Emit `[uo-timing]` stderr lines |",
            "| `UO_TU_CACHE` | `1` | Durable libclang walk IR under `uo/cache/tu/` |",
            "| `UO_DERIVE_CACHE` | `1` | Per-field derive rows under `uo/cache/derive/` |",
            "| `UO_FOLD_CACHE` | `1` | clang `-ast-dump` fold under `uo/cache/fold/` |",
            "| `UO_CTRL_WORKERS` | `1` | Controllability pool size (keep 1; >1 often regresses) |",
            "| `UO_WARM_REPLAY_BUDGET_S` | `120` | CI warm replay budget |",
            "| `UO_CACHE_ROOT` | `<op>/.ascendc-pilot/<arch>/uo/cache` | Relocate every cache (used to force a cold run) |",
            "| `UO_KB_YAML` | `0` | Opt in to layered YAML beside the DB product |",
            "| `closure_mode` | product `full`; `_ensure_bundle` → `off` when meta exists | Skip deep controllability on downstream actions |",
            "",
        ]
    )
    if measured and rows:
        status = "measured"
        if warm_rows:
            status += " (cold + warm on this machine)"
        if totals and totals.get("cold_s") and totals.get("warm_s"):
            speedup = totals["cold_s"] / max(totals["warm_s"], 1e-9)
            status += f"; warm re-run {speedup:.0f}× faster than cold"
    else:
        status = "template only / not yet measured"
    lines.extend([f"_Status: {status}_", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--from-stderr",
        type=Path,
        help="Path to a captured stderr log containing [uo-timing] lines",
    )
    ap.add_argument(
        "--write-doc",
        action="store_true",
        help=f"Write markdown table to {default_doc_path()}",
    )
    ap.add_argument(
        "--doc-path",
        type=Path,
        default=None,
        help="Override output markdown path",
    )
    ap.add_argument(
        "--warm-stderr",
        type=Path,
        help="Second capture, taken with caches warm, to fill the Warm column",
    )
    ap.add_argument(
        "--measure",
        action="store_true",
        help="Run host extraction here, twice (cold then warm), and measure it",
    )
    ap.add_argument("--arch", default="arch35")
    ap.add_argument(
        "--print-rows",
        action="store_true",
        help="Print parsed rows as TSV to stdout",
    )
    args = ap.parse_args(argv)

    rows: list[dict[str, object]] = []
    warm_rows: list[dict[str, object]] = []
    totals: dict[str, float] = {}

    if args.measure:
        try:
            got = measure_extract_host(arch=args.arch)
        except FileNotFoundError as exc:
            print(f"cannot measure: {exc}", file=sys.stderr)
            return 2
        rows = got["cold"]
        warm_rows = got["warm"]
        totals = {"cold_s": got["cold_s"], "warm_s": got["warm_s"]}
        print(
            f"cold={totals['cold_s']:.1f}s warm={totals['warm_s']:.1f}s",
            file=sys.stderr,
        )
    else:
        if args.from_stderr:
            rows = parse_timing_lines(
                Path(args.from_stderr).read_text(encoding="utf-8", errors="replace")
            )
        if args.warm_stderr:
            warm_rows = parse_timing_lines(
                Path(args.warm_stderr).read_text(encoding="utf-8", errors="replace")
            )

    if args.print_rows:
        for row in rows:
            print(
                f"{row.get('seconds')}\t{row.get('phase')}\t"
                f"{'SLOW' if row.get('slow') else ''}\t{row.get('extra')}"
            )

    doc = render_markdown(
        rows, measured=bool(rows), warm_rows=warm_rows, totals=totals
    )
    if args.write_doc:
        out = args.doc_path or default_doc_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    elif not args.print_rows:
        sys.stdout.write(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
