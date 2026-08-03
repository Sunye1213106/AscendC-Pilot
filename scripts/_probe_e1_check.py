# -*- coding: utf-8 -*-
"""E1 的验收: 求解器自己能不能吐出那两条跨维规则。

`IsNzOut=1 → SplitAxis=0` 和 `IsNzOut ⊥ IsTndSwizzle` 原先是人读 host 源码读出来
的。如果联合求解能机械导出它们, 这种「LLM 读源码 → 人工录进 YAML」的模式就可以
废掉 —— 它不认识维度名字, 只认识「两个字段读同一个变量」, 对任何算子都免费成立。

前置: 单维必须先能过。身份坍缩没修干净时 `IsNzOut=1` 自己就 UNSAT, 那时任何蕴含
都是前提为假的平凡真, 没有意义。所以先问单维, 再问成对。

    python scripts/_probe_e1_check.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

#: The dimensions the acceptance criterion is about, plus the one it forces.
FOCUS = ["IsNzOut", "IsTndSwizzle", "SplitAxis"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout", type=int, default=3000)
    ap.add_argument("--dims", nargs="*", default=FOCUS)
    args = ap.parse_args()

    import _probe_reach as probe

    from uo_init import key_reachability as kr
    from uo_init.derived_rules import KIND_IMPLICATION, KIND_PAIR, KIND_VALUE, derive_rules
    from uo_init.key_reachability import KeyReachability

    doc, var_model, schema, _binding = probe.load()
    t0 = time.time()
    # Only the dimensions being asked about: compiling the other sixteen into
    # the solver costs minutes and cannot change an answer about these.
    reach = KeyReachability.from_derivation(
        doc, var_model, timeout_ms=args.timeout,
        rlimit=kr.DEFAULT_RLIMIT, hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
        only=args.dims,
    )
    print(f"context built in {time.time() - t0:.0f}s", flush=True)

    candidates = {
        d.name: d.value_domain for d in schema.dims if d.name in args.dims
    }
    print(f"asking about {sorted(candidates)}", flush=True)

    t1 = time.time()
    out = derive_rules(reach, candidates)
    print(f"{out.queries} queries in {time.time() - t1:.0f}s\n")

    for kind in (KIND_VALUE, KIND_PAIR, KIND_IMPLICATION):
        rules = out.of_kind(kind)
        print(f"{kind}: {len(rules)}")
        for r in rules:
            print(f"    {r.describe()}")
    print(f"undecided: {len(out.undecided)}")

    # The two the plan names. Both are UNSAT-side facts, so a `False` here means
    # the solver could not prove it -- not that it disproved it.
    forced = {(r.excludes[0], r.forces) for r in out.of_kind(KIND_IMPLICATION)}
    pairs = {r.excludes for r in out.of_kind(KIND_PAIR)}
    dead = out.dead_values()

    print("\n--- acceptance ---")
    trivial = ("IsNzOut", 1) in dead or ("IsTndSwizzle", 1) in dead
    if trivial:
        print("  PREMISE DEAD: IsNzOut=1 or IsTndSwizzle=1 is unsat on its own,")
        print("  so any implication over it is vacuous. Identity collapse is not")
        print("  fixed in this derivation -- rerun scripts/_probe_derive.py --refresh.")
    got_split = (("IsNzOut", 1), ("SplitAxis", 0)) in forced
    got_mutex = (("IsNzOut", 1), ("IsTndSwizzle", 1)) in pairs
    print(f"  IsNzOut=1 forces SplitAxis=0     {'YES' if got_split else 'no'}")
    print(f"  IsNzOut=1 excludes IsTndSwizzle=1 {'YES' if got_mutex else 'no'}")
    return 0 if (got_split and got_mutex and not trivial) else 1


if __name__ == "__main__":
    raise SystemExit(main())
