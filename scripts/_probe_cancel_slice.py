# -*- coding: utf-8 -*-
"""Prove base-solver poisoning: slim per-group backends for the 56 SAT keys."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "engines" / "understand-operator" / "src"),
    str(ROOT / "engines" / "common"),
    str(Path(__file__).resolve().parent),
]

from _probe_cancel_nia import collect_vars  # noqa: E402
from _probe_reach import load  # noqa: E402


def main() -> int:
    from acp_common.z3_backend import SolveConfig, Z3Backend
    from uo_init import key_reachability as kr
    from uo_init.key_reachability import TRUE_VAR, KeyReachability, _target_value
    from uo_init.materialize_tiling import expand_legal_with_groups

    doc, vm, schema, _binding = load()
    reach = KeyReachability.from_derivation(
        doc,
        vm,
        timeout_ms=5000,
        rlimit=kr.DEFAULT_RLIMIT,
        hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
    )
    src = reach._backend.ir
    by = {v["id"]: v for v in src["variables"]}

    def slim_backend(dim_names: list[str]):
        need = {TRUE_VAR}
        for name in dim_names:
            need.add(reach._dims[name]["var"])
        changed = True
        while changed:
            changed = False
            for vid in list(need):
                spec = by.get(vid)
                if not spec or not spec.get("derived"):
                    continue
                for ref in collect_vars(spec.get("definition")):
                    if ref not in need:
                        need.add(ref)
                        changed = True
        variables = [by[v] for v in sorted(need) if v in by]
        ir = {
            "variables": variables,
            "constraints": list(src.get("constraints") or []),
        }
        backend = Z3Backend(
            ir,
            SolveConfig(
                timeout_ms=5000,
                rlimit=kr.DEFAULT_RLIMIT,
                hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
            ),
        )
        return backend, len(variables)

    cache = json.loads(
        (ROOT / ".probe_cache" / "fag_cancel_queries.json").read_text(encoding="utf-8")
    )
    sats = [r for r in cache["results"] if r["group_index"] == 0 and r["status"] == "sat"]
    print(f"sat combos from group[0]: {len(sats)}", flush=True)

    singleton_backends = {}
    for group in reach._groups[1:]:
        name = group[0]
        t0 = time.time()
        backend, n_vars = slim_backend([name])
        singleton_backends[name] = backend
        print(f"slim {name}: {n_vars} vars in {time.time() - t0:.2f}s", flush=True)

    for sat in sats:
        target = dict(sat["values"])
        match = None
        for _index, (_gi, dims) in enumerate(expand_legal_with_groups(schema)):
            full = {d.name: str(dims.get(d.name, d.value_domain[0])) for d in schema.dims}
            if all(_target_value(full[n]) == v for n, v in target.items()):
                match = full
                break
        assert match is not None
        print(f"\nSAT combo key_count={sat['key_count']}", flush=True)
        all_sat = True
        for name, backend in singleton_backends.items():
            val = _target_value(match[name])
            expr = {"op": "eq", "var": reach._dims[name]["var"], "value": val}
            t0 = time.time()
            result = backend.solve_expr(expr, label="s")
            status = result.get("status")
            reason = result.get("reason") or ""
            print(
                f"  {name}={val}: {status} {reason} {time.time() - t0:.3f}s",
                flush=True,
            )
            if status != "sat":
                all_sat = False
        print(f"  all singletons sat under slim IR? {all_sat}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
