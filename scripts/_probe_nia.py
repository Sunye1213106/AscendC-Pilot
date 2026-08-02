# -*- coding: utf-8 -*-
"""Is nonlinear arithmetic what stops the solver, and would relaxing it help?

`_probe_reach.py` reports how many keys come back `canceled` -- the solver
spent its budget without deciding either way. This asks why, and whether a
decision is reachable from here at all.

Tiling arithmetic multiplies one tiling variable by another and divides by a
third, so the compiled system is nonlinear integer arithmetic: undecidable in
general, and in practice a solver that does not come back. Replacing each
`x * y` with a fresh unconstrained variable makes it linear.

That replacement is a *relaxation*: the fresh variable admits every value the
product could take and then some, so the feasible set only grows. Hence an
UNSAT under it is an UNSAT for the real system, and the `unreachable` it
licenses is sound. A SAT under it licenses nothing -- it stays `unknown`.
Which is exactly the asymmetry worth having, because `unreachable` is the
verdict currently out of reach.

Two steps, because the first is a full sweep and the second is not:

    python scripts/_probe_nia.py --collect   # one sweep, records every group query
    python scripts/_probe_nia.py --relax     # re-solve the undecided ones, relaxed

Read-only with respect to the engine: the relaxation is installed by patching
the backend from here, never by editing it.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CACHE = ROOT / ".probe_cache"
BUNDLE = CACHE / "fag_bundle.pkl"
RESULT = CACHE / "fag_derive.json"
GROUPS = CACHE / "fag_groups.json"


def load():
    if not (BUNDLE.is_file() and RESULT.is_file()):
        raise SystemExit("no cached derivation; run scripts/_probe_derive.py first")
    with BUNDLE.open("rb") as fh:
        bundle = pickle.load(fh)
    doc_raw = json.loads(RESULT.read_text(encoding="utf-8"))["host_derivation"]

    from uo_init.host_derivation import HostDerivation, _reregister_soft_vars, _to_field
    from uo_init.tpl_bind import merge_literal_encode_alts

    doc = HostDerivation(
        op_name=str(doc_raw.get("op_name") or ""),
        architecture=str(doc_raw.get("architecture") or ""),
        fields=[_to_field(row, None) for row in doc_raw.get("fields") or []],
    )
    var_model = bundle["var_model"]
    _reregister_soft_vars(var_model, doc)
    binding = bundle.get("binding")
    if binding is not None and bundle.get("host_ir") is not None:
        binding = merge_literal_encode_alts(binding, bundle["host_ir"])
    return doc, var_model, bundle["tpl_schema"], binding


def _reach(doc, var_model, *, timeout, rlimit, hard):
    from uo_init import key_reachability as kr
    from uo_init.key_reachability import KeyReachability

    return KeyReachability.from_derivation(
        doc,
        var_model,
        timeout_ms=timeout,
        rlimit=kr.DEFAULT_RLIMIT if rlimit is None else rlimit,
        hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS if hard is None else hard,
    )


# -- step one: what does each group query cost, and how does it end -------
def collect(args) -> int:
    doc, var_model, schema, binding = load()
    from uo_init.materialize_tiling import build_legal_key_rows

    reach = _reach(
        doc, var_model, timeout=args.timeout, rlimit=args.rlimit, hard=args.hard_timeout
    )
    inner = reach._solve_group
    seen: list[dict[str, Any]] = []

    def recording(values):
        started = time.perf_counter()
        out = inner(values)
        seen.append(
            {
                "dims": [name for name, _ in values],
                "values": [[name, value] for name, value in values],
                "status": str(out.get("status") or ""),
                "reason": str(out.get("reason") or "")[:160],
                "seconds": round(time.perf_counter() - started, 2),
            }
        )
        return out

    reach._solve_group = recording
    started = time.perf_counter()
    rows = build_legal_key_rows(
        schema, binding=binding, blocker_ids=[], reachability=reach
    )
    elapsed = time.perf_counter() - started

    by_status = Counter(q["status"] for q in seen)
    keys = Counter(r.status for r in rows)
    print(f"group queries       : {len(seen)}  in {elapsed:.0f}s")
    for name, count in by_status.most_common():
        spent = sum(q["seconds"] for q in seen if q["status"] == name)
        print(f"  {name:10} {count:5}   {spent:7.0f}s total")
    print(f"\nlegal keys          : {len(rows)}")
    for name, count in keys.most_common():
        print(f"  {name:14} {count:6}")

    # Which groups are the undecided ones? A group is named by its dimensions.
    stuck = [q for q in seen if q["status"] not in ("sat", "unsat")]
    if stuck:
        shapes = Counter(" + ".join(q["dims"]) for q in stuck)
        print(f"\nundecided group queries: {len(stuck)}")
        for shape, count in shapes.most_common():
            print(f"  {count:5}  {shape[:100]}")

    CACHE.mkdir(parents=True, exist_ok=True)
    GROUPS.write_text(
        json.dumps({"queries": seen}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nwrote {GROUPS}")
    return 0


# -- the relaxation -------------------------------------------------------
def _install(mode: str):
    """Patch the backend to relax nonlinear operators. Returns an undo callable.

    `mode` is one of:
      as_is       nothing patched, the system as the engine builds it
      mul         every `x * y` with two non-constant sides becomes fresh
      muldiv      the above, plus `/` and `%` with a non-constant divisor
      all         the above, plus `/` and `%` by a constant
    """
    from acp_common import z3_backend as zb

    original = zb.Z3Backend._compile_value_uncached
    if mode == "as_is":
        return lambda: None

    # id(node) -> variable name. A name rather than the compiled variable,
    # because the solver rebuilds its context after a hard timeout and an
    # expression built in the old one cannot be asserted into the new.
    minted: dict[int, str] = {}

    def patched(self, expr):
        # Only step in on a node that already says it is one of the three.
        # The uncached compiler handles bools, ints and bare `{"var": x}`
        # before it normalises anything, and normalising one of those raises
        # -- which the caller reads as "this dimension will not compile" and
        # drops the whole dimension. That is how the first attempt lost
        # `DTemplateNum`.
        if isinstance(expr, dict) and expr.get("op") in ("mul", "div", "mod"):
            from acp_common.constraint_ir import normalize_expr

            node = normalize_expr(expr, self._norm_memo)
            op = node.get("op")
            if op in ("mul", "div", "mod"):
                args = [self._arith_arg(a) for a in node["args"]]
                free = [a for a in args if not self.z3.is_int_value(a)]
                relax = (
                    (op == "mul" and len(free) >= 2)
                    or (op in ("div", "mod") and mode in ("muldiv", "all")
                        and not self.z3.is_int_value(args[1]))
                    or (op in ("div", "mod") and mode == "all")
                )
                if relax:
                    # One name per node, so the DAG keeps sharing: two
                    # references to the same product stay equal, which a
                    # per-reference variable would silently break.
                    key = id(expr)
                    name = minted.get(key)
                    if name is None:
                        name = f"NIA_RELAXED_{len(minted)}"
                        minted[key] = name
                    return self.z3.Int(name)
        return original(self, expr)

    zb.Z3Backend._compile_value_uncached = patched

    def undo():
        zb.Z3Backend._compile_value_uncached = original

    return undo


def _shape_name(dims: list[str]) -> str:
    """A short name for a group. The wide one is named by its size."""
    return dims[0] if len(dims) == 1 else f"<{len(dims)} dims together>"


def relax(args) -> int:
    if not GROUPS.is_file():
        raise SystemExit("run --collect first")
    queries = json.loads(GROUPS.read_text(encoding="utf-8"))["queries"]
    stuck = [q for q in queries if q["status"] not in ("sat", "unsat")]
    if not stuck:
        print("nothing was left undecided; there is nothing to relax")
        return 0
    # One query per distinct group combination is enough to answer the
    # question; the rest repeat the same solve.
    seen: set[tuple] = set()
    unique = []
    for q in stuck:
        key = tuple(tuple(v) for v in q["values"])
        if key not in seen:
            seen.add(key)
            unique.append(q)
    # Take turns between group shapes. One component holds most of the
    # undecided queries, so a plain prefix would sample only that one and say
    # nothing about the single-dimension components -- which are the more
    # telling case, since a lone dimension cannot be blamed on combinatorics.
    by_shape: dict[str, list[dict[str, Any]]] = {}
    for q in unique:
        by_shape.setdefault(" + ".join(q["dims"]), []).append(q)
    ordered: list[dict[str, Any]] = []
    while any(by_shape.values()):
        for bucket in by_shape.values():
            if bucket:
                ordered.append(bucket.pop(0))
    unique = ordered[: args.limit] if args.limit else ordered
    shapes = Counter(" + ".join(q["dims"]) for q in unique)
    print(f"undecided combinations: {len(stuck)} ({len(unique)} distinct, trying those)")
    for shape, count in shapes.most_common():
        print(f"    {count:4}  {shape[:88]}")

    doc, var_model, _schema, _binding = load()
    baseline_dims: int | None = None
    for mode in ("as_is", "mul", "muldiv", "all"):
        undo = _install(mode)
        try:
            reach = _reach(
                doc,
                var_model,
                timeout=args.timeout,
                rlimit=args.rlimit,
                hard=args.hard_timeout,
            )
            # A relaxation that drops a dimension is not comparable with one
            # that keeps it: fewer constraints make UNSAT harder for reasons
            # having nothing to do with arithmetic. Say so rather than let it
            # pass as a result.
            compiled = len(getattr(reach, "_dims", {}) or {})
            if baseline_dims is None:
                baseline_dims = compiled
                print(f"  (unrelaxed baseline: {compiled} dimensions compiled)")
            elif compiled != baseline_dims:
                print(
                    f"  {mode:8} WARNING only {compiled} dimensions compiled, "
                    f"baseline had {baseline_dims} -- results below are not comparable"
                )

            out = Counter()
            per_shape: dict[str, Counter] = {}
            spent = 0.0
            for q in unique:
                values = tuple((name, value) for name, value in q["values"])
                started = time.perf_counter()
                try:
                    got = reach._solve_group(values)
                except KeyError as exc:
                    got = {"status": f"dim_dropped({exc})"}
                spent += time.perf_counter() - started
                status = str(got.get("status") or "")
                out[status] += 1
                per_shape.setdefault(_shape_name(q["dims"]), Counter())[status] += 1
            summary = "  ".join(f"{k}={v}" for k, v in sorted(out.items()))
            print(f"  {mode:8} {summary:40} {spent:6.0f}s")
            for shape in sorted(per_shape):
                counts = per_shape[shape]
                detail = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                print(f"      {shape:22} {detail}")
        finally:
            undo()
    print(
        "\nUNSAT under a relaxation is UNSAT for the real system, so those keys"
        "\nare soundly unreachable. SAT under it proves nothing."
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collect", action="store_true", help="full sweep, record queries")
    ap.add_argument("--relax", action="store_true", help="re-solve undecided, relaxed")
    ap.add_argument("--limit", type=int, default=0, help="only N distinct combinations")
    ap.add_argument("--timeout", type=int, default=5000)
    ap.add_argument("--rlimit", type=int, default=None)
    ap.add_argument("--hard-timeout", type=int, default=None, dest="hard_timeout")
    args = ap.parse_args()
    if args.collect:
        return collect(args)
    if args.relax:
        return relax(args)
    ap.error("pick --collect or --relax")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
