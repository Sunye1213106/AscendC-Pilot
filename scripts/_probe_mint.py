# -*- coding: utf-8 -*-
"""Why each VAR_INIT_* was minted: the full decision state at the mint site.

`_chain_sites` mints an initial-value variable when three tests all fail at
once -- an earlier site did not already give a value, the writes in that
function do not cover every path, and the solver could not show the read
implies a write. This wraps each of those tests, records what it was asked and
what it answered, and prints the trio that was in force when `_init_var` fired.

    python scripts/_probe_mint.py DeterType IsNzOut
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"


def _cond(c) -> str:
    neg = "!" if getattr(c, "negated", False) else " "
    kind = getattr(c, "kind", "")
    return f"{neg}[{kind}] {getattr(c, 'text', '')[:90]}"


def main() -> int:
    sys.setrecursionlimit(20000)
    wanted = sys.argv[1:] or ["DeterType"]

    with BUNDLE.open("rb") as fh:
        bundle = pickle.load(fh)

    from uo_init import derive_key_fields as dkf
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.loop_summary import guards_cover

    log: dict[str, object] = {}
    events: list[dict] = []

    raw_covered = dkf._paths_are_covered

    def covered(paths):
        out = raw_covered(paths)
        log["covered_last"] = (out, [[_cond(c) for c in p] for p in paths])
        return out

    dkf._paths_are_covered = covered

    raw_always = KeyFieldDeriver._always_runs
    raw_local = KeyFieldDeriver._is_local_of
    raw_forces = KeyFieldDeriver._read_forces_a_write
    raw_decl = KeyFieldDeriver._declared_default
    raw_mint = KeyFieldDeriver._init_var

    def always(self, scope, depth):
        out = raw_always(self, scope, depth)
        log.setdefault("always", {})[scope] = out  # type: ignore[union-attr]
        return out

    def is_local(self, defining, scope):
        out = raw_local(self, defining, scope)
        log.setdefault("local", {})[(defining, scope)] = out  # type: ignore[union-attr]
        return out

    def forces(self, pool, defining):
        read = self._read_at
        detail: dict = {"defining": defining, "pool": len(pool)}
        if read is None:
            detail["why"] = "no read site recorded"
        elif not read.conds:
            detail["why"] = "read site has zero path conditions"
            detail["read"] = f"{Path(read.file).name}:{read.line} [{read.function}]"
        else:
            detail["read"] = f"{Path(read.file).name}:{read.line} [{read.function}]"
            detail["read_conds"] = [_cond(c) for c in read.conds]
            imp = guards_cover(
                read.conds,
                [(s.conds, s.function or read.function) for s in pool],
                read_function=read.function,
                members=getattr(self.ir, "class_fields", ()) or (),
            )
            detail["why"] = f"guards_cover -> holds={imp.holds} reason={imp.reason!r} checked={imp.checked}"
        out = raw_forces(self, pool, defining)
        detail["result"] = out
        detail["write_conds"] = [
            {
                "at": f"{Path(s.file).name}:{s.line} [{s.function}]",
                "conds": [_cond(c) for c in s.conds],
            }
            for s in pool
        ]
        log["forces_last"] = detail
        return out

    def declared(self, defining, scope, depth):
        out = raw_decl(self, defining, scope, depth)
        log["declared_last"] = (defining, scope, out)
        return out

    def mint(self, defining, scope, site):
        ref = raw_mint(self, defining, scope, site)
        events.append(
            {
                "var": ref.name if hasattr(ref, "name") else str(ref),
                "defining": defining,
                "scope": scope,
                "site": f"{Path(site.file).name}:{site.line}",
                "site_guards": [g[:110] for g in site.guards],
                "site_conds": [_cond(c) for c in site.conds],
                "covered": log.get("covered_last"),
                "always_runs": dict(log.get("always") or {}).get(scope),
                "is_local": dict(log.get("local") or {}).get((defining, scope)),
                "declared": log.get("declared_last"),
                "forces": log.get("forces_last"),
            }
        )
        return ref

    dkf.KeyFieldDeriver._always_runs = always
    dkf.KeyFieldDeriver._is_local_of = is_local
    dkf.KeyFieldDeriver._read_forces_a_write = forces
    dkf.KeyFieldDeriver._declared_default = declared
    dkf.KeyFieldDeriver._init_var = mint

    from uo_init.host_derivation import encode_function

    binding = bundle["binding"]
    ir = bundle["host_ir"]
    for b in binding.bindings:
        if b.decl.name not in wanted:
            continue
        events.clear()
        deriver = KeyFieldDeriver(
            host_ir=ir,
            resolver=bundle["resolver"],
            var_model=bundle["var_model"],
            max_helper_guards=4,
        )
        res = deriver.derive(
            dim_name=b.decl.name,
            index=b.index,
            host_expr=b.host_expr,
            function=encode_function(ir, binding.site),
        )
        print(f"\n{'=' * 78}\n{b.decl.name}  free={sorted(res.free_vars)}\n{'=' * 78}")
        seen: set[str] = set()
        for e in events:
            if e["var"] in seen:
                continue
            seen.add(str(e["var"]))
            print(f"\n--- {e['var']}  field={e['defining']!r}")
            print(f"  minted in : {e['scope']}  at {e['site']}")
            for g in e["site_guards"]:
                print(f"  site guard: {g}")
            for c in e["site_conds"]:
                print(f"  site cond : {c}")
            print(f"  always_runs({e['scope']}) = {e['always_runs']}")
            print(f"  is_local             = {e['is_local']}")
            cov = e["covered"]
            if cov:
                print(f"  _paths_are_covered   = {cov[0]}  over {len(cov[1])} path(s)")
                for p in cov[1]:
                    print(f"      path: {p}")
            print(f"  _declared_default    = {(e['declared'] or (None, None, None))[2]}")
            f = e["forces"] or {}
            print(f"  _read_forces_a_write = {f.get('result')}")
            print(f"      why  : {f.get('why')}")
            print(f"      read : {f.get('read')}")
            for c in f.get("read_conds") or []:
                print(f"      read cond: {c}")
            for w in f.get("write_conds") or []:
                print(f"      write {w['at']}")
                for c in w["conds"]:
                    print(f"          {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
