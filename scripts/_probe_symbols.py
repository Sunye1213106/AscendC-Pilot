# -*- coding: utf-8 -*-
"""Investigate why three host symbols stay unexpanded and drop 5 TilingKey dims.

Read-only diagnostic. Answers, per symbol:
  * what `_defs_for(name, fn)` returns, in every plausible scope
  * which `return leaf` branch of `_expand_name` actually fires
  * how the symbol appears in the derived tree of the dropped dimensions

    python scripts/_probe_symbols.py defs        # def-site lookup
    python scripts/_probe_symbols.py tree        # shape in the cached trees
    python scripts/_probe_symbols.py trace       # instrumented re-derivation
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CACHE = ROOT / ".probe_cache"
BUNDLE = CACHE / "fag_bundle.pkl"
RESULT = CACHE / "fag_derive.json"

SYMBOLS = ("m0Max", "s2Inner", "deterTilingSplitMode")
DROPPED = ("SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut", "IsTndSwizzle")


def load_bundle() -> dict:
    with BUNDLE.open("rb") as fh:
        return pickle.load(fh)


def load_result() -> dict:
    return json.loads(RESULT.read_text(encoding="utf-8"))


def deriver(bundle):
    from uo_init.derive_key_fields import KeyFieldDeriver

    return KeyFieldDeriver(
        host_ir=bundle["host_ir"],
        resolver=bundle["resolver"],
        var_model=bundle["var_model"],
        max_helper_guards=4,
    )


# --------------------------------------------------------------- defs


def scopes_mentioning(ir, name: str) -> list[str]:
    out = []
    for fn in ir.summaries:
        if ir.local_writes_in(fn).get(name):
            out.append(fn)
    return out


def cmd_defs(args) -> int:
    bundle = load_bundle()
    ir = bundle["host_ir"]
    d = deriver(bundle)
    print(f"host_ir functions: {len(ir.summaries)}")
    print(f"class_fields: {len(getattr(ir, 'class_fields', ()) or ())}")
    for name in SYMBOLS:
        print(f"\n===== {name} =====")
        owners = scopes_mentioning(ir, name)
        print(f"local_writes_in owners ({len(owners)}):")
        for fn in owners:
            ws = ir.local_writes_in(fn).get(name, [])
            for w in ws:
                print(
                    f"    {fn}\n      {w.file}:{w.line}  rhs={w.rhs!r}"
                    f"  guards={list(w.guards())}"
                )
        print(f"in class_fields: {name in (getattr(ir, 'class_fields', ()) or ())}")
        for owner in ("fBaseParams", "tilingData"):
            fd = d._field_defs(f"{owner}.{name}")
            print(f"_field_defs({owner}.{name}): {len(fd)}")
            for s in fd[:8]:
                print(f"    {s.file}:{s.line} fn={s.function} rhs={s.rhs!r}")
        # defs_by_function summaries
        hits = [
            (fn, rs)
            for fn, tbl in ir.defs_by_function().items()
            if (rs := tbl.get(name))
        ]
        print(f"defs_by_function hits: {len(hits)}")
        for fn, rs in hits[:8]:
            print(f"    {fn}: {rs}")
        for fn in dict.fromkeys(owners + [args.scope] if args.scope else owners):
            if not fn:
                continue
            sites = d._defs_for(name, fn)
            canon = d._canonical_name(name, fn)
            print(f"_defs_for({name!r}, {fn!r}) -> {len(sites)}  canon={canon!r}")
            for s in sites:
                print(f"    {s.file}:{s.line} fn={s.function} rhs={s.rhs!r}")
    return 0


# --------------------------------------------------------------- tree


def walk(node, path="$"):
    """Yield (path, node) for every dict/list/str in the encoded DAG."""
    seen = set()

    def rec(n, p):
        if isinstance(n, dict):
            if id(n) in seen:
                return
            seen.add(id(n))
            yield p, n
            for k, v in n.items():
                yield from rec(v, f"{p}.{k}")
        elif isinstance(n, list):
            if id(n) in seen:
                return
            seen.add(id(n))
            yield p, n
            for i, v in enumerate(n):
                yield from rec(v, f"{p}[{i}]")
        else:
            yield p, n

    yield from rec(node, path)


def cmd_tree(args) -> int:
    doc = load_result()
    by = {f["name"]: f for f in doc["fields"]}
    for dim in DROPPED:
        f = by.get(dim)
        if f is None:
            print(f"!! {dim} not in cache")
            continue
        print(f"\n===== {dim} [{f['status']}/{f.get('exactness')}] =====")
        print(f"  host_expr : {f['host_expr']}")
        print(f"  free_vars : {f.get('free_vars')}")
        print(f"  variables : {len(f.get('variables') or [])}")
        print(f"  leaves    : {f.get('value_leaves')}")
        ve = f.get("value_expr")
        hits = {}
        for p, n in walk(ve):
            for sym in SYMBOLS:
                if isinstance(n, str) and n == sym:
                    hits.setdefault((sym, "bare-string"), []).append(p)
                elif isinstance(n, dict) and n.get("var") == sym:
                    hits.setdefault((sym, "var-node"), []).append(p)
                elif isinstance(n, str) and sym in n and n != sym:
                    hits.setdefault((sym, f"substring:{n[:60]}"), []).append(p)
        if not hits:
            print("  (no occurrence of the three symbols in value_expr)")
        for (sym, kind), paths in sorted(hits.items()):
            print(f"  {sym:22} {kind:24} x{len(paths)}   e.g. {paths[0]}")
        # print the parent node of the first bare-string hit
        for sym in SYMBOLS:
            for p, n in walk(ve):
                if isinstance(n, dict) and any(
                    v == sym for v in n.values() if isinstance(v, str)
                ):
                    print(f"  parent node of bare {sym}: {json.dumps(n)[:400]}")
                    break
    return 0


# --------------------------------------------------------------- trace


def cmd_trace(args) -> int:
    """Re-derive the dropped dimensions with the expander instrumented."""
    import uo_init.derive_key_fields as dkf
    from uo_init.expr_ir import Ref

    bundle = load_bundle()
    from uo_init.tpl_bind import merge_literal_encode_alts

    binding = bundle.get("binding")
    if binding is not None and bundle.get("host_ir") is not None:
        bundle["binding"] = merge_literal_encode_alts(binding, bundle["host_ir"])

    events: list[dict] = []
    operand_events: list[dict] = []
    leaf_events: list[dict] = []
    watch = set(SYMBOLS) | set(args.also or [])
    current = {"dim": "?"}

    orig_expand_name = dkf.KeyFieldDeriver._expand_name
    orig_defs_for = dkf.KeyFieldDeriver._defs_for
    orig_loop_only = dkf._loop_scoped_only
    orig_operand = dkf.KeyFieldDeriver._expand_operand
    orig_reduces = dkf.KeyFieldDeriver._reduces_to_inputs
    orig_leaf = dkf._ValueNormalizer._leaf
    orig_derive = dkf.KeyFieldDeriver.derive

    def traced_derive(self, **kw):
        current["dim"] = kw.get("dim_name", "?")
        return orig_derive(self, **kw)

    def traced_expand_name(self, name, original, fn, depth):
        if name not in watch:
            return orig_expand_name(self, name, original, fn, depth)
        canon = self._canonical_name(name, fn)
        active = canon in self._active
        has_prev = self._prev_version.get(canon) is not None
        sites = orig_defs_for(self, name, fn)
        if not sites and canon != name:
            sites = orig_defs_for(self, canon, fn)
        generic = (fn, canon, ())
        cached = generic in self._cache or (
            (fn, canon, self._version_context()) in self._cache
        )
        loop_only = orig_loop_only(sites) if sites else None
        if active and has_prev:
            branch = "L2105 prev-version (x = f(x))"
        elif active:
            branch = "L2107 CYCLE -> leaf"
        elif cached:
            branch = "cache hit"
        elif not sites:
            branch = "L2122 no-def-sites -> leaf"
        elif loop_only:
            branch = "L2129 loop-scoped-only -> leaf"
        else:
            branch = "expanded via _chain"
        out = orig_expand_name(self, name, original, fn, depth)
        events.append(
            {
                "dim": current["dim"],
                "name": name,
                "fn": fn,
                "canon": canon,
                "depth": depth,
                "branch": branch,
                "active_set": sorted(self._active),
                "prev_version": sorted(self._prev_version),
                "n_sites": len(sites),
                "sites": [f"{Path(s.file).name}:{s.line}" for s in sites[:6]],
                "site_guards": [list(s.guards)[:2] for s in sites[:3]],
                "loop_scoped_only": loop_only,
                "result": dkf._pretty_dag(out)[:160],
                "result_is_bare_leaf": isinstance(out, Ref) and out.symbol == name,
            }
        )
        return out

    def traced_operand(self, e, fn, depth):
        name = self._classifier_operand(e, fn)
        if name not in watch:
            return orig_operand(self, e, fn, depth)
        rec = {
            "dim": current["dim"],
            "operand": name,
            "fn": fn,
            "self_routing": self._writes_are_self_routing(name, fn),
            "already_rejected": name in self._rejected,
        }
        out = orig_operand(self, e, fn, depth)
        rec["rejected_after"] = name in self._rejected
        rec["result"] = dkf._pretty_dag(out)[:200]
        operand_events.append(rec)
        return out

    def traced_reduces(self, e, fn):
        out = orig_reduces(self, e, fn)
        if not out:
            # Report the offending names, which is what the predicate hides.
            bad = []
            names = set()
            for node in dkf._walk_dag(e):
                if isinstance(node, dkf.Unknown):
                    bad.append(("<Unknown>", node.reason, None))
                elif isinstance(node, Ref):
                    names.add((node.symbol, node.scope or fn))
                elif isinstance(node, dkf.Call):
                    p = dkf.dotted_path(node)
                    if p is not None:
                        names.add((p, fn))
            for nm, sc in sorted(names):
                res = self._scope(sc).resolve(nm)
                if (
                    not res.closed
                    or not res.roots
                    or any(r not in dkf._DRIVABLE_ROOTS for r in res.roots)
                ):
                    bad.append((nm, sc, list(res.roots) or f"closed={res.closed}"))
            if operand_events:
                operand_events[-1]["reduces_to_inputs"] = False
                operand_events[-1]["blockers"] = [str(b) for b in bad[:12]]
        return out

    def traced_leaf(self, expr):
        text = dkf._leaf_text(expr)
        if text not in watch:
            return orig_leaf(self, expr)
        rec = {
            "dim": current["dim"],
            "text": text,
            "scope": getattr(expr, "scope", ""),
        }
        try:
            out = orig_leaf(self, expr)
            rec["out"] = out
        except Exception as exc:  # noqa: BLE001
            rec["raised"] = f"{type(exc).__name__}: {exc}"
            leaf_events.append(rec)
            raise
        res = self._resolver_for(expr).resolve(text)
        rec["atoms"] = [
            {"root": a.root, "symbol": a.symbol, "text": a.text, "reason": a.reason}
            for a in res.atoms
        ]
        leaf_events.append(rec)
        return out

    dkf.KeyFieldDeriver.derive = traced_derive
    dkf.KeyFieldDeriver._expand_name = traced_expand_name
    dkf.KeyFieldDeriver._expand_operand = traced_operand
    dkf.KeyFieldDeriver._reduces_to_inputs = traced_reduces
    dkf._ValueNormalizer._leaf = traced_leaf
    try:
        from uo_init.host_derivation import derive_host_fields

        doc = derive_host_fields(
            bundle,
            timeout=args.timeout,
            max_helper_guards=4,
            isolate=False,
            only=list(args.dims) or list(DROPPED),
        )
    finally:
        dkf.KeyFieldDeriver.derive = orig_derive
        dkf.KeyFieldDeriver._expand_name = orig_expand_name
        dkf.KeyFieldDeriver._expand_operand = orig_operand
        dkf.KeyFieldDeriver._reduces_to_inputs = orig_reduces
        dkf._ValueNormalizer._leaf = orig_leaf

    from collections import Counter

    print(f"\n=== _expand_name: {len(events)} calls on {sorted(watch)} ===")
    tally = Counter(
        (e["name"], e["branch"], e["fn"], e["n_sites"], tuple(e["sites"]))
        for e in events
    )
    for (name, branch, fn, n, sites), cnt in sorted(tally.items()):
        print(f"  x{cnt:<4} {name:22} {branch:32} sites={n} {list(sites)} in {fn}")
    print("\n  -- leaf-producing events, in order --")
    for e in events:
        if not e["result_is_bare_leaf"]:
            continue
        print(
            f"    {e['name']:22} {e['branch']:32} fn={e['fn']:26} "
            f"sites={e['sites']} active={e['active_set']} prev={e['prev_version']}"
        )

    print(f"\n=== _expand_operand: {len(operand_events)} calls ===")
    for e in operand_events:
        print(json.dumps(e, ensure_ascii=False, indent=2, default=str)[:2500])

    print(f"\n=== _ValueNormalizer._leaf: {len(leaf_events)} calls ===")
    tally2 = Counter(
        (
            e["text"],
            e["scope"],
            json.dumps(e.get("out"), default=str),
            json.dumps(e.get("atoms"), default=str),
        )
        for e in leaf_events
    )
    for (text, scope, out, atoms), cnt in sorted(tally2.items()):
        print(f"  x{cnt:<4} {text:22} scope={scope or '<none>':28} -> {out}")
        print(f"        atoms={atoms}")

    print("\n--- resulting fields ---")
    for f in doc.fields:
        print(
            f"  {f.name:16} {f.status:11} {str(f.exactness or '?'):16} "
            f"free={len(f.free_vars)} vars={len(f.variables)} note={f.note}"
        )
    out = CACHE / "symbol_trace.json"
    out.write_text(
        json.dumps(
            {"expand_name": events, "operand": operand_events, "leaf": leaf_events},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


# --------------------------------------------------------------- leaf


def cmd_leaf(args) -> int:
    """How the normalizer turns an unexpanded name into a tree node."""
    from uo_init.derive_key_fields import _ValueNormalizer
    from uo_init.expr_ir import Ref

    bundle = load_bundle()
    resolver = bundle["resolver"]
    model = bundle["var_model"]
    scoped = {}

    def scope_for(fn):
        if fn not in scoped:
            scoped[fn] = resolver._in_function(fn) if fn else resolver
        return scoped[fn]

    norm = _ValueNormalizer(
        resolver, model, scope_for=scope_for, host_ir=bundle["host_ir"]
    )
    for name in SYMBOLS:
        for fn in ("", "CalcleDeterParam", "CalcleTNDCausalDeterPrefix", "DoSplit"):
            res = scope_for(fn).resolve(name)
            print(
                f"{name:22} scope={fn or '<encode>':28} "
                f"roots={res.roots} closed={res.closed} "
                f"atoms={[(a.root, a.symbol, a.text, a.reason) for a in res.atoms]}"
            )
        try:
            out = norm._leaf(Ref(name))
            print(f"  -> _leaf: {out!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  -> _leaf raised {type(exc).__name__}: {exc}")
        print(f"  -> lookup_constant: {model.lookup_constant(name)!r}")
        print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("leaf")
    p.set_defaults(func=cmd_leaf)
    p = sub.add_parser("defs")
    p.add_argument("--scope", default="")
    p.set_defaults(func=cmd_defs)
    p = sub.add_parser("tree")
    p.set_defaults(func=cmd_tree)
    p = sub.add_parser("trace")
    p.add_argument("dims", nargs="*")
    p.add_argument("--also", nargs="*")
    p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(func=cmd_trace)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
