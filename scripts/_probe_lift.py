# -*- coding: utf-8 -*-
"""Would interprocedural guard lifting close the two remaining sites?

`covered_in` asks whether one *function's* writes leave a path with no value.
For `fBaseParams.blockOuter` no single function covers anything -- the writes
are spread over nine of them -- while the call tree under `DoSparse` does
cover every path. This lifts each write's guards into a chosen ancestor by
adding the path conditions of every call site on the way up, then scores the
lifted set two ways:

  syntactic  `_paths_are_covered`, the decision-tree walk in use today
  solver     is the disjunction of the lifted guards valid? (the same query
             `guards_cover` runs, with `True` as the premise)

and, for a read, whether the lifted read guards imply the lifted write guards.

    python scripts/_probe_lift.py fBaseParams.blockOuter DoSparse
    python scripts/_probe_lift.py fBaseParams.bandIdx DoTiling
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"


def short(path: str) -> str:
    return Path(path).name.replace("flash_attention_score_grad_tiling_", "")


def desc(c) -> str:
    return f"{'!' if getattr(c, 'negated', False) else ''}[{getattr(c, 'kind', '')}] {getattr(c, 'text', '')[:70]}"


def lift(deriver, site, target):
    """`site`'s guards as seen from `target`, or None if the climb misses it.

    Climbs the same way `_read_lines` does -- one call site, outside any loop,
    into a caller entered once -- and collects the path conditions guarding
    each call along the way. Those are conditions on this write happening just
    as much as the ones inside its own function.
    """
    conds = list(site.conds)
    fn = site.function
    hops = []
    while fn and fn != target:
        calls = deriver._calls_to(fn)
        if len(calls) != 1:
            return None, hops
        call = calls[0]
        caller = getattr(call, "caller", "")
        if not caller:
            return None, hops
        from uo_init.derive_key_fields import _decisive_conds

        conds = list(_decisive_conds(call)) + conds
        hops.append(f"{caller}@{short(getattr(call, 'file', ''))}:{getattr(call, 'line', 0)}")
        fn = caller
    return (conds if fn == target else None), hops


def main() -> int:
    sys.setrecursionlimit(20000)
    path = sys.argv[1] if len(sys.argv) > 1 else "fBaseParams.blockOuter"
    target = sys.argv[2] if len(sys.argv) > 2 else "DoSparse"

    with BUNDLE.open("rb") as fh:
        bundle = pickle.load(fh)
    ir = bundle["host_ir"]

    from uo_init.derive_key_fields import (
        DefSite,
        KeyFieldDeriver,
        _decisive_conds,
        _paths_are_covered,
    )
    from uo_init.loop_summary import guards_cover

    deriver = KeyFieldDeriver(
        host_ir=ir,
        resolver=bundle["resolver"],
        var_model=bundle["var_model"],
        max_helper_guards=4,
    )

    writes = sorted(
        [w for w in ir.writes if w.path == path or w.path.endswith("." + path)],
        key=lambda w: (w.file, w.line),
    )
    print(f"=== {path}: {len(writes)} write(s), lifting into {target}\n")

    lifted: list[tuple] = []
    for w in writes:
        site = DefSite(
            rhs=w.rhs, file=w.file, line=w.line, function=w.function,
            conds=_decisive_conds(w),
        )
        conds, hops = lift(deriver, site, target)
        tag = f"{short(w.file)}:{w.line} [{w.function}]"
        if conds is None:
            print(f"  {tag}\n      NOT LIFTED (climb stopped: {hops or 'no single call site'})")
            continue
        print(f"  {tag}  via {' <- '.join(hops) or 'already there'}")
        for c in conds:
            print(f"      {desc(c)}")
        lifted.append((tuple(conds), target))

    if not lifted:
        return 0
    paths = [c for c, _ in lifted]
    print(f"\n  lifted writes reaching {target}: {len(lifted)}/{len(writes)}")
    print(f"  syntactic _paths_are_covered = {_paths_are_covered(paths)}")

    # The same question asked of the solver: with no premise, is the
    # disjunction of the lifted guards valid?
    class Cond:
        kind = "if"

        def __init__(self, text, negated=False):
            self.text, self.negated = text, negated

    premise = [Cond("1")]
    # Extra facts, given as C++ text so they lower through the same atom table
    # as the guards. Used to test whether a specific missing fact -- what a
    # call's result implies about the caller's state -- is the only thing in
    # the way.
    for axiom in sys.argv[3:]:
        premise.append(Cond(axiom))
        print(f"  axiom: {axiom}")

    imp = guards_cover(
        tuple(premise), lifted, read_function=target,
        members=getattr(ir, "class_fields", ()) or (),
    )
    print(f"  solver: disjunction valid    = {imp.holds}  ({imp.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
