# -*- coding: utf-8 -*-
"""The chain frame in force when each VAR_INIT_* was minted, plus what-ifs.

`_probe_mint.py` reads the helpers one at a time, which loses the correlation
as soon as expansion recurses. This wraps `_chain_sites` itself and keeps a
stack, so a mint is reported against the exact `sites`/`pool` it happened in.

Two counterfactuals are evaluated on the same data, without touching the
production code:

- `covered_if_trusted`: `_paths_are_covered` with `guard_clause` conditions
  treated as recording what follows them. Says whether the coverage test is
  failing only because the extractor stopped negating an if/else-if chain.
- `always_runs`: evaluated for the minting scope whether or not the short
  circuit reached it, so the second half of `covered_in` is visible too.

    python scripts/_probe_mint2.py DeterType IsNzOut
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"


def _c(c) -> str:
    return f"{'!' if getattr(c, 'negated', False) else ' '}[{getattr(c, 'kind', '')}] {getattr(c, 'text', '')[:80]}"


def _site(s) -> str:
    return f"{Path(s.file).name.replace('flash_attention_score_grad_tiling_', '')}:{s.line} [{s.function}]"


class _Trusting:
    """A path condition that answers `records_what_follows` with True."""

    __slots__ = ("_c",)

    def __init__(self, c):
        self._c = c

    def __getattr__(self, name):
        if name == "records_what_follows":
            return True
        return getattr(self._c, name)


def main() -> int:
    sys.setrecursionlimit(20000)
    wanted = sys.argv[1:] or ["DeterType"]

    with BUNDLE.open("rb") as fh:
        bundle = pickle.load(fh)

    from uo_init import derive_key_fields as dkf
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.loop_summary import guards_cover

    stack: list[dict] = []
    events: list[dict] = []

    raw_chain = KeyFieldDeriver._chain_sites
    raw_mint = KeyFieldDeriver._init_var

    def chain(self, sites, fn, depth, defining, pool, ident=""):
        stack.append(
            {
                "defining": defining,
                "fn": fn,
                "depth": depth,
                "sites": list(sites),
                "pool": list(pool),
                "read_at": self._read_at,
            }
        )
        try:
            return raw_chain(self, sites, fn, depth, defining, pool, ident)
        finally:
            stack.pop()

    def mint(self, defining, scope, site):
        ref = raw_mint(self, defining, scope, site)
        frame = dict(stack[-1]) if stack else {}
        pool = frame.get("pool") or []
        read = frame.get("read_at")

        by_fn: dict[str, list] = {}
        for s in pool:
            by_fn.setdefault(s.function or frame.get("fn") or "", []).append(s)
        cover: dict[str, dict] = {}
        for name, group in by_fn.items():
            paths = [s.conds for s in group]
            trusted = [tuple(_Trusting(c) for c in p) for p in paths]
            cover[name] = {
                "paths_are_covered": dkf._paths_are_covered(paths),
                "covered_if_trusted": dkf._paths_are_covered(trusted),
                "always_runs": self._always_runs(name, frame.get("depth") or 0),
                "is_local": self._is_local_of(defining, name),
                "n": len(group),
            }

        imp = None
        if read is not None and read.conds and pool:
            imp = guards_cover(
                read.conds,
                [(s.conds, s.function or read.function) for s in pool],
                read_function=read.function,
                members=getattr(self.ir, "class_fields", ()) or (),
            )
        events.append(
            {
                "var": ref.symbol,
                "defining": defining,
                "scope": scope,
                "site": _site(site),
                "frame_fn": frame.get("fn"),
                "sites_order": [_site(s) for s in frame.get("sites") or []],
                "pool_order": [_site(s) for s in pool],
                "pool_conds": {_site(s): [_c(c) for c in s.conds] for s in pool},
                "cover": cover,
                "read": (
                    None
                    if read is None
                    else {
                        "at": _site(read),
                        "conds": [_c(c) for c in read.conds],
                    }
                ),
                "implication": None if imp is None else (imp.holds, imp.reason, imp.checked),
            }
        )
        return ref

    KeyFieldDeriver._chain_sites = chain
    KeyFieldDeriver._init_var = mint

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
        live = set(res.free_vars)
        print(f"\n{'=' * 78}\n{b.decl.name}   host_expr = {b.host_expr[:70]}")
        print(f"free = {sorted(live)}\n{'=' * 78}")
        seen: set[str] = set()
        for e in events:
            if e["var"] in seen:
                continue
            seen.add(e["var"])
            mark = "LIVE " if e["var"] in live else "gone "
            print(f"\n--- {mark}{e['var']}  field={e['defining']!r}")
            print(f"  minted at {e['site']}   (chain called from fn={e['frame_fn']})")
            print(f"  sites in chain order:")
            for s in e["sites_order"]:
                print(f"      {s}")
            if e["pool_order"] != e["sites_order"]:
                print(f"  pool ({len(e['pool_order'])}): {e['pool_order']}")
            print("  coverage per function:")
            for name, c in e["cover"].items():
                print(
                    f"      {name:28} n={c['n']} covered={c['paths_are_covered']}"
                    f"  covered_if_trusted={c['covered_if_trusted']}"
                    f"  always_runs={c['always_runs']}  is_local={c['is_local']}"
                )
            print("  write conds:")
            for s, cs in e["pool_conds"].items():
                print(f"      {s}")
                for c in cs:
                    print(f"          {c}")
            r = e["read"]
            print(f"  read site: {r['at'] if r else None}")
            for c in (r or {}).get("conds") or []:
                print(f"      read cond: {c}")
            print(f"  guards_cover: {e['implication']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
