# -*- coding: utf-8 -*-
"""What, exactly, is每个 unreachable 判决背后的那个矛盾。

`_probe_reach.py` 报出 6113 个 `unreachable`, 但那是个总数, 说不出它们是几种
矛盾。K6 把维度拆成互不共享自由变量的分量, 逐组求解并缓存, 所以 8705 个 key
的判决其实只来自几百次分组查询 —— 一个 unsat 的组合会一次杀掉成百上千个 key。
把这些组合抽出来, 就能人工核对每一条到底该不该死。

判据是: 所有近似只许扩大可行域。真如此, UNSAT 就可信。所以每一条 unsat 都要
能回答「哪些维度取什么值时矛盾」, 再回到源码看那个矛盾是不是真的。

    python scripts/_probe_unreach.py              # 冲突组合, 按杀伤量排序
    python scripts/_probe_unreach.py --limit 800  # 只扫前 N 个 key, 快速看形态
    python scripts/_probe_unreach.py --pairs      # 附: 维度两两共现的死亡率
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="只扫前 N 个 key")
    ap.add_argument("--timeout", type=int, default=5000)
    ap.add_argument("--pairs", action="store_true", help="附维度两两共现统计")
    ap.add_argument("--top", type=int, default=25, help="打印多少条冲突")
    args = ap.parse_args()

    import _probe_reach as probe

    from uo_init import key_reachability as kr
    from uo_init.key_reachability import KeyReachability
    from uo_init.materialize_tiling import build_legal_key_rows

    doc, var_model, schema, binding = probe.load()
    reach = KeyReachability.from_derivation(
        doc,
        var_model,
        timeout_ms=args.timeout,
        rlimit=kr.DEFAULT_RLIMIT,
        hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
    )

    # 每个分量里有哪些维度, 以及它们各自的取值域 —— 判断一个冲突是否「合理」
    # 需要知道被杀的组合在整个域里占多大比例。
    groups = [tuple(sorted(g)) for g in getattr(reach, "_groups", ())]
    print(f"独立分量 {len(groups)} 个:")
    for g in groups:
        print(f"  {len(g):2}维  {', '.join(g)}")

    rows = build_legal_key_rows(schema, binding=binding, blocker_ids=[], reachability=reach)
    if args.limit:
        rows = rows[: args.limit]

    status = Counter(r.status for r in rows)
    print(f"\n扫过 {len(rows)} 个 key: " + ", ".join(f"{k}={v}" for k, v in status.most_common()))

    # 分组查询的缓存就是全部证据: 键是该组维度的取值, 值是求解结果。
    cache = dict(getattr(reach, "_group_cache", {}))
    verdicts = Counter(str((v or {}).get("status") or "?") for v in cache.values())
    print(f"分组查询 {len(cache)} 次: " + ", ".join(f"{k}={v}" for k, v in verdicts.most_common()))

    # 一个 unsat 组合杀掉多少 key: 数有多少 key 的取值落在它上面。
    kills: Counter[Any] = Counter()
    for row in rows:
        if row.status != "unreachable":
            continue
        dims = _row_dims(row)
        for values, hit in cache.items():
            if str((hit or {}).get("status") or "") != "unsat":
                continue
            if all(dims.get(n) == v for n, v in values):
                kills[values] += 1

    unsat = [(v, h) for v, h in cache.items() if str((h or {}).get("status") or "") == "unsat"]
    print(f"\n矛盾组合 {len(unsat)} 条, 按杀伤量排序:\n")
    for values, hit in sorted(unsat, key=lambda p: -kills[p[0]])[: args.top]:
        shown = ", ".join(f"{n}={v}" for n, v in values)
        core = [c for c in (hit or {}).get("unsat_core") or ()]
        print(f"  杀 {kills[values]:5} 个 key   {shown}")
        if core:
            print(f"          core: {', '.join(str(c) for c in core[:8])}")
    if len(unsat) > args.top:
        print(f"  ... 另有 {len(unsat) - args.top} 条")

    if args.pairs:
        print("\n维度取值的死亡率 (该取值下 unreachable 占比):")
        seen: dict[tuple[str, Any], list[int]] = defaultdict(lambda: [0, 0])
        for row in rows:
            for name, value in _row_dims(row).items():
                slot = seen[(name, value)]
                slot[0] += 1
                slot[1] += row.status == "unreachable"
        for (name, value), (total, dead) in sorted(
            seen.items(), key=lambda kv: -(kv[1][1] / max(kv[1][0], 1))
        )[:30]:
            print(f"  {dead / total:6.1%}  {name}={value:<6} ({dead}/{total})")
    return 0


def _row_dims(row: Any) -> dict[str, Any]:
    """一行 legal key 的维度取值, 不管它把它们放在哪个字段里。"""
    for attr in ("dimensions", "dims", "values", "key_dims"):
        got = getattr(row, attr, None)
        if isinstance(got, dict) and got:
            return {k: _plain(v) for k, v in got.items()}
    return {}


def _plain(value: Any) -> Any:
    for attr in ("value", "target"):
        got = getattr(value, attr, None)
        if got is not None:
            return got
    return value


if __name__ == "__main__":
    raise SystemExit(main())
