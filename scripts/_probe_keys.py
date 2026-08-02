# -*- coding: utf-8 -*-
"""Which whole keys the operator can be driven to, each with the input to do it.

A key is nineteen dimensions read off *one* run, so asking each dimension what
it can be separately says nothing about which combinations exist. This drives
all nineteen from the same input and collects the tuples that come out.

What it finds is sound in the direction that matters: every key here comes
with an input that produces it, so it is reachable no matter how loose the
approximation elsewhere. Keys it does not find are not thereby unreachable —
the search is sampling, not proof.
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import (  # noqa: E402
    CONFIRMED,
    Auxiliaries,
    Premises,
    Unknown,
    ValueTree,
    ZeroDenominator,
    domain_for,
    domains_of,
    drivable_root,
    grade_witness,
    invented_range,
    reaching_inputs,
    samples,
)

_DECLARED: dict[str, list] = {}


def _declared_values(dim: str) -> list:
    """What the kernel says this dimension may be -- the targets worth aiming at."""
    if not _DECLARED:
        import os

        from uo_init import paths
        from uo_init.op_spec import discover
        from uo_init.tpl_dsl import parse_file

        relative = os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")
        spec = discover(paths.op_dir(relative=relative))
        for d in parse_file(spec.tiling_key_header).dims:
            got = []
            for raw in d.value_domain:
                try:
                    got.append(int(raw))
                except (TypeError, ValueError):
                    got.append(raw)
            _DECLARED[d.name] = got
    return _DECLARED.get(dim, [])


def _read_off(trees, env, per_dim, why, blame=None, read=None, bans=None, shapes=None):
    """Every dimension's value on this one input, and which ones would not say."""
    row, missing = [], []
    for name, t in trees:
        try:
            got = t.value(env, read=read)
        except ZeroDenominator as exc:
            why[name]["division by zero"] += 1
            if blame is not None:
                blame |= t.vars_under(exc.node)
            if bans is not None:
                learned = t.zero_blame(exc.node, env)
                if learned is not None:
                    bans[learned[0]].add(learned[1])
                elif shapes is not None:
                    shapes[tuple(sorted(t.vars_under(exc.node)))] += 1
            got = None
        except Unknown as exc:
            why[name][str(exc)[:70]] += 1
            got = None
        if isinstance(got, bool):
            got = int(got)
        if not isinstance(got, (int, str)):
            got = None
            missing.append(name)
        row.append(got)
        if got is not None:
            per_dim[name][got] += 1
    return row, missing


def _draw(axes, rng, *, base=None, aim=None):
    """One input: random, or a mutation of one that got somewhere, with the
    variables a reversed path asked for pinned on top."""
    if base:
        env = dict(base)
        for v in rng.sample(sorted(axes), rng.randint(1, 3)):
            env[v] = rng.choice(axes[v])
    else:
        env = {v: rng.choice(vals) for v, vals in axes.items()}
    if aim:
        env.update(aim)
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--repairs", type=int, default=3)
    ap.add_argument("--guided", action="store_true")
    args = ap.parse_args()

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        domains, constants = domains_of(pickle.load(fh)["var_model"])
    saved = doc.get("host_derivation") or {}
    premises = Premises(saved.get("premises") or [])
    # Names the operator computes for itself. Evaluated from each draw rather
    # than drawn: see `Auxiliaries`.
    aux = Auxiliaries.from_rows(saved.get("auxiliaries") or {})

    fields = [f for f in doc["fields"] if f.get("value_expr") is not None]
    trees = [(f["name"], ValueTree(f["value_expr"])) for f in fields]
    roots: dict[str, str] = {}
    for f in doc["fields"]:
        roots.update(f.get("var_roots") or {})
    print(f"{len(trees)} of {len(doc['fields'])} dimensions have an expression")

    # One shared input space: a key comes off a single run, so the dimensions
    # must be driven by the same draw rather than each by its own.
    cuts: dict[str, set] = defaultdict(set)
    allvars: set[str] = set()
    divisors: set[str] = set()
    for _, t in list(trees) + [("", t) for t in aux.trees.values()]:
        c, v = t.cuts()
        allvars |= v
        divisors |= t.divisors()
        for k, s in c.items():
            cuts[k] |= s
    allvars -= aux.names
    for v in allvars & premises.vars:
        cuts[v] |= premises.cuts.get(v, set())

    axes: dict[str, list] = {}
    invented: list[str] = []
    for v in sorted(allvars):
        domain = domain_for(v, domains)
        vals = samples(cuts.get(v, set()), domain, constants)
        if v in divisors:
            vals = [x for x in vals if x != 0] or vals
        axes[v] = premises.keeps(v, vals)
        if invented_range(cuts.get(v, set()), domain):
            invented.append(v)
    space = 1
    for vals in axes.values():
        space *= len(vals)
    print(f"{len(axes)} variables, {space:.3g} combinations in all")
    if aux.names:
        print(f"  {len(aux.names)} more the operator computes, not drawn: "
              f"{sorted(aux.names)}")

    # What the search is allowed to move decides what a hit is worth. A draw
    # that sets one of these is describing host state, so the key it produces
    # is proposed rather than demonstrated.
    undrivable = sorted(v for v in axes if not drivable_root(v, roots))
    print(f"  {len(axes) - len(undrivable)} a test case can set, "
          f"{len(undrivable)} it cannot: {undrivable}")
    if invented:
        print(f"  {len(invented)} with no declared range and nothing comparing "
              f"against them; their points are made up: {invented}\n")
    else:
        print()

    rng = random.Random(args.seed)
    keys: dict[tuple, dict] = {}
    grades: dict[tuple, str] = {}
    per_dim: dict[str, Counter] = {name: Counter() for name, _ in trees}
    partial = Counter()
    why: dict[str, Counter] = defaultdict(Counter)
    refused = 0
    illegal = 0
    #: variable -> values watched to zero a denominator on their own.
    bans: dict[str, set] = defaultdict(set)
    #: The variable sets behind zeros no single value explains.
    zero_shapes: Counter = Counter()
    # Inputs worth going back to: one that reached something new is a better
    # place to look from than a fresh draw, because most of what it set is
    # already past the guards that a fresh draw has to clear again.
    corpus: list[dict] = []
    names = [n for n, _ in trees]

    # Ask each dimension what input would drive it to each value the kernel
    # declares. Random draws reach whatever the code does commonly; these are
    # the only way to the rest.
    wanted: list[dict] = []
    if args.guided:
        for name, t in trees:
            for v in _declared_values(name):
                wanted.extend(reaching_inputs(t, v, axes))
        print(f"path reversal proposed {len(wanted)} partial inputs\n")

    for i in range(args.n):
        aim: dict = {}
        if wanted:
            aim = wanted[i % len(wanted)] if i < 4 * len(wanted) else rng.choice(wanted)
        base: dict = {}
        if not aim and corpus and args.guided and rng.random() < 0.5:
            base = rng.choice(corpus)

        # Dividing by zero is the operator not coming back: that input yields
        # no key and so says nothing about any dimension. It happens here
        # because a draw broke a relation the premises never stated -- a
        # hidden size over a head count, say, where the two were drawn apart.
        # Redraw rather than record it. Charging it to the dimension is what
        # made four of them look unevaluable on a third of all inputs.
        row, missing = [], ["<undrawn>"]
        read: set[str] = set()
        drawn = _draw(axes, rng, base=base, aim=aim)
        for attempt in range(args.repairs + 1):
            if premises.rejects(drawn):
                refused += 1
                break
            blame: set[str] = set()
            read = set()
            # The operator's own intermediate values, from this draw. A name
            # this input does not settle is simply absent, and the dimensions
            # reading it come back with nothing.
            env = {**drawn, **aux.resolve(drawn)}
            before = sum(len(s) for s in bans.values())
            row, missing = _read_off(
                trees, env, per_dim, why, blame, read, bans, zero_shapes
            )
            if sum(len(s) for s in bans.values()) != before:
                # A denominator named a single value as the whole reason it was
                # zero. That is a premise the operator never wrote down, so it
                # narrows the space from here on rather than only this draw.
                for v, bad in bans.items():
                    kept = [x for x in axes[v] if x not in bad]
                    if kept:
                        axes[v] = kept
            if not missing:
                break
            illegal += 1
            loose = sorted(blame - set(aim))
            drawn = (
                {**drawn, **{v: rng.choice(axes[v]) for v in loose if v in axes}}
                if loose
                else _draw(axes, rng, base=base, aim=aim)
            )
        if missing == ["<undrawn>"]:
            continue
        # A draw that reached a value never seen on some dimension is worth
        # keeping even if another dimension failed: the part that got there
        # is what the mutation is meant to preserve.
        fresh = any(
            got is not None and per_dim[name][got] == 1
            for name, got in zip(names, row)
        )
        if missing:
            for name in missing:
                partial[name] += 1
            if fresh:
                corpus.append(drawn)
            continue
        # Graded on the drawn variables the nineteen paths actually consulted:
        # not on host state no taken branch looked at, and not on an auxiliary,
        # which the draw decided rather than stood alongside.
        grade, _ = grade_witness({k: drawn[k] for k in read if k in drawn}, roots)
        seen = keys.get(tuple(row))
        # A confirmed witness replaces a candidate one for the same key: both
        # say the key exists, but only one of them is an input.
        if seen is None or (grade == CONFIRMED and grades[tuple(row)] != CONFIRMED):
            keys[tuple(row)] = drawn
            grades[tuple(row)] = grade
            corpus.append(drawn)

    confirmed = sum(1 for g in grades.values() if g == CONFIRMED)
    print(f"of {args.n} draws: {refused} refused by a premise, {illegal} redrawn "
          f"after dividing by zero, {len(keys)} distinct whole keys found "
          f"({confirmed} on inputs alone, {len(keys) - confirmed} needing host state)")
    if bans:
        learned = {v: sorted(s) for v, s in sorted(bans.items()) if s}
        print(f"  values ruled out as sole cause of a zero denominator: {learned}")
    if zero_shapes:
        print("  zero denominators no single value explains, most common first:")
        for names, n in zero_shapes.most_common(6):
            print(f"    {n:6}  {list(names)}")
    if partial:
        print("\ndraws lost because a dimension could not be evaluated:")
        for name, c in partial.most_common(8):
            print(f"  {c:6}  {name}")
            for reason, n in why[name].most_common(3):
                print(f"          {n:6}  {reason}")
    print("\nper dimension: what the kernel declares, and what was reached")
    short = 0
    for name, _ in trees:
        seen = set(per_dim[name])
        declared = set(_declared_values(name))
        missed = sorted(declared - seen, key=repr)
        short += bool(missed)
        extra = sorted(seen - declared, key=repr) if declared else []
        note = f"missing {missed}" if missed else "all reached"
        if extra:
            note += f" -- and reached {extra}, which it does not declare"
        print(f"  {name:<15} {len(seen)}/{len(declared) or '?'}  {note}")
    print(f"\n{len(trees) - short}/{len(trees)} dimensions fully covered")

    _against_kernel_rules([n for n, _ in trees], keys, per_dim, grades)
    return 0


def _against_kernel_rules(names, keys, per_dim, grades=None) -> None:
    """The kernel's own legality rules are the denominator for coverage.

    A key the host can produce but the kernel does not accept is a defect;
    a key the kernel accepts that no input reaches is a hole in the search
    (or in the operator). Both only show up against this list.
    """
    import os

    from uo_init import paths
    from uo_init.op_spec import discover
    from uo_init.tpl_dsl import expand_legal_instances, parse_file

    relative = os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")
    spec = discover(paths.op_dir(relative=relative))
    if not spec.tiling_key_header:
        print("\nno tiling key header: cannot score coverage")
        return
    schema = parse_file(spec.tiling_key_header)
    legal = expand_legal_instances(schema)
    dims = [d.name for d in schema.dims]
    print(f"\nkernel declares {len(legal)} legal keys over {len(dims)} dimensions")

    unknown = [d for d in dims if d not in names]
    if unknown:
        print(f"  dimensions the host side has no expression for: {unknown}")

    def norm(v):
        return str(int(v)) if isinstance(v, bool) else str(v)

    order = [names.index(d) for d in dims if d in names]
    shared = [d for d in dims if d in names]
    found = {tuple(norm(row[i]) for i in order) for row in keys}
    want = {tuple(norm(inst[d]) for d in shared) for inst in legal}
    hit = found & want
    print(f"  reached {len(hit)} of {len(want)} legal combinations "
          f"({100.0 * len(hit) / max(1, len(want)):.1f}%)")
    if grades:
        sure = {
            tuple(norm(row[i]) for i in order)
            for row, g in grades.items()
            if g == CONFIRMED
        } & want
        # The number that survives contact with a generator. The rest name a
        # value of host tiling state, which nothing a test sets reaches.
        print(f"  of those, {len(sure)} come with an input a case can be built "
              f"from ({100.0 * len(sure) / max(1, len(want)):.1f}%); "
              f"{len(hit) - len(sure)} rest on host state")
    outside = found - want
    if outside:
        print(f"  {len(outside)} keys the host produces that the kernel does not declare")
        # Which pair of dimensions is the disagreement about? A value pair the
        # rules never allow together, that the host nonetheless puts together,
        # is either a wrong derivation or a real contract break -- and naming
        # the pair is what makes it checkable against the source.
        allowed: dict[tuple[int, int], set] = defaultdict(set)
        for row in want:
            for a in range(len(shared)):
                for b in range(a + 1, len(shared)):
                    allowed[(a, b)].add((row[a], row[b]))
        guilt: Counter = Counter()
        for row in outside:
            for (a, b), ok in allowed.items():
                if (row[a], row[b]) not in ok:
                    guilt[(shared[a], row[a], shared[b], row[b])] += 1
        if guilt:
            print("  value pairs the kernel never allows together, most common first:")
            for (da, va, db, vb), c in guilt.most_common(8):
                print(f"    {c:5}  {da}={va} together with {db}={vb}")
        else:
            print("  no single pair explains it: the rules must forbid a wider combination")
        for row in sorted(outside)[:2]:
            print("    e.g. " + ", ".join(f"{d}={v}" for d, v in zip(shared, row)))

    # Where the misses concentrate says what to drive next.
    miss = want - found
    if miss:
        print(f"\n  {len(miss)} legal keys not reached; per-dimension values never seen:")
        for j, d in enumerate(shared):
            never = {row[j] for row in miss} - {row[j] for row in hit}
            if never:
                print(f"    {d:<15} never reached at {sorted(never)}")


if __name__ == "__main__":
    raise SystemExit(main())
