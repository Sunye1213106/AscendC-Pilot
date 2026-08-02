# -*- coding: utf-8 -*-
"""Counterfactuals for the three remaining VAR_INIT_* sites.

Each experiment changes exactly one thing in the probe process, re-derives the
affected dimension and reports which free variables survive. Nothing here
edits production code; the point is to establish which proof step is load
bearing before anyone changes it.

  order    fold `fBaseParams.deterSparseType`'s writes in execution order
           (DoSparse:663 before CalcleCausalDeterParam:747) instead of the
           (file, line) order `_field_defs` sorts by.
  chain    complete the path conditions an `if/else-if` chain of `return`s
           leaves off the statement after it, so the fall-through return no
           longer carries a `guard_clause` that records less than the truth.
  cover    offline: `_paths_are_covered` on GetDeterSparseTilingKey's five
           returns, as recorded and with the missing negations restored.
  base     no change, for the diff.

    python scripts/_probe_whatif.py cover
    python scripts/_probe_whatif.py base order chain
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"

WATCH = {
    "VAR_INIT_36CDA3758519": "bandIdx",
    "VAR_INIT_ECF6DE7D873A": "blockOuter",
    "VAR_INIT_2288AFE53928": "deterSparseType",
    "VAR_INIT_51689D821E98": "GetDeterSparseTilingKey return",
}


def load():
    with BUNDLE.open("rb") as fh:
        return pickle.load(fh)


def derive(bundle, names):
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_derivation import encode_function

    binding = bundle["binding"]
    ir = bundle["host_ir"]
    out = {}
    for b in binding.bindings:
        if b.decl.name not in names:
            continue
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
        out[b.decl.name] = sorted(res.free_vars)
    return out


def report(label, got):
    print(f"\n### {label}")
    for name, free in got.items():
        inits = [v for v in free if v.startswith("VAR_INIT_")]
        print(f"  {name:14} free={len(free):2}  VAR_INIT: {inits or '-'}")
        for v in inits:
            if v in WATCH:
                print(f"                    {v}  = {WATCH[v]}")


# --- experiment: execution order for a member written across functions ------
def exp_order(bundle, names):
    """Fold cross-function writes in call order rather than (file, line).

    `_field_defs` sorts by file then line, which puts
    `common_regbase.cpp:747` (CalcleCausalDeterParam, reached from
    `DoSparse:664`) ahead of `normal_regbase.cpp:663` (DoSparse) -- the
    reverse of the order the program runs them in. `_chain_sites` is
    last-wins, so the earliest site is the one whose fall-through needs a
    value, and putting the wrong site first is what asks for one.
    """
    from uo_init.derive_key_fields import KeyFieldDeriver

    raw = KeyFieldDeriver._field_defs

    def patched(self, path):
        sites = raw(self, path)
        if path.endswith("deterSparseType") and len(sites) > 1:
            sites = sorted(sites, key=lambda s: 0 if s.function == "DoSparse" else 1)
        return sites

    KeyFieldDeriver._field_defs = patched
    try:
        return derive(bundle, names)
    finally:
        KeyFieldDeriver._field_defs = raw


# --- experiment: an if/else-if chain of returns records its own conditions --
def exp_chain(bundle, names):
    """Trust a path that runs out under a `guard_clause`.

    Stands in for completing the conditions the extractor leaves off: see
    `exp_cover`, which checks the sound repair gives the same answer.
    """
    from uo_init import derive_key_fields as dkf

    raw = dkf._records_rest
    dkf._records_rest = lambda paths: True
    try:
        return derive(bundle, names)
    finally:
        dkf._records_rest = raw


# --- offline: is the coverage test the only thing in the way? ---------------
class Cond:
    """A stand-in path condition, so a repaired chain can be scored."""

    def __init__(self, text, negated, file, line, kind):
        self.text, self.negated = text, negated
        self.file, self.line, self.kind = file, line, kind

    @property
    def records_what_follows(self):
        return self.kind != "guard_clause"

    def __repr__(self):
        return f"{'!' if self.negated else ''}{self.text}@{self.line}[{self.kind}]"


def exp_cover(bundle, _names):
    from uo_init import derive_key_fields as dkf

    ir = bundle["host_ir"]
    slot = ir.local_writes_in("GetDeterSparseTilingKey")
    key = next(k for k in slot if "RETURN" in str(k).upper()) if slot else None
    writes = list(slot.get(key, ())) if key else []
    print(f"\n### cover  (GetDeterSparseTilingKey, {len(writes)} return sites)")
    as_recorded = [dkf._decisive_conds(w) for w in writes]
    for w, conds in zip(writes, as_recorded):
        print(f"  line {w.line}: {[repr(c) for c in conds]}")
    print(f"  _paths_are_covered(as recorded)  = {dkf._paths_are_covered(as_recorded)}")

    # The repair: the statement after `if(A){ret} else if(B){ret} else if(C){ret}`
    # runs under !A && !B && !C, and all three are ordinary negations. Rebuild
    # the fall-through return's conditions that way and re-score.
    longest = max(as_recorded, key=len)
    decisions = {(c.file, c.line, c.text): c for c in longest}
    repaired = []
    for conds in as_recorded:
        if all(c.records_what_follows for c in conds):
            repaired.append(conds)
            continue
        seen = {(c.file, c.line, c.text) for c in conds}
        fixed = [
            Cond(c.text, True, c.file, c.line, "if" if c.kind == "guard_clause" else c.kind)
            for c in conds
        ]
        for k, c in decisions.items():
            if k not in seen:
                fixed.append(Cond(c.text, True, c.file, c.line, "if"))
        fixed.sort(key=lambda c: c.line)
        repaired.append(tuple(fixed))
        print(f"  repaired fall-through -> {[repr(c) for c in fixed]}")
    print(f"  _paths_are_covered(repaired)     = {dkf._paths_are_covered(repaired)}")
    return {}


def exp_both(bundle, names):
    """`order` and `chain` at once, to check they do not overlap."""
    from uo_init import derive_key_fields as dkf

    raw = dkf._records_rest
    dkf._records_rest = lambda paths: True
    try:
        return exp_order(bundle, names)
    finally:
        dkf._records_rest = raw


EXPERIMENTS = {
    "base": lambda b, n: derive(b, n),
    "order": exp_order,
    "chain": exp_chain,
    "both": exp_both,
    "cover": exp_cover,
}


def main() -> int:
    sys.setrecursionlimit(20000)
    which = sys.argv[1:] or ["base"]
    names = {"DeterType", "IsNzOut"}
    bundle = load()
    for w in which:
        fn = EXPERIMENTS.get(w)
        if fn is None:
            print(f"unknown experiment: {w}")
            continue
        got = fn(bundle, names)
        if got:
            report(w, got)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
