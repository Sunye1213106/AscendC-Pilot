# -*- coding: utf-8 -*-
"""What would K6 decide if the three unmodelled symbols became free variables?

Read-only experiment. Patches `key_reachability._Rewrite._loose` at runtime so a
bare symbol becomes a declared variable instead of dropping the dimension, then
runs the same sweep `_probe_reach.py` runs and reports the delta.

Variants:
    base     unpatched, reproduces the current numbers
    free     one isolated int variable per (dimension, symbol) -- weakest
    shared   one int variable per symbol, shared across dimensions
    domain   shared, plus discrete value-set domains for the two enum-ish ones

    python scripts/_probe_overapprox.py base free shared domain
    python scripts/_probe_overapprox.py domain --marginals
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CACHE = ROOT / ".probe_cache"
BUNDLE = CACHE / "fag_bundle.pkl"
RESULT = CACHE / "fag_derive.json"

#: Sound value sets read from the operator source, used only by the `domain`
#: variant to show what a *tighter* over-approximation would buy.
DOMAINS = {
    "deterTilingSplitMode": [0, 1, 2],
    "s2Inner": [64, 128, 256, 512],
}


def load():
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


def run(variant: str, args) -> dict:
    import uo_init.key_reachability as kr
    from uo_init.ids import slug

    doc, var_model, schema, binding = load()

    orig_loose = kr._Rewrite._loose
    orig_declare = kr._declare
    minted: dict[str, str] = {}

    def patched_loose(self, name):
        try:
            return orig_loose(self, name)
        except kr._Unadaptable:
            pass
        var_id = f"VAR_UNMODELLED_{slug(name)}"
        if variant == "free":
            var_id = self._rename(var_id)  # isolate per dimension
        minted[var_id] = name
        return {"var": var_id}

    def patched_declare(var_id, value_type, nulls):
        out = orig_declare(var_id, value_type, nulls)
        base = minted.get(var_id)
        if variant == "domain" and base in DOMAINS and out.get("type") == "int":
            out = dict(out)
            out["domain"] = {"kind": "discrete", "values": list(DOMAINS[base])}
        return out

    if variant != "base":
        kr._Rewrite._loose = patched_loose
        kr._declare = patched_declare
    try:
        from uo_init.materialize_tiling import build_legal_key_rows

        reach = kr.KeyReachability.from_derivation(doc, var_model, timeout_ms=args.timeout)
        summary = reach.summary()
        rows = build_legal_key_rows(
            schema, binding=binding, blocker_ids=[], reachability=reach
        )
    finally:
        kr._Rewrite._loose = orig_loose
        kr._declare = orig_declare

    status = Counter(r.status for r in rows)
    out = {
        "variant": variant,
        "compiled": summary["dimensions_compiled"],
        "total": summary["dimensions_total"],
        "exact": summary["dimensions_exact"],
        "omitted": summary["omitted"],
        "minted": sorted(set(minted.values())),
        "n_minted_vars": len(minted),
        "keys": len(rows),
        "status": dict(status),
        "detail": Counter(r.detail for r in rows if r.detail).most_common(5),
    }
    if args.marginals:
        out["marginals"] = marginals(reach, schema, rows)
    if args.cores:
        cores = Counter(
            tuple(sorted(r.unsat_core)) for r in rows if r.status == "unreachable"
        )
        out["unsat_cores"] = [[list(k), v] for k, v in cores.most_common(10)]
    return out


def marginals(reach, schema, rows) -> dict:
    """Per dimension: which declared values can the compiled tree still take?

    Guard-independent, so it isolates what the over-approximation buys on its
    own -- a value ruled out here is ruled out for every key that asks for it.
    """
    out = {}
    for d in schema.dims:
        spec = reach._dims.get(d.name)
        if spec is None:
            out[d.name] = "omitted"
            continue
        alive, dead = [], []
        for v in d.value_domain:
            try:
                val = int(str(v), 0)
            except (TypeError, ValueError):
                continue
            res = reach._backend.solve_expr(
                {"op": "eq", "var": spec["var"], "value": val}, label="marg"
            )
            (alive if res.get("status") == "sat" else dead).append(val)
        out[d.name] = {"domain": list(d.value_domain), "alive": alive, "dead": dead}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("variants", nargs="*", default=["base"])
    ap.add_argument("--timeout", type=int, default=5000)
    ap.add_argument("--marginals", action="store_true")
    ap.add_argument("--cores", action="store_true")
    args = ap.parse_args()
    results = []
    for variant in args.variants or ["base"]:
        print(f"\n########## {variant} ##########", flush=True)
        got = run(variant, args)
        results.append(got)
        print(f"compiled : {got['compiled']}/{got['total']} (exact {got['exact']})")
        print(f"omitted  : {got['omitted']}")
        print(f"minted   : {got['minted']} ({got['n_minted_vars']} vars)")
        print(f"keys     : {got['keys']}  {got['status']}")
        for text, n in got["detail"]:
            print(f"   {n:6}  {text[:120]}")
        if got.get("unsat_cores"):
            print("  unsat cores:")
            for core, n in got["unsat_cores"]:
                print(f"   {n:6}  {core}")
        if got.get("marginals"):
            print("  marginals (values the tree can still take):")
            for name, m in got["marginals"].items():
                if m == "omitted":
                    print(f"   {name:16} OMITTED")
                else:
                    print(
                        f"   {name:16} domain={m['domain']} alive={m['alive']} "
                        f"DEAD={m['dead']}"
                    )
    (CACHE / "overapprox.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nwrote {CACHE / 'overapprox.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
