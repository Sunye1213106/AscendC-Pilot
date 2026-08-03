# -*- coding: utf-8 -*-
"""每个阶段的钱花在哪: 推导逐维耗时、求解逐查询耗时。

一个要跑十分钟的脚本没人会用第二次。这个脚本不产出制品, 只回答「慢在哪一维、
哪一类查询」, 好知道该缩短什么。

    python scripts/_probe_cost.py            # 读缓存里记的推导耗时
    python scripts/_probe_cost.py --solve    # 另外实测求解侧的单值查询耗时
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

DERIVE = ROOT / ".probe_cache" / "fag_derive.json"


def derive_cost() -> None:
    doc = json.loads(DERIVE.read_text(encoding="utf-8"))
    print(f"timeout      : {doc.get('timeout')}s per field")
    print(f"helper guards: {doc.get('max_helper_guards')}")
    print(f"totals       : {doc.get('totals')}")
    print(f"timestamp    : {doc.get('timestamp')}")
    rows = sorted(doc["fields"], key=lambda f: -(f.get("seconds") or 0))
    print()
    print(f"{'dimension':<18}{'sec':>8}{'status':>10}{'exactness':>16}{'chars':>12}")
    print("-" * 64)
    total = 0.0
    for f in rows:
        seconds = float(f.get("seconds") or 0)
        total += seconds
        print(
            f"{f['name']:<18}{seconds:>8.1f}{f.get('status', ''):>10}"
            f"{f.get('exactness', ''):>16}{f.get('expanded_chars') or 0:>12}"
        )
    print("-" * 64)
    print(f"{'TOTAL':<18}{total:>8.1f}")
    slow = [f for f in rows if (f.get("seconds") or 0) > 30]
    if slow:
        print(f"\n{len(slow)} dimension(s) over 30s: " + ", ".join(f["name"] for f in slow))


def solve_cost(timeout_ms: int, limit: int) -> None:
    import _probe_reach as probe

    from uo_init import key_reachability as kr
    from uo_init.key_reachability import KeyReachability, _target_value

    doc, var_model, schema, _binding = probe.load()
    t0 = time.time()
    reach = KeyReachability.from_derivation(
        doc, var_model, timeout_ms=timeout_ms,
        rlimit=kr.DEFAULT_RLIMIT, hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
    )
    print(f"context built in {time.time() - t0:.1f}s")
    summary = reach.summary()
    print(f"groups: {[len(g) for g in summary['groups']]}")

    compiled = dict(reach._dims)
    # Which dimension pairs can even interact: no shared variable means the
    # conjunction is satisfiable whenever each half is, so asking is wasted.
    names = sorted(compiled)
    linked = sum(
        1
        for i, a in enumerate(names)
        for b in names[i + 1:]
        if compiled[a]["support"] & compiled[b]["support"]
    )
    total_pairs = len(names) * (len(names) - 1) // 2
    print(f"dimension pairs sharing a variable: {linked}/{total_pairs}")

    print(f"\n{'query':<28}{'sec':>8}{'status':>10}")
    print("-" * 46)
    asked = 0
    for dim in schema.dims:
        spec = compiled.get(dim.name)
        if spec is None:
            continue
        for raw in dim.value_domain:
            value = _target_value(raw)
            if value is None:
                continue
            if limit and asked >= limit:
                return
            t1 = time.time()
            hit = reach._solve_group(((dim.name, value),))
            asked += 1
            print(
                f"{dim.name + '=' + str(raw):<28}{time.time() - t1:>8.2f}"
                f"{str(hit.get('status')):>10}"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--solve", action="store_true", help="也实测求解耗时")
    ap.add_argument("--timeout", type=int, default=5000)
    ap.add_argument("--limit", type=int, default=0, help="只测前 N 个查询")
    args = ap.parse_args()

    if DERIVE.is_file():
        derive_cost()
    else:
        print(f"no {DERIVE}")
    if args.solve:
        print("\n" + "=" * 64 + "\nsolver\n" + "=" * 64)
        solve_cost(args.timeout, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
