# -*- coding: utf-8 -*-
"""Solve a handful of legal keys and say how long each took.

`_probe_reach.py` classifies all 8705 rows before it prints anything, which is
no use while the solver is still crashing: this stops after `--keys` of them and
flushes as it goes, so the last line printed is the query that killed it.
"""
from __future__ import annotations

import argparse
import time

from _probe_reach import load


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keys", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=5000)
    ap.add_argument("--rlimit", type=int, default=None)
    ap.add_argument("--hard-timeout", type=int, default=None)
    ap.add_argument("--skip", type=int, default=0, help="start at the Nth key")
    args = ap.parse_args()

    doc, var_model, schema, _binding = load()

    from uo_init import key_reachability as kr
    from uo_init.key_reachability import KeyReachability
    from uo_init.materialize_tiling import expand_legal_with_groups

    start = time.time()
    reach = KeyReachability.from_derivation(
        doc,
        var_model,
        timeout_ms=args.timeout,
        rlimit=kr.DEFAULT_RLIMIT if args.rlimit is None else args.rlimit,
        hard_timeout_ms=(
            kr.DEFAULT_HARD_TIMEOUT_MS if args.hard_timeout is None else args.hard_timeout
        ),
    )
    summary = reach.summary()
    print(
        f"compiled {summary['dimensions_compiled']}/{summary['dimensions_total']} dims "
        f"in {time.time() - start:.1f}s",
        flush=True,
    )
    for group in summary.get("groups") or []:
        print(f"  group[{len(group)}] {', '.join(group)}", flush=True)

    seen = 0
    for index, (_gi, dims) in enumerate(expand_legal_with_groups(schema)):
        if index < args.skip:
            continue
        full = {d.name: str(dims.get(d.name, d.value_domain[0])) for d in schema.dims}
        began = time.time()
        print(f"key {index}: solving", flush=True)
        verdict = reach.verdict(full)
        print(
            f"key {index}: {verdict.status} ({time.time() - began:.2f}s) {verdict.reason}",
            flush=True,
        )
        seen += 1
        if seen >= args.keys:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
