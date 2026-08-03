# -*- coding: utf-8 -*-
"""Time each legality premise on its own, to find the slow ones.

The derive phase spends most of its wall clock expanding premises, and a
chunked run cannot say which premise inside a chunk was responsible. This runs
one premise per worker with a short timeout, so a premise that does not finish
is named instead of being hidden inside a chunk that timed out.

    python scripts/_probe_premise_cost.py --layer api --timeout 30
"""
from __future__ import annotations

import argparse
import pickle
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layer", choices=("host", "api"), default="api")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    from uo_init.host_derivation import _premises_isolated

    sys.setrecursionlimit(20000)
    bundle = pickle.loads(BUNDLE.read_bytes())

    if args.layer == "api":
        ir = getattr(bundle.get("api_contract"), "ir", None)
        keep = {
            k: bundle[k]
            for k in ("api_contract", "api_resolver", "var_model", "resolver")
            if k in bundle
        }
    else:
        ir = bundle["host_ir"]
        keep = {
            k: bundle[k]
            for k in ("binding", "host_ir", "resolver", "var_model")
            if k in bundle
        }
    if ir is None:
        print(f"no {args.layer} ir in the bundle")
        return 1

    texts = [(t, fn) for t, fn, _f, _l in ir.legality_premises()]
    total = len(texts)
    print(f"{args.layer}: {total} premises, {args.timeout}s each\n")

    fd, path = tempfile.mkstemp(prefix="uo_premise_cost_", suffix=".pkl")
    with open(fd, "wb") as fh:
        pickle.dump(keep, fh)

    from uo_init.host_derivation import _premise_worker, _run_isolated_batch

    try:
        rows = []
        for lo in range(0, total, args.workers):
            hi = min(lo + args.workers, total)
            started = time.time()
            out = _run_isolated_batch(
                [
                    {
                        "target": _premise_worker,
                        "args": (path, list(sys.path), args.layer, n, n + 1, "", 4, 0),
                        "name": f"premise{n}",
                        "index": -1,
                    }
                    for n in range(lo, hi)
                ],
                timeout=args.timeout,
                workers=args.workers,
            )
            for n, res in zip(range(lo, hi), out):
                ok = res.get("rows") is not None
                rows.append((n, ok, texts[n]))
            print(
                f"  [{lo:3d}:{hi:3d}] {time.time() - started:6.1f}s  "
                + " ".join("ok" if r[1] else "TIMEOUT" for r in rows[lo:hi]),
                flush=True,
            )
    finally:
        Path(path).unlink(missing_ok=True)

    bad = [(n, t) for n, ok, (t, _fn) in rows if not ok]
    print(f"\n{len(bad)}/{total} did not finish in {args.timeout}s")
    for n, text in bad:
        print(f"  #{n}: {str(text)[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
