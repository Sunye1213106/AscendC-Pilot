#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure what a trigram FTS index over `source_line` actually costs and buys.

`accel.build_source_fts` has existed and been switched off, with a comment
citing +16MB and a tokenizer that "silently misses identifiers". The second half
is about FTS5's default word tokenizer, not the trigram one the function
actually asks for -- trigram exists precisely to do substring matching. So the
open questions are the measurable ones: how much bigger, how much faster, and
whether it returns *the same rows* as the `LIKE` scan it would replace.

Equivalence is the gate. A faster recall that answers differently is not an
optimization, it is a silent behaviour change, and the answer gate would only
catch it for needles that happen to be in its 53 cases.

    python tools/uo_fts_tradeoff.py
    python tools/uo_fts_tradeoff.py --keep   # leave the built copy for inspection
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from uo_init.store.accel import build_source_fts  # noqa: E402
from uo_product_audit import find_product  # noqa: E402

#: Needles worth checking: the answer gate's hot patterns, plus cases chosen to
#: break naive tokenization -- snake_case, mixed case, a macro call with
#: punctuation, and a fragment that is not a whole identifier.
NEEDLES = (
    "graphStatus",
    "OP_CHECK_IF",
    "Cast",
    "pipeBase",
    "IsTnd",
    "kernel_deter",
    "keep_prob",
    "scaleValue",
    "InitTilingData",
    "ASCENDC_TPL_ARGS_SEL",
    "sfmg",
    "TQue",
    "atten",
    "GetCoreNumAiv",
)


def build_external(conn: sqlite3.Connection) -> bool:
    """Trigram FTS that indexes `source_line` without copying its text.

    A plain FTS5 table keeps its own copy of the indexed text, which is the
    4.9MB `source_fts_content` shadow of a `source_line` table that already
    holds exactly those bytes. `content=` points the index at that table
    instead, so only the trigram postings are new; the cost is a rowid join to
    get `path` and `line` back.
    """
    try:
        conn.execute("DROP TABLE IF EXISTS source_fts")
        conn.execute(
            "CREATE VIRTUAL TABLE source_fts USING fts5("
            "text, content='source_line', content_rowid='rowid', tokenize='trigram')"
        )
        conn.execute(
            "INSERT INTO source_fts(rowid, text) SELECT rowid, text FROM source_line"
        )
    except sqlite3.OperationalError as exc:
        print(f"external-content build failed: {exc}")
        return False
    return True


def fts_rows_external(conn: sqlite3.Connection, needle: str) -> list[tuple[str, int]]:
    quoted = '"' + needle.replace('"', " ").strip() + '"'
    return [
        (str(p), int(l))
        for p, l in conn.execute(
            "SELECT sl.path, sl.line FROM source_fts f "
            "JOIN source_line sl ON sl.rowid = f.rowid "
            "WHERE f.source_fts MATCH ? ORDER BY sl.path, sl.line",
            (quoted,),
        )
    ]


def like_rows(conn: sqlite3.Connection, needle: str) -> list[tuple[str, int]]:
    return [
        (str(p), int(l))
        for p, l in conn.execute(
            "SELECT path, line FROM source_line WHERE text LIKE '%' || ? || '%' "
            "ORDER BY path, line",
            (needle,),
        )
    ]


def fts_rows(conn: sqlite3.Connection, needle: str) -> list[tuple[str, int]]:
    quoted = '"' + needle.replace('"', " ").strip() + '"'
    return [
        (str(p), int(l))
        for p, l in conn.execute(
            "SELECT path, line FROM source_fts WHERE source_fts MATCH ? ORDER BY path, line",
            (quoted,),
        )
    ]


def timed(fn, *args, repeat: int = 5) -> tuple[float, object]:
    best = float("inf")
    out = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn(*args)
        best = min(best, time.perf_counter() - t0)
    return best * 1000.0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FTS5 trigram cost/benefit for .uo recall")
    ap.add_argument("--op", type=Path, default=None)
    ap.add_argument("--arch", default=None)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument(
        "--external",
        action="store_true",
        help="index source_line via content= instead of copying its text",
    )
    args = ap.parse_args(argv)

    op = args.op or Path(os.environ.get("UO_OP_DIR") or "")
    arch = args.arch or os.environ.get("UO_ARCH") or ""
    product = find_product(op, arch)
    if product is None:
        print("no product found")
        return 2

    work = product.with_suffix(".ftstest.uo")
    print(f"copying {product.name} -> {work.name}")
    shutil.copy2(product, work)
    before = work.stat().st_size

    conn = sqlite3.connect(str(work))
    try:
        probe = fts_rows_external if args.external else fts_rows
        label = "external content" if args.external else "own content copy"
        print(f"mode: {label}")
        t0 = time.perf_counter()
        ok = build_external(conn) if args.external else build_source_fts(conn)
        conn.commit()
        build_s = time.perf_counter() - t0
        if not ok:
            print("FTS build failed (FTS5 unavailable?)")
            return 1
        raw_after = work.stat().st_size
        t0 = time.perf_counter()
        conn.execute("VACUUM")
        conn.commit()
        vacuum_s = time.perf_counter() - t0
        after = work.stat().st_size

        print(f"\nbuild {build_s:.2f}s   vacuum {vacuum_s:.2f}s")
        print(f"size  {before/1048576:8.2f} MB  ->  {after/1048576:8.2f} MB "
              f"(+{(after-before)/1048576:.2f} MB, +{(after/before-1)*100:.1f}%)")
        print(f"      pre-vacuum peak {raw_after/1048576:.2f} MB")

        sizes = {
            str(n): int(s)
            for n, s in conn.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name")
            if str(n).startswith("source_fts")
        }
        print("\n  FTS objects on disk (MB)")
        for name, n in sorted(sizes.items(), key=lambda kv: -kv[1]):
            print(f"    {n/1048576:8.2f}  {name}")

        print(f"\n{'needle':<24}{'LIKE ms':>9}{'FTS ms':>9}{'rows':>8}  equivalence")
        print("-" * 74)
        mismatches = 0
        like_total = fts_total = 0.0
        for needle in NEEDLES:
            l_ms, l_rows = timed(like_rows, conn, needle)
            f_ms, f_rows = timed(probe, conn, needle)
            like_total += l_ms
            fts_total += f_ms
            same = l_rows == f_rows
            if same:
                verdict = "identical"
            else:
                mismatches += 1
                only_like = len(set(l_rows) - set(f_rows))
                only_fts = len(set(f_rows) - set(l_rows))
                verdict = f"DIFFERS  LIKE-only={only_like} FTS-only={only_fts}"
            print(f"{needle:<24}{l_ms:>9.2f}{f_ms:>9.2f}{len(l_rows):>8}  {verdict}")

        print("-" * 74)
        print(f"{'total':<24}{like_total:>9.2f}{fts_total:>9.2f}")
        speedup = (like_total / fts_total) if fts_total else 0.0
        print(f"\nrecall scan is {speedup:.1f}x faster with FTS "
              f"({like_total:.0f}ms -> {fts_total:.0f}ms over {len(NEEDLES)} needles)")
        print(f"row-set equivalence: {len(NEEDLES) - mismatches}/{len(NEEDLES)} identical")
    finally:
        conn.close()
        if not args.keep:
            work.unlink(missing_ok=True)
        else:
            print(f"\nkept {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
